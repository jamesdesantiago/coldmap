"""The shared vocabulary every plugin speaks.

Dataset  normalized case records (+ optional clearance counts) that detectors read
Query    what to look at: state, victim sex, ages, cutoff year
Finding  what a detector reports: a place, method and period with too few solved
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

# Columns every source must provide. Detectors may rely on these and nothing else.
CASE_COLUMNS = {
    "case_id": "Unique record id",
    "state": "Full state name, e.g. California",
    "county": "County label, e.g. 'Riverside, CA'",
    "agency": "Reporting agency name",
    "msa": "Metropolitan area label (may be empty)",
    "year": "Year of death or discovery (int)",
    "month": "1-12, 0 if unknown",
    "solved_raw": "Offender identified when reported, as the source recorded it (bool)",
    "vic_age": "Victim age; 999 = unknown (int)",
    "vic_sex": "Female, Male or Unknown",
    "vic_race": "Source race label",
    "vic_ethnic": "Source ethnicity label",
    "weapon": "Source weapon label",
    "weapon_group": "Grouped method: Gun, Knife, Beating/blunt, Strangle/asphyxia, Fire, "
                    "Other/unknown, Not reported",
    "relationship": "Victim-offender relationship label",
    "circumstance": "Circumstance label",
}
DERIVED_COLUMNS = {"solved": "solved_raw after data fixes (bool)"}
CLEARANCE_COLUMNS = {"state", "county", "agency", "year", "murders", "cleared"}


@dataclass
class Query:
    """What to analyze. Detectors must respect every field they can."""
    state: str | None = None
    victim_sex: str = "Female"
    min_age: int | None = 12            # unknown ages (999) are kept
    as_of: int | None = None            # only use years <= as_of (backtesting)
    exclude_weapons: tuple[str, ...] = ("Not reported",)


class Dataset:
    """Normalized cases plus optional clearance counts, with the data fixes applied."""

    def __init__(self, cases: pd.DataFrame, source: str = "unknown",
                 clearance: pd.DataFrame | None = None, fixes: tuple[str, ...] = ()):
        missing = [c for c in CASE_COLUMNS if c not in cases.columns]
        if missing:
            raise ValueError(f"Dataset is missing required columns: {missing}")
        if "solved" not in cases.columns:
            cases = cases.assign(solved=cases.solved_raw.astype(bool))
        if clearance is not None:
            bad = CLEARANCE_COLUMNS - set(clearance.columns)
            if bad:
                raise ValueError(f"Clearance table is missing columns: {sorted(bad)}")
        self.cases = cases
        self.clearance = clearance
        self.source = source
        self.fixes = fixes

    def select(self, q: Query, *, use_query_age: bool = True, use_exclusions: bool = True) -> pd.DataFrame:
        d = self.cases
        if q.state:
            d = d[d.state == q.state]
        if q.as_of is not None:
            d = d[d.year <= q.as_of]
        d = d[d.vic_sex == q.victim_sex]
        if use_exclusions and q.exclude_weapons:
            d = d[~d.weapon_group.isin(q.exclude_weapons)]
        if use_query_age and q.min_age is not None:
            d = d[d.vic_age >= q.min_age]
        return d

    def __len__(self) -> int:
        return len(self.cases)

    def __repr__(self) -> str:
        return f"Dataset(source={self.source!r}, cases={len(self.cases):,}, fixes={list(self.fixes)})"


@dataclass
class Finding:
    """One flagged place, method and period. A pattern worth review, never a link."""
    detector: str
    place: str
    level: str                          # county, agency, msa, ...
    victim_sex: str
    weapon: str
    start: int
    end: int
    total: int
    solved: int
    expected: float | None = None       # solve rate the detector expected
    p_value: float | None = None
    q_value: float | None = None        # false-discovery-rate adjusted
    score: float | None = None          # detector-specific strength (higher = stronger)
    county: str | None = None
    kind: str | None = None             # serial-pattern or accountability
    found_by: tuple[str, ...] = ()
    confidence: str | None = None       # set by the ensemble
    coverage: float | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def unsolved(self) -> int:
        return self.total - self.solved

    @property
    def solve_rate(self) -> float:
        return self.solved / self.total if self.total else 0.0

    @property
    def span(self) -> int:
        return self.end - self.start + 1

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(unsolved=self.unsolved, solve_rate=round(self.solve_rate, 3))
        return d


def findings_frame(findings: list[Finding]) -> pd.DataFrame:
    return pd.DataFrame([f.to_dict() for f in findings])
