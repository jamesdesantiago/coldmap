"""City data: one row per killing with a location, kept only as coarse grid cells.

Some cities and newsrooms publish homicides with coordinates (for example The Washington Post's
data on 50 large cities, CC BY-NC-SA 4.0: free for non-commercial use with credit, never bundled
with coldmap). coldmap imports your own copy and keeps very little of it:

- each location is snapped to a grid cell of about 1 km on import; exact coordinates, addresses,
  names, race, age and exact dates are never written to disk (the reasons are listed on import);
- what is stored: city, grid cell, year, month, victim sex, solved or not;
- cells with fewer than MIN_SHOWN killings are never shown, so no single killing can be picked out;
- "solved" means closed, by arrest or otherwise (the FBI's definition of cleared).

scan() looks, within each city, for areas (a cell and its neighbours, up to RADIUS_KM from its
centre) where killings were solved far less often than in the rest of the city in the same years:
over the whole period, or optionally also in every window of 1 to 5 years. Monte Carlo
simulation gives each area a p-value that accounts for trying every area in the city;
Benjamini-Hochberg q-values control false discoveries across cities. An area is a pattern worth
review, never evidence that killings are linked.
"""

from __future__ import annotations

import io
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .datasets import MAX_BYTES, identifying, slugify  # noqa: F401  (MAX_BYTES caps the download too)
from .plugins import home

CELL_KM = 1.0
MIN_SHOWN = 3        # cells with fewer killings are never shown
RADIUS_KM = 2.5      # largest area tested, as a radius from its centre cell
MIN_CASES = 15       # smallest area reported
MAX_Q = 0.10
CHUNK = 100          # Monte Carlo runs simulated at a time
KEEP = ("city", "cell", "lat", "lon", "year", "month", "sex", "solved")
WAPO = "The Washington Post, data-homicides (CC BY-NC-SA 4.0; non-commercial use, with credit)"
WAPO_URL = "https://raw.githubusercontent.com/washingtonpost/data-homicides/master/homicide-data.csv"
WAPO_NAME = "The Washington Post: 50 cities"


def wapo_url() -> str:
    import os
    return os.environ.get("COLDMAP_WAPO_URL") or WAPO_URL


