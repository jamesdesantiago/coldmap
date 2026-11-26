"""Built-in region sets. Regions follow widely used state planning regions; they are a
starting point, not a claim about where offenders travel. Contributions welcome."""

from __future__ import annotations

from . import REGIONS, RegionSet


def _ca(*names):
    return tuple(f"{n}, CA" for n in names)


REGIONS.register(RegionSet(
    "california", "California",
    {
        "Southern California": _ca("Los Angeles", "Orange", "Riverside", "San Bernardino", "San Diego",
                                   "Ventura", "Imperial"),
        "Bay Area": _ca("Alameda", "Contra Costa", "Marin", "Napa", "San Francisco", "San Mateo",
                        "Santa Clara", "Solano", "Sonoma"),
        "Central Coast": _ca("Monterey", "Santa Cruz", "San Luis Obispo", "Santa Barbara", "San Benito"),
        "Sacramento Valley": _ca("Sacramento", "Yolo", "Placer", "El Dorado", "Sutter", "Yuba", "Butte",
                                 "Glenn", "Colusa", "Tehama", "Shasta"),
        "San Joaquin Valley": _ca("San Joaquin", "Stanislaus", "Merced", "Madera", "Fresno", "Kings",
                                  "Tulare", "Kern"),
        "Sierra and North": _ca("Del Norte", "Humboldt", "Mendocino", "Lake", "Trinity", "Siskiyou", "Modoc",
                                "Lassen", "Plumas", "Sierra", "Nevada", "Amador", "Calaveras", "Tuolumne",
                                "Mariposa", "Alpine", "Mono", "Inyo"),
    },
    "Six regions covering all 58 counties.",
))

REGIONS.register(RegionSet(
    "washington", "Washington",
    {
        "Puget Sound": tuple(f"{n}, WA" for n in ("King", "Pierce", "Snohomish", "Kitsap", "Thurston")),
    },
    "Puget Sound only; other counties are scanned individually.",
))
