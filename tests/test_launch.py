"""`coldmap open`: the local app (download, check for updates, list states, build with progress)."""

import json
import os
import sys
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

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
    other = df.assign(State="Otherstate", ID=df.ID.astype(str) + "x",  # its own places, like real states
                      CNTYFIPS=df.CNTYFIPS.str.replace(", SS", ", OS"), Agency=df.Agency + " (O)")
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

        def post(p, header=True, body=None):  # returns (status, json)
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + p, method="POST", data=data,
                                         headers={"X-Coldmap": "1", "Content-Type": "application/json"} if header else {})
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
    assert served["path"] == "/" and served["app"].mode == "sample"
    assert not (chome / "sites").exists()  # the app runs setup, with progress

    r = CliRunner().invoke(main, ["open", "California", "--no-browser"])
    assert served["path"] == "/?state=California"


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
    app.setup()
    job = _wait(app)
    assert job.error is None and job.result["findings"] > 0
    assert [s["key"] for s in job.steps][:3] == ["dl-cases", "dl-clearance", "load"]
    assert all(s["state"] == "done" for s in job.steps)
    assert ticks == ["SHR76_25a.csv", "UCR65_25.csv"]
    st = app.status()
    assert st["data"]["ready"] and st["national"]["findings"] == job.result["findings"]
    assert st["data"]["files"][0]["downloaded"] and not st["national"]["stale"]

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


def test_research_flow_from_flag_to_export(chome, tmp_path, server):
    """Setup scans every state; then a flag's evidence, keep, second review, export."""
    cases, clearance = _two_state_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    get, post = server(app)
    for page in ("/", "/flags", "/flags/abc", "/shortlist", "/places/samplestate", "/models", "/ai", "/methods"):
        assert "<title>coldmap</title>" in get(page)[1]
    assert json.loads(get("/api/status")[1])["national"] is None
    with pytest.raises(urllib.error.HTTPError, match="403"):
        post("/api/setup", header=False)
    code, job = post("/api/setup")
    assert code == 202 and job["kind"] == "setup"
    assert _wait(app).error is None

    flags = json.loads(get("/api/flags")[1])["flags"]
    assert {f["state"] for f in flags} == {"Samplestate", "Otherstate"} and all(f["id"] for f in flags)
    f = flags[0]
    d = json.loads(get(f"/api/flag/{f['id']}")[1])
    assert d["flag"]["id"] == f["id"] and d["series"] and d["cases_total"] == len(d["cases"]) > 0
    assert d["decision"] is None

    with pytest.raises(urllib.error.HTTPError, match="400"):  # export needs a second review
        post("/api/decide", body={"id": f["id"], "status": "sent"})
    post("/api/decide", body={"id": f["id"], "status": "kept"})
    post("/api/note", body={"id": f["id"], "note": "Checked local news; no known series."})
    with pytest.raises(urllib.error.HTTPError, match="400"):
        post("/api/decide", body={"id": f["id"], "status": "reviewed"})  # needs the reviewer's name
    post("/api/decide", body={"id": f["id"], "status": "reviewed", "reviewer": "A.B."})
    md = get(f"/api/export?id={f['id']}")[1]
    assert md.startswith("# Lead for review:") and "Reviewed by A.B." in md
    assert "not evidence that cases are linked" in md and "Checked local news" in md
    assert json.loads(get("/api/status")[1])["decisions"]["reviewed"] == 1

    places = json.loads(get("/api/places?sex=Female")[1])
    assert {p["state"] for p in places} == {"Samplestate", "Otherstate"}
    both = {p["state"]: p for p in json.loads(get("/api/places?sex=all")[1])}
    women = {p["state"]: p for p in places}
    assert both["Samplestate"]["killings"] > women["Samplestate"]["killings"]  # men and women together
    assert both["Samplestate"]["flags"] >= women["Samplestate"]["flags"]
    prof = json.loads(get("/api/place?state=Samplestate&sex=Female")[1])
    county = prof["counties"][0]["county"]
    cp = json.loads(get(f"/api/place?state=Samplestate&county={urllib.parse.quote(county)}&sex=Female")[1])
    assert cp["cells"] and cp["killings"] > 0
    ai = json.loads(get("/api/ai")[1])
    assert ai["desktop"]["mcpServers"]["coldmap"]["env"]["COLDMAP_CASES"] == str(cases)
    assert "research_flags" in [t[0] for t in ai["tools"]]


def test_one_job_at_a_time(chome, tmp_path, server):
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    gate = threading.Event()
    app.start("national", "Waiting", [("x", "Wait")], lambda job: gate.wait(10))
    _, post = server(app)
    with pytest.raises(urllib.error.HTTPError, match="409"):
        post("/api/national")
    gate.set()
    _wait(app)


