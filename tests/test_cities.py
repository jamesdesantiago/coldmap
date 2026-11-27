"""City data: coarse cells only, nothing that identifies people, and the area scan."""

import numpy as np
import pandas as pd

from coldmap import cities


def city_csv(seed=0, planted=True):
    """A synthetic city about 12 km across: 2,400 killings, 60% solved, with a low-clearance pocket."""
    rng = np.random.default_rng(seed)
    n = 2400
    lat = 40.0 + rng.uniform(0, 0.11, n)
    lon = -75.0 + rng.uniform(0, 0.14, n)
    solved = rng.random(n) < 0.6
    if planted:   # about 1.5 km around one point: 10% solved
        near = np.hypot((lat - 40.05) * 110.6, (lon + 74.93) * 85.0) < 1.5
        solved[near] = rng.random(near.sum()) < 0.1
    return pd.DataFrame({
        "uid": [f"X-{i}" for i in range(n)], "reported_date": [f"{2008 + i % 9}0{1 + i % 9}15" for i in range(n)],
        "victim_last": "DOE", "victim_first": "JANE", "victim_race": "Other", "victim_age": "30",
        "victim_sex": np.where(rng.random(n) < 0.2, "Female", "Male"), "city": "Sampleton", "state": "ss",
        "lat": lat.round(6), "lon": lon.round(6),
        "disposition": np.where(solved, "Closed by arrest", "Open/No arrest")}).to_csv(index=False)


def test_import_keeps_only_coarse_cells(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path))
    text = city_csv() + "1,20100101,A,B,Other,1,Male,Tinyville,SS,41.0,-75.0,Closed by arrest\n"
    pv = cities.preview(text)
    for col in ("victim_last", "victim_first", "victim_race", "victim_age", "lat", "lon", "uid"):
        assert col in pv["left_out"]
    assert "race" in pv["left_out"]["victim_race"] and "1 km" in pv["left_out"]["lat"]
    m = cities.add("Sample", text)
    assert m["source"].startswith("The Washington Post")              # recognised, credited
    assert m["cities"] == 1 and m["dropped"]["in cities with fewer than 3 killings"] == 1
    stored = (tmp_path / "cities" / "sample.csv").read_text()
    assert stored.splitlines()[0] == ",".join(cities.KEEP)
    for word in ("DOE", "JANE", "Other", "X-1"):
        assert word not in stored
    d = cities.load()
    assert d.city.iloc[0] == "Sampleton, SS"                          # state code upper-cased
    assert d.groupby("cell")[["lat", "lon"]].nunique().max().max() == 1   # one point per cell: its centre
    g = cities.grid("Sampleton, SS")
    assert all(c["killings"] >= cities.MIN_SHOWN for c in g["cells"])


def test_scan_finds_the_planted_area_and_not_chance(tmp_path, monkeypatch):
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path))
    cities.add("Sample", city_csv())
    r = cities.scan(reps=199)
    top = [a for a in r["areas"] if a["sex"] == "all"][0]
    assert abs(top["lat"] - 40.05) < 0.02 and abs(top["lon"] + 74.93) < 0.03
    assert top["solved"] / top["killings"] < 0.3 and top["rest_rate"] > 0.5
    cities.remove("sample")
    cities.add("Null", city_csv(seed=1, planted=False))
    assert cities.scan(reps=199)["areas"] == []


def test_get_the_post_data_in_one_click(tmp_path, monkeypatch):
    import time
    from coldmap.interfaces import launch
    from coldmap.sample import make_sample
    src = tmp_path / "homicide-data.csv"
    src.write_text(city_csv(), encoding="latin-1")
    monkeypatch.setenv("COLDMAP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("COLDMAP_WAPO_URL", src.as_uri())
    cases, clearance = make_sample(tmp_path)
    app = launch.App("files", cases, clearance)
    app.city_get_wapo()
    while app.job.running:
        time.sleep(0.05)
    assert app.job.error is None
    m = cities.all_meta()[0]
    assert m["name"] == cities.WAPO_NAME and m["source"] == cities.WAPO and m["rows"] == 2400
    home = tmp_path / "home"
    for f in home.rglob("*"):
        if f.is_file():
            assert "JANE" not in f.read_text(encoding="utf-8", errors="ignore"), f   # names never kept


def test_cross_check_matches_place_victims_and_years(monkeypatch):
    from types import SimpleNamespace
    from coldmap import datasets
    monkeypatch.setattr(datasets, "_STATE_ABBR", {})   # don't leave this made-up case file in the shared cache
    cases = pd.DataFrame({"state": ["Nebraska"] * 4 + ["Kentucky"] * 2,
                          "agency": ["Omaha", "Omaha", "Omaha Tribal", "Lincoln", "Louisville Metro", "Louisville Metro"],
                          "county": ["Douglas, NE", "Douglas, NE", "Thurston, NE", "Lancaster, NE",
                                     "Jefferson, KY", "Jefferson, KY"]})
    data = SimpleNamespace(cases=cases)
    cities._PLACES.clear()
    assert cities.city_places(data, "Omaha, NE") == {"state": "Nebraska", "agency": "Omaha", "county": "Douglas, NE"}
    assert cities.city_places(data, "Louisville, KY")["agency"] == "Louisville Metro"
    assert cities.city_places(data, "Nowhere, NE") is None
    flag = dict(id="f1", state="Nebraska", place="Douglas, NE", level="county", county="Douglas, NE", counties=None,
                sex="Female", weapon="Knife", start=2010, end=2014, confidence="high")
    other = {**flag, "id": "f2", "start": 1990, "end": 1995}            # years don't overlap
    men = {**flag, "id": "f3", "sex": "Male"}
    areas = [dict(city="Omaha, NE", sex="Female", start=2007, end=2017), dict(city="Omaha, NE", sex="all", start=2007, end=2017)]
    cities.cross_check(data, areas, [flag, other, men])
    assert [f["id"] for f in areas[0]["flags"]] == ["f1"]                # women only
    assert [f["id"] for f in areas[1]["flags"]] == ["f1", "f3"]          # both
