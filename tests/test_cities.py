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
