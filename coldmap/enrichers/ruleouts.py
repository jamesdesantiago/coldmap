"""Rule-out checks: ordinary explanations to rule out before a flag is worth anyone's time.

False alarms cost communities and families, so every flag is checked against the explanations
that most often turn out to be right. Each check gives a verdict:

    explains   a known explanation fits (for example, a known series that ended in a conviction)
    weakens    something in the data could account for part of the flag
    clear      nothing found

Checks:
    known-series  same place, victims and method, overlapping years, as an adjudicated series in
                  the benchmark (coldmap/benchmarks/known_series.json; shown by place and outcome,
                  never by name)
    reporting     agencies here reported murders to the FBI (Return A, MAP's clearance file) in
                  years they sent no case records, or the case file holds under 80% of them
    clearances    agencies here told the FBI they cleared far more murders than the case file shows
                  as solved, so part of the gap may be in reporting rather than in solving
    data-fixes    known coding problems (coldmap/fixes) that touch this state and period

A verdict never hides a flag. It is shown beside it, so the researcher decides.
"""

from __future__ import annotations

from . import ENRICHERS, Enricher
from .builtin import _memo

VERDICTS = ("explains", "weakens", "clear")


def _rows(data, f):
    """Rows of the case file (any victim, any method) for the flag's place, via a county index
    built once per dataset (filtering 900,000 rows for every finding would be slow)."""
    import numpy as np
    c = data.cases
    by_county = _memo(data, ("idx", "county"), lambda: c.groupby("county", sort=False).indices)
    if f.level == "msa":
        by_msa = _memo(data, ("idx", "msa"), lambda: c.groupby("msa", sort=False).indices)
        return c.iloc[by_msa.get(f.place, np.array([], dtype=int))]
    counties = f.extras.get("counties") or [f.county or f.place]
    idx = [by_county[k] for k in counties if k in by_county]
    rows = c.iloc[np.concatenate(idx)] if idx else c.iloc[[]]
    if f.level == "agency":
        rows = rows[rows.agency == f.place]
    return rows


def _reported(data, rows, start, end):
    """The clearance file's rows for these agencies and years."""
    import numpy as np
    cl = data.clearance
    by_county = _memo(data, ("idx", "clearance-county"), lambda: cl.groupby("county", sort=False).indices)
    idx = [by_county[k] for k in rows.county.dropna().unique() if k in by_county]
    rep = cl.iloc[np.concatenate(idx)] if idx else cl.iloc[[]]
    return rep[rep.agency.isin(rows.agency.dropna().unique()) & rep.year.between(start, end)]


