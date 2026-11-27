"""The research workspace behind the coldmap app: flags, a flag's evidence, places, and the
researcher's decisions (keep, dismiss, second review, sent) with an export for MAP.

Everything lives on this computer in COLDMAP_HOME/research, so the MCP server can read the
same flags and shortlist an AI assistant is helping with. Decisions keep a copy of the flag,
so a later re-scan never loses what someone reviewed.
"""

from __future__ import annotations

import hashlib
import re
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..plugins import home

STATUSES = ("kept", "reviewed", "sent", "dismissed")
WEAPONS = ["Gun", "Knife", "Beating/blunt", "Strangle/asphyxia", "Fire", "Other/unknown", "Not reported"]
CASE_COLS = ["year", "month", "agency", "solved", "vic_age", "vic_race", "weapon", "relationship", "circumstance"]
_lock = threading.RLock()


def flag_id(r: dict) -> str:
    key = "|".join(str(r.get(k)) for k in ("state", "level", "place", "sex", "weapon", "start", "end"))
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def with_ids(rows: list[dict]) -> list[dict]:
    seen: dict[str, int] = {}
    for r in rows:
        if not r.get("id"):
            i = flag_id(r)
            seen[i] = seen.get(i, 0) + 1
            r["id"] = i if seen[i] == 1 else f"{i}-{seen[i]}"
    return rows


# ---- a flag's evidence -----------------------------------------------------------------------
def _mask(c, r: dict, by_year: bool):
    if r.get("level") == "region":
        m = c.county.isin(r.get("counties") or [])
    else:
        col = r["level"] if r["level"] in c.columns else "county"
        m = c[col] == r["place"]
    if r.get("state"):
        m &= c.state == r["state"]
    m &= (c.vic_sex == r["sex"]) & ((c.weapon_group == r["weapon"]) | (c.weapon == r["weapon"])) & (c.vic_age >= 12)
    if not by_year:
        m &= c.year.between(r["start"], r["end"])
    return m


MAX_CASES = 6000


def _age_band(a) -> str:
    a = int(a)
    return "Unknown" if a >= 999 else "Under 18" if a < 18 else "18–29" if a < 30 else "30–44" if a < 45 else "45 and over"


def flag_detail(data, r: dict) -> dict:
    """Everything needed to research a flag: this place, method and victims in every year (the
    trend and the case rows, no names exist in the data), the state's rate for the same method,
    and how the rest of the state's cases break down in the flagged years, for comparison."""
    c = data.cases
    place_mask = _mask(c, r, by_year=True)
    place = c[place_mask]
    series = place.groupby("year").solved.agg(["size", "sum"])
    same = (c.state == r["state"]) & (c.vic_sex == r["sex"]) & (c.weapon_group == r["weapon"]) & (c.vic_age >= 12)
    state_series = c[same].groupby("year").solved.agg(["size", "sum"])
    rows = place
    covered = [int(c.year.min()), int(c.year.max())]
    if len(rows) > MAX_CASES:  # very large places: the flagged years and the years around them
        for pad in (25, 15, 10, 5, 2, 0):
            rows = place[place.year.between(r["start"] - pad, r["end"] + pad)]
            if len(rows) <= MAX_CASES:
                break
        rows = rows.head(MAX_CASES)
        covered = [int(rows.year.min()), int(rows.year.max())]
    rows = rows.sort_values(["year", "month"])
    cases = [[_clean(v) for v in rec] for rec in rows[CASE_COLS].itertuples(index=False)]
    rest = c[same & ~place_mask & c.year.between(r["start"], r["end"])]
    base = {"month": rest.month.value_counts(normalize=True), "age": rest.vic_age.map(_age_band).value_counts(normalize=True),
            "relationship": rest.relationship.fillna("").replace("", "Not recorded").value_counts(normalize=True),
            "circumstance": rest.circumstance.fillna("").replace("", "Not recorded").value_counts(normalize=True),
            "weapon": rest.weapon.value_counts(normalize=True), "race": rest.vic_race.value_counts(normalize=True)}
    y0, y1 = int(c.year.min()), int(c.year.max())
    return {"years": [y0, y1], "covered": covered, "truncated": len(place) > len(rows),
            "series": [[int(y), int(n), int(s)] for y, (n, s) in series.iterrows()],
            "state_series": [[int(y), int(n), int(s)] for y, (n, s) in state_series.iterrows()],
            "case_cols": CASE_COLS, "cases": cases, "cases_total": int(len(place)),
            "baseline": {k: {str(_clean(i)): round(float(v), 4) for i, v in ser.head(40).items()} for k, ser in base.items()},
            "baseline_n": int(len(rest))}


