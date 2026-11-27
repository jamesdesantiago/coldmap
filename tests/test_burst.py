"""The experimental month-level burst detector: finds the sample's planted series; off by default."""

from coldmap import Query, load
from coldmap.detectors import DETECTORS
from coldmap.ensemble import DEFAULT_DETECTORS
from coldmap.sample import make_sample


def test_burst_finds_the_planted_series_by_month(tmp_path):
    cases, clearance = make_sample(tmp_path)
    data = load(cases, clearance_path=clearance)
    found = DETECTORS.get("burst")().detect(data, Query(state="Samplestate", victim_sex="Female"))
    top = found[0]
    assert top.weapon == "Strangle/asphyxia" and top.place.startswith("Harbor")
    assert top.extras["months"].count("-") == 2 and top.extras["months_long"] <= 24
    assert top.q_value <= 0.10


def test_burst_is_experimental_and_off_by_default():
    assert "burst" not in DEFAULT_DETECTORS
    assert DETECTORS.get("burst").tier == "sensitive" and "Experimental" in DETECTORS.get("burst").summary
