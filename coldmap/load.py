"""Loaders for Murder Accountability Project (MAP) files.

Every loader returns a DataFrame in one normalized schema so detectors never
depend on a source's own column names.

Normalized case schema
----------------------
case_id, state, county, agency, msa, source, year, month,
homicide_type, solved_raw, vic_age, vic_sex, vic_race, vic_ethnic,
off_sex, weapon, weapon_group, relationship, circumstance
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pandas as pd

# Grouping used by the improved detectors. MAP's own algorithm uses the raw
# weapon codes; grouping pools codes that agencies use interchangeably.
WEAPON_GROUPS: dict[str, str] = {
    "Handgun - pistol, revolver, etc": "Gun",
    "Firearm, type not stated": "Gun",
    "Rifle": "Gun",
    "Shotgun": "Gun",
    "Other gun": "Gun",
    "Knife or cutting instrument": "Knife",
    "Blunt object - hammer, club, etc": "Beating/blunt",
    "Personal weapons, includes beating": "Beating/blunt",
    "Strangulation - hanging": "Strangle/asphyxia",
    "Asphyxiation - includes death by gas": "Strangle/asphyxia",
    "Fire": "Fire",
    "Weapon Not Reported": "Not reported",
}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

_SHR_COLUMNS = {
    "ID": "case_id", "State": "state", "CNTYFIPS": "county", "Agency": "agency",
    "MSA": "msa", "Source": "source", "Year": "year", "Month": "month",
    "Homicide": "homicide_type", "Solved": "solved_raw", "VicAge": "vic_age",
    "VicSex": "vic_sex", "VicRace": "vic_race", "VicEthnic": "vic_ethnic",
    "OffSex": "off_sex", "Weapon": "weapon", "Relationship": "relationship",
    "Circumstance": "circumstance",
}


def _read_csv(path: Path, **kw) -> pd.DataFrame:
    path = Path(path)
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not names:
                raise ValueError(f"No CSV inside {path}")
            with z.open(names[0]) as f:
                return pd.read_csv(f, low_memory=False, **kw)
    return pd.read_csv(path, low_memory=False, **kw)


def load_shr(path: str | Path, murders_only: bool = True) -> pd.DataFrame:
    """Load MAP's case-level Supplementary Homicide Report file (SHR76_25a.csv or .zip).

    murders_only drops negligent manslaughter, as MAP's algorithm does.
    """
    raw = _read_csv(Path(path))
    missing = [c for c in _SHR_COLUMNS if c not in raw.columns]
    if missing:
        raise ValueError(f"Not a MAP SHR file; missing columns: {missing}")
    df = raw[list(_SHR_COLUMNS)].rename(columns=_SHR_COLUMNS)
    if murders_only:
        df = df[df.homicide_type.astype(str).str.startswith("Murder")]
    df["solved_raw"] = df.solved_raw.eq("Yes")
    df["vic_age"] = pd.to_numeric(df.vic_age, errors="coerce").fillna(999).astype(int)
    df["year"] = df.year.astype(int)
    df["month"] = df.month.map({m: i + 1 for i, m in enumerate(MONTHS)}).fillna(0).astype(int)
    df["weapon_group"] = df.weapon.map(WEAPON_GROUPS).fillna("Other/unknown")
    df["circumstance"] = df.circumstance.fillna("")
    return df.reset_index(drop=True)


def load_clearance(path: str | Path) -> pd.DataFrame:
    """Load MAP's agency clearance file (UCR65_25.csv): murders and clearances per agency-year."""
    raw = _read_csv(Path(path))
    df = raw.rename(columns={"ORI": "ori", "Name": "name", "YEAR": "year", "MRD": "murders",
                             "CLR": "cleared", "Source": "source", "State": "state",
                             "County": "county", "Agency": "agency"})
    df["cleared"] = df.cleared.fillna(0)
    # Align county names with the case file (Dade County became Miami-Dade in 1997).
    df["county"] = df.county.replace({"Dade, FL": "Miami-Dade, FL"})
    return df
