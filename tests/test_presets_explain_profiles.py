import pytest

import coldmap
from coldmap import PRESETS, Query
from coldmap.core.profile import PROFILE_COLUMNS, add_profile
from coldmap.detectors import make
from coldmap.presets import resolve

from .conftest import make_dataset, state_rows


def test_presets_registered_and_resolve():
    assert {"strict", "balanced", "profiles", "exploratory"} <= set(PRESETS.names())
    dets, params = resolve("strict", None, {"scan": {"reps": 99}})
    assert dets == ("scan",) and params["scan"] == {"max_q": 0.05, "min_unsolved": 5, "reps": 99}
    dets, _ = resolve("balanced", ["window"], None)
    assert dets == ("window",)          # explicit detectors win


def test_run_with_preset(planted):
    out = coldmap.run(planted, Query(), preset="strict", params={"scan": {"reps": 499, "levels": ("county",)}})
    assert out and all(f.found_by == ("scan",) for f in out) and all(f.unsolved >= 5 for f in out)


def test_min_unsolved_filters(planted):
    assert not make("window", min_unsolved=1000).detect(planted, Query())


def test_profile_columns_exclude_race_and_circumstance():
    assert PROFILE_COLUMNS == ("age_band",)
    with pytest.raises(ValueError):
        add_profile(make_dataset(state_rows(False)).cases, ("circumstance_group",))


def test_age_band_split_tags_findings(planted):
    out = make("window", split_by=("age_band",)).detect(planted, Query())
    assert out and out[0].extras["profile"] == {"age_band": "30-44"}


def test_matcher_respects_profiles(planted):
    from coldmap import Finding, Matcher
    a = Finding("x", "A, TL", "county", "Female", "Knife", 1990, 1993, 10, 1, county="A, TL",
                extras={"profile": {"age_band": "18-29"}})
    b = Finding("y", "A, TL", "county", "Female", "Knife", 1990, 1993, 10, 1, county="A, TL",
                extras={"profile": {"age_band": "45+"}})
    c = Finding("z", "A, TL", "county", "Female", "Knife", 1990, 1993, 10, 1, county="A, TL")
    m = Matcher()
    assert not m.agree(a, b) and m.agree(a, c)


def test_explain_has_sections_and_notice(planted):
    f = coldmap.run(planted, Query(), params={"scan": {"reps": 499, "levels": ("county",)}})[0]
    e = coldmap.explain(f, planted)
    assert {"what", "agreement", "statistics", "data", "cases", "next", "text"} <= set(e)
    assert "not evidence that cases are linked" in e["text"]
    assert "Detectors agree" in e["agreement"] or "Two or more" in e["agreement"]


def test_fix_scope():
    fx = coldmap.FIXES.get("california-1983-1995-relationship")
    assert fx.applies_to("California", 1990, 1992) and not fx.applies_to("Texas", 1990, 1992)
    assert not fx.applies_to("California", 2000, 2004)
