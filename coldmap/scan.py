"""Temporal scan statistic with Monte Carlo significance and FDR control.

For each group (a place x victim sex x weapon group), this searches every time
window of every length and finds the one where solved cases fall furthest below
what was expected. Expected is the solve rate in the *rest of the state* for the same
victim sex and weapon group in the same years, so a flag means "this place did much
worse than comparable cases in its state at the time", which accounts for the
long national decline in clearance.

Significance is tested the way Kulldorff's scan statistic is: simulate the
group's solved counts under the state rates many times, take the best window in
each simulation, and rank the real best window among them. That corrects for
having tried every window. Across groups, the Benjamini-Hochberg procedure
controls the false discovery rate, so a q-value of 0.05 means about 5% of flags
at or below it are expected to be noise.

Place can be "agency", "county" or "msa": agency catches series concentrated in
one city (Gary, Indiana) that are diluted at county level; msa catches series
that cross county lines.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .detect import Flag, _prep


def _llr(S, N, p0):
    """Binomial log-likelihood ratio for 'solve rate lower than p0'. Arrays broadcast."""
    with np.errstate(divide="ignore", invalid="ignore"):
        q = S / N
        a = np.where(S > 0, S * np.log(q / p0), 0.0)
        b = np.where(N - S > 0, (N - S) * np.log((1 - q) / (1 - p0)), 0.0)
        out = a + b
    return np.where((N > 0) & (q < p0), out, 0.0)


def _windows(T, min_len, max_len):
    i, j = np.triu_indices(T)
    L = j - i + 1
    keep = (L >= min_len) & (L <= max_len)
    return i[keep], j[keep]


def _scan_group(n, s, p0t, wi, wj, min_cases, reps, rng, top_k=3):
    """Best window plus up to top_k-1 further windows that don't overlap it.

    Every window is tested against the distribution of the *best* window in each
    simulation, which is conservative for the secondary windows.
    """
    cn = np.concatenate([[0], np.cumsum(n)])
    ce = np.concatenate([[0], np.cumsum(n * p0t)])
    N = cn[wj + 1] - cn[wi]
    E = ce[wj + 1] - ce[wi]
    ok = N >= min_cases
    if not ok.any():
        return []
    wi, wj, N, E = wi[ok], wj[ok], N[ok], E[ok]
    p0 = np.clip(E / N, 1e-6, 1 - 1e-6)
    cs = np.concatenate([[0], np.cumsum(s)])
    S = cs[wj + 1] - cs[wi]
    llr = _llr(S, N, p0)
    if llr.max() <= 0:
        return []
    sims = rng.binomial(n.astype(int), np.clip(p0t, 0, 1), size=(reps, len(n)))
    csim = np.concatenate([np.zeros((reps, 1)), np.cumsum(sims, axis=1)], axis=1)
    best = _llr(csim[:, wj + 1] - csim[:, wi], N, p0).max(axis=1)
    out, taken = [], np.zeros(len(n), bool)
    for k in np.argsort(-llr):
        if len(out) >= top_k or llr[k] <= 0:
            break
        if taken[wi[k]:wj[k] + 1].any():
            continue
        taken[wi[k]:wj[k] + 1] = True
        p = (1 + int((best >= llr[k]).sum())) / (reps + 1)
        out.append((wi[k], wj[k], int(N[k]), int(S[k]), float(p0[k]), float(llr[k]), p))
    return out


SERIAL_METHODS = {"Strangle/asphyxia", "Beating/blunt", "Knife", "Other/unknown", "Fire"}


def kind_of(weapon: str, total: int) -> str:
    """'serial-pattern' for methods typical of serial homicide in groups small enough to
    be one offender's work; otherwise 'accountability' (a place solving fewer cases)."""
    return "serial-pattern" if weapon in SERIAL_METHODS and total <= 100 else "accountability"


