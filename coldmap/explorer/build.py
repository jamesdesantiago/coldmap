"""Build the static explorer site (index.html + agg.json + cases.json) for one state."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from ..issues import apply_fixes

WEAPONS = ["Gun", "Knife", "Beating/blunt", "Strangle/asphyxia", "Fire", "Other/unknown", "Not reported"]


def _scan_rows(df: pd.DataFrame, state: str, counties: list[str], reps: int) -> dict:
    """Precompute strict-detector flags for the page: {sex: [[county_idx, agency|None, weapon_idx,
    start, end, total, solved, baseline, q], ...]}."""
    from ..scan import scan
    ac = df[df.state == state].groupby("agency").county.agg(lambda s: s.mode().iat[0])
    cidx = {c: i for i, c in enumerate(counties)}
    out = {}
    for sx, name in ((0, "Female"), (1, "Male")):
        rows = []
        for level in ("county", "agency"):
            for f in scan(df, state=state, place=level, victim_sex=name, reps=reps, max_len=25):
                county = f.place if level == "county" else ac.get(f.place)
                if county not in cidx or f.weapon not in WEAPONS:
                    continue
                rows.append([cidx[county], f.place if level == "agency" else None, WEAPONS.index(f.weapon),
                             f.start, f.end, f.total, f.solved, f.baseline, round(f.q_value, 4)])
        out[sx] = rows
    return out


def build_site(df: pd.DataFrame, state: str, out_dir: Path, reps: int = 999) -> Path:
    d = df[df.state == state].copy()
    if d.empty:
        raise ValueError(f"No cases for state {state!r}. Use the full name, e.g. 'California'.")
    raw = d.solved_raw.astype(bool)
    fixed, _ = apply_fixes(d)
    d["sr"], d["sf"] = raw.astype(int), fixed.solved.astype(int)
    d["wi"] = d.weapon_group.map(WEAPONS.index)
    d["ad"] = (d.vic_age >= 12).astype(int)
    d["sx"] = d.vic_sex.map({"Female": 0, "Male": 1}).fillna(2).astype(int)
    d = d[d.county.notna()]
    suffix = d.county.str.extract(r"(, [A-Z]{2})$")[0].dropna()
    strip = suffix.iloc[0] if len(suffix) else ""
    counties = sorted(d.county.unique())
    d["ci"] = d.county.map(counties.index)

    agg = (d.groupby(["ci", "sx", "ad", "wi", "year"])
             .agg(t=("sr", "size"), r=("sr", "sum"), f=("sf", "sum")).reset_index().values.tolist())

    f = d[d.sx == 0]
    lists = {k: sorted(f[col].astype(str).unique()) for k, col in
             [("agencies", "agency"), ("rel", "relationship"), ("circ", "circumstance"),
              ("weaponRaw", "weapon"), ("race", "vic_race")]}
    idx = {k: {v: i for i, v in enumerate(vals)} for k, vals in lists.items()}
    cases = [[int(r.ci), int(r.year), int(r.month), idx["agencies"][str(r.agency)], int(r.sr), int(r.sf),
              int(r.vic_age), idx["race"][str(r.vic_race)], int(r.wi), idx["weaponRaw"][str(r.weapon)],
              idx["circ"][str(r.circumstance)], idx["rel"][str(r.relationship)]] for r in f.itertuples()]

    busiest = d.county.value_counts().index[0]
    meta = {"state": state, "years": [int(d.year.min()), int(d.year.max())],
            "counties": [c.removesuffix(strip) for c in counties],
            "defaultCounty": busiest.removesuffix(strip), "weapons": WEAPONS, **lists,
            "scan": _scan_rows(df, state, counties, reps)}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "agg.json").write_text(json.dumps({"meta": meta, "agg": agg}, separators=(",", ":")))
    (out_dir / "cases.json").write_text(json.dumps(cases, separators=(",", ":")))
    shutil.copy(Path(__file__).with_name("index.html"), out_dir / "index.html")
    return out_dir / "index.html"
