"""Checks against MAP's real file. Skipped unless COLDMAP_SHR is set."""

from coldmap import map_algorithm
from coldmap.validate import KNOWN_SERIES, backtest, run_validation


def test_known_series_caught_by_at_least_one_detector(real):
    report = run_validation(real, scan={"reps": 499, "max_len": 25})
    for row in report.itertuples():
        assert row.window != "missed" or row.scan != "missed", f"Both detectors missed {row.series}"


def test_scan_catches_slow_series(real):
    vann = next(s for s in KNOWN_SERIES if s.agency == "Gary")
    report = run_validation(real, detectors=("scan",), scan={"reps": 499, "max_len": 25})
    assert report.set_index("series").loc[vann.name, "scan"] != "missed"


def test_backtest_gives_lead_time_for_suff(real):
    suff = KNOWN_SERIES[0]
    r = backtest(real, suff, "scan", reps=499, max_len=25)
    assert r["first_flagged"] is not None and r["first_flagged"] < suff.arrest


def test_map_port_top_flag(real):
    # MAP's published method puts Fulton County, GA strangulations of women at the top nationally.
    top = map_algorithm(real)[0]
    assert top.place == "Fulton, GA" and top.weapon == "Strangulation - hanging"


def test_2021_artifact_present(real):
    ca21 = real[(real.state == "California") & (real.year == 2021) & ~real.solved_raw]
    share = (ca21.relationship != "Relationship not determined").mean()
    assert share > 0.4, "2021 coding artifact no longer present; revisit the fix"
