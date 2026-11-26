"""Regions: groups of neighboring counties a detector can scan as one place.

Offenders cross county lines. Southern California's "Freeway Killers" (Kearney,
Bonin, Kraft) left young men across five counties in 1976-1983; each county's
share looks ordinary, the region's does not. Scanning regions catches that.

A RegionSet maps counties in one state to named regions. Built-ins ship for
some states; define your own in JSON and load it with `load_regions`:

    {"name": "texas-metros", "state": "Texas",
     "regions": {"Houston area": ["Harris, TX", "Fort Bend, TX", "Montgomery, TX"], ...}}

Counties left out of every region are scanned only as counties. Register a set
with REGIONS.register(...) or ship it in a plugin through `coldmap.regions`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..core.registry import Registry


@dataclass(frozen=True)
class RegionSet:
    name: str
    state: str
    regions: dict[str, tuple[str, ...]] = field(default_factory=dict)
    note: str = ""

    def county_to_region(self) -> dict[str, str]:
        out = {}
        for region, counties in self.regions.items():
            for c in counties:
                if c in out:
                    raise ValueError(f"{c} is in two regions of {self.name}: {out[c]} and {region}")
                out[c] = region
        return out


REGIONS: Registry[RegionSet] = Registry("region set", "coldmap.regions")


def load_regions(path: str | Path, register: bool = True) -> RegionSet:
    d = json.loads(Path(path).read_text())
    rs = RegionSet(d["name"], d["state"], {k: tuple(v) for k, v in d["regions"].items()}, d.get("note", ""))
    rs.county_to_region()  # validate
    if register:
        REGIONS.unregister(rs.name)
        REGIONS.register(rs)
    return rs


def add_region(d: pd.DataFrame, sets: list[str] | None = None) -> pd.DataFrame:
    """Add a `region` column from the region sets for each state in d (None where unassigned)."""
    lookup: dict[tuple[str, str], str] = {}
    for name, rs in REGIONS:
        if sets is not None and name not in sets:
            continue
        for county, region in rs.county_to_region().items():
            lookup[(rs.state, county)] = region
    d = d.copy()
    d["region"] = [lookup.get((s, c)) for s, c in zip(d.state, d.county)]
    return d


def members(region: str) -> list[str]:
    for _, rs in REGIONS:
        if region in rs.regions:
            return list(rs.regions[region])
    return []


from . import builtin  # noqa: E402,F401