@ENRICHERS.register
class RuleOuts(Enricher):
    name = "ruleouts"
    summary = "Checks each flag against ordinary explanations: a known series, reporting gaps, clearance records, coding problems"

    min_missing = 3      # murders reported to the FBI in a year with no case records, to count as a gap
    series_cover = 0.5   # a known series "explains" a flag when it covers at least this share of its years
    clearance_gap = 0.20  # Return A clearance rate this far above the case file's solve rate

    def enrich(self, findings, data):
        if not findings:
            return findings
        from ..benchmarks import load_series
        from ..fixes import FIXES
        series = _memo(data, ("known-series",), load_series)
        c = data.cases
        state_of = _memo(data, ("county-state",),
                         lambda: c.dropna(subset=["county"]).drop_duplicates("county").set_index("county").state.to_dict())
        cl = data.clearance
        for f in findings:
            rows = _rows(data, f)
            state = (state_of.get(f.county) if f.county else None) or (rows.state.mode().iat[0] if len(rows) else None)
            rep = _reported(data, rows, f.start, f.end) if cl is not None and len(rows) else None
            out = [self._known(f, state, series), self._reporting(f, rows, rep), self._clearances(f, rows, rep),
                   self._fixes(f, state, FIXES)]
            out = [o for o in out if o]
            f.extras["ruleouts"] = out
            f.extras["ruleout"] = next((v for v in VERDICTS if any(o["status"] == v for o in out)), "clear")
        return findings

    # ---- the checks ---------------------------------------------------------------------------
    def _known(self, f, state, series):
        weapons = {f.weapon}
        def overlap(s):  # years the series was active within the flag
            spans = s.active or [[s.start, s.end]]
            return sum(max(0, min(b, f.end) - max(a, f.start) + 1) for a, b in spans)

        hits = [s for s in series
                if s.state == state and s.victim_sex == f.victim_sex and weapons & set(s.weapons)
                and overlap(s) > 0
                and (s.county in (f.extras.get("counties") or [f.county, f.place])
                     or (s.agency and s.agency == f.place))]
        if not hits:
            return {"check": "known-series", "title": "Known series", "status": "clear",
                    "text": "No adjudicated series in coldmap's benchmark matches this place, victims, method and period."}
        span = f.end - f.start + 1
        s = max(hits, key=overlap)
        years = overlap(s)
        # "Explains" needs the series to cover most of the flag's years and be big enough to account for
        # a good share of its unsolved killings; a 10-victim series can't explain hundreds.
        big_enough = (s.victims or 0) >= 0.5 * f.unsolved if s.victims else f.unsolved <= 15
        if years / span >= self.series_cover and big_enough:
            return {"check": "known-series", "title": "Known series", "status": "explains",
                    "text": f"Matches a known series that has been through the courts: {s.label or s.county}. It covers "
                            f"{years} of this flag's {span} years, so much of the flag may be that series, already "
                            "solved. Check whether anything here falls outside it."}
        size = (f" The series accounts for about {s.victims} killings; this flag has {f.unsolved} unsolved."
                if s.victims else "")
        return {"check": "known-series", "title": "Known series", "status": "weakens",
                "text": f"Overlaps a known series that has been through the courts ({s.label or s.county}) for {years} of "
                        f"this flag's {span} years.{size} Some of these killings may belong to it, but it can't account "
                        "for the whole flag."}

    def _reporting(self, f, rows, rep):
        if rep is None:
            return None
        if rep.empty:
            return {"check": "reporting", "title": "Reporting gaps", "status": "weakens",
                    "text": "None of the agencies here appear in the FBI's clearance reports for these years, so "
                            "coldmap can't tell how complete the case file is."}
        reported = rep.groupby(["agency", "year"]).murders.sum()
        have = rows[rows.year.between(f.start, f.end)].groupby(["agency", "year"]).size()
        gaps = [(a, int(y), int(n)) for (a, y), n in reported.items()
                if n >= self.min_missing and have.get((a, y), 0) == 0]
        share = (rows.year.between(f.start, f.end).sum() / reported.sum()) if reported.sum() else None
        notes = []
        if gaps:
            by: dict[str, list] = {}
            for a, y, n in gaps:
                by.setdefault(a, []).append((y, n))
            parts = [f"{a} reported {sum(n for _, n in v)} murders in {self._years([y for y, _ in v])} but sent no case records"
                     for a, v in sorted(by.items(), key=lambda kv: -sum(n for _, n in kv[1]))[:3]]
            notes.append("; ".join(parts) + ". Those killings aren't in the case file at all.")
        if share is not None and share < 0.8:
            notes.append(f"Overall the case file holds {share:.0%} of the murders agencies here reported in these years.")
        if notes:
            return {"check": "reporting", "title": "Reporting gaps", "status": "weakens", "text": " ".join(notes)}
        return {"check": "reporting", "title": "Reporting gaps", "status": "clear",
                "text": "The agencies here sent case records for the years they reported murders to the FBI"
                        + (f", and the case file holds {min(share, 1):.0%} of them." if share is not None else ".")}

    def _clearances(self, f, rows, rep):
        if rep is None or "cleared" not in rep.columns:
            return None
        inside = rows[rows.year.between(f.start, f.end)]
        if rep.murders.sum() < 10 or len(inside) < 10:
            return None
        cleared = min(rep.cleared.sum() / rep.murders.sum(), 1.0)
        solved = inside.solved.mean()
        if cleared - solved >= self.clearance_gap:
            return {"check": "clearances", "title": "Clearance records", "status": "weakens",
                    "text": f"Agencies here told the FBI they cleared {cleared:.0%} of murders in these years, but the "
                            f"case file shows {solved:.0%} solved across all victims and methods. Part of the gap may be "
                            "in how cases were reported rather than whether they were solved. (Clearance counts can "
                            "include cases from earlier years.)"}
        if abs(cleared - solved) < 0.10:
            text = (f"The FBI clearance reports ({cleared:.0%} cleared) are in line with the case file "
                    f"({solved:.0%} solved across all victims and methods) for these years.")
        elif cleared < solved:
            text = (f"Agencies here reported clearing {cleared:.0%} of murders to the FBI, lower than the case file's "
                    f"{solved:.0%} solved across all victims and methods, so the case file doesn't understate "
                    "solving here.")
        else:
            text = (f"Agencies here reported clearing {cleared:.0%} of murders to the FBI, somewhat above the case "
                    f"file's {solved:.0%}; not enough of a gap to explain the flag.")
        return {"check": "clearances", "title": "Clearance records", "status": "clear", "text": text}

    def _fixes(self, f, state, FIXES):
        hits = [fx for _, fx in FIXES if fx.name != "solved-at-report" and fx.applies_to(state, f.start, f.end)]
        if not hits:
            return {"check": "data-fixes", "title": "Known coding problems", "status": "clear",
                    "text": "None of coldmap's documented coding problems touch this state and period."}
        fixed = [fx.title for fx in hits if fx.apply is not None]
        open_ = [fx.title for fx in hits if fx.apply is None]
        if open_:
            return {"check": "data-fixes", "title": "Known coding problems", "status": "weakens",
                    "text": "Documented problems coldmap can only mark, not correct, touch this state and period: "
                            + "; ".join(open_) + ". Read DATA_ISSUES.md before relying on the flag."
                            + (f" (Already corrected: {'; '.join(fixed)}.)" if fixed else "")}
        return {"check": "data-fixes", "title": "Known coding problems", "status": "clear",
                "text": "Documented problems touch this state and period, and coldmap has corrected them: "
                        + "; ".join(fixed) + "."}

    @staticmethod
    def _years(ys: list[int]) -> str:
        ys = sorted(set(ys))
        runs, start = [], ys[0]
        for a, b in zip(ys, ys[1:] + [None]):
            if b != a + 1:
                runs.append(f"{start}" if start == a else f"{start}–{a}")
                if b is not None:
                    start = b
        return ", ".join(runs)
