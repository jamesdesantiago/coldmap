"""Reporting coverage: how much of a place's murders actually made it into the case file.

The clearance file (UCR65_25) counts murders each agency reported in summary
form. The case file (SHR) only has the murders agencies also reported in detail.
Where the case file holds far fewer cases than the clearance file, clusters can
hide in the gap, and a flag's solve rate rests on partial data.

coverage = case-file murders / clearance-file murders for the flag's place and years.
"""

from __future__ import annotations

import pandas as pd

from .detect import Flag


def coverage_table(shr: pd.DataFrame, clearance: pd.DataFrame, level: str = "county") -> pd.DataFrame:
    """Case-file vs clearance-file counts by place and year. level: county or agency."""
    key = "county" if level == "county" else "agency"
    a = shr.groupby(["state", key, "year"]).size().rename("case_file")
    c = clearance.rename(columns={"county": "county", "agency": "agency"})
    b = c.groupby(["state", key, "year"]).murders.sum().rename("clearance_file")
    t = pd.concat([a, b], axis=1).fillna(0)
    t = t[t.index.get_level_values("year") >= shr.year.min()].sort_index()  # case file starts 1976
    t["coverage"] = (t.case_file / t.clearance_file).where(t.clearance_file > 0)
    return t


def add_coverage(flags: list[Flag], shr: pd.DataFrame, clearance: pd.DataFrame,
                 state: str) -> list[Flag]:
    """Attach coverage to each flag (None where the clearance file has no match)."""
    tables = {}
    for f in flags:
        level = "agency" if f.level == "agency" else "county"
        if level not in tables:
            tables[level] = coverage_table(shr[shr.state == state],
                                           clearance[clearance.state == state], level)
        t = tables[level]
        try:
            rows = t.loc[(state, f.place)].loc[f.start:f.end]
        except KeyError:
            continue
        if rows.clearance_file.sum() > 0:
            f.coverage = round(float(rows.case_file.sum() / rows.clearance_file.sum()), 2)
    return flags


def low_coverage_places(shr: pd.DataFrame, clearance: pd.DataFrame, state: str,
                        min_murders: int = 50, below: float = 0.8) -> pd.DataFrame:
    """Places whose case file covers less than `below` of reported murders, by decade."""
    t = coverage_table(shr[shr.state == state], clearance[clearance.state == state]).reset_index()
    t["decade"] = (t.year // 10) * 10
    g = t.groupby(["county", "decade"])[["case_file", "clearance_file"]].sum()
    g = g[g.clearance_file >= min_murders]
    g["coverage"] = (g.case_file / g.clearance_file).round(2)
    return g[g.coverage < below].sort_values("coverage").reset_index()