def _clean(v):
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    return v


# ---- places ----------------------------------------------------------------------------------
BOTH = ("all", "both", "")


def _sex(c, sex: str):
    """Rows for one victim sex, or every victim when sex is "all"."""
    return c.vic_sex.notna() if sex.lower() in BOTH else c.vic_sex == sex


def _sex_ok(f: dict, sex: str) -> bool:
    return sex.lower() in BOTH or f["sex"] == sex


def states_table(data, flags: list[dict], sex: str) -> list[dict]:
    c = data.cases[_sex(data.cases, sex) & data.cases.county.notna() & (data.cases.vic_age >= 12)]
    g = c.groupby("state").solved.agg(["size", "sum"])
    nflags: dict[str, int] = {}
    for f in flags:
        if _sex_ok(f, sex) and f["confidence"] != "possible":
            nflags[f["state"]] = nflags.get(f["state"], 0) + 1
    return [{"state": s, "killings": int(n), "solved": int(k), "flags": nflags.get(s, 0)} for s, (n, k) in g.iterrows()]


def state_profile(data, flags: list[dict], state: str, sex: str) -> dict:
    c = data.cases[(data.cases.state == state) & _sex(data.cases, sex) & data.cases.county.notna()
                   & (data.cases.vic_age >= 12)]
    if c.empty:
        raise KeyError(state)
    g = c.groupby("county").solved.agg(["size", "sum"])
    nflags: dict[str, int] = {}
    for f in flags:
        if f["state"] == state and _sex_ok(f, sex) and f["confidence"] != "possible":
            for k in f.get("counties") or [f.get("county")]:
                nflags[k] = nflags.get(k, 0) + 1
    trend = c.groupby("year").solved.agg(["size", "sum"])
    rates = per_capita(c, "county")
    return {"state": state, "population_source": rates.get("_source"),
            "counties": [{"county": k, "killings": int(n), "solved": int(s), "flags": nflags.get(k, 0),
                          "per_100k": rates.get(k)}
                         for k, (n, s) in g.iterrows()],
            "trend": [[int(y), int(n), int(s)] for y, (n, s) in trend.iterrows()]}


def population() -> tuple[str, "object"] | tuple[None, None]:
    """A county-level dataset of yours with a population column, if there is one:
    (dataset name, frame with place, year, population)."""
    from .. import datasets
    for m in datasets.all_meta():
        col = next((c for c in m["numeric"] if "population" in c.lower() or c.lower() in ("pop", "pop_total")), None)
        if m["level"] == "county" and col:
            df = datasets.load(m["slug"])[["place", "year", col]].rename(columns={col: "population"})
            return m["name"], df.groupby(["place", "year"]).population.sum().reset_index()
    return None, None


def per_capita(cases, level: str = "county") -> dict:
    """Killings per 100,000 people per year, by county, over the years both the case file and your
    population dataset cover. Empty when there is no population dataset."""
    name, pop = population()
    if pop is None or cases.empty:
        return {}
    k = cases.groupby([level, "year"]).size().rename("killings").reset_index().rename(columns={level: "place"})
    j = k.merge(pop, on=["place", "year"], how="inner")
    j = j[j.population > 0]
    g = j.groupby("place").agg(killings=("killings", "sum"), person_years=("population", "sum"))
    out = {pl: round(float(r.killings / r.person_years * 100000), 2) for pl, r in g.iterrows() if r.person_years > 0}
    out["_source"] = name
    return out


def county_profile(data, state: str, county: str, sex: str) -> dict:
    c = data.cases[(data.cases.state == state) & (data.cases.county == county) & _sex(data.cases, sex)
                   & (data.cases.vic_age >= 12)]
    if c.empty:
        raise KeyError(county)
    g = c.groupby(["weapon_group", "year"]).solved.agg(["size", "sum"])
    cells = [[WEAPONS.index(w) if w in WEAPONS else 5, int(y), int(n), int(s)] for (w, y), (n, s) in g.iterrows()]
    agencies = c.groupby("agency").solved.agg(["size", "sum"]).sort_values("size", ascending=False).head(12)
    yrs = data.cases.year
    rate = per_capita(c, "county")
    return {"state": state, "county": county, "per_100k": rate.get(county), "population_source": rate.get("_source"),
            "weapons": WEAPONS, "years": [int(yrs.min()), int(yrs.max())],
            "cells": cells, "killings": int(len(c)), "solved": int(c.solved.sum()),
            "agencies": [{"agency": a, "killings": int(n), "solved": int(s)} for a, (n, s) in agencies.iterrows()]}


