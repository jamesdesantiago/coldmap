"""Registry of known data problems and the fixes coldmap applies.

Each issue is documented in DATA_ISSUES.md. Detectors report which fixes were
applied so every result says what was changed. To add an issue: write a fix
function, add an Issue entry, document it, and add a test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class Issue:
    id: str
    title: str
    summary: str
    fix: Callable[[pd.DataFrame], pd.DataFrame] | None  # None = caveat only, no data change


def _fix_2021_relationship(df: pd.DataFrame) -> pd.DataFrame:
    # In 2021 many reports (mostly California) record the offender as unknown,
    # which MAP reads as unsolved, while naming the victim-offender relationship.
    # A named relationship (wife, girlfriend, acquaintance) implies police knew
    # who the offender was. We treat those as solved.
    known_rel = df.relationship.ne("Relationship not determined")
    df["solved"] = df.solved | (~df.solved & known_rel & df.year.eq(2021))
    return df


ISSUES: list[Issue] = [
    Issue(
        id="solved-at-report",
        title="'Solved' means solved when the report was filed",
        summary=("MAP marks a case solved if the offender's sex was known when the agency "
                 "filed its report. Cases solved later stay unsolved, so known serial "
                 "killings still appear as unsolved clusters."),
        fix=None,
    ),
    Issue(
        id="2021-relationship-coding",
        title="2021 reports with unknown offender but a named relationship",
        summary=("In 2021, about 1,300 reports nationally (about 1,100 in California) list the "
                 "offender as unknown yet name the relationship to the victim. That is ~51% of "
                 "California's 'unsolved' 2021 cases versus ~2% in other years. Likely tied to "
                 "the FBI's 2021 move to NIBRS. Fix: count those 2021 cases as solved."),
        fix=_fix_2021_relationship,
    ),
]


def apply_fixes(df: pd.DataFrame, skip: tuple[str, ...] = ()) -> tuple[pd.DataFrame, list[str]]:
    """Return a copy with a `solved` column after fixes, plus the ids of fixes applied."""
    out = df.copy()
    out["solved"] = out.solved_raw.astype(bool)
    applied = []
    for issue in ISSUES:
        if issue.fix is None or issue.id in skip:
            continue
        out = issue.fix(out)
        applied.append(issue.id)
    return out, applied
