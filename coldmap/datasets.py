"""Your own datasets: local data about places and times, for research and your own models.

A dataset is a CSV keyed by a place (county, agency or state) and a time (a year or a date),
with any measures or notes beside them: counts of missing people, a highway opening, a change
in an agency's staffing, research notes. coldmap keeps a cleaned copy in
COLDMAP_HOME/datasets, never uploads it, shows matching rows on each flag, and hands every
dataset to models as data.aux["dataset:<slug>"] (columns: place, level, year, month, then yours).

Datasets describe places and times, never people. Columns that identify individuals (names,
addresses, phone numbers, emails, IP addresses, dates of birth, biometric or DNA records, licence
plates, exact coordinates) are left out on import and never stored. See ETHICS.md.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .plugins import home

LEVELS = ("county", "agency", "state")
MAX_BYTES = 25 * 1024 * 1024
_lock = threading.RLock()

# Column names that identify people. Matched against the lower-cased name with separators removed.
_ID_NAMES = re.compile(
    r"(^|_)(first|last|full|middle|given|sur|maiden|alias|nick)?_?name(s)?$|^name$|surname|address|street|"
    r"apartment|zip|postcode|postal|phone|mobile|cell|email|e_mail|^ip$|ip_?addr|ipv[46]|mac_?addr|imei|"
    r"ssn|social_?security|passport|licen[cs]e|plate|vin$|dob$|date_?of_?birth|birth_?date|birthday|"
    r"finger|print_?id|biometric|dna|codis|afis|face|photo|iris|^lat(itude)?$|^lon(g|gitude)?$|coord|"
    r"geo_?point|gps|account|card_?num|username|user_?id|person_?id|suspect|victim_?name|offender_?name")
# Values that identify people, whatever the column is called.
_ID_VALUES = [("email addresses", re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)),
              ("IP addresses", re.compile(r"^(\d{1,3}\.){3}\d{1,3}$|^[0-9a-f]{0,4}(:[0-9a-f]{0,4}){2,7}$", re.I)),
              ("phone numbers", re.compile(r"^\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}$")),
              ("social security numbers", re.compile(r"^\d{3}-\d{2}-\d{4}$"))]
_STATE_ABBR: dict[str, str] = {}


def folder() -> Path:
    return home() / "datasets"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48] or "dataset"


def _norm(col: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(col).lower()).strip("_")


def identifying(df: pd.DataFrame) -> dict[str, str]:
    """{column: why it was left out} for columns that identify people."""
    out = {}
    for col in df.columns:
        if _ID_NAMES.search(_norm(col)):
            out[col] = "its name says it identifies people"
            continue
        vals = df[col].dropna().astype(str).str.strip()
        vals = vals[vals != ""].head(200)
        if len(vals):
            for what, rx in _ID_VALUES:
                if vals.map(lambda v: bool(rx.match(v))).mean() >= 0.5:
                    out[col] = f"it holds {what}"
                    break
    return out


def _read(text: str) -> pd.DataFrame:
    if len(text.encode()) > MAX_BYTES:
        raise ValueError("That file is over 25 MB. Aggregate it by place and year first.")
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as e:
        raise ValueError(f"That doesn't read as a CSV file: {e}") from None
    if df.empty or len(df.columns) < 2:
        raise ValueError("A dataset needs at least a place column and a time column.")
    return df


# ---- matching places and times -----------------------------------------------------------------
def _abbr(data) -> dict[str, str]:
    """State name -> two-letter code, read from county labels ("Multnomah, OR")."""
    if not _STATE_ABBR:
        c = data.cases.dropna(subset=["county"]).drop_duplicates("state")
        for st, cty in zip(c.state, c.county):
            if "," in cty:
                _STATE_ABBR[st.lower()] = cty.rsplit(",", 1)[1].strip()
    return _STATE_ABBR


def _match_places(values: pd.Series, level: str, data) -> pd.Series:
    """Map raw place values onto the labels the case file uses (None where nothing matches)."""
    c = data.cases
    if level == "state":
        known = {s.lower(): s for s in c.state.dropna().unique()}
        abbr = {v.lower(): k for k, v in _abbr(data).items()}
        def f(v):
            v = v.strip().lower()
            s = known.get(v) or known.get(abbr.get(v, ""), None)
            return s
        return values.map(f)
    col = "county" if level == "county" else "agency"
    known = {s.lower(): s for s in c[col].dropna().unique()}
    ab = _abbr(data)

    def f(v):
        v = str(v).strip()
        hit = known.get(v.lower())
        if hit or level != "county":
            return hit
        # "Multnomah County, Oregon" / "Multnomah County, OR" -> "Multnomah, OR"
        name, _, st = v.rpartition(",")
        name = re.sub(r"\s+(county|parish|borough|census area|municipality)$", "", name.strip(), flags=re.I)
        st = st.strip()
        st = ab.get(st.lower(), st)
        return known.get(f"{name}, {st}".lower())
    return values.map(f)


def _times(values: pd.Series) -> tuple[pd.Series, pd.Series]:
    """(year, month) from a column of years or dates; month 0 when only the year is known."""
    v = values.astype(str).str.strip()
    year = pd.to_numeric(v, errors="coerce")
    if year.notna().mean() >= 0.8 and year.dropna().between(1900, 2100).all():
        return year.astype("Int64"), pd.Series(0, index=v.index)
    d = pd.to_datetime(v, errors="coerce", format="mixed")
    return d.dt.year.astype("Int64"), d.dt.month.fillna(0).astype(int)


def _guess(df: pd.DataFrame, data) -> dict:
    """Best guesses for the place column and level, and the time column."""
    best = (0.0, None, None)
    for col in df.columns:
        sample = df[col].head(300)
        for level in LEVELS:
            rate = _match_places(sample, level, data).notna().mean()
            if rate > best[0]:
                best = (rate, col, level)
    time_col, trate = None, 0.0
    for col in df.columns:
        if col == best[1]:
            continue
        y, _ = _times(df[col].head(300))
        rate = y.notna().mean()
        if rate > trate:
            time_col, trate = col, rate
    return {"place": best[1], "level": best[2] or "county", "time": time_col if trate >= 0.5 else None}


def preview(text: str, data) -> dict:
    """What coldmap would import: columns, which are left out and why, its guesses, a sample."""
    df = _read(text)
    ids = identifying(df)
    safe = df[[c for c in df.columns if c not in ids]]
    g = _guess(safe, data) if len(safe.columns) >= 2 else {"place": None, "level": "county", "time": None}
    cols = []
    for c in df.columns:
        num = pd.to_numeric(df[c].replace("", None), errors="coerce")
        cols.append({"name": c, "left_out": ids.get(c), "numeric": bool(len(df) and num.notna().mean() >= 0.9)})
    return {"rows": len(df), "columns": cols, "guess": g,
            "sample": safe.head(8).to_dict(orient="records")}


def check(text: str, data, place: str, level: str, time: str) -> dict:
    """How well a chosen place and time column match the case file."""
    df = _read(text)
    if place not in df.columns or time not in df.columns:
        raise ValueError("Choose a place column and a time column.")
    if level not in LEVELS:
        raise ValueError("The place level must be county, agency or state.")
    m = _match_places(df[place], level, data)
    y, _ = _times(df[time])
    bad = df.loc[m.isna(), place].astype(str).drop_duplicates().head(6).tolist()
    return {"rows": len(df), "places_matched": int(m.notna().sum()), "times_read": int(y.notna().sum()),
            "unmatched_examples": bad, "places": int(m.dropna().nunique())}


# ---- storing --------------------------------------------------------------------------------------
def add(name: str, text: str, data, place: str, level: str, time: str, keep: list[str] | None = None,
        description: str = "", source: str = "") -> dict:
    """Clean and store a dataset. Identifying columns are dropped whatever `keep` says; rows whose
    place or time can't be read are left out and counted."""
    name = name.strip()[:80]
    if not name:
        raise ValueError("Give the dataset a name.")
    df = _read(text)
    ids = identifying(df)
    for col in (place, time):
        if col in ids:
            raise ValueError(f"The column {col!r} identifies people, so it can't be the place or time.")
    report = check(text, data, place, level, time)
    if not report["places_matched"] or not report["times_read"]:
        raise ValueError("No rows matched a place in the case file with a readable time. Check the columns "
                         "and the place level.")
    keep = [c for c in (keep if keep is not None else df.columns)
            if c in df.columns and c not in ids and c not in (place, time)]
    year, month = _times(df[time])
    out = pd.DataFrame({"place": _match_places(df[place], level, data), "level": level, "year": year,
                        "month": month})
    for c in keep:
        num = pd.to_numeric(df[c].replace("", None), errors="coerce")
        out[c] = num if num.notna().mean() >= 0.9 else df[c]
    out = out.dropna(subset=["place", "year"])
    slug = slugify(name)
    with _lock:
        d = folder() / slug
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        out.to_csv(d / "data.csv", index=False)
        meta = {"slug": slug, "name": name, "description": description.strip()[:500],
                "source": source.strip()[:300], "level": level, "columns": keep,
                "numeric": [c for c in keep if pd.api.types.is_numeric_dtype(out[c])],
                "rows": int(len(out)), "dropped_rows": int(len(df) - len(out)), "places": int(out.place.nunique()),
                "years": [int(out.year.min()), int(out.year.max())], "left_out": ids,
                "added": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (d / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    attach(data)
    return meta


def remove(slug: str, data=None) -> None:
    with _lock:
        d = folder() / slugify(slug)
        if not d.exists():
            raise ValueError("There's no dataset with that name.")
        shutil.rmtree(d)
    if data is not None:
        data.aux.pop(f"dataset:{slug}", None)


def all_meta() -> list[dict]:
    out = []
    if folder().is_dir():
        for m in sorted(folder().glob("*/meta.json")):
            try:
                out.append(json.loads(m.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
    return out


def load(slug: str) -> pd.DataFrame:
    return pd.read_csv(folder() / slug / "data.csv")


def attach(data) -> None:
    """Give every dataset to models: data.aux["dataset:<slug>"]."""
    for k in [k for k in data.aux if k.startswith("dataset:")]:
        data.aux.pop(k)
    for m in all_meta():
        try:
            data.aux[f"dataset:{m['slug']}"] = load(m["slug"])
        except (OSError, ValueError):
            pass


def fingerprint() -> str:
    h = hashlib.sha1()
    for m in all_meta():
        h.update((m["slug"] + m["added"]).encode())
    return h.hexdigest()[:10]


def for_place(places: list[str], level_places: dict[str, list[str]], years: tuple[int, int]) -> list[dict]:
    """Rows of every dataset that match a flag's places (county, agency or state), within `years`."""
    out = []
    for m in all_meta():
        want = level_places.get(m["level"], [])
        if not want:
            continue
        try:
            df = load(m["slug"])
        except (OSError, ValueError):
            continue
        df = df[df.place.isin(want)]
        if df.empty:
            continue
        inside = df[df.year.between(*years)]
        series = (df.groupby("year")[m["numeric"]].sum().reset_index().values.tolist() if m["numeric"] else [])
        out.append({"slug": m["slug"], "name": m["name"], "description": m.get("description", ""),
                    "source": m.get("source", ""), "level": m["level"], "columns": m["columns"],
                    "numeric": m["numeric"], "series": [[int(r[0])] + [_num(x) for x in r[1:]] for r in series],
                    "rows": json.loads(inside.head(300).to_json(orient="records")), "rows_total": int(len(inside)),
                    "all_rows": int(len(df))})
    return out


def _num(x):
    try:
        f = float(x)
        return int(f) if f.is_integer() else round(f, 4)
    except (TypeError, ValueError):
        return None
