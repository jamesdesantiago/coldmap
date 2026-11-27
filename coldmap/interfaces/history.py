"""Flag history: how each nationwide scan's flags compare with the last one.

Every scan is saved as a small snapshot in COLDMAP_HOME/research/history. The next scan is matched
against it: a flag "continues" when the earlier scan had one for the same state, place, level,
victims and method in overlapping years (its years and id may shift as data arrives), otherwise it
is "new"; earlier flags with no match are "gone". Continuing flags carry a trend in unsolved
killings and the date they were first seen.

Flags that disappear when new data arrives are evidence about false alarms, so each comparison says
what changed between the scans: the data, the models, or both.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..plugins import home

KEEP = 20  # snapshots kept
FIELDS = ("id", "state", "level", "place", "sex", "weapon", "start", "end", "total", "solved", "confidence")


def folder() -> Path:
    return home() / "research" / "history"


def snapshots() -> list[Path]:
    return sorted(folder().glob("*.json")) if folder().is_dir() else []


def _key(r: dict) -> tuple:
    return (r.get("state"), r.get("level"), r.get("place"), r.get("sex"), r.get("weapon"))


def compare(rows: list[dict], generated: str, data_stamp: str, model_stamp: str) -> dict:
    """Annotate `rows` with r["history"], save this scan's snapshot, and return the summary."""
    prev_path = next((p for p in reversed(snapshots()) if p.stem != _stem(generated)), None)
    prev = json.loads(prev_path.read_text(encoding="utf-8")) if prev_path else None
    by_key: dict[tuple, list[dict]] = {}
    for r in (prev or {}).get("flags", []):
        by_key.setdefault(_key(r), []).append(r)
    matched: set[str] = set()
    counts = {"new": 0, "continuing": 0, "growing": 0, "shrinking": 0, "steady": 0}
    for r in rows:
        cands = [p for p in by_key.get(_key(r), []) if p["start"] <= r["end"] and r["start"] <= p["end"]
                 and p["id"] not in matched]
        if prev is None:
            r["history"] = None
            continue
        if not cands:
            r["history"] = {"status": "new", "since": generated}
            counts["new"] += 1
            continue
        p = max(cands, key=lambda c: min(c["end"], r["end"]) - max(c["start"], r["start"]))
        matched.add(p["id"])
        delta = (r["total"] - r["solved"]) - (p["total"] - p["solved"])
        trend = "growing" if delta > 0 else "shrinking" if delta < 0 else "steady"
        r["history"] = {"status": "continuing", "trend": trend, "delta_unsolved": delta,
                        "since": p.get("since") or prev["generated"],
                        "before": {k: p[k] for k in ("start", "end", "total", "solved")}}
        counts["continuing"] += 1
        counts[trend] += 1
    gone = [p for ps in by_key.values() for p in ps if p["id"] not in matched] if prev else []
    changed = None
    if prev:
        changed = [w for w, a, b in (("data", prev.get("data_stamp"), data_stamp),
                                     ("models", prev.get("model_stamp"), model_stamp)) if a != b] or ["nothing"]
    summary = {"previous": prev["generated"] if prev else None, "changed": changed, **counts,
               "gone": len(gone), "gone_flags": [{k: g.get(k) for k in FIELDS} for g in
                                                 sorted(gone, key=lambda g: g["solved"] - g["total"])[:200]]}
    snap = {"generated": generated, "data_stamp": data_stamp, "model_stamp": model_stamp,
            "flags": [{**{k: r.get(k) for k in FIELDS}, "since": (r.get("history") or {}).get("since") or generated}
                      for r in rows]}
    folder().mkdir(parents=True, exist_ok=True)
    (folder() / f"{_stem(generated)}.json").write_text(json.dumps(snap), encoding="utf-8")
    for old in snapshots()[:-KEEP]:
        old.unlink()
    return summary


def _stem(generated: str) -> str:
    return datetime.fromisoformat(generated).strftime("%Y%m%d-%H%M%S")
