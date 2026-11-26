"""Fixed rolling windows: sensitive, no multiple-testing control.

Groups by place, victim sex and weapon group; flags every `window`-year span
with at least `min_cases` killings and a solve rate at or below `threshold`.
Overlapping windows for the same group are merged, keeping the one with the
most unsolved cases. p_value is a one-window binomial test against the group's
own long-run solve rate (not corrected for multiple testing).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scipy.stats import binom

from ..core.types import Finding
from . import DETECTORS
from .base import Detector


@DETECTORS.register
class SlidingWindow(Detector):
    name = "window"
    summary = "Fixed rolling windows below a solve-rate threshold; catches more, noisier"
    tier = "sensitive"

    @dataclass
    class Params:
        place: str = field(default="county", metadata={"help": "county, agency or msa"})
        window: int = field(default=4, metadata={"help": "Window length in years"})
        threshold: float = field(default=0.40, metadata={"help": "Flag at or below this solve rate"})
        min_cases: int = field(default=8, metadata={"help": "Minimum killings in a window"})
        max_p: float | None = field(default=None, metadata={"help": "Optional binomial p cutoff"})

    def detect(self, data, query):
        p = self.params
        d = data.select(query)
        d = d[d[p.place].notna()]
        if d.empty:
            return []
        years = range(d.year.min(), d.year.max() + 1)
        out = []
        yearly = d.groupby([p.place, "weapon_group", "year"]).solved.agg(["size", "sum"])
        for (place, w), grp in yearly.groupby(level=[0, 1]):
            grp = grp.droplevel([0, 1]).reindex(years, fill_value=0)
            bt, bs = grp["size"].sum(), grp["sum"].sum()
            if bt < p.min_cases:
                continue
            base = bs / bt
            tot = grp["size"].rolling(p.window).sum().dropna()
            sol = grp["sum"].rolling(p.window).sum().dropna()
            cands = []
            for end in tot.index:
                t, s = int(tot[end]), int(sol[end])
                if t >= p.min_cases and s / t <= p.threshold:
                    pv = float(binom.cdf(s, t, base))
                    if p.max_p is None or pv <= p.max_p:
                        cands.append(Finding(self.name, place, p.place, query.victim_sex, w,
                                             end - p.window + 1, end, t, s, expected=round(base, 3),
                                             p_value=pv, score=float(t - s),
                                             county=place if p.place == "county" else None))
            cands.sort(key=lambda f: f.unsolved, reverse=True)
            kept = []
            for f in cands:
                if not any(abs(k.start - f.start) < p.window for k in kept):
                    kept.append(f)
            out.extend(kept)
        return sorted(out, key=lambda f: f.unsolved, reverse=True)
