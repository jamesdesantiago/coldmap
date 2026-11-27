"""Month-level bursts: short runs of unsolved killings hidden inside yearly totals.

The strict scan works in years, so a few months of killings in one place can disappear into a
year's total. This detector looks for windows of 1 to 24 months where solved cases fall furthest
below what the rest of the state solved for the same method and victims that year (smoothed toward
the long-run rate, as in `scan`). Monte Carlo simulation gives each window a p-value that accounts
for trying every window; Benjamini-Hochberg q-values control false discoveries across groups.

Cases without a recorded month are left out (none in MAP's current file) and counted on each
finding.

EXPERIMENTAL, off by default. Measured on MAP's file (November 2026), against the yearly `scan`:
- Benchmark, 9 adjudicated series: burst found 1 fully and 1 partly (scan: 5 and 2), and found no
  series that scan misses.
- False-alarm tests, women, 3 shuffled runs: California 0 real / 0 chance (scan 8 / 1.0); Indiana
  0 / 0 (scan 5 / 0); Illinois 9 / 2.0 (scan 11 / 4.3); Washington 4 / 1.7 (scan 7 / 2.3).
Testing ~14,000 month windows per place forces a strict multiple-testing correction, and real series
usually span years, which `scan` already covers. Labelled "sensitive" because its chance-flag share
is not lower than scan's. A starting point to improve, not a detector to rely on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..core.types import Finding
from ..stats import bh_qvalues, llr
from . import DETECTORS
from .base import Detector


@DETECTORS.register
class MonthBurst(Detector):
    name = "burst"
    summary = "Experimental: short bursts of 1-24 months; measured weaker than scan (see its description)"
    tier = "sensitive"

    @dataclass
    class Params:
        levels: tuple[str, ...] = field(default=("county", "agency"), metadata={"help": "Places to scan: county, agency"})
        min_len: int = field(default=1, metadata={"help": "Shortest window (months)"})
        max_len: int = field(default=24, metadata={"help": "Longest window (months)"})
        min_cases: int = field(default=6, metadata={"help": "Minimum killings in a window"})
        reps: int = field(default=999, metadata={"help": "Monte Carlo simulations"})
        max_q: float | None = field(default=0.10, metadata={"help": "False discovery rate cutoff"})
        top_k: int = field(default=2, metadata={"help": "Non-overlapping windows kept per group"})
        shrink: float = field(default=20.0, metadata={"help": "Smoothing of yearly reference rates (cases)"})
        screen_p: float = field(default=0.05, metadata={"help": "Skip simulation if the best window's p exceeds this"})
        seed: int = field(default=0, metadata={"help": "Random seed"})
        min_unsolved: int = field(default=4, metadata={"help": "Minimum unsolved killings in a flagged window"})

    def detect(self, data, query):
        d = data.select(query)
        no_month = int((d.month == 0).sum())
        d = d[d.month > 0]
        out = []
        for level in self.params.levels:
            out += self._level(d, query, level, no_month)
        return sorted(out, key=lambda f: (f.q_value, -f.score))

    def _level(self, d, query, level, no_month):
        from scipy.stats import binom
        p = self.params
        d = d[d[level].notna()]
        if d.empty:
            return []
        y0, y1 = int(d.year.min()), int(d.year.max())
        T = (y1 - y0 + 1) * 12
        d = d.assign(t=(d.year - y0) * 12 + d.month - 1)
        ref = d.groupby(["state", "weapon_group", "year"]).solved.agg(["size", "sum"])
        rng = np.random.default_rng(p.seed)
        results, tested = [], 0
        for (st, place, w), g in d.groupby(["state", level, "weapon_group"]):
            if len(g) < p.min_cases:
                continue
            n = np.bincount(g.t, minlength=T).astype(float)
            s = np.bincount(g.t, weights=g.solved.astype(float), minlength=T)
            # Reference: the rest of the state, same method and victims, that year (smoothed).
            years = np.arange(y0, y1 + 1)
            rs = ref.loc[(st, w)].reindex(years, fill_value=0)
            yn = g.groupby("year").size().reindex(years, fill_value=0).to_numpy(float)
            ys = g.groupby("year").solved.sum().reindex(years, fill_value=0).to_numpy(float)
            rest_n, rest_s = rs["size"].to_numpy(float) - yn, rs["sum"].to_numpy(float) - ys
            if rest_n.sum() <= 0:
                continue
            tested += 1
            overall = rest_s.sum() / rest_n.sum()
            p_year = np.clip((rest_s + p.shrink * overall) / (rest_n + p.shrink), 0.02, 0.97)
            p0t = np.repeat(p_year, 12)
            # Only the span where this place has killings by this method.
            lo, hi = int(g.t.min()), int(g.t.max()) + 1
            n, s, p0t = n[lo:hi], s[lo:hi], p0t[lo:hi]
            found = self._scan(n, s, p0t, rng, binom)
            for i, j, NN, SS, p0, ratio, pv in found:
                a, b = lo + i, lo + j
                ys0, ms0, ys1, ms1 = y0 + a // 12, a % 12 + 1, y0 + b // 12, b % 12 + 1
                results.append(Finding(self.name, place, level, query.victim_sex, w, int(ys0), int(ys1), NN, SS,
                                       expected=round(p0, 3), p_value=pv, score=round(ratio, 2),
                                       county=place if level == "county" else None,
                                       extras={"months": f"{ys0}-{ms0:02d} to {ys1}-{ms1:02d}",
                                               "months_long": b - a + 1, "no_month": no_month}))
        if not results:
            return []
        q = bh_qvalues(np.array([f.p_value for f in results]), m=max(tested, len(results)))
        for f, qq in zip(results, q):
            f.q_value = float(qq)
        return [f for f in results if (p.max_q is None or f.q_value <= p.max_q) and f.unsolved >= p.min_unsolved]

    def _scan(self, n, s, p0t, rng, binom):
        """Best windows of 1..max_len months, with a Monte Carlo p-value for the scan as a whole.
        Works one window length at a time so memory stays small over ~600 months."""
        p = self.params
        T = len(n)
        cn, cs, ce = (np.concatenate([[0], np.cumsum(x)]) for x in (n, s, n * p0t))
        cands = []
        for L in range(p.min_len, min(p.max_len, T) + 1):
            N = cn[L:] - cn[:-L]
            ok = N >= p.min_cases
            if not ok.any():
                continue
            S, E = cs[L:] - cs[:-L], ce[L:] - ce[:-L]
            p0 = np.clip(E / np.where(N > 0, N, 1), 1e-6, 1 - 1e-6)
            r = np.where(ok, llr(S, N, p0), 0.0)
            for k in np.flatnonzero(r > 0):
                cands.append((float(r[k]), int(k), int(k + L - 1), int(N[k]), int(S[k]), float(p0[k])))
        if not cands:
            return []
        best = max(cands)
        # Cheap screen before simulating.
        if binom.cdf(best[4], best[3], best[5]) > p.screen_p:
            return []
        sims = rng.binomial(n.astype(int), np.clip(p0t, 0, 1), size=(p.reps, T))
        csim = np.concatenate([np.zeros((p.reps, 1)), np.cumsum(sims, axis=1)], axis=1)
        top = np.zeros(p.reps)
        for L in range(p.min_len, min(p.max_len, T) + 1):
            N = cn[L:] - cn[:-L]
            ok = N >= p.min_cases
            if not ok.any():
                continue
            E = ce[L:] - ce[:-L]
            p0 = np.clip(E / np.where(N > 0, N, 1), 1e-6, 1 - 1e-6)
            Ssim = csim[:, L:] - csim[:, :-L]
            r = np.where(ok, llr(Ssim, N, p0), 0.0)
            top = np.maximum(top, r.max(axis=1))
        out, taken = [], np.zeros(T, bool)
        for ratio, i, j, NN, SS, p0 in sorted(cands, reverse=True):
            if len(out) >= p.top_k:
                break
            if taken[i:j + 1].any():
                continue
            taken[i:j + 1] = True
            pv = (1 + int((top >= ratio).sum())) / (p.reps + 1)
            out.append((i, j, NN, SS, p0, ratio, pv))
        return out
