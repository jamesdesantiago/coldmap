"""Temporal scan statistic: strict, false-alarm controlled.

For each place x victim sex x weapon group, searches every window from
`min_len` to `max_len` years for the one where solved cases fall furthest below
the solve rate in the *rest of the state* in the same years (leave-one-out,
smoothed toward the long-run rate). Monte Carlo simulation gives each window a
p-value that accounts for trying every window (Kulldorff-style); the
Benjamini-Hochberg procedure gives q-values across groups at each level.

Runs at several levels (agency, county, region, msa): agency catches series
inside one city (Gary, Indiana); region catches series that cross county lines
(Southern California's Freeway Killers), using region sets from coldmap.regions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import binom

from ..core.profile import add_profile
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
        levels: tuple[str, ...] = field(default=("county", "agency", "region"),
                                        metadata={"help": "Places to scan: county, agency, msa, region"})
        region_max_len: int = field(default=12, metadata={
            "help": "Longest window for regions; big regions otherwise favor decades-long trends"})
        region_sets: tuple[str, ...] | None = field(default=None, metadata={
            "help": "Region sets to use for the region level (default: all registered)"})
        min_cases: int = field(default=8, metadata={"help": "Minimum killings in a window"})
        min_len: int = field(default=1, metadata={"help": "Shortest window (years)"})
        max_len: int = field(default=25, metadata={"help": "Longest window (years)"})
        reps: int = field(default=999, metadata={"help": "Monte Carlo simulations"})
        max_q: float | None = field(default=0.10, metadata={"help": "False discovery rate cutoff"})
        top_k: int = field(default=3, metadata={"help": "Non-overlapping windows kept per group"})
        shrink: float = field(default=20.0, metadata={"help": "Smoothing of yearly reference rates (cases)"})
        screen_p: float = field(default=0.05, metadata={"help": "Skip simulation if best window's p exceeds this"})
        seed: int = field(default=0, metadata={"help": "Random seed"})
        min_unsolved: int = field(default=0, metadata={"help": "Minimum unsolved killings in a flagged window"})
        split_by: tuple[str, ...] = field(default=(), metadata={
            "help": "Victim-profile splits: age_band (see core/profile.py for why others are not offered)"})

    def detect(self, data, query):
        out = []
        d = add_profile(data.select(query), tuple(self.params.split_by))
        if "region" in self.params.levels:
            from ..regions import add_region, members
            d = add_region(d, list(self.params.region_sets) if self.params.region_sets else None)
        for level in self.params.levels:
            found = self._detect_level(d, query, level)
            if level == "region":
                for f in found:
                    f.extras["counties"] = members(f.place)
            out += found
        return sorted(out, key=lambda f: (f.q_value, -f.score))

    def _detect_level(self, d: pd.DataFrame, query, level: str) -> list[Finding]:
        p = self.params
        d = d[d[level].notna()]
        if level == "msa":
            d = d[~d.msa.astype(str).str.contains("Rural|Not in", case=False, na=False)]
        if d.empty:
            return []
        years = np.arange(d.year.min(), d.year.max() + 1)
        max_len = min(p.max_len, p.region_max_len) if level == "region" else p.max_len
        wi, wj = windows(len(years), p.min_len, max_len)
        split = list(p.split_by)
        ref = d.groupby(["state", "weapon_group", *split, "year"]).solved.agg(["size", "sum"])
        keys = ["state", level, "weapon_group", *split]
        g = d.groupby(keys + ["year"]).solved.agg(["size", "sum"])
        lv = list(range(len(keys)))
        rng = np.random.default_rng(p.seed)
        results, tested = [], 0
        for key, grp in g.groupby(level=lv):
            st, place, w, prof = key[0], key[1], key[2], dict(zip(split, key[3:]))
            grp = grp.droplevel(lv).reindex(years, fill_value=0)
            n, s = grp["size"].to_numpy(float), grp["sum"].to_numpy(float)
            if n.sum() < p.min_cases:
                continue
            tested += 1
            rs = ref.loc[(st, w, *prof.values())].reindex(years, fill_value=0)
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
                                       score=round(score, 2), county=place if level == "county" else None,
                                       extras={"profile": prof} if prof else {}))
        if not results:
            return []
        q = bh_qvalues(np.array([f.p_value for f in results]), m=max(tested, len(results)))
        for f, qq in zip(results, q):
            f.q_value = float(qq)
        return [f for f in results if (p.max_q is None or f.q_value <= p.max_q) and f.unsolved >= p.min_unsolved]
