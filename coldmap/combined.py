"""Run several detectors and merge their flags.

Modes
-----
both    scan (strict) + sliding window (sensitive), merged. Default.
scan    scan only: false-alarm controlled, misses series hidden in big counties.
window  sliding window only: catches more, with no false-alarm control.
map     MAP's original algorithm.

In "both" mode, a scan flag and a window flag agree when they share a county
(an agency flag counts for its county), victim sex and weapon group, and their
years overlap. The window flag is also kept as its own finding when the scan
flag spans more than twice as many years, so short bursts aren't absorbed. Each merged flag records `found_by` and a
`confidence`:

high      both detectors agree
strong    scan only: statistically significant after correction
possible  window only: unusual, but not confirmed by the stricter test
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .detect import Flag, map_algorithm, sliding_window

MODES = ("both", "scan", "window", "map")
_RANK = {"high": 0, "strong": 1, "possible": 2}


def _agency_county(df: pd.DataFrame, state: str | None) -> dict[str, str]:
    d = df if state is None else df[df.state == state]
    return d.groupby("agency").county.agg(lambda s: s.mode().iat[0] if len(s.mode()) else None).to_dict()


def _county_of(f: Flag, ac: dict[str, str]) -> str | None:
    return ac.get(f.place) if f.level == "agency" else f.place


def detect_all(df: pd.DataFrame, method: str = "both", state: str | None = None,
               victim_sex: str = "Female", levels: tuple[str, ...] = ("county", "agency"),
               scan_kw: dict | None = None, window_kw: dict | None = None,
               kind: str | None = None) -> list[Flag]:
    """Run the chosen detector(s). Returns flags with found_by, confidence and county set.
    kind: keep only 'serial-pattern' or 'accountability' flags (None keeps both)."""
    flags = _detect_all(df, method, state, victim_sex, levels, scan_kw, window_kw)
    return [f for f in flags if kind is None or f.kind == kind]


def _detect_all(df, method, state, victim_sex, levels, scan_kw, window_kw) -> list[Flag]:
    if method not in MODES:
        raise ValueError(f"method must be one of {MODES}")
    scan_kw = {"max_len": 25, **(scan_kw or {})}
    window_kw = window_kw or {}
    ac = _agency_county(df, state)

    if method == "map":
        out = map_algorithm(df, state=state, victim_sex=victim_sex)
        return [replace(f, found_by=("map",), county=f.place) for f in out]

    scan_flags: list[Flag] = []
    if method in ("both", "scan"):
        from .scan import scan
        for lvl in levels:
            scan_flags += scan(df, state=state, place=lvl, victim_sex=victim_sex, **scan_kw)
        scan_flags = [replace(f, found_by=("scan",), confidence="strong", county=_county_of(f, ac))
                      for f in scan_flags]
    window_flags: list[Flag] = []
    if method in ("both", "window"):
        from .scan import kind_of
        window_flags = [replace(f, found_by=("window",), confidence="possible", county=f.place,
                                kind=kind_of(f.weapon, f.total))
                        for f in sliding_window(df, state=state, victim_sex=victim_sex, **window_kw)]

    if method == "scan":
        return scan_flags
    if method == "window":
        return window_flags

    merged = list(scan_flags)
    for w in window_flags:
        match = [s for s in scan_flags if s.county == w.county and s.weapon == w.weapon
                 and s.victim_sex == w.victim_sex and s.start <= w.end and s.end >= w.start]
        for s in match:
            s.found_by, s.confidence = ("scan", "window"), "high"
        # Keep the window flag as its own finding unless a matching scan flag covers
        # about the same years. A short burst inside a long scan window (the Hillside
        # Stranglers inside 24 years of Los Angeles strangulations) is a different,
        # sharper finding and must not be absorbed.
        w_len = w.end - w.start + 1
        if not any((s.end - s.start + 1) <= 2 * w_len for s in match):
            merged.append(w)
    return sorted(merged, key=lambda f: (_RANK[f.confidence], -f.unsolved))
