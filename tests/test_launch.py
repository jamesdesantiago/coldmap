"""`coldmap open`: data download, cached builds, state matching."""

import click
import pytest
from click.testing import CliRunner

from coldmap.interfaces import launch
from coldmap.interfaces.cli import main
from coldmap.sample import make_sample


@pytest.fixture
def chome(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def test_prepare_builds_once_then_reuses(chome, tmp_path):
    cases, clearance = make_sample(tmp_path)
    site = launch.prepare("samplestate", cases, clearance)  # case-insensitive state
    assert (site / "index.html").exists() and (site / "agg.json").exists()
    stamp = (site / ".coldmap-build").stat().st_mtime_ns
    assert launch.prepare("Samplestate", cases, clearance) == site
    assert (site / ".coldmap-build").stat().st_mtime_ns == stamp  # cache hit, no rebuild


def test_unknown_state_suggests(chome, tmp_path):
    cases, clearance = make_sample(tmp_path)
    with pytest.raises(click.ClickException, match="Samplestate"):
        launch.prepare("Sampelstate", cases, clearance)


def test_ensure_data_downloads_then_skips(chome, monkeypatch):
    calls = []

    def fake(url, dest, label):
        calls.append(dest.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x")

    monkeypatch.setattr(launch, "download", fake)
    cases, clearance = launch.ensure_data()
    assert cases.name == "SHR76_25a.csv" and clearance.name == "UCR65_25.csv"
    launch.ensure_data()
    assert calls == ["SHR76_25a.csv", "UCR65_25.csv"]


def test_failed_case_download_explains_manual_route(chome, monkeypatch):
    def boom(url, dest, label):
        raise OSError("no network")

    monkeypatch.setattr(launch, "download", boom)
    with pytest.raises(click.ClickException, match="--cases"):
        launch.ensure_data()


def test_clearance_is_optional(chome, monkeypatch):
    def partial(url, dest, label):
        if "UCR" in dest.name:
            raise OSError("moved")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x")

    monkeypatch.setattr(launch, "download", partial)
    cases, clearance = launch.ensure_data()
    assert cases.exists() and clearance is None


def test_open_sample_serves(chome, monkeypatch):
    served = {}
    monkeypatch.setattr(launch, "serve",
                        lambda lib, state, port, open_browser: served.update(lib=lib, state=state, b=open_browser))
    r = CliRunner().invoke(main, ["open", "--sample", "--no-browser"])
    assert r.exit_code == 0, r.output
    assert "not evidence that cases are linked" in r.output
    assert served["state"] == "Samplestate" and served["b"] is False
    assert (served["lib"].site("Samplestate") / "index.html").exists()


def _two_state_sample(tmp_path):
    """The sample plus a copy of it relabelled as a second state."""
    import pandas as pd
    cases, clearance = make_sample(tmp_path)
    df = pd.read_csv(cases)
    other = df.assign(State="Otherstate", ID=df.ID.astype(str) + "x")
    pd.concat([df, other]).to_csv(cases, index=False)
    return cases, clearance


def test_server_lists_and_builds_every_state_on_request(chome, tmp_path):
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    cases, clearance = _two_state_sample(tmp_path)
    lib = launch.Library(cases, clearance)
    assert lib.states() == ["Otherstate", "Samplestate"]
    lib.build("Samplestate")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), launch._handler(lib, "Samplestate"))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    get = lambda p: urllib.request.urlopen(base + p).read().decode()
    try:
        assert "<title>coldmap</title>" in get("/")  # redirects to the first state
        states = json.loads(get("/states.json"))["states"]
        assert [s["slug"] for s in states] == ["otherstate", "samplestate"]
        assert "Building Otherstate" in get("/otherstate/")  # not built yet: progress page
        urllib.request.urlopen(urllib.request.Request(base + "/build?state=Otherstate", method="POST"))
        assert "<title>coldmap</title>" in get("/otherstate/")
        assert json.loads(get("/otherstate/agg.json"))["meta"]["state"] == "Otherstate"
        with pytest.raises(urllib.error.HTTPError):
            get("/nowhere/")
    finally:
        httpd.shutdown()


def test_states_list_is_cached_without_loading(chome, tmp_path, monkeypatch):
    cases, clearance = make_sample(tmp_path)
    launch.Library(cases, clearance).states()
    lib = launch.Library(cases, clearance)
    monkeypatch.setattr(lib, "data", lambda: pytest.fail("loaded the case file"))
    assert lib.states() == ["Samplestate"]
