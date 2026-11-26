"""The research workspace behind the coldmap app: flags, a flag's evidence, places, and the
researcher's decisions (keep, dismiss, second review, sent) with an export for MAP.

Everything lives on this computer in COLDMAP_HOME/research, so the MCP server can read the
same flags and shortlist an AI assistant is helping with. Decisions keep a copy of the flag,
so a later re-scan never loses what someone reviewed.
"""

from __future__ import annotations

import hashlib
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


def flag_detail(data, r: dict) -> dict:
    """The trend behind a flag (this place, method and victims, every year), the state's rate
    for the same method, and the case rows in the flagged years (no names exist in the data)."""
    c = data.cases
    place = c[_mask(c, r, by_year=True)]
    series = place.groupby("year").solved.agg(["size", "sum"])
    st = c[(c.state == r["state"]) & (c.vic_sex == r["sex"]) & (c.weapon_group == r["weapon"]) & (c.vic_age >= 12)]
    state_series = st.groupby("year").solved.agg(["size", "sum"])
    rows = place[place.year.between(r["start"], r["end"])].sort_values(["year", "month"])
    cases = [[_clean(v) for v in rec] for rec in rows[CASE_COLS].itertuples(index=False)]
    y0, y1 = int(c.year.min()), int(c.year.max())
    return {"years": [y0, y1],
            "series": [[int(y), int(n), int(s)] for y, (n, s) in series.iterrows()],
            "state_series": [[int(y), int(n), int(s)] for y, (n, s) in state_series.iterrows()],
            "case_cols": CASE_COLS, "cases": cases[:400], "cases_total": len(cases)}


def _clean(v):
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    return v


# ---- places ----------------------------------------------------------------------------------
def states_table(data, flags: list[dict], sex: str) -> list[dict]:
    c = data.cases[(data.cases.vic_sex == sex) & data.cases.county.notna()]
    g = c.groupby("state").solved.agg(["size", "sum"])
    nflags: dict[str, int] = {}
    for f in flags:
        if f["sex"] == sex and f["confidence"] != "possible":
            nflags[f["state"]] = nflags.get(f["state"], 0) + 1
    return [{"state": s, "killings": int(n), "solved": int(k), "flags": nflags.get(s, 0)} for s, (n, k) in g.iterrows()]


def state_profile(data, flags: list[dict], state: str, sex: str) -> dict:
    c = data.cases[(data.cases.state == state) & (data.cases.vic_sex == sex) & data.cases.county.notna()]
    if c.empty:
        raise KeyError(state)
    g = c.groupby("county").solved.agg(["size", "sum"])
    nflags: dict[str, int] = {}
    for f in flags:
        if f["state"] == state and f["sex"] == sex and f["confidence"] != "possible":
            for k in f.get("counties") or [f.get("county")]:
                nflags[k] = nflags.get(k, 0) + 1
    trend = c.groupby("year").solved.agg(["size", "sum"])
    return {"state": state,
            "counties": [{"county": k, "killings": int(n), "solved": int(s), "flags": nflags.get(k, 0)}
                         for k, (n, s) in g.iterrows()],
            "trend": [[int(y), int(n), int(s)] for y, (n, s) in trend.iterrows()]}


def county_profile(data, state: str, county: str, sex: str) -> dict:
    c = data.cases[(data.cases.state == state) & (data.cases.county == county) & (data.cases.vic_sex == sex)
                   & (data.cases.vic_age >= 12)]
    if c.empty:
        raise KeyError(county)
    g = c.groupby(["weapon_group", "year"]).solved.agg(["size", "sum"])
    cells = [[WEAPONS.index(w) if w in WEAPONS else 5, int(y), int(n), int(s)] for (w, y), (n, s) in g.iterrows()]
    agencies = c.groupby("agency").solved.agg(["size", "sum"]).sort_values("size", ascending=False).head(12)
    yrs = data.cases.year
    return {"state": state, "county": county, "weapons": WEAPONS, "years": [int(yrs.min()), int(yrs.max())],
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