def decode(raw: bytes) -> str:
    """UTF-8, else Windows-1252/Latin-1 (the Post's file is Latin-1)."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")

_LAT = re.compile(r"^lat(itude)?$|^y$")
_LON = re.compile(r"^lon(g|gitude)?$|^lng$|^x$")
_DATE = re.compile(r"date|^when$|occurred|reported")
_YEAR = re.compile(r"^year$|^yr$")
_CITY = re.compile(r"^city$|^place$|^municipality$|^jurisdiction$")
_STATE = re.compile(r"^state$|^st$")
_STATUS = re.compile(r"dispo|status|clear|solved|closed|arrest")
_SEX = re.compile(r"(^|_)sex$|gender")
_UNSOLVED = re.compile(r"open|unsolved|no arrest|^no$|^n$|false|^0$|pending|active|unclear")
_SOLVED = re.compile(r"clos|clear|arrest|solved|^yes$|^y$|true|^1$")


def folder() -> Path:
    return home() / "cities"


def _norm(c: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(c).lower()).strip("_")


def _read(text: str) -> pd.DataFrame:
    if len(text.encode()) > MAX_BYTES:
        raise ValueError("That file is over 25 MB.")
    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as e:
        raise ValueError(f"That doesn't read as a CSV file: {e}") from None
    if df.empty:
        raise ValueError("That file has no rows.")
    return df


def _find(df: pd.DataFrame, rx: re.Pattern) -> str | None:
    return next((c for c in df.columns if rx.search(_norm(c))), None)


def columns(df: pd.DataFrame) -> dict:
    """The columns coldmap needs, guessed from their names."""
    cols = {"lat": _find(df, _LAT), "lon": _find(df, _LON), "date": _find(df, _DATE), "year": _find(df, _YEAR),
            "city": _find(df, _CITY), "state": _find(df, _STATE), "status": _find(df, _STATUS),
            "sex": _find(df, _SEX)}
    missing = [k for k in ("lat", "lon", "city", "status") if not cols[k]]
    if not (cols["date"] or cols["year"]):
        missing.append("date or year")
    return {"columns": cols, "missing": missing}


def _city(df: pd.DataFrame, cols: dict) -> pd.Series:
    city = df[cols["city"]].astype(str).str.strip()
    if cols["state"]:
        city = city + ", " + df[cols["state"]].astype(str).str.strip().str.upper()
    return city


def _solved(v: pd.Series) -> pd.Series:
    s = v.astype(str).str.strip().str.lower()
    return pd.Series(np.where(s.str.contains(_UNSOLVED), 0, np.where(s.str.contains(_SOLVED), 1, -1)),
                     index=v.index)


def _when(df: pd.DataFrame, cols: dict) -> tuple[pd.Series, pd.Series]:
    if cols["date"]:
        raw = df[cols["date"]].astype(str).str.strip()
        d = pd.to_datetime(raw, format="%Y%m%d", errors="coerce")
        d = d.fillna(pd.to_datetime(raw.where(d.isna()), errors="coerce", format="mixed"))
        year, month = d.dt.year, d.dt.month
        if cols["year"]:
            year = year.fillna(pd.to_numeric(df[cols["year"]], errors="coerce"))
        return year, month.fillna(0)
    return pd.to_numeric(df[cols["year"]], errors="coerce"), pd.Series(0, index=df.index)


def _source(df: pd.DataFrame) -> str:
    c = {_norm(x) for x in df.columns}
    return WAPO if {"uid", "disposition", "reported_date", "victim_last"} <= c else ""


def _grid(df: pd.DataFrame, cell_km: float) -> pd.DataFrame:
    """Snap points to cells of `cell_km` per city; drop points far from the city's centre (bad
    geocodes). Returns city, cell, lat, lon (the cell's centre, rounded)."""
    out = []
    for city, g in df.groupby("city"):
        lat0, lon0 = g.y.median(), g.x.median()
        far = (np.hypot((g.y - lat0) * 110.574, (g.x - lon0) * 111.320 * math.cos(math.radians(lat0))) > 60)
        g = g[~far]
        dlat, dlon = cell_km / 110.574, cell_km / (111.320 * math.cos(math.radians(lat0)))
        i, j = np.floor(g.y / dlat).astype(int), np.floor(g.x / dlon).astype(int)
        out.append(g.assign(cell=i.astype(str) + ":" + j.astype(str),
                            lat=((i + 0.5) * dlat).round(4), lon=((j + 0.5) * dlon).round(4)))
    return pd.concat(out) if out else df.iloc[0:0]


def preview(text: str) -> dict:
    df = _read(text)
    found = columns(df)
    cols = found["columns"]
    left_out = identifying(df)
    for c in df.columns:
        n = _norm(c)
        if c in {cols["city"], cols["state"], cols["status"], cols["sex"], cols["year"]}:
            continue
        if c in {cols["lat"], cols["lon"]}:
            left_out[c] = "exact locations are turned into ~1 km cells and never stored"
        elif c == cols["date"]:
            left_out[c] = "only the year and month are kept"
        elif "race" in n or "ethnic" in n:
            left_out[c] = "coldmap never splits by race or ethnicity"
        elif c in left_out:
            continue
        else:
            left_out[c] = "not needed"
    out = {"rows": len(df), "columns": cols, "missing": found["missing"], "left_out": left_out,
           "source": _source(df)}
    if not found["missing"]:
        out["cities"] = int(_city(df, cols).nunique())
        vals = df[cols["status"]].drop_duplicates().head(12)
        out["status_values"] = {str(k): ("solved" if v == 1 else "unsolved" if v == 0 else "unknown, left out")
                                for k, v in zip(vals, _solved(vals))}
    return out


def add(name: str, text: str, source: str = "", cell_km: float = CELL_KM) -> dict:
    df = _read(text)
    found = columns(df)
    if found["missing"]:
        raise ValueError("Couldn't find these columns: " + ", ".join(found["missing"]) + ".")
    cols = found["columns"]
    city = _city(df, cols)
    year, month = _when(df, cols)
    sex = (df[cols["sex"]].astype(str).str.strip().str.title() if cols["sex"] else pd.Series("", index=df.index))
    t = pd.DataFrame({"city": city, "y": pd.to_numeric(df[cols["lat"]], errors="coerce"),
                      "x": pd.to_numeric(df[cols["lon"]], errors="coerce"), "year": year, "month": month,
                      "sex": sex.where(sex.isin(["Female", "Male"]), "Unknown"),
                      "solved": _solved(df[cols["status"]])})
    dropped = {"no location": int(t[["y", "x"]].isna().any(axis=1).sum()),
               "no year": int(t.year.isna().sum()), "status unknown": int((t.solved < 0).sum())}
    t = t.dropna(subset=["y", "x", "year"])
    t = t[(t.solved >= 0) & t.y.between(-90, 90) & t.x.between(-180, 180)]
    before = len(t)
    t = _grid(t, cell_km)
    dropped["location far from the city (bad geocode)"] = before - len(t)
    size = t.groupby("city").city.transform("size")
    dropped[f"in cities with fewer than {MIN_SHOWN} killings"] = int((size < MIN_SHOWN).sum())
    t = t[size >= MIN_SHOWN]
    if t.empty:
        raise ValueError("No usable rows: every row was missing a location, year or status.")
    t = t.assign(year=t.year.astype(int), month=t.month.astype(int), solved=t.solved.astype(int))[list(KEEP)]
    slug = slugify(name or "city data")
    folder().mkdir(parents=True, exist_ok=True)
    t.to_csv(folder() / f"{slug}.csv", index=False)
    meta = {"slug": slug, "name": name or "City data", "source": source or _source(df), "cell_km": cell_km,
            "rows": len(t), "cities": int(t.city.nunique()), "years": [int(t.year.min()), int(t.year.max())],
            "dropped": {k: v for k, v in dropped.items() if v}, "left_out": sorted(preview(text)["left_out"]),
            "added": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (folder() / f"{slug}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    _results_path().unlink(missing_ok=True)   # earlier results no longer match the data
    return meta


def remove(slug: str) -> None:
    for ext in ("csv", "json"):
        p = folder() / f"{slugify(slug)}.{ext}"
        if p.exists():
            p.unlink()
    _results_path().unlink(missing_ok=True)


def all_meta() -> list[dict]:
    if not folder().is_dir():
        return []
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder().glob("*.json"))]


def load(slug: str | None = None) -> pd.DataFrame:
    slugs = [slugify(slug)] if slug else [m["slug"] for m in all_meta()]
    frames = [pd.read_csv(folder() / f"{s}.csv", dtype={"cell": str}) for s in slugs
              if (folder() / f"{s}.csv").exists()]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(KEEP))


