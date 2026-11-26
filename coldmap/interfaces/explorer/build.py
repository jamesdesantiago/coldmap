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


def _group(w: str) -> str:
    return w if w in WEAPONS else WEAPON_GROUPS.get(w, "Other/unknown")


def build_site(data: Dataset, state: str, out_dir: Path, detectors=DEFAULT_DETECTORS,
               params: dict | None = None) -> Path:
    params = params or {}
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
    ens = Ensemble.from_names(detectors, params)
    names = [x.name for x in ens.detectors]
    views = {"ensemble": {}, **{n: {} for n in names}}
    for sx, sex in ((0, "Female"), (1, "Male")):
        q = Query(state=state, victim_sex=sex)
        found = {det.name: enrich(det.detect(data, q), data, ens.enrichers) for det in ens.detectors}
        views["ensemble"][sx] = ens.combine(copy.deepcopy(found))
        for n in names:
            views[n][sx] = Ensemble([x for x in ens.detectors if x.name == n]).combine(copy.deepcopy({n: found[n]}))

    def row(fd):
        c = cidx.get(fd.county)
        if c is None:
            return None
        return [c, fd.place if fd.level != "county" else None, WEAPONS.index(_group(fd.weapon)),
                fd.start, fd.end, fd.total, fd.solved, fd.expected,
                None if fd.q_value is None else round(fd.q_value, 4),
                [names.index(x) for x in fd.found_by if x in names], CONF.index(fd.confidence), fd.kind,
                {k.split("-")[1]: [v["count"], v["typical"]] for k, v in fd.extras.items()
                 if k.startswith("namus-") and isinstance(v, dict)} or None,
                {k: v for k, v in explain(fd, data).items() if k in ("what", "agreement", "statistics", "data", "cases", "namus")},
                fd.extras.get("profile", {}).get("age_band")]

    strip = counties[0][counties[0].rfind(","):] if "," in counties[0] else ""
    busiest = d.county.value_counts().index[0]
    meta = {
        "state": state, "years": [int(d.year.min()), int(d.year.max())],
        "counties": [c.removesuffix(strip) for c in counties], "defaultCounty": busiest.removesuffix(strip),
        "weapons": WEAPONS, "confidence": CONF, "fixes": list(data.fixes), **lists,
        "detectors": [{"name": x.name, "summary": x.summary, "tier": x.tier} for x in ens.detectors],
        "findings": {v: {sx: [r for r in map(row, fl) if r] for sx, fl in by.items()} for v, by in views.items()},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "agg.json").write_text(json.dumps({"meta": meta, "agg": agg}, separators=(",", ":"), default=str))
    (out_dir / "cases.json").write_text(json.dumps(cases, separators=(",", ":")))
    shutil.copy(Path(__file__).with_name("index.html"), out_dir / "index.html")
    return out_dir / "index.html"
