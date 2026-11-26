"""`coldmap open`: the local app (download, check for updates, list states, build with progress)."""

import json
import shutil
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import click
import pytest
from click.testing import CliRunner

from coldmap.interfaces import launch
from coldmap.interfaces.cli import main
from coldmap.interfaces.explorer.build import BUILD_STEPS
from coldmap.sample import make_sample


@pytest.fixture
def chome(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def _wait(app, timeout=120):
    end = time.time() + timeout
    while app.job and app.job.running:
        assert time.time() < end, "job never finished"
        time.sleep(0.05)
    return app.job


def _two_state_sample(tmp_path):
    """The sample plus a copy of it relabelled as a second state."""
    import pandas as pd
    cases, clearance = make_sample(tmp_path)
    df = pd.read_csv(cases)
    other = df.assign(State="Otherstate", ID=df.ID.astype(str) + "x")
    pd.concat([df, other]).to_csv(cases, index=False)
    return cases, clearance


@pytest.fixture
def server():
    started = []

    def start(app):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), launch._handler(app))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        started.append(httpd)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"

        def get(p):
            with urllib.request.urlopen(base + p) as r:
                return r.geturl().removeprefix(base), r.read().decode()

        def post(p, header=True):
            req = urllib.request.Request(base + p, method="POST", headers={"X-Coldmap": "1"} if header else {})
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        return get, post
    yield start
    for h in started:
        h.shutdown()


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


def test_build_reports_every_step(chome, tmp_path):
    cases, clearance = make_sample(tmp_path)
    seen = []
    launch.Library(cases, clearance).build("Samplestate", progress=seen.append)
    assert seen == [k for k, _ in BUILD_STEPS]


def test_ensure_data_downloads_then_skips(chome, monkeypatch):
    calls = []

    def fake(url, dest, label, progress=None):
        calls.append(dest.name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("x")
        return {"size": 1, "etag": "v1"}

    monkeypatch.setattr(launch, "download", fake)
    cases, clearance = launch.ensure_data()
    assert cases.name == "SHR76_25a.csv" and clearance.name == "UCR65_25.csv"
    launch.ensure_data()
    assert calls == ["SHR76_25a.csv", "UCR65_25.csv"]


def test_failed_case_download_explains_manual_route(chome, monkeypatch):
    def boom(url, dest, label, progress=None):
        raise OSError("no network")

    monkeypatch.setattr(launch, "download", boom)
    with pytest.raises(click.ClickException, match="--cases"):
        launch.ensure_data()


def test_open_does_no_work_before_the_page(chome, monkeypatch):
    """`coldmap open` starts the app at once: no download, no prompt, no build."""
    monkeypatch.setattr(launch, "download", lambda *a, **k: pytest.fail("downloaded before the page opened"))
    served = {}
    monkeypatch.setattr(launch, "serve", lambda app, port, open_browser, path="/": served.update(
        app=app, path=path, b=open_browser))
    r = CliRunner().invoke(main, ["open", "--no-browser"])
    assert r.exit_code == 0, r.output
    assert "not evidence that cases are linked" in r.output
    assert served["path"] == "/" and served["b"] is False
    assert served["app"].mode == "map" and served["app"].lib is None

    r = CliRunner().invoke(main, ["open", "--sample", "--no-browser"])
    assert r.exit_code == 0, r.output
    assert served["path"] == "/?build=Samplestate" and served["app"].mode == "sample"
    assert not (chome / "sites").exists()  # the page builds it, with progress


def test_download_job_with_progress(chome, tmp_path, monkeypatch):
    cases, clearance = make_sample(tmp_path / "src")
    ticks = []

    def fake(url, dest, label, progress=None):
        src = cases if "SHR" in dest.name else clearance
        progress(0, src.stat().st_size)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dest)
        progress(src.stat().st_size, src.stat().st_size)
        ticks.append(dest.name)
        return {"size": src.stat().st_size, "etag": f"etag-{dest.name}"}

    monkeypatch.setattr(launch, "download", fake)
    app = launch.App("map")
    assert app.status()["data"]["ready"] is False
    job = _wait(app) if app.download() else None
    assert job.error is None and job.result == {"states": 1}
    assert [s["state"] for s in job.steps] == ["done"] * 3
    assert ticks == ["SHR76_25a.csv", "UCR65_25.csv"]
    st = app.status()
    assert st["data"]["ready"] and st["states"][0]["name"] == "Samplestate" and st["states"][0]["cases"] > 0
    assert st["data"]["files"][0]["downloaded"]

    # update check compares ETags without downloading
    monkeypatch.setattr(launch, "remote_info", lambda url: {"size": 1, "etag": "etag-SHR76_25a.csv"
                                                            if "SHR" in url else "etag-UCR65_25.csv"})
    monkeypatch.setattr(launch, "_url", lambda key: launch.MAP_FILES[key][0])
    assert app.check_updates()["updates"] is False
    monkeypatch.setattr(launch, "remote_info", lambda url: {"size": 1, "etag": "new"})
    assert app.check_updates()["updates"] is True


