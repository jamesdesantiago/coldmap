"""Cluster detectors.

map_algorithm   A faithful port of MAP's published SPSS algorithm (2010-2017):
                group by place, victim sex and weapon over all years; keep groups
                where 33% or fewer were solved; rank by unsolved count.
sliding_window  coldmap's improved version: grouped weapons, rolling time windows,
                a minimum group size, and a binomial test against the group's own
                long-run solve rate, so small-county noise can be told from signal.

Both return a list of Flag records. A flag is a pattern worth review, not a link.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd
from scipy.stats import binom

from .issues import apply_fixes


@dataclass
class Flag:
    method: str
    place: str
    victim_sex: str
    weapon: str
    start: int
    end: int
    total: int
    solved: int
    baseline: float | None = None   # long-run solve rate for this place/sex/weapon
    p_value: float | None = None    # chance of this few solved if the baseline held
    fixes: tuple[str, ...] = ()

    @property
    def unsolved(self) -> int:
        return self.total - self.solved

    @property
    def solve_rate(self) -> float:
        return self.solved / self.total if self.total else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d.update(unsolved=self.unsolved, solve_rate=round(self.solve_rate, 3))
        return d


def _prep(df: pd.DataFrame, use_fixes: bool) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if "solved" in df.columns and not use_fixes:
        return df, ()
    if use_fixes:
        out, applied = apply_fixes(df)
        return out, tuple(applied)
    out = df.copy()
    out["solved"] = out.solved_raw.astype(bool)
    return out, ()


def map_algorithm(df: pd.DataFrame, place: str = "county", victim_sex: str = "Female",
                  threshold: float = 0.33, use_fixes: bool = False,
                  state: str | None = None) -> list[Flag]:
    """MAP's algorithm as published. Defaults reproduce it exactly (raw data, raw weapons)."""
    d, fixes = _prep(df, use_fixes)
    if state:
        d = d[d.state == state]
    d = d[(d.vic_sex == victim_sex) & d[place].notna() & (d[place].astype(str) != "")]
    if place == "msa":
        d = d[~d.msa.astype(str).str.contains("Rural|Not in", case=False, na=False)]
    g = d.groupby([place, "weapon"]).agg(total=("solved", "size"), solved=("solved", "sum"),
                                         start=("year", "min"), end=("year", "max")).reset_index()
    g = g[g.solved / g.total <= threshold]
    g = g.assign(uns=g.total - g.solved).sort_values("uns", ascending=False)
    return [Flag("map", r[place], victim_sex, r["weapon"], int(r["start"]), int(r["end"]),
                 int(r["total"]), int(r["solved"]), fixes=fixes) for _, r in g.iterrows()]


def sliding_window(df: pd.DataFrame, place: str = "county", victim_sex: str = "Female",
                   window: int = 4, threshold: float = 0.40, min_cases: int = 8,
                   min_age: int | None = 12, max_p: float | None = None,
                   use_fixes: bool = True, state: str | None = None,
                   exclude_weapons: tuple[str, ...] = ("Not reported",)) -> list[Flag]:
    """Rolling-window detector. Overlapping windows for the same group are merged,
    keeping the one with the most unsolved cases."""
    d, fixes = _prep(df, use_fixes)
    if state:
        d = d[d.state == state]
    d = d[(d.vic_sex == victim_sex) & ~d.weapon_group.isin(exclude_weapons)]
    if min_age is not None:
        d = d[d.vic_age >= min_age]  # 999 (unknown) is kept: often unidentified adults
    flags: list[Flag] = []
    yearly = d.groupby([place, "weapon_group", "year"]).solved.agg(["size", "sum"])
    for (p, w), grp in yearly.groupby(level=[0, 1]):
        grp = grp.droplevel([0, 1]).reindex(range(d.year.min(), d.year.max() + 1), fill_value=0)
        base_t, base_s = grp["size"].sum(), grp["sum"].sum()
        if base_t < min_cases:
            continue
        base = base_s / base_t
        tot = grp["size"].rolling(window).sum().dropna()
        sol = grp["sum"].rolling(window).sum().dropna()
        cands = []
        for end_year in tot.index:
            t, s = int(tot[end_year]), int(sol[end_year])
            if t >= min_cases and s / t <= threshold:
                pv = float(binom.cdf(s, t, base))
                if max_p is None or pv <= max_p:
                    cands.append(Flag("sliding_window", p, victim_sex, w, end_year - window + 1,
                                      end_year, t, s, round(base, 3), pv, fixes))
        cands.sort(key=lambda f: f.unsolved, reverse=True)
        kept: list[Flag] = []
        for f in cands:
            if not any(abs(k.start - f.start) < window for k in kept):
                kept.append(f)
        flags.extend(kept)
    return sorted(flags, key=lambda f: f.unsolved, reverse=True)


def cases_for(df: pd.DataFrame, flag: Flag, use_fixes: bool = True,
              min_age: int | None = 12) -> pd.DataFrame:
    """The case rows behind a flag, unsolved first. min_age should match the detector's."""
    d, _ = _prep(df, use_fixes)
    col = "weapon_group" if flag.method == "sliding_window" else "weapon"
    place_col = "county" if flag.place in set(d.county) else "msa"
    m = ((d[place_col] == flag.place) & (d[col] == flag.weapon) & (d.vic_sex == flag.victim_sex)
         & d.year.between(flag.start, flag.end))
    if min_age is not None:
        m &= d.vic_age >= min_age
    cols = ["year", "month", "agency", "solved", "vic_age", "vic_race", "vic_ethnic",
            "weapon", "circumstance", "relationship"]
    return d.loc[m, cols].sort_values(["solved", "year", "month"])


def flags_to_frame(flags: list[Flag]) -> pd.DataFrame:
    return pd.DataFrame([f.to_dict() for f in flags])
