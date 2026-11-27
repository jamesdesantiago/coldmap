"""Build the static explorer site (index.html + agg.json + cases.json) for one state.

The page knows nothing about specific detectors: it shows whatever detectors
were run here, each on its own and combined, from the metadata written below.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

from ...core.types import Dataset, Query
from ...detectors import DETECTORS
from ...enrichers import enrich
from ...explain import explain
from ...ensemble import DEFAULT_DETECTORS, Ensemble
from ...sources.map_files import WEAPON_GROUPS

WEAPONS = ["Gun", "Knife", "Beating/blunt", "Strangle/asphyxia", "Fire", "Other/unknown", "Not reported"]
CONF = ["high", "strong", "possible"]
# What build_site reports to its `progress` callback, in order (key, plain-language label).
BUILD_STEPS = [("count", "Count cases by county and year"),
               ("women", "Search for clusters among women"),
               ("men", "Search for clusters among men"),
               ("explain", "Write plain-language explanations"),
               ("quality", "Check data quality"),
               ("save", "Save the explorer")]


def _group(w: str) -> str:
    return w if w in WEAPONS else WEAPON_GROUPS.get(w, "Other/unknown")


def plugin_catalog() -> dict:
    """Everything registered, for the app's Plugins section."""
    from ... import DETECTORS, ENRICHERS, FIXES, PRESETS, REGIONS, SOURCES
    from ...quality import CHECKS
    return {
        "detectors": [c.describe() for _, c in DETECTORS],
        "presets": [{"name": n, "summary": p.summary, "detectors": list(p.detectors), "params": p.params}
                    for n, p in PRESETS],
        "enrichers": [{"name": n, "summary": c.summary} for n, c in ENRICHERS],
        "fixes": [{"name": n, "title": f.title, "summary": f.summary, "changes_data": f.apply is not None,
                   "states": list(f.states), "years": list(f.years) if f.years else None} for n, f in FIXES],
        "checks": [{"name": n, "summary": c.summary, "needs_clearance": c.needs_clearance} for n, c in CHECKS],
        "regions": [{"name": n, "state": r.state, "note": r.note,
                     "regions": {k: list(v) for k, v in r.regions.items()}} for n, r in REGIONS],
        "sources": [{"name": n, "summary": c.summary} for n, c in SOURCES],
    }


def _quality(data: Dataset, state: str) -> dict:
    from ...quality import CHECKS, report
    out = {}
    for name, t in report(data, state, top=8).items():
        out[name] = {"summary": CHECKS.get(name).summary,
                     "rows": json.loads(t.to_json(orient="records"))}
    return out


def _json_or_none(path):
    return json.loads(Path(path).read_text()) if path and Path(path).exists() else None


