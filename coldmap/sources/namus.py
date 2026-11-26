"""NamUs (National Missing and Unidentified Persons System) CSV exports.

NamUs data isn't openly downloadable: any registered user (free) can run an
Advanced Search and export the results to CSV. Export open Missing Persons and
open Unidentified Persons cases for the states you care about and pass the files
to coldmap.load(aux={...}).

Privacy: names and any column that could identify a person (name, nickname,
address, phone, contact) are dropped on load and never stored or displayed.
coldmap keeps only date, place, sex, age and race fields, for counting.

Column names vary between NamUs export versions, so each field accepts several
spellings; pass `columns={"date": "My Column"}` to override.
"""

from __future__ import annotations

import re

import pandas as pd

from . import SOURCES, Source
from .map_files import read_csv

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
ABBR = {v: k for k, v in STATES.items()}
_IDENTIFYING = re.compile(r"name|nickname|alias|address|phone|contact|email", re.I)


def _pick(df: pd.DataFrame, options: list[str], override: str | None) -> str | None:
    if override:
        return override
    lower = {c.lower().strip(): c for c in df.columns}
    for o in options:
        if o.lower() in lower:
            return lower[o.lower()]
    return None


def _county_label(county, state_full):
    if pd.isna(county) or pd.isna(state_full) or state_full not in ABBR:
        return None
    c = re.sub(r"\s+(County|Parish|Borough|Census Area|Municipality)$", "", str(county).strip(), flags=re.I)
    return f"{c}, {ABBR[state_full]}"


def _sex(v):
    v = str(v).strip().lower()
    return "Female" if v.startswith("f") else "Male" if v.startswith("m") else "Unknown"


class _NamUs(Source):
    date_options: list[str] = []
    age_options: list[str] = []

    def __init__(self, columns: dict[str, str] | None = None):
        self.columns = columns or {}

    def load_cases(self, path):
        raise NotImplementedError(f"{self.name} has no homicide cases; load it with aux={{'{self.name}': path}}")

    def load_aux(self, path):
        raw = read_csv(path)
        raw = raw[[c for c in raw.columns if not _IDENTIFYING.search(c)]]   # privacy: drop identifying fields
        col = lambda key, opts: _pick(raw, opts, self.columns.get(key))
        need = {"date": col("date", self.date_options), "state": col("state", ["State"]),
                "county": col("county", ["County"]), "sex": col("sex", ["Biological Sex", "Sex"])}
        missing = [k for k, v in need.items() if v is None]
        if missing:
            raise ValueError(f"{self.name}: can't find columns for {missing}. Columns present: "
                             f"{list(raw.columns)}. Pass columns={{...}} to map them.")
        st = raw[need["state"]].astype(str).str.strip()
        state = st.map(lambda s: STATES.get(s.upper(), s if s in ABBR else None))
        out = pd.DataFrame({
            "case_id": raw[col("case_id", ["Case", "Case Number", "NamUs Case", "Case #"])].astype(str)
                       if col("case_id", ["Case", "Case Number", "NamUs Case", "Case #"]) else raw.index.astype(str),
            "date": pd.to_datetime(raw[need["date"]], errors="coerce"),
            "state": state,
            "county": [_county_label(c, s) for c, s in zip(raw[need["county"]], state)],
            "sex": raw[need["sex"]].map(_sex),
        })
        age_col = col("age", self.age_options)
        out["age"] = pd.to_numeric(raw[age_col], errors="coerce") if age_col else pd.NA
        race_col = col("race", ["Race / Ethnicity", "Race/Ethnicity", "Race"])
        out["race"] = raw[race_col].astype(str) if race_col else ""
        out["year"] = out.date.dt.year
        out["kind"] = self.name
        return out.dropna(subset=["year", "county"]).astype({"year": int}).reset_index(drop=True)


@SOURCES.register
class NamUsMissing(_NamUs):
    name = "namus-missing"
    summary = "NamUs Missing Persons CSV export (registered users can export from Advanced Search)"
    date_options = ["DLC", "Date of Last Contact", "Date Last Contact", "Last Contact Date", "Date Missing"]
    age_options = ["Missing Age", "Age Missing", "Age at Missing", "Age Last Seen", "Age"]


@SOURCES.register
class NamUsUnidentified(_NamUs):
    name = "namus-unidentified"
    summary = "NamUs Unidentified Persons CSV export (remains not yet identified)"
    date_options = ["DBF", "Date Body Found", "Date Found", "Date of Discovery", "Found Date"]
    age_options = ["Age From", "Estimated Age From", "Min Age", "Age"]