def _pick(d: pd.DataFrame, sex: str) -> pd.DataFrame:
    return d if sex == "all" else d[d.sex == sex]


def grid(city: str, sex: str = "all") -> dict:
    """Cells of one city for drawing: only cells with at least MIN_SHOWN killings."""
    d = _pick(load(), sex)
    d = d[d.city == city]
    g = d.groupby(["cell", "lat", "lon"]).solved.agg(["size", "sum"]).reset_index()
    hidden = int((g["size"] < MIN_SHOWN).sum())
    g = g[g["size"] >= MIN_SHOWN]
    res = results()
    return {"city": city, "sex": sex, "min_shown": MIN_SHOWN, "hidden_cells": hidden,
            "killings": int(len(d)), "solved": int(d.solved.sum()),
            "cells": [{"lat": float(r.lat), "lon": float(r.lon), "killings": int(r["size"]), "solved": int(r["sum"])}
                      for _, r in g.iterrows()],
            "areas": [a for a in (res or {}).get("areas", []) if a["city"] == city and a["sex"] == sex]}


# ---- scan ---------------------------------------------------------------------------------------
def _city_scan(d: pd.DataFrame, rng, reps: int, radius_km: float, min_cases: int, top_k: int = 3,
               max_years: int = 5, periods: bool = False) -> list[dict]:
    from scipy import sparse
    from .stats import llr
    years = np.sort(d.year.unique())
    cells = d.groupby("cell")[["lat", "lon"]].first()
    ci = {c: k for k, c in enumerate(cells.index)}
    nc, ny = len(cells), len(years)
    yi = np.searchsorted(years, d.year.to_numpy())
    kk = d.cell.map(ci).to_numpy()
    n = np.zeros((nc, ny))
    s = np.zeros((nc, ny))
    np.add.at(n, (kk, yi), 1)
    np.add.at(s, (kk, yi), d.solved.to_numpy())
    p_year = np.clip(s.sum(0) / np.maximum(n.sum(0), 1), 1e-6, 1 - 1e-6)   # the whole city, that year
    # Areas: each cell grown outwards to its neighbours, nearest first, up to radius_km.
    lat0 = float(cells.lat.mean())
    xy = np.c_[cells.lat.to_numpy() * 110.574, cells.lon.to_numpy() * 111.320 * math.cos(math.radians(lat0))]
    rows, cols, centre, radius = [], [], [], []
    z = 0
    for c in range(nc):
        dist = np.hypot(*(xy - xy[c]).T)
        order = np.argsort(dist)
        order = order[dist[order] <= radius_km + 1e-9]
        for m in range(1, len(order) + 1):
            if m < len(order) and dist[order[m]] == dist[order[m - 1]]:
                continue  # add cells at the same distance together
            rows += [z] * m
            cols += list(order[:m])
            centre.append(c)
            radius.append(float(dist[order[m - 1]]))
            z += 1
    M = sparse.csr_matrix((np.ones(len(rows)), (rows, cols)), shape=(z, nc))
    # The whole period, and with `periods` also every window of 1..max_years years.
    wins = [(0, ny - 1)]
    if periods:
        wins += [(a, b) for a in range(ny) for b in range(a, min(ny, a + max_years)) if (a, b) != (0, ny - 1)]
    # Null: solved labels drawn at the city's rate for each year, cell by cell.
    cands, tests = [], []
    for a, b in wins:
        nw, sw = n[:, a:b + 1].sum(1), s[:, a:b + 1].sum(1)
        N, S, E = M @ nw, M @ sw, M @ (n[:, a:b + 1] * p_year[a:b + 1]).sum(1)
        ok = N >= min_cases
        if not ok.any():
            continue
        p0 = np.clip(E / np.maximum(N, 1), 1e-6, 1 - 1e-6)
        ratio = np.where(ok, llr(S, N, p0), 0.0)
        for k in np.argsort(-ratio)[:40]:
            if ratio[k] > 0:
                cands.append((float(ratio[k]), int(k), a, b, int(N[k]), int(S[k]), float(p0[k])))
        idx = np.flatnonzero(ok)
        tests.append((a, b, M[idx], N[idx], p0[idx]))
    if not cands:
        return []
    # Null: solved labels drawn at the city's rate for each year, cell by cell; simulated in chunks
    # of CHUNK runs so memory stays bounded however large the file is.
    best = np.zeros(reps)
    ni = n.astype(np.int64)
    for c0 in range(0, reps, CHUNK):
        c1 = min(reps, c0 + CHUNK)
        sims = rng.binomial(ni[None, :, :], p_year[None, None, :], size=(c1 - c0, nc, ny)).astype(np.int32)
        for a, b, Mi, Ni, pi in tests:
            Ssim = (Mi @ sims[:, :, a:b + 1].sum(2).T).T
            best[c0:c1] = np.maximum(best[c0:c1], llr(Ssim, Ni[None, :], pi[None, :]).max(1))
        del sims
    members = [M.indices[M.indptr[k]:M.indptr[k + 1]] for k in range(z)]
    out, taken = [], np.zeros(nc, bool)
    for ratio, k, a, b, NN, SS, p0 in sorted(cands, reverse=True):
        if len(out) >= top_k:
            break
        if taken[members[k]].any():
            continue
        taken[members[k]] = True
        y0, y1 = int(years[a]), int(years[b])
        win = d[d.year.between(y0, y1)]
        rest_n = len(win) - NN
        rest_s = int(win.solved.sum()) - SS
        out.append({"lat": float(cells.lat.iloc[centre[k]]), "lon": float(cells.lon.iloc[centre[k]]),
                    "radius_km": round(radius[k] + 0.5 * CELL_KM, 1), "cells": int(len(members[k])),
                    "killings": NN, "solved": SS, "expected": round(p0, 3),
                    "rest_rate": round(rest_s / rest_n, 3) if rest_n else None,
                    "start": y0, "end": y1, "score": round(ratio, 2),
                    "p_value": (1 + int((best >= ratio).sum())) / (reps + 1)})
    return out


