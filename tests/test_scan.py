import numpy as np
import pandas as pd

from coldmap.coverage import add_coverage
from coldmap.scan import bh_qvalues, kind_of, scan

from .conftest import make_cases


def _state(planted: bool, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for c in ["A, TL", "B, TL", "C, TL", "D, TL", "E, TL"]:
        for y in range(1980, 2010):
            for _ in range(4):
                rows.append((c, y, "Strangle/asphyxia", bool(rng.random() < 0.75), "Relationship not determined"))
    if planted:  # County A, 1990-1993: 12 extra killings, none solved
        rows += [("A, TL", y, "Strangle/asphyxia", False, "Relationship not determined")
                 for y in range(1990, 1994) for _ in range(3)]
    return make_cases(rows)


def test_scan_finds_planted_cluster():
    flags = scan(_state(True), reps=499, max_q=0.05)
    assert flags, "planted cluster not found"
    f = flags[0]
    assert f.place == "A, TL" and f.start >= 1985 and f.end <= 1998
    assert f.q_value <= 0.05 and f.kind == "serial-pattern"


def test_scan_quiet_on_null_data():
    # No planted cluster: at q <= 0.05 we expect no (or almost no) flags.
    assert len(scan(_state(False, seed=7), reps=499, max_q=0.05)) <= 1


def test_as_of_hides_future():
    assert not scan(_state(True), reps=199, max_q=0.05, as_of=1988)


def test_bh_qvalues_known_values():
    q = bh_qvalues(np.array([0.01, 0.04, 0.03, 0.5]))
    assert np.allclose(q, [0.04, 0.0533333, 0.0533333, 0.5], atol=1e-6)


def test_kind_of():
    assert kind_of("Strangle/asphyxia", 20) == "serial-pattern"
    assert kind_of("Gun", 20) == "accountability"
    assert kind_of("Knife", 500) == "accountability"


def test_coverage_attached():
    shr = _state(True)
    years = sorted(shr.year.unique())
    clearance = pd.DataFrame({"state": "Testland", "county": "A, TL", "agency": "PD",
                              "year": years, "murders": [8] * len(years), "cleared": 0})
    flags = add_coverage(scan(shr, reps=499, max_q=0.1), shr, clearance, "Testland")
    a = [f for f in flags if f.place == "A, TL"][0]
    assert a.coverage is not None and a.coverage < 1.0
