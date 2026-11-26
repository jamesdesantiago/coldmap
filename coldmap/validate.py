"""Validation against known, adjudicated serial cases.

A detector that cannot find killers we already know about should not be trusted
to find ones we don't. Each entry is a solved series whose cases still appear as
unsolved in the data (MAP records 'solved' at report time).

Add cases only when they are publicly adjudicated (conviction or official
attribution), and cite the source in `note`.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .detect import Flag, sliding_window


@dataclass(frozen=True)
class KnownSeries:
    name: str
    state: str
    place: str
    victim_sex: str
    weapons: tuple[str, ...]      # weapon groups the victims are likely coded under
    start: int
    end: int
    expect_detected: bool = True  # False = documented blind spot we want to fix
    note: str = ""


KNOWN_SERIES: list[KnownSeries] = [
    KnownSeries("William Suff (Riverside Prostitute Killer)", "California", "Riverside, CA",
                "Female", ("Other/unknown", "Strangle/asphyxia", "Knife"), 1986, 1991,
                note="Convicted 1995 of 12 murders in Riverside County, 1986-1991."),
    KnownSeries("Hillside Stranglers (Bianchi and Buono)", "California", "Los Angeles, CA",
                "Female", ("Strangle/asphyxia",), 1977, 1978,
                note="Strangulations of women in Los Angeles, 1977-1978; both convicted."),
    KnownSeries("Golden State Killer, Orange County murders", "California", "Orange, CA",
                "Female", ("Beating/blunt",), 1980, 1981,
                note="Joseph DeAngelo bludgeoned victims in Orange County 1980-1981; pleaded guilty 2020."),
    KnownSeries("Gary Ridgway (Green River Killer)", "Washington", "King, WA",
                "Female", ("Other/unknown", "Strangle/asphyxia"), 1982, 1984,
                note="Pleaded guilty 2003 to 48 murders, most in King County 1982-1984. "
                     "Used by MAP to develop its algorithm."),
    KnownSeries("Darren Vann (Gary, Indiana)", "Indiana", "Lake, IN",
                "Female", ("Strangle/asphyxia",), 1994, 2014, expect_detected=False,
                note="Strangulations spread thinly over ~20 years. MAP's original county "
                     "grouping flagged Gary; coldmap's 4-year windows currently miss it. "
                     "Known blind spot: slow, long-running series."),
]


def detected_by(series: KnownSeries, flags: list[Flag]) -> list[Flag]:
    return [f for f in flags if f.place == series.place and f.victim_sex == series.victim_sex
            and f.weapon in series.weapons and f.start <= series.end and f.end >= series.start]


def run_validation(df: pd.DataFrame, **detector_kwargs) -> pd.DataFrame:
    """Run sliding_window on each known series' state and report hits and misses."""
    rows = []
    cache: dict[str, list[Flag]] = {}
    for s in KNOWN_SERIES:
        if s.state not in cache:
            cache[s.state] = sliding_window(df, state=s.state, **detector_kwargs)
        hits = detected_by(s, cache[s.state])
        best = max(hits, key=lambda f: f.unsolved) if hits else None
        rows.append({
            "series": s.name, "place": s.place, "years": f"{s.start}-{s.end}",
            "detected": bool(hits), "expected": s.expect_detected,
            "ok": bool(hits) == s.expect_detected or bool(hits),
            "best_flag": (f"{best.weapon} {best.start}-{best.end}: {best.solved}/{best.total} solved"
                          if best else ""),
        })
    return pd.DataFrame(rows)