def build_site(data: Dataset, state: str, out_dir: Path, detectors=DEFAULT_DETECTORS,
               params: dict | None = None, profiles: bool = True,
               benchmark_file: str | Path | None = None, controls_file: str | Path | None = None,
               progress=None, enrichers: tuple[str, ...] | None = None) -> Path:
    """Build the app. benchmark_file / controls_file are JSON written by
    `coldmap benchmark --json` and `coldmap controls --json` (optional; shown if given).
    progress, if given, is called with each BUILD_STEPS key as that step starts.
    enrichers: which enrichers to run (default: the built-in defaults)."""
    params = params or {}
    step = progress or (lambda key: None)
    step("count")
    d = data.cases[(data.cases.state == state) & data.cases.county.notna()].copy()
    if d.empty:
        raise ValueError(f"No cases for state {state!r}. Use the full name, e.g. 'California'.")
    d["wi"] = d.weapon_group.map(WEAPONS.index)
    d["ad"] = (d.vic_age >= 12).astype(int)
    d["sx"] = d.vic_sex.map({"Female": 0, "Male": 1}).fillna(2).astype(int)
    d["s"] = d.solved.astype(int)
    counties = sorted(d.county.unique())
    cidx = {c: i for i, c in enumerate(counties)}
    d["ci"] = d.county.map(cidx)
    agg = (d.groupby(["ci", "sx", "ad", "wi", "year"]).agg(t=("s", "size"), s=("s", "sum"))
             .reset_index().values.tolist())

    f = d[d.sx == 0]
    lists = {k: sorted(f[col].astype(str).unique()) for k, col in
             [("agencies", "agency"), ("rel", "relationship"), ("circ", "circumstance"),
              ("weaponRaw", "weapon"), ("race", "vic_race")]}
    idx = {k: {v: i for i, v in enumerate(vals)} for k, vals in lists.items()}
    cases = [[int(r.ci), int(r.year), int(r.month), idx["agencies"][str(r.agency)], int(r.s),
              int(r.vic_age), idx["race"][str(r.vic_race)], int(r.wi), idx["weaponRaw"][str(r.weapon)],
              idx["circ"][str(r.circumstance)], idx["rel"][str(r.relationship)]] for r in f.itertuples()]

    # Run each detector once per victim sex; combine for the ensemble view.
    ekw = {"enrichers": tuple(enrichers)} if enrichers else {}
    ens = Ensemble.from_names(detectors, params, **ekw)
    names = [x.name for x in ens.detectors]
    views = {"ensemble": {}, **{n: {} for n in names}}
    prof = None
    if profiles:
        from ...presets import resolve
        pd_, pp_ = resolve("profiles")
        prof = Ensemble.from_names(pd_, pp_, **ekw)
        views["profiles"] = {}
    for sx, sex in ((0, "Female"), (1, "Male")):
        step("women" if sx == 0 else "men")
        q = Query(state=state, victim_sex=sex)
        found = {det.name: enrich(det.detect(data, q), data, ens.enrichers) for det in ens.detectors}
        views["ensemble"][sx] = ens.combine(copy.deepcopy(found))
        for n in names:
            views[n][sx] = Ensemble([x for x in ens.detectors if x.name == n]).combine(copy.deepcopy({n: found[n]}))
        if prof:
            views["profiles"][sx] = prof.run(data, q)

    busy = d.county.value_counts()

    def row(fd):
        cs = [cidx[x] for x in fd.extras.get("counties", []) if x in cidx] if fd.level == "region" else []
        if cs:
            c = cidx[max((counties[i] for i in cs), key=lambda x: busy.get(x, 0))]
        else:
            c = cidx.get(fd.county)
        if c is None:
            return None
        return [c, fd.place if fd.level != "county" else None, WEAPONS.index(_group(fd.weapon)),
                fd.start, fd.end, fd.total, fd.solved, fd.expected,
                None if fd.q_value is None else round(fd.q_value, 4),
                [names.index(x) for x in fd.found_by if x in names], CONF.index(fd.confidence), fd.kind,
                {k.split("-")[1]: [v["count"], v["typical"]] for k, v in fd.extras.items()
                 if k.startswith("namus-") and isinstance(v, dict)} or None,
                {k: v for k, v in explain(fd, data).items()
                 if k in ("what", "agreement", "statistics", "data", "cases", "namus", "plugins")},
                fd.extras.get("profile", {}).get("age_band"), cs or None]

    step("explain")
    findings = {v: {sx: [r for r in map(row, fl) if r] for sx, fl in by.items()} for v, by in views.items()}
    step("quality")
    quality = _quality(data, state)
    step("save")
    strip = counties[0][counties[0].rfind(","):] if "," in counties[0] else ""
    busiest = d.county.value_counts().index[0]
    meta = {
        "state": state, "years": [int(d.year.min()), int(d.year.max())],
        "counties": [c.removesuffix(strip) for c in counties], "defaultCounty": busiest.removesuffix(strip),
        "weapons": WEAPONS, "confidence": CONF, "fixes": list(data.fixes), **lists,
        "detectors": [{"name": x.name, "summary": x.summary, "tier": x.tier} for x in ens.detectors],
        "views": ([{"id": "ensemble", "label": "Balanced", "kind": "preset",
                    "summary": "All detectors combined, labeled by agreement"}]
                  + ([{"id": "profiles", "label": "By age band", "kind": "preset",
                       "summary": "Combined, split by victim age band"}] if prof else [])
                  + [{"id": x.name, "label": x.name, "kind": "detector", "tier": x.tier, "summary": x.summary}
                     for x in ens.detectors]),
        "findings": findings,
        "plugins": plugin_catalog(),
        "quality": quality,
        "benchmark": _json_or_none(benchmark_file),
        "controls": _json_or_none(controls_file),
        "namus": {k: len(v) for k, v in getattr(data, "aux", {}).items()},
        "cases_total": int(len(d)),
        "national_cases": int(len(data.cases)),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "agg.json").write_text(json.dumps({"meta": meta, "agg": agg}, separators=(",", ":"), default=str))
    (out_dir / "cases.json").write_text(json.dumps(cases, separators=(",", ":")))
    shutil.copy(Path(__file__).with_name("index.html"), out_dir / "index.html")
    return out_dir / "index.html"
