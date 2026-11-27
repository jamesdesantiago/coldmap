"""Fourth security audit: bounded memory and downloads, safe file names, malformed local files."""

import json

import pytest

from coldmap import benchmarks
from coldmap.interfaces import history


def test_series_import_name_cannot_leave_its_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    csv = tmp_path / "s.csv"
    csv.write_text("name,state,county,victim_sex,weapons,start,end,arrest,note\n"
                   "A,Ohio,\"Lucas, OH\",Female,Knife,1990,1994,1996,Convicted 1998.\n")
    out = benchmarks.import_csv(csv, name="../../escaped")
    assert (tmp_path / "home" / "benchmarks") in __import__("pathlib").Path(out["file"]).parents
    assert not (tmp_path / "escaped.json").exists()


@pytest.mark.parametrize("bad", [{"start": "abc"}, {"victims": "many"}, {"weapons": "Knife"},
                                 {"active": [[1990]]}, {"label": 5}, {"start": True}])
def test_malformed_series_are_skipped_not_fatal(tmp_path, monkeypatch, bad):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path))
    good = {"name": "A", "state": "Ohio", "county": "Lucas, OH", "victim_sex": "Female", "weapons": ["Knife"],
            "start": 1990, "end": 1994, "arrest": 1996, "note": "Convicted 1998."}
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "x.json").write_text(json.dumps([good, {**good, **bad}]))
    series, problems = benchmarks.load_local()
    assert len(series) == 1 and len(problems) == 1


def test_damaged_history_snapshot_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path))
    row = {"id": "a", "state": "S", "level": "county", "place": "A", "sex": "Female", "weapon": "Knife",
           "start": 1990, "end": 1995, "total": 10, "solved": 2}
    history.compare([dict(row)], "2026-01-01T00:00:00+00:00", "d", "m")
    (history.folder() / "20260301-000000.json").write_text("{not json")
    rows = [dict(row)]
    h = history.compare(rows, "2026-06-01T00:00:00+00:00", "d", "m")
    assert h["previous"] == "2026-01-01T00:00:00+00:00" and rows[0]["history"]["status"] == "continuing"


def test_download_stops_past_its_limit(tmp_path):
    from coldmap.interfaces.launch import download
    src = tmp_path / "big.csv"
    src.write_bytes(b"a,b\n" + b"1,2\n" * 300_000)
    with pytest.raises(OSError):
        download(src.as_uri(), tmp_path / "out.csv", "x", progress=lambda d, t: None, max_bytes=100_000)
    assert not (tmp_path / "out.csv").exists() and not (tmp_path / "out.csv.part").exists()