def scan(reps: int = 999, radius_km: float = RADIUS_KM, min_cases: int = MIN_CASES, max_q: float = MAX_Q,
         seed: int = 0, periods: bool = False, progress=None) -> dict:
    """Scan every city for women, men and both; save and return the results.

    periods=False tests each area over the whole period (about 2.5 minutes for the Post's 50 cities).
    periods=True also tests every window of 1-5 years: about 10x slower, and because many more
    areas are tried, an area has to stand out much further to count (on the Post's data it found
    none at q <= 0.10, where the whole-period scan found 4)."""
    from .stats import bh_qvalues
    d = load()
    rng = np.random.default_rng(seed)
    areas, tested = [], 0
    groups = [(c, sx) for c in sorted(d.city.unique()) for sx in ("Female", "Male", "all")]
    for i, (city, sex) in enumerate(groups):
        if progress:
            progress(i, len(groups), city)
        g = _pick(d[d.city == city], sex)
        if len(g) < 2 * min_cases:
            continue
        tested += 1
        for a in _city_scan(g, rng, reps, radius_km, min_cases, periods=periods):
            areas.append({"city": city, "sex": sex, **a})
    if areas:
        q = bh_qvalues(np.array([a["p_value"] for a in areas]), m=max(tested, len(areas)))
        for a, qq in zip(areas, q):
            a["q_value"] = round(float(qq), 4)
    areas = sorted([a for a in areas if a["q_value"] <= max_q], key=lambda a: (a["q_value"], -a["score"]))
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tested": tested,
           "settings": {"cell_km": CELL_KM, "radius_km": radius_km, "min_cases": min_cases, "max_q": max_q,
                        "reps": reps, "periods": periods},
           "areas": areas}
    _results_path().parent.mkdir(parents=True, exist_ok=True)
    _results_path().write_text(json.dumps(out), encoding="utf-8")
    return out


def _results_path() -> Path:
    return home() / "research" / "cities.json"


def results() -> dict | None:
    p = _results_path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
