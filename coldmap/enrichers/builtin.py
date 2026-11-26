from __future__ import annotations

import weakref

import pandas as pd

from . import ENRICHERS, Enricher

SERIAL_METHODS = {"Strangle/asphyxia", "Beating/blunt", "Knife", "Other/unknown", "Fire",
                  "Strangulation - hanging", "Asphyxiation - includes death by gas",
                  "Knife or cutting instrument", "Blunt object - hammer, club, etc",
                  "Personal weapons, includes beating", "Other or type unknown"}


def kind_of(weapon: str, total: int, max_series: int = 100) -> str:
    """serial-pattern: methods typical of serial homicide, in a group small enough to be one
    offender's work. accountability: guns or large groups (a place solving fewer cases)."""
    return "serial-pattern" if weapon in SERIAL_METHODS and total <= max_series else "accountability"


_MEMO: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _memo(data, key, fn):
    """Per-Dataset cache: national tables are reused across every finding and every run."""
    m = _MEMO.setdefault(data, {})
    if key not in m:
        m[key] = fn()
    return m[key]


def county_of(cases: pd.DataFrame, level: str) -> pd.Series:
    """Most common county for each place at `level` (ties: first alphabetically, as Series.mode)."""
    n = cases.groupby([level, "county"]).size().rename("n").reset_index()
    n = n.sort_values(["n", "county"], ascending=[False, True], kind="mergesort")
    return n.drop_duplicates(level).set_index(level).county


@ENRICHERS.register
class CountyEnricher(Enricher):
    name = "county"
    summary = "Set the county of agency- and metro-level findings"

    def enrich(self, findings, data):
        need = {f.level for f in findings if f.county is None and f.level != "county"}
        maps = {lvl: _memo(data, ("county_of", lvl), lambda lvl=lvl: county_of(data.cases, lvl))
                for lvl in need if lvl in data.cases.columns}
        for f in findings:
            if f.county is None:
                f.county = f.place if f.level == "county" else maps.get(f.level, {}).get(f.place)
        return findings


@ENRICHERS.register
class KindEnricher(Enricher):
    name = "kind"
    summary = "Label findings serial-pattern or accountability"

    def enrich(self, findings, data):
        for f in findings:
            f.kind = f.kind or kind_of(f.weapon, f.total)
        return findings


def coverage_table(cases: pd.DataFrame, clearance: pd.DataFrame, level: str = "county") -> pd.DataFrame:
    """Case-file vs clearance-file murders by state, place and year."""
    a = cases.groupby(["state", level, "year"]).size().rename("case_file")
    b = clearance.groupby(["state", level, "year"]).murders.sum().rename("clearance_file")
    t = pd.concat([a, b], axis=1).fillna(0)
    t = t[t.index.get_level_values("year") >= cases.year.min()].sort_index()
    t["coverage"] = (t.case_file / t.clearance_file).where(t.clearance_file > 0)
    return t


@ENRICHERS.register
class CoverageEnricher(Enricher):
    name = "coverage"
    summary = "Share of the place's reported murders present in the case file (needs clearance data)"

    def enrich(self, findings, data):
        if data.clearance is None:
            return findings
        tables = {}
        for f in findings:
            level = f.level if f.level in ("county", "agency") else "county"
            place = f.place if level == f.level else f.county
            if level not in tables:
                tables[level] = _memo(data, ("coverage", level),
                                      lambda: coverage_table(data.cases, data.clearance, level))
            t = tables[level]
            rows = t[(t.index.get_level_values(1) == place)]
            rows = rows[(rows.index.get_level_values(2) >= f.start) & (rows.index.get_level_values(2) <= f.end)]
            if rows.clearance_file.sum() > 0:
                f.coverage = round(float(rows.case_file.sum() / rows.clearance_file.sum()), 2)
        return findings


def low_coverage_places(data, state: str, min_murders: int = 50, below: float = 0.8) -> pd.DataFrame:
    """Counties and decades where the case file holds less than `below` of reported murders."""
    if data.clearance is None:
        raise ValueError("Load the dataset with clearance data to check coverage")
    t = coverage_table(data.cases[data.cases.state == state],
                       data.clearance[data.clearance.state == state]).reset_index()
    t["decade"] = (t.year // 10) * 10
    g = t.groupby(["county", "decade"])[["case_file", "clearance_file"]].sum()
    g = g[g.clearance_file >= min_murders]
    g["coverage"] = (g.case_file / g.clearance_file).round(2)
    return g[g.coverage < below].sort_values("coverage").reset_index()
