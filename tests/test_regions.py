import json

import numpy as np
import pytest

import coldmap
from coldmap import REGIONS, Finding, Matcher, Query, RegionSet, load_regions
from coldmap.detectors import make

from .conftest import make_dataset


def _spread_series(seed=3):
    """Six counties with ~75% solved strangulations; an unsolved series spread thinly across
    three of them (2 per county per year, 1990-1993), too thin to stand out in any one county."""
    rng = np.random.default_rng(seed)
    counties = ["A, TL", "B, TL", "C, TL", "D, TL", "E, TL", "F, TL"]
    rows = [(c, y, "Strangle/asphyxia", bool(rng.random() < 0.75), "Relationship not determined")
            for c in counties for y in range(1980, 2010) for _ in range(4)]
    rows += [(c, y, "Strangle/asphyxia", False, "Relationship not determined")
             for c in counties[:3] for y in range(1990, 1994) for _ in range(2)]
    return make_dataset(rows)


@pytest.fixture
def test_regions():
    rs = RegionSet("testland", "Testland", {"North": ("A, TL", "B, TL", "C, TL"), "South": ("D, TL", "E, TL", "F, TL")})
    REGIONS.register(rs)
    yield rs
    REGIONS.unregister("testland")


def test_builtin_california_covers_all_counties():
    ca = REGIONS.get("california").county_to_region()
    assert len(ca) == 58 and ca["Orange, CA"] == "Southern California"


def test_region_set_rejects_overlaps():
    with pytest.raises(ValueError):
        RegionSet("bad", "X", {"a": ("C1",), "b": ("C1",)}).county_to_region()


def test_load_regions_json(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"name": "tmp-set", "state": "Testland", "regions": {"All": ["A, TL", "B, TL"]}}))
    try:
        rs = load_regions(p)
        assert REGIONS.get("tmp-set") is rs and rs.regions["All"] == ("A, TL", "B, TL")
    finally:
        REGIONS.unregister("tmp-set")


def test_region_scan_catches_spread_series(test_regions):
    data = _spread_series()
    county = make("scan", reps=499, levels=("county",), max_q=0.05).detect(data, Query())
    region = make("scan", reps=499, levels=("region",), max_q=0.05, region_sets=("testland",)).detect(data, Query())
    north = [f for f in region if f.place == "North"]
    assert north and north[0].start <= 1993 and north[0].end >= 1990
    assert set(north[0].extras["counties"]) == {"A, TL", "B, TL", "C, TL"}
    assert len(north) > 0 and len([f for f in county if f.start <= 1993 and f.end >= 1990]) <= len(north) + 3


def test_matcher_region_overlaps_member_county():
    reg = Finding("scan", "North", "region", "Female", "Knife", 1990, 1993, 20, 2,
                  extras={"counties": ["A, TL", "B, TL"]})
    cty = Finding("window", "B, TL", "county", "Female", "Knife", 1991, 1994, 9, 1, county="B, TL")
    other = Finding("window", "Z, TL", "county", "Female", "Knife", 1991, 1994, 9, 1, county="Z, TL")
    m = Matcher()
    assert m.agree(reg, cty) and not m.agree(reg, other)
    assert not m.duplicate(reg, cty)   # region and county findings are kept separately


def test_benchmark_runs_each_victim_sex_separately():
    from coldmap.benchmarks import KnownSeries, evaluate
    rows = [("A, TL", y, "Knife", True, "Wife") for y in range(1990, 2000) for _ in range(5)]
    data = make_dataset(rows)
    men = KnownSeries("men", "Testland", "A, TL", None, "Male", ("Knife",), 1990, 1995, 1996)
    women = KnownSeries("women", "Testland", "A, TL", None, "Female", ("Knife",), 1990, 1995, 1996)
    calls = []

    class Spy(coldmap.Detector):
        name = "test-spy"

        def detect(self, data, query):
            calls.append(query.victim_sex)
            return []

    coldmap.DETECTORS.register(Spy)
    try:
        evaluate(data, detectors=("test-spy",), series=[women, men])
        assert sorted(calls) == ["Female", "Male"]
    finally:
        coldmap.DETECTORS.unregister("test-spy")
