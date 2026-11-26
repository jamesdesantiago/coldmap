import os
import pickle

import numpy as np
import pandas as pd
import pytest

from coldmap import Dataset
from coldmap.fixes import apply_fixes


def make_cases(rows, state="Testland"):
    """rows: (county, year, weapon_group, solved, relationship[, agency]) for adult female victims."""
    recs = []
    for i, r in enumerate(rows):
        county, year, wg, solved, rel = r[:5]
        agency = r[5] if len(r) > 5 else county.split(",")[0] + " PD"
        recs.append(dict(case_id=str(i), state=state, county=county, agency=agency, msa="",
                         year=year, month=1, solved_raw=solved, vic_age=30, vic_sex="Female",
                         vic_race="White", vic_ethnic="Unknown", weapon=wg, weapon_group=wg,
                         relationship=rel, circumstance=""))
    return pd.DataFrame(recs)


def make_dataset(rows, clearance=None):
    cases, fixes = apply_fixes(make_cases(rows), "map-shr")
    return Dataset(cases, source="test", clearance=clearance, fixes=fixes)


def state_rows(planted: bool, seed=1):
    """Five counties of strangulations, ~75% solved; optionally a planted unsolved burst in A."""
    rng = np.random.default_rng(seed)
    rows = [(c, y, "Strangle/asphyxia", bool(rng.random() < 0.75), "Relationship not determined")
            for c in ["A, TL", "B, TL", "C, TL", "D, TL", "E, TL"] for y in range(1980, 2010) for _ in range(4)]
    if planted:
        rows += [("A, TL", y, "Strangle/asphyxia", False, "Relationship not determined")
                 for y in range(1990, 1994) for _ in range(3)]
    return rows


@pytest.fixture(scope="session")
def planted():
    return make_dataset(state_rows(True))


@pytest.fixture(scope="session")
def null_data():
    return make_dataset(state_rows(False, seed=7))


@pytest.fixture(scope="session")
def real():
    cached = os.environ.get("COLDMAP_DATASET_PICKLE")
    if cached and os.path.exists(cached):
        return pickle.load(open(cached, "rb"))
    path = os.environ.get("COLDMAP_CASES") or os.environ.get("COLDMAP_SHR")
    if not path:
        pytest.skip("Set COLDMAP_CASES to MAP's SHR file to run real-data tests")
    import coldmap
    return coldmap.load(path)
