"""MCP server: any MCP client (Claude, etc.) can use coldmap as tools.

    COLDMAP_CASES=/path/SHR76_25a.csv [COLDMAP_CLEARANCE=/path/UCR65_25.csv]
    [COLDMAP_NAMUS_MISSING=/path/missing.csv] [COLDMAP_NAMUS_UNIDENTIFIED=/path/uid.csv] coldmap-mcp

Tools are registry-driven: list_plugins shows whatever detectors are installed,
and scan_clusters runs any combination of them. Results never say cases are
linked; the ethics notice travels with every result.
"""

from __future__ import annotations

import os
from functools import lru_cache

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .. import DETECTORS, ENRICHERS, FIXES, Query, load
from ..ensemble import DEFAULT_DETECTORS, Ensemble

ETHICS = ("These are statistical patterns worth review, not evidence that any cases are linked. "
          "Leads go to the Murder Accountability Project or the investigating agency, never to "
          "families, suspects or the public as fact.")

mcp = _Server("coldmap")


@lru_cache(maxsize=1)
def _data():
    path = os.environ.get("COLDMAP_CASES") or os.environ.get("COLDMAP_SHR")
    if not path:
        raise RuntimeError("Set COLDMAP_CASES to MAP's SHR76_25a.csv (or .zip).")
    aux = {k: os.environ[v] for k, v in (("namus-missing", "COLDMAP_NAMUS_MISSING"),
                                          ("namus-unidentified", "COLDMAP_NAMUS_UNIDENTIFIED")) if os.environ.get(v)}
    return load(path, source=os.environ.get("COLDMAP_SOURCE", "map-shr"),
                clearance_path=os.environ.get("COLDMAP_CLEARANCE"), aux=aux)


@mcp.tool()
def list_plugins() -> dict:
    """Installed detectors (with tiers and parameters), presets, data fixes and enrichers."""
    from ..presets import PRESETS
    return {"detectors": [c.describe() for _, c in DETECTORS],
            "presets": {n: {"summary": p.summary, "detectors": list(p.detectors)} for n, p in PRESETS},
            "default_ensemble": list(DEFAULT_DETECTORS),
            "fixes": [{"name": n, "title": f.title, "summary": f.summary, "changes_data": bool(f.apply)}
                      for n, f in FIXES],
            "enrichers": {n: c.summary for n, c in ENRICHERS}}


@mcp.tool()
def scan_clusters(state: str, detectors: list[str] | None = None, params: dict | None = None,
                  victim_sex: str = "Female", kind: str | None = "serial-pattern", top: int = 20,
                  preset: str | None = None) -> dict:
    """Run detectors as an ensemble for a state (full name, e.g. 'California').
    detectors: names from list_plugins (default: the default ensemble).
    params: per-detector overrides, e.g. {"scan": {"levels": ["agency"]}, "window": {"window": 6}}.
    Each finding has found_by and confidence: high (2+ detectors agree), strong (one strict
    detector), possible (one sensitive detector; mostly noise in false-alarm tests).
    kind: 'serial-pattern', 'accountability' or null. preset: strict, balanced, profiles, exploratory."""
    from ..presets import resolve
    params = {k: {pk: tuple(pv) if isinstance(pv, list) else pv for pk, pv in v.items()}
              for k, v in (params or {}).items()}
    detectors, params = resolve(preset, detectors, params)
    ens = Ensemble.from_names(detectors or DEFAULT_DETECTORS, params)
    findings = ens.run(_data(), Query(state=state, victim_sex=victim_sex), kind=kind)
    return {"findings": [f.to_dict() for f in findings[:top]], "total": len(findings),
            "detectors": [d.name for d in ens.detectors], "data_fixes": list(_data().fixes),
            "notice": ETHICS}


