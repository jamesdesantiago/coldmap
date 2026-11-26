"""Data fixes and caveats, as plugins.

A Fix corrects a known problem in a source's data before any detector sees it.
A fix with `apply=None` is a caveat: documented and reported, no data change.
Every fix is listed in DATA_ISSUES.md and has a test.

Add one:

    from coldmap.fixes import FIXES, Fix

    def _apply(df):
        ...
        return df

    FIXES.register(Fix("my-fix", "Short title", "What, where, why.", _apply))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from ..core.registry import Registry


@dataclass(frozen=True)
class Fix:
    name: str
    title: str
    summary: str
    apply: Callable[[pd.DataFrame], pd.DataFrame] | None = None
    sources: tuple[str, ...] = ("map-shr",)   # sources this fix applies to


FIXES: Registry[Fix] = Registry("fix", "coldmap.fixes")


def _fix_2021_relationship(df: pd.DataFrame) -> pd.DataFrame:
    known_rel = df.relationship.ne("Relationship not determined")
    df["solved"] = df.solved | (~df.solved & known_rel & df.year.eq(2021))
    return df


FIXES.register(Fix(
    "solved-at-report", "'Solved' means solved when the report was filed",
    "A case is solved if the offender was identified when the agency filed its report. Cases "
    "solved later stay unsolved, so known serial killings still appear as unsolved clusters.",
))
FIXES.register(Fix(
    "2021-relationship-coding", "2021 reports with unknown offender but a named relationship",
    "In 2021, about 1,300 reports nationally (about 1,100 in California) list the offender as "
    "unknown yet name the relationship to the victim: ~51% of California's 'unsolved' 2021 cases "
    "versus ~2% in other years. Likely tied to the FBI's 2021 move to NIBRS. Fix: count those "
    "2021 cases as solved.",
    _fix_2021_relationship,
))


def apply_fixes(cases: pd.DataFrame, source: str, skip: tuple[str, ...] = ()) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """Return cases with a `solved` column after every applicable fix, and the fixes applied."""
    out = cases.copy()
    out["solved"] = out.solved_raw.astype(bool)
    applied = []
    for name, fix in FIXES:
        if fix.apply is None or name in skip or source not in fix.sources:
            continue
        out = fix.apply(out)
        applied.append(name)
    return out, tuple(applied)
