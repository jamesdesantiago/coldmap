"""Scan every state at once and write one ranked list of flags (national.json).

Each place is still compared with the rest of its own state, exactly as in a state build;
"nationwide" means every state is searched in one pass and the flags are ranked together,
so the strongest patterns anywhere in the country surface first. The app's Nationwide page
reads the file; each flag links to its state's explorer for the heatmap and case rows.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ...core.types import Dataset, Query
from ...ensemble import DEFAULT_DETECTORS, Ensemble
from ...explain import explain

NATIONAL_STEPS = [("women", "Search every state for clusters among women"),
                  ("men", "Search every state for clusters among men"),
                  ("explain", "Write plain-language explanations"),
                  ("save", "Save the results")]


def build_national(data: Dataset, out_dir: Path, detectors=DEFAULT_DETECTORS, enrichers=None,
                   progress=None) -> Path:
    """progress(key) as each NATIONAL_STEPS step starts; progress("explain", done, total) as it goes."""
    step = progress or (lambda *a: None)
    ens = Ensemble.from_names(detectors, {}, **({"enrichers": tuple(enrichers)} if enrichers else {}))
    found = []
    for key, sex in (("women", "Female"), ("men", "Male")):
        step(key)
        found += ens.run(data, Query(state=None, victim_sex=sex))

    c = data.cases
    state_of = c.dropna(subset=["county"]).drop_duplicates("county").set_index("county").state.to_dict()
    for col in ("agency", "msa"):
        state_of.update({("@" + col, k): v for k, v in
                         c.dropna(subset=[col]).drop_duplicates(col).set_index(col).state.items()})

    def where(f) -> str | None:
        counties = f.extras.get("counties") or [f.county]
        for x in counties:
            if x in state_of:
                return state_of[x]
        return state_of.get(("@" + f.level, f.place))

    step("explain", 0, len(found))
    rows = []
    for i, f in enumerate(found, 1):
        e = explain(f, data)
        rows.append({
            "state": where(f), "place": f.place, "level": f.level, "county": f.county,
            "counties": f.extras.get("counties"), "sex": f.victim_sex, "weapon": f.weapon,
            "start": f.start, "end": f.end, "total": f.total, "solved": f.solved,
            "expected": f.expected, "q": None if f.q_value is None else round(f.q_value, 4),
            "confidence": f.confidence, "kind": f.kind, "by": list(f.found_by),
            **{k: e[k] for k in ("what", "agreement", "statistics", "data", "cases", "plugins", "namus") if k in e},
        })
        if i % 25 == 0 or i == len(found):
            step("explain", i, len(found))

    step("save")
    rank = {"high": 0, "strong": 1, "possible": 2}
    rows.sort(key=lambda r: (rank.get(r["confidence"], 3), -(r["total"] - r["solved"])))
    meta = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "years": [int(c.year.min()), int(c.year.max())], "detectors": list(detectors),
            "enrichers": list(enrichers or ens.enrichers), "fixes": list(data.fixes),
            "states": sorted({r["state"] for r in rows if r["state"]}), "national_cases": int(len(c))}
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "national.json"
    out.write_text(json.dumps({"meta": meta, "findings": rows}, separators=(",", ":"), default=str))
    return out
