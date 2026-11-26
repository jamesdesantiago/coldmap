"""Validation and backtesting against known, adjudicated serial cases.

A detector that cannot find killers we already know about should not be trusted
to find ones we don't. Each entry is a solved series whose cases still appear as
unsolved in the data (MAP records 'solved' at report time).

Backtesting asks the more useful question: using only the data available at the
time, in what year would the detector first have flagged the series? The gap
between that year and the arrest is the lead time the tool could have given.

Add series only when they are publicly adjudicated (conviction, guilty plea or
official attribution), and cite the source in `note`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .detect import Flag, sliding_window


@dataclass(frozen=True)
class KnownSeries:
    name: str
    state: str
    county: str
    agency: str | None            # agency that reported most victims, if one dominates
    victim_sex: str
    weapons: tuple[str, ...]      # weapon groups the victims are likely coded under
    start: int
    end: int
    arrest: int                   # year the offender was arrested
    note: str = ""


KNOWN_SERIES: list[KnownSeries] = [
    KnownSeries("William Suff (Riverside Prostitute Killer)", "California", "Riverside, CA",
                "Riverside County", "Female", ("Other/unknown", "Strangle/asphyxia", "Knife"),
                1986, 1991, 1992, "Convicted 1995 of 12 murders in Riverside County, 1986-1991."),
    KnownSeries("Hillside Stranglers (Bianchi and Buono)", "California", "Los Angeles, CA",
                "Los Angeles", "Female", ("Strangle/asphyxia",), 1977, 1978, 1979,
                "Strangulations of women in Los Angeles, 1977-1978; both convicted."),
    KnownSeries("Golden State Killer, Orange County murders", "California", "Orange, CA",
                None, "Female", ("Beating/blunt",), 1980, 1981, 2018,
                "Joseph DeAngelo bludgeoned victims in Orange County 1980-1981; pleaded guilty 2020."),
    KnownSeries("Gary Ridgway (Green River Killer)", "Washington", "King, WA", "King County",
                "Female", ("Other/unknown", "Strangle/asphyxia"), 1982, 1984, 2001,
                "Pleaded guilty 2003 to 48 murders, most in King County 1982-1984. "
                "Used by MAP to develop its algorithm."),
    KnownSeries("Darren Vann (Gary, Indiana)", "Indiana", "Lake, IN", "Gary", "Female",
                ("Strangle/asphyxia",), 1994, 2014, 2014,
                "Strangulations spread thinly over ~20 years; identified after MAP's algorithm "
                "flagged Gary. Missed by 4-year windows; caught by the scan detector."),
]


def _hit(series: KnownSeries, flags: list[Flag]) -> list[Flag]:
    places = {series.county, series.agency}
    return [f for f in flags if f.place in places and f.victim_sex == series.victim_sex
            and f.weapon in series.weapons and f.start <= series.end and f.end >= series.start
            and (f.kind in (None, "serial-pattern"))]


def _detect(df, series, detector, as_of=None, **kw):
    if detector == "both":
        from .combined import detect_all
        d = df if as_of is None else df[df.year <= as_of]
        levels = ("county", "agency") if series.agency else ("county",)
        scan_kw = {k: v for k, v in kw.items() if k in ("reps", "max_len", "max_q", "min_cases")}
        return detect_all(d, "both", state=series.state, levels=levels, scan_kw=scan_kw)
    if detector == "window":
        d = df if as_of is None else df[df.year <= as_of]
        return sliding_window(d, state=series.state, **kw)
    from .scan import scan
    flags = scan(df, state=series.state, place="county", as_of=as_of, **kw)
    if series.agency:
        flags += scan(df, state=series.state, place="agency", as_of=as_of, **kw)
    return flags


def run_validation(df: pd.DataFrame, detectors=("window", "scan", "both"), **kw) -> pd.DataFrame:
    """Did each detector flag each known series, using all data?"""
    rows = []
    cache: dict = {}
    for s in KNOWN_SERIES:
        row = {"series": s.name, "years": f"{s.start}-{s.end}"}
        for det in detectors:
            key = (det, s.state, s.agency is not None)
            if key not in cache:
                cache[key] = _detect(df, s, det, **kw.get(det, {}))
            hits = _hit(s, cache[key])
            best = max(hits, key=lambda f: f.unsolved) if hits else None
            row[det] = (f"{best.place}: {best.weapon} {best.start}-{best.end}, "
                        f"{best.solved}/{best.total} solved"
                        + (f" [{best.confidence}]" if best.confidence else "") if best else "missed")
        rows.append(row)
    return pd.DataFrame(rows)


def backtest(df: pd.DataFrame, series: KnownSeries, detector: str = "scan",
             years_after: int = 3, **kw) -> dict:
    """First year the detector would have flagged the series using only data up to that year."""
    first = None
    for y in range(series.start, series.end + years_after + 1):
        if _hit(series, _detect(df, series, detector, as_of=y, **kw)):
            first = y
            break
    return {"series": series.name, "detector": detector, "series_years": f"{series.start}-{series.end}",
            "arrest": series.arrest, "first_flagged": first,
            "lead_time_years": (series.arrest - first) if first else None}


def run_backtests(df: pd.DataFrame, detectors=("window", "scan", "both"), **kw) -> pd.DataFrame:
    return pd.DataFrame([backtest(df, s, det, **kw.get(det, {}))
                         for s in KNOWN_SERIES for det in detectors])
