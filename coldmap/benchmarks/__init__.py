"""Benchmarks: score any detector or ensemble against known, adjudicated series.

The series live in known_series.json so contributors can add cases without
touching code. Add only publicly adjudicated series (conviction, guilty plea or
official attribution), with a note citing the basis.

Your own series (for example converted from a database you have access to under its own terms)
go in COLDMAP_HOME/benchmarks/*.json, or `coldmap series import FILE.csv`. They are used by the
benchmark and the rule-out checks on this computer only, never bundled or uploaded.

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
    label: str = ""   # neutral description for the app: place, victims, years, outcome; no names
    victims: int | None = None   # killings attributed, as stated in the note (None when it doesn't say)
    active: list | None = None   # [[start, end], ...] when the note gives separate active periods
    source: str = "built in"     # "built in", or the local file it came from


REQUIRED = ("name", "state", "county", "victim_sex", "weapons", "start", "end", "arrest", "note")
ADJUDICATED = ("convict", "pleaded", "plea", "guilty", "sentenced", "attribut", "adjudicat")


def check_series(d: dict) -> str | None:
    """Why a series entry can't be used, or None. Only adjudicated series with a stated basis count."""
    missing = [k for k in REQUIRED if d.get(k) in (None, "", [])]
    if missing:
        return f"missing {', '.join(missing)}"
    if not any(w in str(d["note"]).lower() for w in ADJUDICATED):
        return "the note must state the legal basis (conviction, guilty plea or official attribution)"
    if d["victim_sex"] not in ("Female", "Male"):
        return "victim_sex must be Female or Male"
    for k in ("name", "state", "county", "note"):
        if not isinstance(d[k], str):
            return f"{k} must be text"
    for k in ("agency", "label"):
        if d.get(k) is not None and not isinstance(d[k], str):
            return f"{k} must be text"
    if not isinstance(d["weapons"], list) or not all(isinstance(w, str) for w in d["weapons"]):
        return "weapons must be a list of methods"
    for k in ("start", "end", "arrest") + (("victims",) if d.get("victims") is not None else ()):
        if isinstance(d[k], bool) or not isinstance(d[k], int):
            return f"{k} must be a whole number"
    if d["start"] > d["end"]:
        return "start is after end"
    a = d.get("active")
    if a is not None and not (isinstance(a, list) and all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(y, int) and not isinstance(y, bool) for y in p)
            and p[0] <= p[1] for p in a)):
        return "active must be a list of [start, end] years"
    return None


def local_folder() -> Path:
    from ..plugins import home
    return home() / "benchmarks"


def load_local() -> tuple[list[KnownSeries], list[str]]:
    """Your own series files: (usable series, problems found)."""
    series, problems = [], []
    if not local_folder().is_dir():
        return series, problems
    for f in sorted(local_folder().glob("*.json")):
        try:
            entries = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            problems.append(f"{f.name}: couldn't read it ({e})")
            continue
        for i, d in enumerate(entries if isinstance(entries, list) else []):
            why = check_series(d) if isinstance(d, dict) else "not an object"
            if why:
                problems.append(f"{f.name}, entry {i + 1}: {why}")
                continue
            fields = {"agency": None, **{k: d.get(k) for k in KnownSeries.__dataclass_fields__ if k in d and k != "source"}}
            series.append(KnownSeries(**{**fields, "weapons": tuple(d["weapons"]), "source": f.name}))
    return series, problems


def import_csv(csv_path: str | Path, name: str | None = None) -> dict:
    """Turn a CSV of adjudicated series into a local series file. Columns: name, state, county,
    agency, victim_sex, weapons (separated by ;), start, end, arrest, note, label, victims."""
    # UTF-8 (with or without Excel's BOM), else Windows-1252, which Excel on Windows saves "CSV" as.
    for enc in ("utf-8-sig", "cp1252"):
        try:
            df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    entries, problems = [], []
    for i, r in df.iterrows():
        d = {k: (r.get(k) or None) for k in ("name", "state", "county", "agency", "victim_sex", "note", "label")}
        d["weapons"] = [w.strip() for w in str(r.get("weapons", "")).split(";") if w.strip()]
        for k in ("start", "end", "arrest", "victims"):
            v = str(r.get(k, "")).strip()
            d[k] = int(float(v)) if v else None
        why = check_series(d)
        if why:
            problems.append(f"row {i + 2}: {why}")
        else:
            entries.append({k: v for k, v in d.items() if v is not None})
    from ..datasets import slugify
    out = local_folder() / f"{slugify(name or Path(csv_path).stem)}.json"   # never outside the folder
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"file": str(out), "series": len(entries), "problems": problems}


def load_series(path: str | Path | None = None, local: bool = True) -> list[KnownSeries]:
    """The bundled series (or `path`), plus your own from COLDMAP_HOME/benchmarks unless local=False."""
    bundled = _load_file(path)
    return bundled + (load_local()[0] if local and path is None else [])


def _load_file(path: str | Path | None = None) -> list[KnownSeries]:
    text = (Path(path).read_text(encoding="utf-8") if path
            else files(__package__).joinpath("known_series.json").read_text(encoding="utf-8"))
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
