import pandas as pd

import coldmap
from coldmap import Ensemble, Matcher, Query
from coldmap.fixes import apply_fixes

from .conftest import make_cases, make_dataset, state_rows


def test_ensemble_agreement_is_high(planted):
    out = coldmap.run(planted, Query(), params={"scan": {"reps": 499, "levels": ("county",)}})
    top = out[0]
    assert top.place == "A, TL" and top.confidence == "high" and set(top.found_by) == {"scan", "window"}


def test_single_detector_confidence_follows_tier(planted):
    s = coldmap.run(planted, Query(), detectors=["scan"], params={"scan": {"reps": 499, "levels": ("county",)}})
    w = coldmap.run(planted, Query(), detectors=["window"])
    assert {f.confidence for f in s} == {"strong"} and {f.confidence for f in w} == {"possible"}


def test_custom_matcher(planted):
    class Never(Matcher):
        def agree(self, a, b):
            return False

    ens = Ensemble.from_names(params={"scan": {"reps": 199, "levels": ("county",)}}, matcher=Never(), dedupe=False)
    assert all(f.confidence != "high" for f in ens.run(planted, Query()))


def test_kind_filter(planted):
    out = coldmap.run(planted, Query(), params={"scan": {"reps": 199}}, kind="accountability")
    assert all(f.kind == "accountability" for f in out)


def test_2021_fix_only_touches_2021():
    df = make_cases([("A, TL", 2021, "Gun", False, "Wife"), ("A, TL", 2020, "Gun", False, "Wife"),
                     ("A, TL", 2021, "Gun", False, "Relationship not determined")])
    out, applied = apply_fixes(df, "map-shr")
    assert "2021-relationship-coding" in applied and out.solved.tolist() == [True, False, False]


def test_coverage_and_county_enrichers():
    rows = state_rows(True)
    years = sorted({r[1] for r in rows})
    clearance = pd.DataFrame({"state": "Testland", "county": "A, TL", "agency": "A PD",
                              "year": years, "murders": 8, "cleared": 0})
    data = make_dataset(rows, clearance=clearance)
    out = coldmap.run(data, Query(), detectors=["scan"], params={"scan": {"reps": 499}}, dedupe=False)
    agency = [f for f in out if f.level == "agency"]
    assert agency and agency[0].county == "A, TL"
    a = [f for f in out if f.place == "A, TL"][0]
    assert a.coverage is not None and a.coverage < 1.0
