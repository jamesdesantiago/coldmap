"""MCP server: lets an AI assistant (Claude or any MCP client) use coldmap as tools.

Run:  COLDMAP_SHR=/path/to/SHR76_25a.csv COLDMAP_CLEARANCE=/path/to/UCR65_25.csv coldmap-mcp
Then add it to your MCP client's config as a stdio server.

The tools return data, flags and caveats. They never state that cases are
linked; the ETHICS notice travels with every scan result so the assistant
repeats it to the user.
"""

from __future__ import annotations

import os
from functools import lru_cache

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .detect import Flag, cases_for
from .issues import ISSUES, apply_fixes
from .load import load_shr
from .validate import run_validation

ETHICS = ("These are statistical patterns worth review, not evidence that any cases are linked. "
          "Leads go to the Murder Accountability Project or the investigating agency, never to "
          "families, suspects or the public as fact.")

mcp = _Server("coldmap")


@lru_cache(maxsize=1)
def _clearance():
    path = os.environ.get("COLDMAP_CLEARANCE")
    if not path:
        return None
    from .load import load_clearance
    return load_clearance(path)


@lru_cache(maxsize=1)
def _data():
    path = os.environ.get("COLDMAP_SHR")
    if not path:
        raise RuntimeError("Set COLDMAP_SHR to the path of MAP's SHR76_25a.csv (or .zip).")
    df, _ = apply_fixes(load_shr(path))
    return df


@mcp.tool()
def scan_clusters(state: str, victim_sex: str = "Female", level: str = "county",
                  max_q: float = 0.10, min_cases: int = 8, top: int = 20) -> dict:
    """Find places, methods and periods where far fewer killings were solved than in the rest
    of the state at the time. state is a full name like 'California'. level is county, agency
    or msa. Flags carry a Monte Carlo p-value, a false-discovery-rate q-value, and a kind:
    'serial-pattern' or 'accountability' (a place solving fewer cases in general)."""
    from .scan import scan
    flags = scan(_data(), state=state, place=level, victim_sex=victim_sex, max_q=max_q,
                 min_cases=min_cases, use_fixes=False)
    if _clearance() is not None:
        from .coverage import add_coverage
        flags = add_coverage(flags, _data(), _clearance(), state)
    return {"flags": [f.to_dict() for f in flags[:top]], "total_flags": len(flags), "notice": ETHICS,
            "fixes_applied": [i.id for i in ISSUES if i.fix]}


@mcp.tool()
def get_flag_cases(place: str, weapon_group: str, start: int, end: int,
                   victim_sex: str = "Female", level: str = "county") -> dict:
    """List the case records (no names) behind a flag. place like 'Kern, CA' for a county,
    or an agency name like 'Gary' with level='agency'."""
    f = Flag("scan", place, victim_sex, weapon_group, start, end, 0, 0, level=level)
    rows = cases_for(_data(), f, use_fixes=False)
    return {"cases": rows.to_dict(orient="records"), "count": len(rows), "notice": ETHICS}


@mcp.tool()
def query_cases(state: str, county: str | None = None, victim_sex: str | None = None,
                weapon_group: str | None = None, year_from: int | None = None,
                year_to: int | None = None, unsolved_only: bool = False, limit: int = 200) -> dict:
    """Filter case records. weapon_group is one of Gun, Knife, Beating/blunt,
    Strangle/asphyxia, Fire, Other/unknown, Not reported."""
    d = _data()
    m = d.state == state
    if county: m &= d.county == county
    if victim_sex: m &= d.vic_sex == victim_sex
    if weapon_group: m &= d.weapon_group == weapon_group
    if year_from: m &= d.year >= year_from
    if year_to: m &= d.year <= year_to
    if unsolved_only: m &= ~d.solved
    r = d[m]
    cols = ["county", "agency", "year", "month", "solved", "vic_age", "vic_sex", "vic_race",
            "weapon", "circumstance", "relationship"]
    return {"count": len(r), "solved_rate": round(float(r.solved.mean()), 3) if len(r) else None,
            "rows": r[cols].head(limit).to_dict(orient="records")}


@mcp.tool()
def data_issues() -> list[dict]:
    """Known problems in the data and how coldmap handles them. Check before interpreting results."""
    return [{"id": i.id, "title": i.title, "summary": i.summary, "fix_applied": bool(i.fix)} for i in ISSUES]


@mcp.tool()
def coverage_gaps(state: str, below: float = 0.8) -> list[dict]:
    """Counties and decades where the case file holds under `below` of reported murders.
    Clusters can hide there. Needs COLDMAP_CLEARANCE set to UCR65_25.csv."""
    if _clearance() is None:
        return [{"error": "Set COLDMAP_CLEARANCE to MAP's UCR65_25.csv to use this tool."}]
    from .coverage import low_coverage_places
    return low_coverage_places(_data(), _clearance(), state, below=below).to_dict(orient="records")


@mcp.tool()
def validation_report() -> list[dict]:
    """How the detector performs on known, adjudicated serial cases."""
    return run_validation(_data(), scan={"max_len": 25}).to_dict(orient="records")


def main():
    mcp.run()


if __name__ == "__main__":
    main()
