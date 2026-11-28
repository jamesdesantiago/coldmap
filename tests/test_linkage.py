"""Case links: similarity without race or 'undetermined' codes, groups, the checklist and the route."""

import pandas as pd

from coldmap import linkage


def frame(**cols):
    n = len(next(iter(cols.values()))) if cols else 1
    base = {"agency": ["A"] * n, "weapon": ["Knife"] * n, "circumstance": ["Other arguments"] * n,
            "relationship": ["Stranger"] * n, "vic_age": [30] * n, "year": [1990] * n, "month": [5] * n,
            "vic_race": ["White"] * n}
    return pd.DataFrame({**base, **cols})


def test_rare_details_count_more_and_undetermined_never_matches():
    ref = frame(circumstance=["Other arguments"] * 18 + ["Rape"] * 2, agency=["A"] * 20,
                relationship=["Stranger"] * 5 + ["Relationship not determined"] * 15)
    sc = linkage.Scorer(ref)
    common = sc.matrix(frame(circumstance=["Other arguments"]), frame(circumstance=["Other arguments"]))[0, 0]
    rare = sc.matrix(frame(circumstance=["Rape"]), frame(circumstance=["Rape"]))[0, 0]
    assert rare > common
    und = sc.matrix(frame(relationship=["Relationship not determined"]), frame(relationship=["Relationship not determined"]))[0, 0]
    known = sc.matrix(frame(), frame())[0, 0]
    assert und < known                                   # "not determined" isn't a match


def test_race_is_never_used():
    ref = frame(vic_race=["White"] * 10 + ["Black"] * 10, agency=["A"] * 20)
    sc = linkage.Scorer(ref)
    a, b = frame(vic_race=["White"]), frame(vic_race=["Black"])
    assert sc.matrix(a, b)[0, 0] == sc.matrix(a, a)[0, 0]
    assert sc.pairs(a, b)[0] == sc.matrix(a, b)[0, 0]


def test_checklist_marks_ordinary_explanations_as_warnings():
    res = {"groups": [], "unsolved": 10}
    out = linkage.checklist({"state": "S", "ruleout": "weakens"}, res, None)
    assert any(c["ok"] is False and "weakens" in c["text"] for c in out)
    out = linkage.checklist({"state": "S", "ruleout": "clear"}, res, {"real": 10, "chance": 1})
    assert any(c["ok"] is True and "No ordinary explanation" in c["text"] for c in out)
    assert any(c["ok"] is True and "10%" in c["text"] for c in out)


def test_links_on_the_sample_and_the_route(tmp_path, monkeypatch):
    import time
    from coldmap.interfaces import launch
    from coldmap.sample import make_sample
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    app.national()
    while app.job.running:
        time.sleep(0.05)
    _, rows = app.flags()
    f = next(r for r in rows if r["weapon"] == "Strangle/asphyxia")
    out = app.case_links(f["id"], {})
    assert out["unsolved"] >= 3 and "checklist" in out
    assert all(0 <= a < len(out["cases"]) and 0 <= b < len(out["cases"]) for a, b, _ in out["links"])
    assert all("vic_race" not in c and "race" not in c for c in out["cases"])
    narrow = app.case_links(f["id"], {"start": str(f["end"]), "end": str(f["start"])})   # reversed years are fixed
    assert narrow["start"] == f["start"] and narrow["end"] == f["end"]
    monkeypatch.setattr(linkage, "MAX_CASES", 2)
    assert app.case_links(f["id"], {})["too_many"]


def test_link_strength_is_bounded(tmp_path, monkeypatch):
    import time
    from coldmap.interfaces import launch
    from coldmap.sample import make_sample
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    app.national()
    while app.job.running:
        time.sleep(0.05)
    _, rows = app.flags()
    f = next(r for r in rows if r["weapon"] == "Strangle/asphyxia")
    loose = app.case_links(f["id"], {"min": "0.95"})
    tight = app.case_links(f["id"], {"min": "0.999"})
    assert loose["min_pct"] == 0.95 and tight["min_pct"] == 0.999
    assert len(loose["links"]) >= len(tight["links"])
    assert loose["groups"] == tight["groups"]                     # groups don't depend on the slider
    for bad in ("nan", "abc", "5", "-1"):
        assert 0.95 <= app.case_links(f["id"], {"min": bad})["min_pct"] <= 0.999