def test_states_list_is_cached_without_loading(chome, tmp_path, monkeypatch):
    cases, clearance = make_sample(tmp_path)
    launch.Library(cases, clearance).states()
    lib = launch.Library(cases, clearance)
    monkeypatch.setattr(lib, "data", lambda: pytest.fail("loaded the case file"))
    assert lib.states() == ["Samplestate"] and lib.counts["Samplestate"] > 0


def test_busy_port_is_refused_not_shared():
    """On Windows the stdlib server would share a busy port; ours must fail so serve() falls back."""
    a = launch._Server(("127.0.0.1", 0), launch._handler(launch.App("map")))
    try:
        with pytest.raises(OSError):
            launch._Server(("127.0.0.1", a.server_address[1]), launch._handler(launch.App("map")))
    finally:
        a.server_close()


# ---- plugins and nationwide ------------------------------------------------------------------
def test_plugin_file_adds_notes_and_rebuilds(chome, tmp_path):
    from coldmap import plugins
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    site = app.lib.build("Samplestate")
    old = app.lib.stamp
    r = app.plugin_action("example", {}, b"")
    assert r["added"]["provides"] == [{"kind": "enricher", "name": "before-after"}]
    assert "before-after" in plugins.enabled()["enrichers"]
    assert app.lib.stamp != old and not app.lib.is_built("Samplestate")  # plugins changed: rebuild
    site = app.lib.build("Samplestate")
    rows = json.loads((site / "agg.json").read_text())["meta"]["findings"]["ensemble"]["0"]
    notes = [n for r in rows for n in (r[13].get("plugins") or [])]
    assert notes and all(n["by"] == "before-after" and "During:" in n["text"] for n in notes)

    app.plugin_action("enable", {"kind": "enricher", "name": "before-after", "on": "0"}, b"")
    assert "before-after" not in plugins.enabled()["enrichers"]
    with pytest.raises(click.ClickException, match="rely on it"):
        app.plugin_action("enable", {"kind": "enricher", "name": "county", "on": "0"}, b"")
    app.plugin_action("remove", {"file": "before_after.py"}, b"")
    assert plugins.files() == []


def test_bad_plugin_files_are_refused_and_nothing_breaks(chome, tmp_path):
    from coldmap import plugins
    with pytest.raises(ValueError, match="valid Python"):
        plugins.add("broken.py", "def (:\n")
    with pytest.raises(ValueError, match="didn't register"):
        plugins.add("empty.py", "x = 1\n")
    with pytest.raises(ValueError, match="ImportError|ModuleNotFoundError"):
        plugins.add("needs.py", "import not_a_real_module_xyz\n")
    with pytest.raises(ValueError, match="simple name"):
        plugins.add("../evil.py", "x = 1\n")
    assert plugins.files() == [] and not list(plugins.folder().glob("*.py"))


def test_starter_plugin_works_and_names_do_not_clash(chome):
    from coldmap import plugins
    from coldmap.enrichers import ENRICHERS
    a = plugins.add(*plugins.starter())
    b = plugins.add(*plugins.starter())
    assert (a["file"], b["file"]) == ("my_plugin.py", "my_plugin_2.py")
    assert {"my-plugin", "my-plugin-2"} <= set(ENRICHERS.names())
    assert ENRICHERS.origin("my-plugin") == "file my_plugin.py"


def test_models_change_marks_the_scan_out_of_date(chome, tmp_path):
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    app.national()
    assert _wait(app).error is None and app.status()["national"]["stale"] is False
    app.plugin_action("example", {}, b"")
    assert app.status()["national"]["stale"] is True  # still shown, with a re-scan offer
    assert app.flags()[1]


def test_plugin_guide_ships_inside_the_app(chome, tmp_path, server):
    """The guide is served by the app itself, so its link works offline and before any merge."""
    cases, clearance = make_sample(tmp_path)
    get, _ = server(launch.App("files", cases, clearance))
    assert "<title>coldmap</title>" in get("/guide")[1]
    guide = get("/guide.md")[1]
    assert guide.startswith("# Plugins") and "../examples/before_after.py" in guide
    assert "class BeforeAfter(Enricher)" in get("/guide/before_after.py")[1]
    page = get("/models")[1]
    assert 'href="/models/guide"' in page and "PLUGINS.md" not in page


