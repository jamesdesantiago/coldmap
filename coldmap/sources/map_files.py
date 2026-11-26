"""Murder Accountability Project files: SHR76_25a (cases) and UCR65_25 (clearance)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

from . import SOURCES, Source

WEAPON_GROUPS: dict[str, str] = {
    "Handgun - pistol, revolver, etc": "Gun", "Firearm, type not stated": "Gun", "Rifle": "Gun",
    "Shotgun": "Gun", "Other gun": "Gun",
    "Knife or cutting instrument": "Knife",
    "Blunt object - hammer, club, etc": "Beating/blunt",
    "Personal weapons, includes beating": "Beating/blunt",
    "Strangulation - hanging": "Strangle/asphyxia",
    "Asphyxiation - includes death by gas": "Strangle/asphyxia",
    "Fire": "Fire", "Weapon Not Reported": "Not reported",
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
_SHR = {"ID": "case_id", "State": "state", "CNTYFIPS": "county", "Agency": "agency", "MSA": "msa",
        "Year": "year", "Month": "month", "Homicide": "homicide_type", "Solved": "solved_raw",
        "VicAge": "vic_age", "VicSex": "vic_sex", "VicRace": "vic_race", "VicEthnic": "vic_ethnic",
        "Weapon": "weapon", "Relationship": "relationship", "Circumstance": "circumstance"}


def read_csv(path: str | Path, **kw) -> pd.DataFrame:
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError(f"No CSV inside {path}")
            with z.open(names[0]) as f:
                return pd.read_csv(f, low_memory=False, **kw)
    return pd.read_csv(path, low_memory=False, **kw)


@SOURCES.register
class MapSHR(Source):
    name = "map-shr"
    summary = "MAP's case-level Supplementary Homicide Report file (SHR76_25a.csv/.zip)"

    def __init__(self, murders_only: bool = True):
        self.murders_only = murders_only

    def load_cases(self, path):
        raw = read_csv(path)
        missing = [c for c in _SHR if c not in raw.columns]
        if missing:
            raise ValueError(f"Not a MAP SHR file; missing columns: {missing}")
        df = raw[list(_SHR)].rename(columns=_SHR)
        if self.murders_only:
            df = df[df.homicide_type.astype(str).str.startswith("Murder")]
        df["solved_raw"] = df.solved_raw.eq("Yes")
        df["vic_age"] = pd.to_numeric(df.vic_age, errors="coerce").fillna(999).astype(int)
        df["year"] = df.year.astype(int)
        df["month"] = df.month.map({m: i + 1 for i, m in enumerate(MONTHS)}).fillna(0).astype(int)
        df["weapon_group"] = df.weapon.map(WEAPON_GROUPS).fillna("Other/unknown")
        df["circumstance"] = df.circumstance.fillna("")
        return df.drop(columns="homicide_type").reset_index(drop=True)


@SOURCES.register
class MapClearance(Source):
    name = "map-clearance"
    summary = "MAP's agency clearance file (UCR65_25.csv): murders and clearances per agency-year"

    def load_cases(self, path):
        raise NotImplementedError("map-clearance has no case records; use it as a clearance source")

    def load_clearance(self, path):
        raw = read_csv(path)
        df = raw.rename(columns={"ORI": "ori", "Name": "name", "YEAR": "year", "MRD": "murders",
                                 "CLR": "cleared", "Source": "source", "State": "state",
                                 "County": "county", "Agency": "agency"})
        df["cleared"] = df.cleared.fillna(0)
        # Dade County became Miami-Dade in 1997; the case file uses only the new name.
        df["county"] = df.county.replace({"Dade, FL": "Miami-Dade, FL"})
        return df