def test_failed_clearance_download_is_a_note(chome, tmp_path, monkeypatch):
    cases, _ = make_sample(tmp_path / "src")

    def partial(url, dest, label, progress=None):
        if "UCR" in dest.name:
            raise OSError("moved")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(cases, dest)
        return {"size": 1, "etag": None}

    monkeypatch.setattr(launch, "download", partial)
    app = launch.App("map")
    app.download()
    job = _wait(app)
    assert job.error is None and "clearance" in job.notes[0]
    assert app.lib.clearance is None


def test_server_lists_and_builds_states_with_progress(chome, tmp_path, server):
    cases, clearance = _two_state_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    get, post = server(app)

    _, page = get("/")
    assert "Choose a state" in page and "<title>coldmap</title>" in page
    st = json.loads(get("/api/status")[1])
    assert st["states"] is None and st["job"]["kind"] == "index"  # listing starts in the background
    _wait(app)
    st = json.loads(get("/api/status")[1])
    assert [s["slug"] for s in st["states"]] == ["otherstate", "samplestate"]
    assert not any(s["built"] for s in st["states"])

    url, _ = get("/otherstate/")  # not built yet: back to the app, which builds it
    assert url == "/?build=otherstate"
    with pytest.raises(urllib.error.HTTPError, match="403"):
        post("/api/build?state=otherstate", header=False)
    code, job = post("/api/build?state=otherstate")
    assert code == 202 and job["title"] == "Building Otherstate"
    assert [s["key"] for s in job["steps"]] == ["load"] + [k for k, _ in BUILD_STEPS]
    done = _wait(app)
    assert done.error is None and done.result["slug"] == "otherstate"

    assert json.loads(get("/otherstate/agg.json")[1])["meta"]["state"] == "Otherstate"
    menu = json.loads(get("/states.json")[1])["states"]
    assert [s["built"] for s in menu] == [True, False]
    assert get("/nowhere/")[0] == "/"


def test_one_job_at_a_time(chome, tmp_path, server):
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    gate = threading.Event()
    app.start("index", "Waiting", [("x", "Wait")], lambda job: gate.wait(10))
    _, post = server(app)
    with pytest.raises(urllib.error.HTTPError, match="409"):
        post("/api/build?state=Samplestate")
    gate.set()
    _wait(app)


def test_states_list_is_cached_without_loading(chome, tmp_path, monkeypatch):
    cases, clearance = make_sample(tmp_path)
    launch.Library(cases, clearance).states()
    lib = launch.Library(cases, clearance)
    monkeypatch.setattr(lib, "data", lambda: pytest.fail("loaded the case file"))
    assert lib.states() == ["Samplestate"] and lib.counts["Samplestate"] > 0