# ---- decisions: keep, dismiss, second review, sent --------------------------------------------
def _decisions_file() -> Path:
    return home() / "research" / "decisions.json"


def decisions() -> dict:
    try:
        return json.loads(_decisions_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decide(fid: str, status: str, flag: dict | None = None, note: str | None = None,
           reviewer: str | None = None) -> dict:
    """Record a decision. `reviewed` needs the second reviewer's name (ETHICS.md: a person other
    than the researcher reviews every lead before it leaves the project); `sent` needs `reviewed`."""
    if status not in STATUSES:
        raise ValueError(f"Unknown status {status!r}.")
    with _lock:
        all_ = decisions()
        d = all_.get(fid) or {"id": fid, "created": _now(), "note": "", "history": []}
        if flag:
            d["flag"] = {k: v for k, v in flag.items() if k != "id"}
        if "flag" not in d:
            raise ValueError("Unknown flag.")
        if note is not None:
            d["note"] = note.strip()[:4000]
        if status == "reviewed":
            reviewer = (reviewer or "").strip()[:80]
            if not reviewer:
                raise ValueError("Add the name or initials of the second person who reviewed this lead.")
            d["reviewer"], d["reviewed"] = reviewer, _now()
        if status == "sent" and not d.get("reviewer"):
            raise ValueError("A second person has to review a lead before it is sent.")
        if status in ("kept", "dismissed"):
            d.pop("reviewer", None)
            d.pop("reviewed", None)
        d["status"], d["updated"] = status, _now()
        d["history"] = (d.get("history") or [])[-20:] + [{"status": status, "at": d["updated"]}]
        all_[fid] = d
        _decisions_file().parent.mkdir(parents=True, exist_ok=True)
        _decisions_file().write_text(json.dumps(all_, indent=1), encoding="utf-8")
        return d


def note(fid: str, text: str) -> dict:
    with _lock:
        all_ = decisions()
        if fid not in all_:
            raise ValueError("Keep the flag first, then add a note.")
        all_[fid]["note"], all_[fid]["updated"] = text.strip()[:4000], _now()
        _decisions_file().write_text(json.dumps(all_, indent=1), encoding="utf-8")
        return all_[fid]


def forget(fid: str) -> None:
    with _lock:
        all_ = decisions()
        if all_.pop(fid, None) is not None:
            _decisions_file().write_text(json.dumps(all_, indent=1), encoding="utf-8")


def export_markdown(d: dict, version: str, data_date: str | None) -> str:
    """A lead summary for the Murder Accountability Project. Only reviewed leads export."""
    if d.get("status") not in ("reviewed", "sent"):
        raise ValueError("Only leads a second person has reviewed can be exported.")
    f = d["flag"]
    who = {"Female": "women", "Male": "men"}.get(f["sex"], "victims")
    rate = f["solved"] / f["total"] if f["total"] else 0
    gap = round((rate - f["expected"]) * 100) if f.get("expected") is not None else None
    years = f"{f['start']}–{f['end']}" if f["start"] != f["end"] else str(f["start"])
    lines = [
        f"# Lead for review: {f['place']}, {f['state']}",
        f"{f['weapon']} killings of {who}, {years}",
        "",
        "> A flag is a pattern worth review, not evidence that cases are linked. Only investigators can link "
        "cases. Do not contact families, witnesses or possible suspects.",
        "",
        f"Reviewed by {d['reviewer']} on {d['reviewed'][:10]}. Prepared with coldmap {version}"
        + (f" from MAP's files downloaded {data_date[:10]}." if data_date else "."),
        "",
        "## The numbers",
        f"- {f['total']} killings, {f['solved']} solved ({rate:.0%}), {f['total'] - f['solved']} unsolved",
    ]
    if gap is not None:
        lines.append(f"- Expected solve rate {f['expected']:.0%}; gap {gap:+d} points")
    lines += [f"- Confidence: {f.get('confidence')}; found by {', '.join(f.get('by') or [])}"]
    if f.get("q") is not None:
        lines.append(f"- q = {f['q']}")
    lines += ["", "## Why it was flagged", f.get("what", ""), "", f.get("agreement", "")]
    if f.get("ruleouts"):
        word = {"explains": "May explain this", "weakens": "Weakens this", "clear": "Nothing found"}
        lines += ["", "## Rule-out checks", *[f"- {r['title']}: {word.get(r['status'], r['status'])}. {r['text']}"
                                               for r in f["ruleouts"]]]
    if f.get("statistics"):
        lines += ["", f"Statistics: {f['statistics']}"]
    if f.get("data"):
        lines += ["", "## Data notes", *[f"- {n}" for n in f["data"]]]
    if f.get("cases"):
        lines += ["", "## Victims, in aggregate", f["cases"]]
    if f.get("plugins"):
        lines += ["", "## Notes from plugins", *[f"- {n['title']} ({n['by']}): {n['text']}" for n in f["plugins"]]]
    if d.get("note"):
        lines += ["", "## Researcher's note", d["note"]]
    lines += ["", "## Reproduce",
              f"coldmap scan SHR76_25a.csv --state \"{f['state']}\" --clearance UCR65_25.csv --explain 5",
              ""]
    return "\n".join(lines)


# ---- the map: case-file county labels -> census county codes (us-atlas) ---------------------
STATE_FIPS = {"AL": "01", "AK": "02", "AZ": "04", "AR": "05", "CA": "06", "CO": "08", "CT": "09", "DE": "10",
              "DC": "11", "FL": "12", "GA": "13", "HI": "15", "ID": "16", "IL": "17", "IN": "18", "IA": "19",
              "KS": "20", "KY": "21", "LA": "22", "ME": "23", "MD": "24", "MA": "25", "MI": "26", "MN": "27",
              "MS": "28", "MO": "29", "MT": "30", "NE": "31", "NV": "32", "NH": "33", "NJ": "34", "NM": "35",
              "NY": "36", "NC": "37", "ND": "38", "OH": "39", "OK": "40", "OR": "41", "PA": "42", "RI": "44",
              "SC": "45", "SD": "46", "TN": "47", "TX": "48", "UT": "49", "VT": "50", "VA": "51", "WA": "53",
              "WV": "54", "WI": "55", "WY": "56"}
ATLAS = Path(__file__).with_name("explorer") / "vendor" / "counties-10m.json"
_FIPS: dict[str, str | None] = {}
# Counties renamed or redrawn since the case file's labels, or garbled in the atlas.
FIPS_ALIASES = {"Dona Ana, NM": "35013", "Shannon, SD": "46102", "Clifton Forge, VA": "51005",
                "Wrangell-Petersburg, AK": "02195", "Prince of Wales-Outer Ketchikan, AK": "02198",
                "Skagway-Hoonah-Angoon, AK": "02105"}
_ATLAS_IDX: dict = {}


def _key(name: str) -> str:
    import unicodedata
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\bsaint\b", "st", n)
    n = re.sub(r"\s+(county|parish|borough|census area|municipality|city and borough)$", "", n.strip())
    return re.sub(r"[^a-z0-9]", "", n)


def county_fips(label: str) -> str | None:
    """Census county code for a case-file county label ("Multnomah, OR" -> "41051")."""
    if label in _FIPS:
        return _FIPS[label]
    if not _ATLAS_IDX:
        for g in json.loads(ATLAS.read_text(encoding="utf-8"))["objects"]["counties"]["geometries"]:
            fid = g["id"]
            city = int(fid[2:]) >= 500 and fid[:2] in ("51", "24", "29", "32")
            _ATLAS_IDX.setdefault((fid[:2], _key(g["properties"]["name"]), city), fid)
    out = FIPS_ALIASES.get(label)
    if out:
        pass
    elif label.strip().lower() == "district of columbia":
        out = "11001"
    elif ", " in label:
        name, st = label.rsplit(", ", 1)
        city = name.endswith(" city")
        name = name[:-5] if city else name
        sf = STATE_FIPS.get(st.strip())
        if sf:
            k = _key(name)
            out = _ATLAS_IDX.get((sf, k, city)) or _ATLAS_IDX.get((sf, k, not city))
    _FIPS[label] = out
    return out


def map_counties(data, sex: str) -> dict:
    """Every county's killings and solved (victims 12 and older), keyed by census code, plus the
    label -> code table the page uses to place flags."""
    c = data.cases[_sex(data.cases, sex) & data.cases.county.notna() & (data.cases.vic_age >= 12)]
    g = c.groupby("county").solved.agg(["size", "sum"])
    counties, unmatched = {}, []
    for label, (n, s) in g.iterrows():
        f = county_fips(label)
        if f:
            prev = counties.get(f, [label, 0, 0])
            counties[f] = [prev[0], prev[1] + int(n), prev[2] + int(s)]
        else:
            unmatched.append([label, int(n)])
    labels = data.cases.county.dropna().unique()
    return {"counties": counties, "fips": {lb: county_fips(lb) for lb in labels if county_fips(lb)},
            "unmatched": sorted(unmatched, key=lambda x: -x[1])[:20]}
