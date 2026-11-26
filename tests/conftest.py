import os

import pandas as pd
import pytest


def make_cases(rows):
    """rows: list of (county, year, weapon_group, solved, relationship) for female adult victims."""
    base = []
    for i, (county, year, wg, solved, rel) in enumerate(rows):
        base.append(dict(case_id=str(i), state="Testland", county=county, agency="PD", msa="",
                         source="FBI", year=year, month=1, homicide_type="Murder",
                         solved_raw=solved, vic_age=30, vic_sex="Female", vic_race="White",
                         vic_ethnic="Unknown", off_sex="Male" if solved else "Unknown",
                         weapon=wg, weapon_group=wg, relationship=rel, circumstance=""))
    return pd.DataFrame(base)


@pytest.fixture
def synthetic():
    rows = []
    # Quiet county: 40 cases over 20 years, 80% solved.
    for y in range(1990, 2010):
        rows += [("Quiet, TL", y, "Gun", True, "Acquaintance"), ("Quiet, TL", y, "Gun", y % 5 != 0, "Relationship not determined")]
    # Hot county: normally solved, but 1995-1998 strangulations mostly unsolved.
    for y in range(1990, 2010):
        rows += [("Hot, TL", y, "Strangle/asphyxia", True, "Husband")]
    for y in range(1995, 1999):
        rows += [("Hot, TL", y, "Strangle/asphyxia", False, "Relationship not determined")] * 3
    return make_cases(rows)


@pytest.fixture(scope="session")
def real():
    path = os.environ.get("COLDMAP_SHR")
    if not path:
        pytest.skip("Set COLDMAP_SHR to MAP's SHR file to run real-data tests")
    from coldmap import load_shr
    return load_shr(path)
