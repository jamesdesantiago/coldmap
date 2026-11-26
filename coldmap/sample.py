"""Synthetic sample data in MAP's file formats, for trying coldmap in seconds.

    coldmap sample                       # writes sample_cases.csv and sample_clearance.csv
    coldmap scan sample_cases.csv --state Samplestate --explain 1

Everything here is invented: a fictional state ("Samplestate", "SS") with six
fictional counties. No real victims, places or agencies. Built in:

- a planted series: 14 unsolved strangulations of women aged 18-35 in Harbor
  County, 1988-1991, reported by the Harbor County Sheriff (every detector
  should flag it, with 'high' confidence)
- the 2021 coding problem: 30 unsolved 2021 cases that name an identifying
  relationship (the 2021 fix and `coldmap quality` should catch it)
- a reporting gap: Pine County reports murders to the clearance file but sends
  no case records for 2000-2004 (the coverage check should catch it)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .sources.map_files import MONTHS

STATE, ABBR = "Samplestate", "SS"
COUNTIES = {"Harbor": 22, "Pine": 14, "Riverbend": 30, "Mesa": 8, "Lakeview": 12, "Cedar": 6}  # cases/yr
WEAPONS = [("Handgun - pistol, revolver, etc", .45), ("Knife or cutting instrument", .15),
           ("Personal weapons, includes beating", .1), ("Blunt object - hammer, club, etc", .07),
           ("Strangulation - hanging", .05), ("Firearm, type not stated", .08), ("Shotgun", .03),
           ("Other or type unknown", .05), ("Fire", .02)]
KNOWN_REL = ["Acquaintance", "Wife", "Husband", "Friend", "Girlfriend", "Boyfriend", "Other - known to victim"]


def make_sample(out_dir: str | Path = ".", seed: int = 7) -> tuple[Path, Path]:
    rng = np.random.default_rng(seed)
    rows = []
    wnames, wp = zip(*WEAPONS)
    wp = np.array(wp) / sum(wp)

    def add(county, year, sex, age, weapon, solved, rel=None, agency=None, circ=None):
        rows.append({
            "ID": f"{year}{len(rows):07d}{ABBR}", "CNTYFIPS": f"{county}, {ABBR}", "Ori": f"{ABBR}{len(rows) % 999:05d}",
            "State": STATE, "Agency": agency or f"{county} Police", "Agentype": "Municipal police", "Source": "FBI",
            "Solved": "Yes" if solved else "No", "Year": year, "Month": MONTHS[int(rng.integers(0, 12))],
            "Incident": 1, "ActionType": "Normal update", "Homicide": "Murder and non-negligent manslaughter",
            "Situation": "Single victim/single offender" if solved else "Single victim/unknown offender(s)",
            "VicAge": age, "VicSex": sex, "VicRace": rng.choice(["White", "Black", "Asian", "Unknown"]),
            "VicEthnic": "Unknown or not reported", "OffAge": 30 if solved else 999,
            "OffSex": "Male" if solved else "Unknown", "OffRace": "Unknown", "OffEthnic": "Unknown or not reported",
            "Weapon": weapon,
            "Relationship": rel or (rng.choice(KNOWN_REL) if solved else "Relationship not determined"),
            "Circumstance": circ or ("Other arguments" if solved else "Circumstances undetermined"),
            "Subcircum": "", "VicCount": 0, "OffCount": 0, "FileDate": "", "MSA": f"{county} Metro, {ABBR}",
        })

    for county, per_year in COUNTIES.items():
        for year in range(1980, 2024):
            if county == "Pine" and 2000 <= year <= 2004:
                continue  # reporting gap: no case records these years
            for _ in range(rng.poisson(per_year)):
                sex = "Female" if rng.random() < 0.22 else "Male"
                age = int(rng.integers(14, 75)) if rng.random() > 0.02 else 999
                solved = rng.random() < (0.72 if sex == "Female" else 0.62)
                add(county, year, sex, age, rng.choice(wnames, p=wp), solved)

    # Planted series: Harbor County, 1988-1991.
    for i in range(14):
        add("Harbor", 1988 + i % 4, "Female", int(rng.integers(18, 36)), "Strangulation - hanging", False,
            agency="Harbor County Sheriff")
    # The 2021 coding problem.
    for _ in range(30):
        c = rng.choice(list(COUNTIES))
        add(c, 2021, rng.choice(["Female", "Male"]), int(rng.integers(18, 60)), "Handgun - pistol, revolver, etc",
            False, rel=rng.choice(KNOWN_REL))

    cases = pd.DataFrame(rows)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases_path = out_dir / "sample_cases.csv"
    cases.to_csv(cases_path, index=False)

    # Clearance file: murders per agency-year, including the Pine County gap years.
    c = cases.groupby(["CNTYFIPS", "Agency", "Year"]).agg(MRD=("Solved", "size"),
                                                         CLR=("Solved", lambda s: (s == "Yes").sum())).reset_index()
    gap = pd.DataFrame([{"CNTYFIPS": f"Pine, {ABBR}", "Agency": "Pine Police", "Year": y,
                         "MRD": int(rng.poisson(14)), "CLR": int(rng.poisson(9))} for y in range(2000, 2005)])
    c = pd.concat([c, gap], ignore_index=True)
    clearance = pd.DataFrame({"ORI": f"{ABBR}00001", "Name": c.Agency.str.upper(), "YEAR": c.Year, "MRD": c.MRD,
                              "CLR": c.CLR, "Source": "FBI", "State": STATE, "County": c.CNTYFIPS,
                              "Agency": c.Agency})
    clearance_path = out_dir / "sample_clearance.csv"
    clearance.to_csv(clearance_path, index=False)
    return cases_path, clearance_path
