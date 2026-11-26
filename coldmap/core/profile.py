"""Optional victim-profile dimensions detectors can split by.

Serial offenders often target a type of victim (Suff and Ridgway: young women
in sex work). Splitting by profile can sharpen a signal, at the cost of smaller
groups (so pair it with the false-discovery control in `scan`).

Not offered, on purpose:
- Race and ethnicity: race-based clusters risk spotlighting communities and are
  easy to misuse.
- Circumstance: it is circular. Police record "circumstances undetermined"
  largely *because* a case is unsolved, so splitting by circumstance creates
  clusters out of the coding itself, and negative controls can't detect it
  (shuffling solved labels breaks the very link that causes the bias).
A plugin can add other dimensions, but should show it avoids these traps.
"""

from __future__ import annotations

import pandas as pd

AGE_BANDS = [(12, 17, "12-17"), (18, 29, "18-29"), (30, 44, "30-44"), (45, 200, "45+")]

PROFILE_COLUMNS = ("age_band",)


def _age_band(a: int) -> str:
    if a >= 999:
        return "unknown"
    for lo, hi, label in AGE_BANDS:
        if lo <= a <= hi:
            return label
    return "under 12"


def add_profile(d: pd.DataFrame, columns) -> pd.DataFrame:
    """Return d with any requested profile columns added (no copy if none requested)."""
    cols = [c for c in columns if c not in d.columns]
    if not cols:
        return d
    d = d.copy()
    for c in cols:
        if c == "age_band":
            d[c] = d.vic_age.map(_age_band)
        else:
            raise ValueError(f"Unknown profile column {c!r}; available: {PROFILE_COLUMNS}")
    return d
