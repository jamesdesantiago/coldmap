"""Statistics shared by detectors: scan likelihood ratios, Monte Carlo, FDR."""

from __future__ import annotations

import numpy as np


def llr(S, N, p0):
    """Binomial log-likelihood ratio for 'solve rate lower than p0'. Arrays broadcast."""
    with np.errstate(divide="ignore", invalid="ignore"):
        q = S / N
        a = np.where(S > 0, S * np.log(q / p0), 0.0)
        b = np.where(N - S > 0, (N - S) * np.log((1 - q) / (1 - p0)), 0.0)
        out = a + b
    return np.where((N > 0) & (q < p0), out, 0.0)


def windows(T, min_len, max_len):
    i, j = np.triu_indices(T)
    L = j - i + 1
    keep = (L >= min_len) & (L <= max_len)
    return i[keep], j[keep]


def scan_group(n, s, p0t, wi, wj, min_cases, reps, rng, top_k=3):
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
    ratio = llr(S, N, p0)
    if ratio.max() <= 0:
        return []
    sims = rng.binomial(n.astype(int), np.clip(p0t, 0, 1), size=(reps, len(n)))
    csim = np.concatenate([np.zeros((reps, 1)), np.cumsum(sims, axis=1)], axis=1)
    best = llr(csim[:, wj + 1] - csim[:, wi], N, p0).max(axis=1)
    out, taken = [], np.zeros(len(n), bool)
    for k in np.argsort(-ratio):
        if len(out) >= top_k or ratio[k] <= 0:
            break
        if taken[wi[k]:wj[k] + 1].any():
            continue
        taken[wi[k]:wj[k] + 1] = True
        p = (1 + int((best >= ratio[k]).sum())) / (reps + 1)
        out.append((wi[k], wj[k], int(N[k]), int(S[k]), float(p0[k]), float(ratio[k]), p))
    return out


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


