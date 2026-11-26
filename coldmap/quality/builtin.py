from __future__ import annotations

import numpy as np
import pandas as pd

from ..fixes import NOT_IDENTIFYING
from . import CHECKS, Check


def _cases(data, state):
    c = data.cases
    return c[c.state == state] if state else c


@CHECKS.register
class OffenderUnknownButRelated(Check):
    name = "unknown-offender-with-relationship"
    summary = ("State-years where many 'unsolved' cases name a relationship that identifies the "
               "offender (wife, acquaintance...): the signature of the 2021 coding problem")

    def run(self, data, state=None, min_cases=50, min_share=0.10):
        c = _cases(data, state)
        u = c[~c.solved_raw]
        g = u.groupby(["state", "year"]).agg(
            unsolved=("solved_raw", "size"),
            named=("relationship", lambda r: (~r.isin(NOT_IDENTIFYING)).sum()))
        g["share"] = g.named / g.unsolved
        typical = g.groupby(level=0).share.transform("median")
        g["typical"] = typical
        g = g[(g.unsolved >= min_cases) & (g.share >= min_share) & (g.share >= 3 * typical)]
        g = g.reset_index().sort_values("named", ascending=False)
        return pd.DataFrame({"where": g.state, "when": g.year,
                             "detail": [f"{n:,} of {u:,} unsolved name an identifying relationship "
                                        f"({s:.0%}; typical {t:.0%})"
                                        for n, u, s, t in zip(g.named, g.unsolved, g.share, g.typical)],
                             "size": g.named})


@CHECKS.register
class WeaponNotReportedSpike(Check):
    name = "weapon-not-reported-spike"
    summary = "Agency-years where an unusual share of cases has no weapon recorded"

    def run(self, data, state=None, min_cases=8, min_share=0.5):
        c = _cases(data, state)
        g = c.groupby(["state", "agency", "year"]).agg(
            cases=("weapon_group", "size"), missing=("weapon_group", lambda w: (w == "Not reported").sum()))
        g["share"] = g.missing / g.cases
        g = g[(g.cases >= min_cases) & (g.share >= min_share)].reset_index()
        g = g.sort_values("missing", ascending=False)
        return pd.DataFrame({"where": g.agency + ", " + g.state, "when": g.year,
                             "detail": [f"{m} of {n} cases have no weapon recorded" for m, n in zip(g.missing, g.cases)],
                             "size": g.missing})


@CHECKS.register
class SolveRateJump(Check):
    name = "solve-rate-jump"
    summary = "State-years whose solve rate jumps or drops sharply against the years around them"

    def run(self, data, state=None, min_cases=100, min_jump=0.12):
        c = _cases(data, state)
        g = c.groupby(["state", "year"]).agg(n=("solved", "size"), rate=("solved", "mean")).reset_index()
        rows = []
        for st, s in g.groupby("state"):
            s = s.set_index("year").sort_index()
            # Neighbors only: the median of the two years either side, excluding the year itself.
            around = pd.Series([s.rate.drop(y).loc[y - 2:y + 2].median() for y in s.index], index=s.index)
            jump = s.rate - around
            for y in s.index[(s.n >= min_cases) & (jump.abs() >= min_jump)]:
                rows.append({"where": st, "when": int(y),
                             "detail": f"solved {s.rate[y]:.0%} vs {around[y]:.0%} in surrounding years "
                                       f"({s.n[y]:,} cases)",
                             "size": round(float(abs(jump[y])), 3)})
        return pd.DataFrame(rows, columns=["where", "when", "detail", "size"]).sort_values("size", ascending=False)


@CHECKS.register
class MissingAgencyYears(Check):
    name = "missing-agency-years"
    summary = "Agency-years with murders in the clearance file but no cases in the case file"
    needs_clearance = True

    def run(self, data, state=None, min_murders=5):
        c = _cases(data, state)
        cl = data.clearance if not state else data.clearance[data.clearance.state == state]
        cl = cl[cl.year >= c.year.min()]
        have = c.groupby(["state", "agency", "year"]).size().rename("case_file")
        rep = cl.groupby(["state", "agency", "year"]).murders.sum().rename("clearance_file")
        t = pd.concat([have, rep], axis=1).fillna(0)
        t = t[(t.case_file == 0) & (t.clearance_file >= min_murders)].reset_index()
        g = (t.groupby(["state", "agency"])
               .agg(years=("year", lambda y: f"{int(y.min())}-{int(y.max())} ({len(y)} yrs)"),
                    murders=("clearance_file", "sum")).reset_index().sort_values("murders", ascending=False))
        return pd.DataFrame({"where": g.agency + ", " + g.state, "when": g.years,
                             "detail": [f"{int(m):,} reported murders with no case records" for m in g.murders],
                             "size": g.murders.astype(int)})


@CHECKS.register
class CoverageGaps(Check):
    name = "coverage-gaps"
    summary = "Counties and decades where the case file holds under 80% of reported murders"
    needs_clearance = True

    def run(self, data, state=None):
        from ..enrichers.builtin import low_coverage_places
        states = [state] if state else sorted(data.cases.state.dropna().unique())
        frames = [low_coverage_places(data, s).assign(state=s) for s in states]
        t = pd.concat(frames) if frames else pd.DataFrame()
        if t.empty:
            return pd.DataFrame(columns=["where", "when", "detail", "size"])
        t = t.sort_values("clearance_file", ascending=False)
        return pd.DataFrame({"where": t.county, "when": t.decade.astype(int).astype(str) + "s",
                             "detail": [f"case file has {int(a):,} of {int(b):,} reported murders ({c:.0%})"
                                        for a, b, c in zip(t.case_file, t.clearance_file, t.coverage)],
                             "size": (t.clearance_file - t.case_file).astype(int)})
