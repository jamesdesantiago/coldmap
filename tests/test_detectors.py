import numpy as np

from coldmap import Query
from coldmap.detectors import make
from coldmap.stats import bh_qvalues

from .conftest import make_dataset


def test_window_finds_planted(planted):
    f = make("window").detect(planted, Query())
    assert f and f[0].place == "A, TL" and f[0].start <= 1993 and f[0].end >= 1990


def test_scan_finds_planted_with_low_q(planted):
    f = make("scan", reps=499, levels=("county",)).detect(planted, Query())
    assert f and f[0].place == "A, TL" and f[0].q_value <= 0.05


def test_scan_quiet_on_null(null_data):
    assert len(make("scan", reps=499, levels=("county",), max_q=0.05).detect(null_data, Query())) <= 1


def test_scan_respects_as_of(planted):
    assert not make("scan", reps=199, levels=("county",), max_q=0.05).detect(planted, Query(as_of=1988))


def test_scan_agency_level(planted):
    f = make("scan", reps=499, levels=("agency",)).detect(planted, Query())
    assert f and f[0].place == "A PD" and f[0].level == "agency"


def test_map_threshold():
    data = make_dataset([("A, TL", 2000, "Knife", False, "Relationship not determined")] * 3
                        + [("A, TL", 2000, "Knife", True, "Wife")])
    assert len(make("map").detect(data, Query())) == 1
    assert not make("map", threshold=0.2).detect(data, Query())


def test_bh_qvalues():
    assert np.allclose(bh_qvalues(np.array([0.01, 0.04, 0.03, 0.5])), [0.04, 0.0533333, 0.0533333, 0.5], atol=1e-6)
