from coldmap import apply_fixes, map_algorithm, sliding_window
from coldmap.detect import cases_for

from .conftest import make_cases


def test_sliding_window_finds_planted_cluster(synthetic):
    flags = sliding_window(synthetic, threshold=0.4, min_cases=8)
    assert len(flags) == 1
    f = flags[0]
    assert (f.place, f.weapon) == ("Hot, TL", "Strangle/asphyxia")
    assert f.start <= 1995 and f.end >= 1998
    assert f.p_value < 0.01


def test_quiet_county_not_flagged(synthetic):
    assert not [f for f in sliding_window(synthetic) if f.place == "Quiet, TL"]


def test_overlapping_windows_merged(synthetic):
    flags = sliding_window(synthetic, threshold=0.6, min_cases=6)
    hot = [f for f in flags if f.place == "Hot, TL"]
    for a in hot:
        for b in hot:
            assert a is b or abs(a.start - b.start) >= 4


def test_map_algorithm_threshold():
    df = make_cases([("A, TL", 2000, "Knife", False, "Relationship not determined")] * 3
                    + [("A, TL", 2000, "Knife", True, "Wife")])
    assert len(map_algorithm(df)) == 1            # 25% solved -> flagged
    assert not map_algorithm(df, threshold=0.2)   # below 25% threshold -> not flagged


def test_2021_fix_only_touches_2021():
    df = make_cases([("A, TL", 2021, "Gun", False, "Wife"), ("A, TL", 2020, "Gun", False, "Wife"),
                     ("A, TL", 2021, "Gun", False, "Relationship not determined")])
    out, applied = apply_fixes(df)
    assert "2021-relationship-coding" in applied
    assert out.solved.tolist() == [True, False, False]


def test_cases_for_returns_unsolved_first(synthetic):
    f = sliding_window(synthetic)[0]
    rows = cases_for(synthetic, f)
    assert len(rows) == f.total
    assert not rows.iloc[0].solved
