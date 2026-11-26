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
    """Installed detectors (with tiers and parameters), data fixes and enrichers."""
    return {"detectors": [c.describe() for _, c in DETECTORS],
            "default_ensemble": list(DEFAULT_DETECTORS),
            "fixes": [{"name": n, "title": f.title, "summary": f.summary, "changes_data": bool(f.apply)}
                      for n, f in FIXES],
            "enrichers": {n: c.summary for n, c in ENRICHERS}}


@mcp.tool()
def scan_clusters(state: str, detectors: list[str] | None = None, params: dict | None = None,
                  victim_sex: str = "Female", kind: str | None = "serial-pattern", top: int = 20) -> dict:
    """Run detectors as an ensemble for a state (full name, e.g. 'California').
    detectors: names from list_plugins (default: the default ensemble).
    params: per-detector overrides, e.g. {"scan": {"levels": ["agency"]}, "window": {"window": 6}}.
    Each finding has found_by and confidence: high (2+ detectors agree), strong (one strict
    detector), possible (one sensitive detector). kind: 'serial-pattern', 'accountability' or null."""
    params = {k: {pk: tuple(pv) if isinstance(pv, list) else pv for pk, pv in v.items()}
              for k, v in (params or {}).items()}
    ens = Ensemble.from_names(detectors or DEFAULT_DETECTORS, params)
    findings = ens.run(_data(), Query(state=state, victim_sex=victim_sex), kind=kind)
    return {"findings": [f.to_dict() for f in findings[:top]], "total": len(findings),
            "detectors": [d.name for d in ens.detectors], "data_fixes": list(_data().fixes),
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


def main():
    mcp.run()


if __name__ == "__main__":
    main()