def bh_qvalues(p: np.ndarray, m: int | None = None) -> np.ndarray:
    """Benjamini-Hochberg q-values. m = total tests (defaults to len(p))."""
    p = np.asarray(p, float)
    m = m or len(p)
    order = np.argsort(p)
    ranked = p[order] * m / np.arange(1, len(p) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(q)
    out[order] = np.minimum(q, 1.0)
    return out


def scan(df: pd.DataFrame, state: str | None = None, place: str = "county",
         victim_sex: str = "Female", min_cases: int = 8, min_len: int = 1, max_len: int = 12,
         reps: int = 999, max_q: float | None = 0.10, min_age: int | None = 12,
         use_fixes: bool = True, as_of: int | None = None, seed: int = 0,
         screen_p: float = 0.05, top_k: int = 3, shrink: float = 20.0,
         exclude_weapons: tuple[str, ...] = ("Not reported",)) -> list[Flag]:
    """Run the scan. as_of limits data to years <= as_of (for backtesting).

    Groups whose best window is unremarkable even before simulation (analytic
    binomial screen above screen_p) skip the Monte Carlo step and count as p=1;
    they still count in the FDR denominator, so the correction stays honest.
    """
    from scipy.stats import binom

    d, fixes = _prep(df, use_fixes)
    if state:
        d = d[d.state == state]
    if as_of is not None:
        d = d[d.year <= as_of]
    d = d[(d.vic_sex == victim_sex) & ~d.weapon_group.isin(exclude_weapons) & d[place].notna()]
    if place == "msa":
        d = d[~d.msa.astype(str).str.contains("Rural|Not in", case=False, na=False)]
    if min_age is not None:
        d = d[d.vic_age >= min_age]
    if d.empty:
        return []
    years = np.arange(d.year.min(), d.year.max() + 1)
    T = len(years)
    wi, wj = _windows(T, min_len, max_len)

    # Reference rates: state x weapon group x year (all places pooled).
    ref = d.groupby(["state", "weapon_group", "year"]).solved.agg(["size", "sum"])

    g = d.groupby(["state", place, "weapon_group", "year"]).solved.agg(["size", "sum"])
    rng = np.random.default_rng(seed)
    results, tested = [], 0
    for (st, p, w), grp in g.groupby(level=[0, 1, 2]):
        grp = grp.droplevel([0, 1, 2]).reindex(years, fill_value=0)
        n, s = grp["size"].to_numpy(float), grp["sum"].to_numpy(float)
        if n.sum() < min_cases:
            continue
        tested += 1
        # Leave-one-out reference: the rest of the state, excluding this place,
        # so a place that dominates its state (Los Angeles) is not compared with itself.
        try:
            rs = ref.loc[(st, w)].reindex(years, fill_value=0)
        except KeyError:
            continue
        rest_n = rs["size"].to_numpy(float) - n
        rest_s = rs["sum"].to_numpy(float) - s
        rest_all = rest_s.sum() / rest_n.sum() if rest_n.sum() > 0 else np.nan
        if not np.isfinite(rest_all):
            continue
        # Shrink each year's rate toward the long-run rate (prior worth `shrink` cases)
        # so thin years can't produce a 100% expectation.
        p0t = np.clip((rest_s + shrink * rest_all) / (rest_n + shrink), 0.02, 0.97)
        # Analytic screen on the best single window before simulating.
        cn = np.concatenate([[0], np.cumsum(n)]); cs = np.concatenate([[0], np.cumsum(s)])
        ce = np.concatenate([[0], np.cumsum(n * p0t)])
        N = cn[wj + 1] - cn[wi]; S = cs[wj + 1] - cs[wi]; E = ce[wj + 1] - ce[wi]
        ok = N >= min_cases
        if not ok.any():
            continue
        pa = binom.cdf(S[ok], N[ok], np.clip(E[ok] / N[ok], 1e-6, 1 - 1e-6)).min()
        if pa > screen_p:
            continue
        for i, j, NN, SS, p0, llr, pv in _scan_group(n, s, p0t, wi, wj, min_cases, reps, rng, top_k):
            results.append(Flag("scan", p, victim_sex, w, int(years[i]), int(years[j]), NN, SS,
                                round(p0, 3), pv, fixes, q_value=None, llr=round(llr, 2),
                                level=place, kind=kind_of(w, NN)))
    if not results:
        return []
    q = bh_qvalues(np.array([f.p_value for f in results]), m=max(tested, len(results)))
    for f, qq in zip(results, q):
        f.q_value = float(qq)
    out = [f for f in results if max_q is None or f.q_value <= max_q]
    return sorted(out, key=lambda f: (f.q_value, -f.llr))
