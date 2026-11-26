"""Checks against MAP's real file. Skipped unless COLDMAP_CASES is set."""

from coldmap import Query
from coldmap.benchmarks import backtest, evaluate, load_series
from coldmap.detectors import make


def test_ensemble_catches_every_known_series(real):
    report = evaluate(real, detectors=("ensemble",), params={"ensemble": {"params": {"scan": {"reps": 499}}}})
    known = report[report.series != "RECOVERED"]
    missed = known[known.ensemble == "missed"].series.tolist()
    # Randy Kraft (male victims) is a documented miss; anything else is a regression.
    assert missed == ["Randy Kraft (Scorecard Killer)"], f"Ensemble missed: {missed}"


def test_scan_catches_slow_series(real):
    report = evaluate(real, detectors=("scan",), params={"scan": {"reps": 499}})
    assert report.set_index("series").loc["Darren Vann (Gary, Indiana)", "scan"] != "missed"


def test_backtest_gives_lead_time_for_suff(real):
    suff = load_series()[0]
    r = backtest(real, suff, "scan", {"reps": 499})
    assert r["first_flagged"] is not None and r["first_flagged"] < suff.arrest


def test_map_port_top_flag(real):
    top = make("map").detect(real, Query())[0]
    assert top.place == "Fulton, GA" and top.weapon == "Strangulation - hanging"


def test_2021_artifact_present(real):
    c = real.cases
    ca21 = c[(c.state == "California") & (c.year == 2021) & ~c.solved_raw]
    assert (ca21.relationship != "Relationship not determined").mean() > 0.4
