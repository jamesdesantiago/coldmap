"""Checks against MAP's real file. Skipped unless COLDMAP_SHR is set."""

from coldmap import map_algorithm
from coldmap.validate import KNOWN_SERIES, run_validation


def test_known_series(real):
    report = run_validation(real)
    for s, row in zip(KNOWN_SERIES, report.itertuples()):
        if s.expect_detected:
            assert row.detected, f"Detector missed {s.name}"


def test_map_port_top_flag(real):
    # MAP's published method puts Fulton County, GA strangulations of women at the top nationally.
    top = map_algorithm(real)[0]
    assert top.place == "Fulton, GA" and top.weapon == "Strangulation - hanging"


def test_2021_artifact_present(real):
    ca21 = real[(real.state == "California") & (real.year == 2021) & ~real.solved_raw]
    share = (ca21.relationship != "Relationship not determined").mean()
    assert share > 0.4, "2021 coding artifact no longer present; revisit the fix"
