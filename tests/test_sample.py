import coldmap
from coldmap import Query
from coldmap.quality import report
from coldmap.sample import make_sample


def test_sample_quickstart_finds_planted_series_and_problems(tmp_path):
    cases, clearance = make_sample(tmp_path)
    data = coldmap.load(cases, clearance_path=clearance)
    assert "2021-relationship-coding" in data.fixes

    out = coldmap.run(data, Query(state="Samplestate"), params={"scan": {"reps": 499}}, kind="serial-pattern")
    top = out[0]
    assert top.county == "Harbor, SS" and top.weapon == "Strangle/asphyxia" and top.confidence == "high"
    assert top.start <= 1991 and top.end >= 1988

    r = report(data)
    assert (r["unknown-offender-with-relationship"]["when"] == 2021).any()
    assert r["missing-agency-years"]["where"].str.contains("Pine").any()


def test_unknown_age_policy(tmp_path):
    cases, _ = make_sample(tmp_path)
    data = coldmap.load(cases)
    keep = data.select(Query(state="Samplestate"))
    drop = data.select(Query(state="Samplestate", keep_unknown_age=False))
    assert (keep.vic_age >= 999).any() and not (drop.vic_age >= 999).any()
