"""Temporal scan statistic: strict, false-alarm controlled.

For each place x victim sex x weapon group, searches every window from
`min_len` to `max_len` years for the one where solved cases fall furthest below
the solve rate in the *rest of the state* in the same years (leave-one-out,
smoothed toward the long-run rate). Monte Carlo simulation gives each window a
p-value that accounts for trying every window (Kulldorff-style); the
Benjamini-Hochberg procedure gives q-values across groups at each level.

Runs at several levels (agency, county, msa): agency catches series inside one
city (Gary, Indiana); msa catches series that cross county lines.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import binom

from ..core.types import Finding
from ..stats import bh_qvalues, scan_group, windows
from . import DETECTORS
from .base import Detector


@DETECTORS.register
class TemporalScan(Detector):
    name = "scan"
    summary = "Every window length vs the rest of the state; Monte Carlo + FDR; few false alarms"
    tier = "strict"

    @dataclass
    class Params:
        levels: tuple[str, ...] = field(default=("county", "agency"),
                                        metadata={"help": "Places to scan: county, agency, msa"})
        min_cases: int = field(default=8, metadata={"help": "Minimum killings in a window"})
        min_len: int = field(default=1, metadata={"help": "Shortest window (years)"})
        max_len: int = field(default=25, metadata={"help": "Longest window (years)"})
        reps: int = field(default=999, metadata={"help": "Monte Carlo simulations"})
        max_q: float | None = field(default=0.10, metadata={"help": "False discovery rate cutoff"})
        top_k: int = field(default=3, metadata={"help": "Non-overlapping windows kept per group"})
        shrink: float = field(default=20.0, metadata={"help": "Smoothing of yearly reference rates (cases)"})
        screen_p: float = field(default=0.05, metadata={"help": "Skip simulation if best window's p exceeds this"})
        seed: int = field(default=0, metadata={"help": "Random seed"})

    def detect(self, data, query):
        out = []
        for level in self.params.levels:
            out += self._detect_level(data.select(query), query, level)
        return sorted(out, key=lambda f: (f.q_value, -f.score))

    def _detect_level(self, d: pd.DataFrame, query, level: str) -> list[Finding]:
        p = self.params
        d = d[d[level].notna()]
        if level == "msa":
            d = d[~d.msa.astype(str).str.contains("Rural|Not in", case=False, na=False)]
        if d.empty:
            return []
        years = np.arange(d.year.min(), d.year.max() + 1)
        wi, wj = windows(len(years), p.min_len, p.max_len)
        ref = d.groupby(["state", "weapon_group", "year"]).solved.agg(["size", "sum"])
        g = d.groupby(["state", level, "weapon_group", "year"]).solved.agg(["size", "sum"])
        rng = np.random.default_rng(p.seed)
        results, tested = [], 0
        for (st, place, w), grp in g.groupby(level=[0, 1, 2]):
            grp = grp.droplevel([0, 1, 2]).reindex(years, fill_value=0)
            n, s = grp["size"].to_numpy(float), grp["sum"].to_numpy(float)
            if n.sum() < p.min_cases:
                continue
            tested += 1
            rs = ref.loc[(st, w)].reindex(years, fill_value=0)
            rest_n = rs["size"].to_numpy(float) - n
            rest_s = rs["sum"].to_numpy(float) - s
            if rest_n.sum() <= 0:
                continue
            rest_all = rest_s.sum() / rest_n.sum()
            p0t = np.clip((rest_s + p.shrink * rest_all) / (rest_n + p.shrink), 0.02, 0.97)
            # Cheap analytic screen before simulating.
            cn, cs, ce = (np.concatenate([[0], np.cumsum(x)]) for x in (n, s, n * p0t))
            N, S, E = cn[wj + 1] - cn[wi], cs[wj + 1] - cs[wi], ce[wj + 1] - ce[wi]
            ok = N >= p.min_cases
            if not ok.any() or binom.cdf(S[ok], N[ok], np.clip(E[ok] / N[ok], 1e-6, 1 - 1e-6)).min() > p.screen_p:
                continue
            for i, j, NN, SS, p0, score, pv in scan_group(n, s, p0t, wi, wj, p.min_cases, p.reps, rng, p.top_k):
                results.append(Finding(self.name, place, level, query.victim_sex, w, int(years[i]),
                                       int(years[j]), NN, SS, expected=round(p0, 3), p_value=pv,
                                       score=round(score, 2), county=place if level == "county" else None))
        if not results:
            return []
        q = bh_qvalues(np.array([f.p_value for f in results]), m=max(tested, len(results)))
        for f, qq in zip(results, q):
            f.q_value = float(qq)
        return [f for f in results if p.max_q is None or f.q_value <= p.max_q]
