"""Neighbouring counties: borders from the bundled shapes, groups within a state, off by default."""

from coldmap.core.types import Finding
from coldmap.detectors import DETECTORS
from coldmap.detectors.neighbours import _strongest, adjacency, groups
from coldmap.ensemble import DEFAULT_DETECTORS


def test_borders_and_groups():
    assert {"39051", "39123", "39173", "26115"} <= adjacency()["39095"]       # Lucas, OH
    g = groups(["Lucas, OH", "Wood, OH", "Fulton, OH", "Monroe, MI", "Nowhere, XX"])
    assert g["Lucas, OH"] == ["Lucas, OH", "Fulton, OH", "Wood, OH"]          # Michigan's Monroe left out
    assert "Monroe, MI" not in g and "Nowhere, XX" not in g


def test_overlapping_groups_keep_the_strongest():
    def f(centre, counties, q, start=1980, end=1985):
        return Finding("neighbours", centre + " and neighbours", "neighbours", "Female", "Knife", start, end, 20, 2,
                       q_value=q, score=1.0, county=centre, extras={"counties": counties})
    kept = _strongest([f("A", ["A", "B"], 0.05), f("B", ["B", "A"], 0.01), f("C", ["C", "D"], 0.02),
                       f("A", ["A", "B"], 0.03, 1995, 1999)])
    assert [(k.county, k.start) for k in kept] == [("B", 1980), ("C", 1980), ("A", 1995)]


def test_off_by_default():
    assert "neighbours" not in DEFAULT_DETECTORS and "Experimental" in DETECTORS.get("neighbours").summary
