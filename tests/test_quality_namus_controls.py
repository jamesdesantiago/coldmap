import pandas as pd

import coldmap
from coldmap import Query
from coldmap.benchmarks.controls import false_alarms, shuffle_solved
from coldmap.quality import CHECKS, report

from .conftest import make_dataset, state_rows


def _namus_missing_csv(path):
    # Synthetic file in the layout of a NamUs Missing Persons export (names included on purpose).
    rows = []
    for i, y in enumerate(range(1980, 2010)):
        rows.append({"Case": f"MP{i}", "DLC": f"{y}-06-01", "Legal First Name": "Jane", "Legal Last Name": "Doe",
                     "Missing Age": "30 Years", "City": "A City", "County": "A County", "State": "TL",
                     "Biological Sex": "Female", "Race / Ethnicity": "White"})
    for j in range(8):  # extra missing women in 1990-1993
        rows.append({"Case": f"MPX{j}", "DLC": f"{1990 + j % 4}-03-01", "Legal First Name": "X",
                     "Legal Last Name": "Y", "Missing Age": 25, "City": "A City", "County": "A",
                     "State": "TL", "Biological Sex": "F", "Race / Ethnicity": "White"})
    pd.DataFrame(rows).to_csv(path, index=False)


def test_namus_loader_drops_names_and_normalizes(tmp_path, monkeypatch):
    from coldmap.sources import namus
    monkeypatch.setitem(namus.STATES, "TL", "Testland")
    monkeypatch.setitem(namus.ABBR, "Testland", "TL")
    p = tmp_path / "missing.csv"
    _namus_missing_csv(p)
    t = coldmap.SOURCES.get("namus-missing")().load_aux(p)
    assert not any("name" in c.lower() for c in t.columns)
    assert set(t.county) == {"A, TL"} and set(t.sex) == {"Female"} and t.year.min() == 1980
    assert t.age.max() == 30


def test_namus_age_text():
    from coldmap.sources.namus import _age
    assert _age("54 Years") == 54 and _age("6 Months") == 0 and _age("20-30 Years") == 20 and _age("") is None


def test_namus_enricher_counts(tmp_path, monkeypatch, planted):
    from coldmap.sources import namus
    monkeypatch.setitem(namus.STATES, "TL", "Testland")
    monkeypatch.setitem(namus.ABBR, "Testland", "TL")
    p = tmp_path / "missing.csv"
    _namus_missing_csv(p)
    planted.aux = {"namus-missing": coldmap.SOURCES.get("namus-missing")().load_aux(p)}
    try:
        out = coldmap.run(planted, Query(), detectors=["window"])
        a = [f for f in out if f.place == "A, TL"][0]
        info = a.extras["namus-missing"]
        assert info["count"] >= 8 and info["ratio"] > 2
        assert "namus-missing.count" in coldmap.findings_frame(out).columns
    finally:
        planted.aux = {}


def test_shuffle_preserves_stratum_rates(planted):
    null = shuffle_solved(planted, Query())
    k = ["year"]
    assert (planted.cases.groupby(k).solved.mean() == null.cases.groupby(k).solved.mean()).all()


def test_false_alarms_lower_on_null_than_real(planted):
    t = false_alarms(planted, Query(), detectors=("scan",), params={"scan": {"reps": 199, "levels": ("county",)}},
                     runs=3, kind=None)
    row = t.iloc[0]
    assert row.real_findings >= 1 and row.null_findings < row.real_findings


def test_quality_checks_run_and_find_planted_problem():
    rows = state_rows(False) + [("B, TL", 2005, "Not reported", False, "Relationship not determined")] * 12
    data = make_dataset(rows)
    r = report(data)
    assert set(r) == {n for n, c in CHECKS if not c.needs_clearance}
    hit = r["weapon-not-reported-spike"]
    assert len(hit) == 1 and hit.iloc[0]["when"] == 2005