@mcp.tool()
def triage_finding(state: str, place: str, weapon_group: str, start: int, end: int,
                   level: str = "county", victim_sex: str = "Female") -> dict:
    """Explain a finding in plain language and check it: the numbers, which detectors agree and how
    much to trust that, data problems touching this place and period, coverage, NamUs context,
    who the victims were in aggregate, and next steps. Then search public news for whether the
    series is already known before suggesting anyone act on it."""
    from ..explain import explain
    from ..presets import resolve
    dets, prm = resolve("balanced")
    findings = Ensemble.from_names(dets, prm).run(_data(), Query(state=state, victim_sex=victim_sex))
    match = [f for f in findings if f.place == place and f.weapon == weapon_group
             and f.start <= end and f.end >= start]
    if not match:
        return {"found": False, "note": "No detector flags this place, method and period at default settings.",
                "notice": ETHICS}
    f = max(match, key=lambda x: (x.start == start and x.end == end, x.unsolved))
    e = explain(f, _data())
    return {"found": True, "finding": f.to_dict(), "explanation": {k: v for k, v in e.items() if k != "text"},
            "markdown": e["text"], "news_search_queries": [
                f"{(f.county or place).split(',')[0]} County women killed {start} {end} unsolved",
                f"{(f.county or place).split(',')[0]} serial killer {start}s women"],
            "notice": ETHICS}


@mcp.tool()
def get_cases(state: str, place: str, weapon_group: str, start: int, end: int,
              level: str = "county", victim_sex: str = "Female", min_age: int | None = 12) -> dict:
    """The case records (no names) behind a finding. place is a county like 'Kern, CA' or,
    with level='agency', an agency like 'Gary'."""
    d = _data().select(Query(state=state, victim_sex=victim_sex, min_age=min_age), use_exclusions=False)
    d = d[(d[level] == place) & (d.weapon_group == weapon_group) & d.year.between(start, end)]
    cols = ["year", "month", "agency", "county", "solved", "vic_age", "vic_race", "vic_ethnic",
            "weapon", "circumstance", "relationship"]
    rows = d[cols].sort_values(["solved", "year", "month"])
    return {"count": len(rows), "unsolved": int((~rows.solved).sum()),
            "cases": rows.to_dict(orient="records"), "notice": ETHICS}


@mcp.tool()
def coverage_gaps(state: str, below: float = 0.8) -> list[dict]:
    """Counties and decades where the case file holds under `below` of reported murders.
    Clusters can hide there. Needs COLDMAP_CLEARANCE."""
    from ..enrichers.builtin import low_coverage_places
    if _data().clearance is None:
        return [{"error": "Set COLDMAP_CLEARANCE to MAP's UCR65_25.csv to use this tool."}]
    return low_coverage_places(_data(), state, below=below).to_dict(orient="records")


@mcp.tool()
def false_alarms(state: str, detectors: list[str] | None = None, runs: int = 3) -> list[dict]:
    """Estimate how many findings each detector produces by chance, by running it on data where
    unsolved cases are shuffled across places. Use it to judge how much to trust findings."""
    from ..benchmarks.controls import false_alarms as fa
    dets = tuple(detectors or (*DEFAULT_DETECTORS, "ensemble"))
    return fa(_data(), Query(state=state), dets, runs=runs).to_dict(orient="records")


@mcp.tool()
def data_quality(state: str | None = None, top: int = 10) -> dict:
    """Reporting anomalies and gaps that can create or hide findings. Check before trusting a finding."""
    from ..quality import CHECKS, report
    return {name: {"summary": CHECKS.get(name).summary, "rows": t.to_dict(orient="records")}
            for name, t in report(_data(), state, top=top).items()}


@mcp.tool()
def benchmark(detectors: list[str] | None = None) -> list[dict]:
    """How detectors (and 'ensemble') score on known, adjudicated serial cases."""
    from ..benchmarks import evaluate
    return evaluate(_data(), tuple(detectors or (*DEFAULT_DETECTORS, "ensemble"))).to_dict(orient="records")


