"""Benchmarks: score any detector or ensemble against known, adjudicated series.

The series live in known_series.json so contributors can add cases without
touching code. Add only publicly adjudicated series (conviction, guilty plea or
official attribution), with a note citing the basis.

evaluate()  did each detector (and the ensemble) flag each series, using all data?
            'full' = the finding covers most of the series' years and isn't much longer;
            'partial' = it touches the series but mostly describes something else.
backtest()  using only data available at the time, when would it first have flagged it?
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import pandas as pd

from ..core.types import Dataset, Finding, Query
from ..detectors import DETECTORS
from ..ensemble import DEFAULT_DETECTORS, Ensemble
from ..enrichers import enrich


@dataclass(frozen=True)
class KnownSeries:
    name: str
    state: str
    county: str
    agency: str | None
    victim_sex: str
    weapons: tuple[str, ...]
    start: int
    end: int
    arrest: int
    note: str = ""


def load_series(path: str | Path | None = None) -> list[KnownSeries]:
    text = Path(path).read_text() if path else files(__package__).joinpath("known_series.json").read_text()
    return [KnownSeries(**{**d, "weapons": tuple(d["weapons"])}) for d in json.loads(text)]


GROUPS = {"Gun", "Knife", "Beating/blunt", "Strangle/asphyxia", "Fire", "Other/unknown", "Not reported"}


def _group(weapon: str) -> str:
    from ..sources.map_files import WEAPON_GROUPS
    return weapon if weapon in GROUPS else WEAPON_GROUPS.get(weapon, "Other/unknown")


def hit(series: KnownSeries, findings: list[Finding]) -> list[Finding]:
    places = {series.county, series.agency} - {None}
    return [f for f in findings if (f.place in places or f.county == series.county
                                    or series.county in f.extras.get("counties", ()))
            and f.victim_sex == series.victim_sex and _group(f.weapon) in series.weapons
            and f.start <= series.end and f.end >= series.start and f.kind in (None, "serial-pattern")]


def grade(series: KnownSeries, f: Finding) -> str:
    """'full' if the finding covers at least half the series' years without being much longer than
    the series; otherwise 'partial' (it touches the series but mostly describes something else)."""
    s_span = series.end - series.start + 1
    overlap = min(f.end, series.end) - max(f.start, series.start) + 1
    tight = f.span <= max(2 * s_span, s_span + 6)
    return "full" if overlap / s_span >= 0.5 and tight else "partial"


def best_hit(series: KnownSeries, findings: list[Finding]):
    hits = hit(series, findings)
    if not hits:
        return None, None
    best = max(hits, key=lambda f: (grade(series, f) == "full", f.unsolved))
    return best, grade(series, best)


def _runner(name: str, params: dict):
    if name == "ensemble":
        ens = Ensemble.from_names(params.get("detectors", DEFAULT_DETECTORS), params.get("params"))
        return lambda data, q: ens.run(data, q)
    det = DETECTORS.get(name)(**params)
    return lambda data, q: enrich(det.detect(data, q), data)


def evaluate(data: Dataset, detectors=(*DEFAULT_DETECTORS, "ensemble"), params: dict | None = None,
             series: list[KnownSeries] | None = None) -> pd.DataFrame:
    params = params or {}
    series = series or load_series()
    rows, cache = [], {}
    for s in series:
        row = {"series": s.name, "years": f"{s.start}-{s.end}"}
        for name in detectors:
            key = (name, s.state, s.victim_sex)
            if key not in cache:
                cache[key] = _runner(name, params.get(name, {}))(data, Query(state=s.state, victim_sex=s.victim_sex))
            best, g = best_hit(s, cache[key])
            row[name] = ("missed" if best is None else
                         f"{g}: {best.place}, {best.weapon} {best.start}-{best.end}, {best.solved}/{best.total} solved"
                         + (f" [{best.confidence}]" if best.confidence else ""))
        rows.append(row)
    out = pd.DataFrame(rows)
    caught = {d: f"{out[d].str.startswith('full').sum()} full, {out[d].str.startswith('partial').sum()} partial "
                 f"of {len(out)}" for d in detectors}
    return pd.concat([out, pd.DataFrame([{"series": "RECOVERED", "years": "", **caught}])], ignore_index=True)


def evaluate_records(data: Dataset, detectors=(*DEFAULT_DETECTORS, "ensemble"), params: dict | None = None,
                     series: list[KnownSeries] | None = None) -> list[dict]:
    """Like evaluate(), but structured: one record per series with a result per detector."""
    params = params or {}
    series = series or load_series()
    cache, out = {}, []
    for s in series:
        rec = {"name": s.name, "state": s.state, "county": s.county, "victim_sex": s.victim_sex,
               "start": s.start, "end": s.end, "arrest": s.arrest, "note": s.note, "results": {}}
        for name in detectors:
            key = (name, s.state, s.victim_sex)
            if key not in cache:
                cache[key] = _runner(name, params.get(name, {}))(data, Query(state=s.state, victim_sex=s.victim_sex))
            best, g = best_hit(s, cache[key])
            rec["results"][name] = None if best is None else {
                "grade": g, "place": best.place, "level": best.level, "weapon": best.weapon,
                "start": best.start, "end": best.end, "solved": best.solved, "total": best.total,
                "confidence": best.confidence}
        out.append(rec)
    return out


def backtest(data: Dataset, s: KnownSeries, detector: str = "ensemble", params: dict | None = None,
             years_after: int = 3) -> dict:
    """First year `detector` flags series `s` using only data up to that year."""
    run = _runner(detector, params or {})
    first = None
    for y in range(s.start, s.end + years_after + 1):
        if hit(s, run(data, Query(state=s.state, victim_sex=s.victim_sex, as_of=y))):
            first = y
            break
    return {"series": s.name, "detector": detector, "series_years": f"{s.start}-{s.end}",
            "arrest": s.arrest, "first_flagged": first,
            "lead_time_years": (s.arrest - first) if first else None}


def backtest_all(data: Dataset, detectors=(*DEFAULT_DETECTORS, "ensemble"), params: dict | None = None,
                 series: list[KnownSeries] | None = None) -> pd.DataFrame:
    params = params or {}
    return pd.DataFrame([backtest(data, s, d, params.get(d, {}))
                         for s in (series or load_series()) for d in detectors])
