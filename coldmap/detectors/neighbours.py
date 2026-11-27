"""Neighbouring counties: a county scanned together with the counties that border it.

Offenders cross county lines, so each county's share of a series can look ordinary while the group's
does not. The strict scan pools counties only where a region set exists (California, Puget Sound).
This detector does it everywhere: for every county, the group "that county and its neighbours in the
same state" (borders from the US Census county shapes coldmap ships) is scanned like a place,
with the same statistics as `scan` (every window of years, rest of the state as reference, Monte
Carlo p-values, Benjamini-Hochberg q-values across groups).

Groups overlap, so one real cluster can surface in several groups; findings keep only the
strongest of overlapping groups for the same method and years. A finding names the centre county
and lists every county in its group.

EXPERIMENTAL, off by default: none of the bundled known series crosses a county line outside the
regions `scan` already covers, so the benchmark cannot show whether it helps. See the Models page
for its measured false-alarm rate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from scipy.stats import binom

from ..core.types import Finding
from ..stats import bh_qvalues, scan_group, windows
from . import DETECTORS
from .base import Detector


@lru_cache(maxsize=1)
def adjacency() -> dict[str, frozenset[str]]:
    """{county code: codes of the counties that share a border}, from the bundled county shapes."""
    from ..interfaces.research import ATLAS
    topo = json.loads(ATLAS.read_text(encoding="utf-8"))
    by_arc: dict[int, set[str]] = {}

    def arcs(a):
        if isinstance(a, int):
            yield a if a >= 0 else ~a
        else:
            for x in a:
                yield from arcs(x)
    for g in topo["objects"]["counties"]["geometries"]:
        for k in arcs(g.get("arcs", [])):
            by_arc.setdefault(k, set()).add(g["id"])
    out: dict[str, set[str]] = {}
    for ids in by_arc.values():
        for a in ids:
            out.setdefault(a, set()).update(ids - {a})
    return {k: frozenset(v) for k, v in out.items()}


def groups(labels) -> dict[str, list[str]]:
    """{centre county label: [centre, neighbours...]} for counties in the same state with a border."""
    from ..interfaces.research import county_fips
    code = {lb: county_fips(lb) for lb in labels}
    by_code = {c: lb for lb, c in code.items() if c}
    adj = adjacency()
    out = {}
    for lb, c in code.items():
        if not c:
            continue
        near = sorted(by_code[n] for n in adj.get(c, ()) if n in by_code and n[:2] == c[:2])
        if near:
            out[lb] = [lb, *near]
    return out


@DETECTORS.register
class Neighbours(Detector):
    name = "neighbours"
    summary = "Experimental: each county with its neighbours, scanned like scan; off by default"
    tier = "strict"

    @dataclass
    class Params:
        min_cases: int = field(default=8, metadata={"help": "Minimum killings in a window"})
        min_len: int = field(default=1, metadata={"help": "Shortest window (years)"})
        max_len: int = field(default=12, metadata={"help": "Longest window (years)"})
        reps: int = field(default=999, metadata={"help": "Monte Carlo simulations"})
        max_q: float | None = field(default=0.10, metadata={"help": "False discovery rate cutoff"})
        top_k: int = field(default=2, metadata={"help": "Non-overlapping windows kept per group"})
        shrink: float = field(default=20.0, metadata={"help": "Smoothing of yearly reference rates (cases)"})
        screen_p: float = field(default=0.05, metadata={"help": "Skip simulation if best window's p exceeds this"})
        seed: int = field(default=0, metadata={"help": "Random seed"})
        min_unsolved: int = field(default=0, metadata={"help": "Minimum unsolved killings in a flagged window"})

    def detect(self, data, query):
        p = self.params
        d = data.select(query)
        d = d[d.county.notna()]
        if d.empty:
            return []
        years = np.arange(d.year.min(), d.year.max() + 1)
        wi, wj = windows(len(years), p.min_len, p.max_len)
        g = d.groupby(["state", "county", "weapon_group", "year"]).solved.agg(["size", "sum"])
        ref = d.groupby(["state", "weapon_group", "year"]).solved.agg(["size", "sum"])
        rng = np.random.default_rng(p.seed)
        results, tested = [], 0
        for st, ds in d.groupby("state"):
            for centre, members in groups(ds.county.unique()).items():
                for w in ds.weapon_group.unique():
                    try:
                        parts = [g.loc[(st, c, w)] for c in members if (st, c, w) in g.index]
                    except KeyError:
                        continue
                    if not parts:
                        continue
                    grp = sum(x.reindex(years, fill_value=0) for x in parts)
                    n, s = grp["size"].to_numpy(float), grp["sum"].to_numpy(float)
                    if n.sum() < p.min_cases or len(parts) < 2:
                        continue
                    tested += 1
                    rs = ref.loc[(st, w)].reindex(years, fill_value=0)
                    rest_n, rest_s = rs["size"].to_numpy(float) - n, rs["sum"].to_numpy(float) - s
                    if rest_n.sum() <= 0:
                        continue
                    rest_all = rest_s.sum() / rest_n.sum()
                    p0t = np.clip((rest_s + p.shrink * rest_all) / (rest_n + p.shrink), 0.02, 0.97)
                    cn, cs, ce = (np.concatenate([[0], np.cumsum(x)]) for x in (n, s, n * p0t))
                    N, S, E = cn[wj + 1] - cn[wi], cs[wj + 1] - cs[wi], ce[wj + 1] - ce[wi]
                    ok = N >= p.min_cases
                    if not ok.any() or binom.cdf(S[ok], N[ok], np.clip(E[ok] / N[ok], 1e-6, 1 - 1e-6)).min() > p.screen_p:
                        continue
                    for i, j, NN, SS, p0, score, pv in scan_group(n, s, p0t, wi, wj, p.min_cases, p.reps, rng, p.top_k):
                        results.append(Finding(self.name, f"{centre} and neighbours", "neighbours", query.victim_sex,
                                               w, int(years[i]), int(years[j]), NN, SS, expected=round(p0, 3),
                                               p_value=pv, score=round(score, 2), county=centre,
                                               extras={"counties": members}))
        if not results:
            return []
        q = bh_qvalues(np.array([f.p_value for f in results]), m=max(tested, len(results)))
        for f, qq in zip(results, q):
            f.q_value = float(qq)
        kept = [f for f in results if (p.max_q is None or f.q_value <= p.max_q) and f.unsolved >= p.min_unsolved]
        return _strongest(kept)


def _strongest(found: list[Finding]) -> list[Finding]:
    """Overlapping groups find the same cluster: keep the strongest finding among those that share a
    county, method and overlapping years."""
    out: list[Finding] = []
    for f in sorted(found, key=lambda f: (f.q_value, -f.score)):
        if any(o.weapon == f.weapon and o.start <= f.end and f.start <= o.end
               and set(o.extras["counties"]) & set(f.extras["counties"]) for o in out):
            continue
        out.append(f)
    return out