def test_your_datasets_describe_places_never_people(chome, tmp_path, server):
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    get, post = server(app)
    post("/api/setup")
    _wait(app)
    flags = json.loads(get("/api/flags")[1])["flags"]
    f = next(x for x in flags if x.get("county"))
    county = f["county"]
    name, st = county.rsplit(", ", 1)
    text = "County,Year,Missing reports,Reporter email,Note\n" + "\n".join(
        f'"{name} County, Samplestate",{y},{y % 5},someone{y}@example.org,checked' for y in range(f["start"] - 2, f["end"] + 3))
    pv = post("/api/datasets/preview", body={"text": text})[1]
    left = {c["name"]: c["left_out"] for c in pv["columns"] if c["left_out"]}
    assert list(left) == ["Reporter email"]
    assert pv["guess"] == {"place": "County", "level": "county", "time": "Year"}
    ck = post("/api/datasets/check", body={"text": text, "place": "County", "level": "county", "time": "Year"})[1]
    assert ck["places_matched"] == ck["rows"] > 0
    m = post("/api/datasets/add", body={"name": "Missing reports", "text": text, "place": "County", "level": "county",
                                         "time": "Year", "keep": ["Missing reports", "Note", "Reporter email"]})[1]
    assert m["columns"] == ["Missing reports", "Note"] and "Reporter email" in m["left_out"]  # never stored
    stored = (chome / "datasets" / "missing-reports" / "data.csv").read_text()
    assert "@" not in stored and "Reporter" not in stored
    assert "dataset:missing-reports" in app.lib.data().aux  # models can use it
    d = json.loads(get(f"/api/flag/{f['id']}")[1])
    mine = d["datasets"][0]
    assert mine["name"] == "Missing reports" and mine["rows_total"] > 0 and mine["series"]
    assert json.loads(get("/api/status")[1])["national"]["stale"] is True  # models may use it: re-scan offered
    post("/api/datasets/remove?slug=missing-reports")
    assert json.loads(get("/api/datasets")[1]) == []


def test_map_places_counties_and_ships_its_assets(chome, tmp_path, server):
    from coldmap.interfaces import research
    assert research.county_fips("Multnomah, OR") == "41051"
    assert research.county_fips("Baltimore city, MD") == "24510" and research.county_fips("Baltimore, MD") == "24005"
    assert research.county_fips("De Kalb, GA") == "13089" and research.county_fips("Dona Ana, NM") == "35013"
    assert research.county_fips("District of Columbia") == "11001"
    cases, clearance = make_sample(tmp_path)
    get, _ = server(launch.App("files", cases, clearance))
    assert "d3js.org" in get("/vendor/d3.v7.min.js")[1][:200]
    assert '"counties"' in get("/vendor/counties-10m.json")[1][:400]
    with pytest.raises(urllib.error.HTTPError, match="404"):
        get("/vendor/../launch.py")
    m = json.loads(get("/api/map?sex=all")[1])
    assert set(m) == {"counties", "fips", "unmatched"}


def test_one_click_ai_connection(chome, tmp_path, monkeypatch):
    from coldmap.interfaces import connect
    cfg = tmp_path / "Claude" / "claude_desktop_config.json"
    cfg.parent.mkdir()
    # The mistake people make: a second {...} pasted below the first.
    cfg.write_text('{\n  "preferences": {"sidebarMode": "chat"}\n}\n\n{\n  "mcpServers": {"other": {"command": "x"}}\n}\n')
    monkeypatch.setattr(connect, "desktop_path", lambda: cfg)
    server = {"command": "coldmap-mcp", "args": [], "env": {"COLDMAP_HOME": "h"}}
    assert "more than one JSON object" in connect.desktop_status(server)["problem"]
    r = connect.connect_desktop(server)
    assert r["repaired"] and Path(r["backup"]).exists()
    fixed = json.loads(cfg.read_text())  # one valid object now
    assert fixed["preferences"] == {"sidebarMode": "chat"}
    assert fixed["mcpServers"] == {"other": {"command": "x"}, "coldmap": server}
    st = connect.desktop_status(server)
    assert st["connected"] and st["current"] and st["problem"] is None


def test_ai_check_starts_the_real_server(chome, tmp_path):
    import shutil as sh
    from coldmap.interfaces import connect
    exe = Path(sys.executable).with_name("coldmap-mcp.exe" if os.name == "nt" else "coldmap-mcp")
    if not exe.exists() or sh.which(str(exe)) is None and not exe.exists():
        pytest.skip("coldmap-mcp isn't installed in this environment")
    pytest.importorskip("mcp")
    cases, _ = make_sample(tmp_path)
    r = connect.test_server({"command": str(exe), "args": [], "env": {"COLDMAP_CASES": str(cases),
                                                                        "COLDMAP_HOME": str(chome)}})
    assert r["ok"], r
    assert {"research_flags", "shortlist", "local_datasets"} <= set(r["tools"])
