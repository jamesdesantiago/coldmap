"""Rule-out checks: a known series, reporting gaps, clearance records, coding problems."""

import pytest

from coldmap import Finding, load
from coldmap.benchmarks import KnownSeries
from coldmap.enrichers import ruleouts
from coldmap.enrichers.builtin import _MEMO
from coldmap.sample import make_sample


@pytest.fixture
def data(tmp_path):
    cases, clearance = make_sample(tmp_path)
    return load(cases, clearance_path=clearance)


def finding(place="Harbor, SS", level="county", weapon="Strangle/asphyxia", start=1990, end=1993,
            total=12, solved=2, **kw):
    return Finding("scan", place, level, "Female", weapon, start, end, total, solved, expected=0.7,
                   county=place if level == "county" else kw.pop("county", None), **kw)


def run(data, f, series=()):
    _MEMO.setdefault(data, {})[("known-series",)] = list(series)
    ruleouts.RuleOuts().enrich([f], data)
    return {r["check"]: r for r in f.extras["ruleouts"]}, f.extras["ruleout"]


def series(start, end, victims=None, active=None, county="Harbor, SS", weapons=("Strangle/asphyxia",)):
    return KnownSeries("test series", "Samplestate", county, None, "Female", weapons, start, end, end + 1,
                       "test", "Harbor County, SS, strangulations of women (conviction)", victims, active)


def test_a_known_series_explains_only_what_it_can(data):
    small = finding(start=1990, end=1993, total=12, solved=2)          # 10 unsolved
    got, verdict = run(data, small, [series(1989, 1994, victims=8)])
    assert got["known-series"]["status"] == "explains" and verdict == "explains"
    assert "Harbor County" in got["known-series"]["text"] and "test series" not in got["known-series"]["text"]

    big = finding(start=1980, end=2000, total=300, solved=60)          # 240 unsolved
    got, _ = run(data, big, [series(1989, 1994, victims=8)])
    assert got["known-series"]["status"] == "weakens" and "240 unsolved" in got["known-series"]["text"]

    gap = finding(start=1990, end=1993, total=12, solved=2)            # inside the series' quiet years
    got, _ = run(data, gap, [series(1985, 2007, victims=10, active=[[1985, 1988], [2002, 2007]])])
    assert got["known-series"]["status"] == "clear"

    other_method = finding(weapon="Gun")
    got, _ = run(data, other_method, [series(1989, 1994, victims=8)])
    assert got["known-series"]["status"] == "clear"


def test_reporting_gaps_are_found(data):
    # The sample's Pine Police reported murders to the FBI in 2000-2004 but sent no case records.
    pine = data.cases[data.cases.agency == "Pine Police"]
    assert not pine.empty and not pine.year.between(2000, 2004).any()
    f = finding(place="Pine, SS", start=1998, end=2006, weapon="Gun")
    got, verdict = run(data, f)
    assert got["reporting"]["status"] == "weakens" and verdict in ("weakens", "explains")
    assert "Pine Police reported" in got["reporting"]["text"] and "2000–2004" in got["reporting"]["text"]


def test_every_check_runs_and_nothing_is_hidden(data):
    f = finding()
    got, verdict = run(data, f)
    assert set(got) >= {"known-series", "reporting", "data-fixes"}
    assert verdict in ruleouts.VERDICTS
    assert all(r["text"] for r in got.values())


def test_new_built_in_enrichers_start_on_for_existing_users(tmp_path, monkeypatch):
    import json
    from coldmap import plugins
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path))
    (tmp_path / "settings.json").write_text(json.dumps({"enrichers": ["county", "kind", "coverage"]}))  # namus off, pre-0.6
    on = plugins.enabled()["enrichers"]
    assert "ruleouts" in on and "namus" not in on      # the new check starts on; their choice stands
    plugins.set_enabled("enricher", "ruleouts", False)
    assert "ruleouts" not in plugins.enabled()["enrichers"]  # and switching it off sticks