# ---- the research workspace the coldmap app keeps (COLDMAP_HOME) ------------------------------
@mcp.tool()
def research_flags(state: str | None = None, victim_sex: str = "Female", confidence: str = "strong",
                   kind: str | None = None, top: int = 25) -> dict:
    """The ranked national list of flags the coldmap app shows (from its last nationwide scan).
    confidence: "high" (detectors agree), "strong" (high + strong) or "all". state: full name."""
    import json
    from ..plugins import home
    from .research import with_ids
    path = home() / "sites" / "_national" / "national.json"
    if not path.exists():
        return {"error": "No nationwide scan yet. Open the coldmap app (coldmap open) to run one.",
                "ethics": ETHICS}
    rows = with_ids(json.loads(path.read_text())["findings"])
    keep = {"high": ("high",), "strong": ("high", "strong")}.get(confidence, ("high", "strong", "possible"))
    rows = [r for r in rows if r["sex"] == victim_sex and r["confidence"] in keep
            and (not state or r["state"] == state) and (not kind or r["kind"] == kind)]
    cols = ("id", "state", "place", "level", "weapon", "start", "end", "total", "solved", "expected",
            "confidence", "kind", "ruleout", "what")
    return {"flags": [{k: r.get(k) for k in cols} for r in rows[:top]], "matching": len(rows), "ethics": ETHICS}


@mcp.tool()
def shortlist() -> dict:
    """Flags the researcher kept in the coldmap app, with their notes and review status
    (kept, reviewed by a second person, sent to MAP). Dismissed flags are left out."""
    from .research import decisions
    out = [{"id": d["id"], "status": d.get("status"), "note": d.get("note"), "reviewer": d.get("reviewer"),
            "flag": {k: d["flag"].get(k) for k in ("state", "place", "weapon", "start", "end", "total",
                                                    "solved", "expected", "confidence", "what")}}
           for d in decisions().values() if d.get("status") != "dismissed"]
    return {"shortlist": out, "ethics": ETHICS}


@mcp.tool()
def local_datasets(place: str | None = None, start: int | None = None, end: int | None = None) -> dict:
    """The researcher's own datasets about places and times (added in the coldmap app). Without
    `place`, describes each one; with a place label as the case file writes it (e.g. "Multnomah, OR",
    a state name or an agency), returns matching rows, optionally limited to years start..end.
    They hold no personal identifiers: coldmap leaves those out on import."""
    from .. import datasets
    metas = datasets.all_meta()
    if not place:
        return {"datasets": metas, "ethics": ETHICS}
    out = []
    for m in metas:
        df = datasets.load(m["slug"])
        df = df[df.place == place]
        if start is not None:
            df = df[df.year >= start]
        if end is not None:
            df = df[df.year <= end]
        if len(df):
            out.append({"dataset": m["name"], "rows": df.head(200).to_dict(orient="records"), "matching": len(df)})
    return {"place": place, "matches": out, "ethics": ETHICS}


@mcp.tool()
def app_views(name: str | None = None, inputs: dict | None = None) -> dict:
    """Pages that plugins add to the coldmap app. Without `name`, lists them and their inputs;
    with a name (and optional inputs such as {"state": "Ohio"}), returns that page's blocks:
    text, numbers, tables and charts as data."""
    from ..views import VIEWS, Context, render
    from .research import decisions, with_ids
    from ..plugins import home
    import json
    pages = {n: v for n, v in VIEWS if v.place == "page"}
    if not name:
        return {"pages": [v.describe() for v in pages.values()], "ethics": ETHICS}
    if name not in pages:
        return {"error": f"No page called {name!r}.", "pages": list(pages)}
    path = home() / "sites" / "_national" / "national.json"
    flags = with_ids(json.loads(path.read_text())["findings"]) if path.exists() else []
    return {"page": name, "blocks": render(pages[name], Context(_data(), flags, decisions()), **(inputs or {})),
            "ethics": ETHICS}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
