"""False alarms in every state: saved per state, resumable, stoppable, shown on flags."""

import json
import time

from coldmap.interfaces import launch
from coldmap.sample import make_sample


def wait(app):
    while app.job.running:
        time.sleep(0.05)
    assert app.job.error is None, app.job.error


def test_controls_every_state(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    app.controls_all(runs=1)
    wait(app)
    saved = json.loads((tmp_path / "home" / "research" / "controls.json").read_text())
    assert set(saved["states"]) == {"Samplestate|Female", "Samplestate|Male"}
    women = saved["states"]["Samplestate|Female"]
    assert women["all"]["real"] >= 1 and {"high", "strong", "possible"} <= set(women)
    c = app.chance_for({"state": "Samplestate", "sex": "Female", "confidence": "high"})
    assert c["real"] == women["high"]["real"] and c["runs"] == 1
    assert app.chance_for({"state": "Elsewhere", "sex": "Female"}) is None
    # a second run skips what's saved
    before = (tmp_path / "home" / "research" / "controls.json").stat().st_mtime_ns
    app.controls_all(runs=1)
    wait(app)
    assert (tmp_path / "home" / "research" / "controls.json").stat().st_mtime_ns == before


def test_stop_is_only_for_long_jobs(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    app.controls_all(runs=1)
    app.stop_job()
    wait(app)
    assert app.job.stop and (app.job.result.get("stopped") or app.job.result.get("states") is not None)
