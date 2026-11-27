"""Flag history between scans, your own known series, and the benchmark in the app."""

import json

import pytest

from coldmap.interfaces import history


def flag(fid, place, start, end, total, solved, **kw):
    return {"id": fid, "state": "S", "level": "county", "place": place, "sex": "Female", "weapon": "Knife",
            "start": start, "end": end, "total": total, "solved": solved, "confidence": "high", **kw}


def test_history_new_continuing_gone(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path))
    first = [flag("a", "A", 1990, 1995, 20, 5), flag("b", "B", 2000, 2004, 10, 2), flag("c", "C", 1980, 1982, 8, 1)]
    assert history.compare(first, "2026-01-01T00:00:00+00:00", "d1", "m1")["previous"] is None
    assert all(r["history"] is None for r in first)                     # nothing to compare with yet
    second = [flag("a2", "A", 1990, 1997, 26, 5),                         # years shifted, 6 more unsolved
              flag("b", "B", 2000, 2004, 10, 3),                          # one more solved
              flag("d", "D", 2010, 2012, 9, 1)]                           # new
    h = history.compare(second, "2026-06-01T00:00:00+00:00", "d2", "m1")
    assert (h["new"], h["continuing"], h["gone"], h["growing"], h["shrinking"]) == (1, 2, 1, 1, 1)
    assert h["changed"] == ["data"] and h["gone_flags"][0]["place"] == "C"
    a = second[0]["history"]
    assert a["status"] == "continuing" and a["trend"] == "growing" and a["delta_unsolved"] == 6
    assert a["since"] == "2026-01-01T00:00:00+00:00" and a["before"]["end"] == 1995
    assert second[2]["history"]["status"] == "new"
    third = [flag("a3", "A", 1990, 1997, 26, 5)]
    history.compare(third, "2026-09-01T00:00:00+00:00", "d2", "m2")
    assert third[0]["history"]["since"] == "2026-01-01T00:00:00+00:00"  # first seen carries through


def test_your_series_need_a_stated_legal_basis(tmp_path, monkeypatch):
    from coldmap.benchmarks import import_csv, load_local, load_series
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path))
    csv = tmp_path / "mine.csv"
    csv.write_text(
        "name,state,county,agency,victim_sex,weapons,start,end,arrest,note,label,victims\n"
        "A,Ohio,\"Franklin, OH\",,Female,Knife;Strangle/asphyxia,1990,1994,1996,Convicted 1998 of 6 murders.,"
        "\"Franklin County, OH, 1990–1994 (conviction, 1998)\",6\n"
        "B,Ohio,\"Lucas, OH\",,Female,Gun,1990,1994,1996,Suspected but never charged.,,\n")
    r = import_csv(csv)
    assert r["series"] == 1 and "legal basis" in r["problems"][0]
    mine, problems = load_local()
    assert len(mine) == 1 and mine[0].source == "mine.json" and mine[0].weapons == ("Knife", "Strangle/asphyxia")
    assert mine[0].victims == 6 and not problems
    assert len(load_series()) == len(load_series(local=False)) + 1


def test_benchmark_runs_in_the_app(tmp_path, monkeypatch):
    import time
    from coldmap.benchmarks import KnownSeries
    from coldmap.interfaces import launch
    from coldmap.sample import make_sample
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    cases, clearance = make_sample(tmp_path)
    planted = KnownSeries("planted", "Samplestate", "Harbor, SS", None, "Female", ("Strangle/asphyxia",),
                          1980, 1996, 1997, "Convicted (synthetic)", "Harbor County, SS (synthetic)")
    monkeypatch.setattr("coldmap.benchmarks.load_series", lambda *a, **k: [planted])
    app = launch.App("files", cases, clearance)
    app.benchmark()
    while app.job.running:
        time.sleep(0.05)
    assert app.job.error is None
    out = json.loads((tmp_path / "home" / "research" / "benchmark.json").read_text())
    assert out["series"][0]["label"] == "Harbor County, SS (synthetic)"
    assert out["caught"]["ensemble"]["full"] + out["caught"]["ensemble"]["partial"] == 1  # the planted series is found
