import pytest

import coldmap
from coldmap import DETECTORS, Dataset, Detector, Finding, Query, Registry
from coldmap.interfaces.params import parse_overrides

from .conftest import make_cases


def test_builtin_plugins_registered():
    assert {"map", "window", "scan"} <= set(DETECTORS.names())
    assert {"county", "kind", "coverage"} <= set(coldmap.ENRICHERS.names())
    assert {"map-shr", "map-clearance"} <= set(coldmap.SOURCES.names())
    assert "2021-relationship-coding" in coldmap.FIXES


def test_registry_rejects_duplicates_and_unknowns():
    r = Registry("thing", "coldmap.test-none")

    class A:
        name = "a"

    r.register(A)
    with pytest.raises(ValueError):
        class A2:
            name = "a"
        r.register(A2)
    with pytest.raises(KeyError, match="Available: a"):
        r.get("b")


def test_detector_params_are_typed_and_described():
    desc = DETECTORS.get("scan").describe()
    assert desc["tier"] == "strict"
    assert any(p["name"] == "max_q" and p["default"] == 0.10 for p in desc["params"])
    with pytest.raises(TypeError, match="no parameter"):
        DETECTORS.get("window")(nope=1)


def test_dataset_validates_schema():
    with pytest.raises(ValueError, match="missing required columns"):
        Dataset(make_cases([("A, TL", 2000, "Gun", True, "Wife")]).drop(columns="county"))


def test_query_filters(planted):
    d = planted.select(Query(state="Testland", as_of=1985))
    assert d.year.max() == 1985 and set(d.vic_sex) == {"Female"}


def test_parse_overrides():
    p = parse_overrides(["scan.reps=499", "scan.levels=county,agency", "window.threshold=0.3", "x.name=abc"])
    assert p == {"scan": {"reps": 499, "levels": ("county", "agency")}, "window": {"threshold": 0.3},
                 "x": {"name": "abc"}}


def test_custom_detector_plugs_into_ensemble(planted):
    class Everything(Detector):
        name = "test-everything"
        summary = "flags county A always"
        tier = "sensitive"

        def detect(self, data, query):
            return [Finding(self.name, "A, TL", "county", query.victim_sex, "Strangle/asphyxia",
                            1990, 1993, 28, 4, county="A, TL")]

    DETECTORS.register(Everything)
    try:
        out = coldmap.run(planted, Query(), detectors=["window", "test-everything"])
        top = [f for f in out if f.place == "A, TL"][0]
        assert set(top.found_by) == {"window", "test-everything"} and top.confidence == "high"
    finally:
        DETECTORS.unregister("test-everything")
