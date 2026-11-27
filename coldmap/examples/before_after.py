"""Before & after: an example coldmap plugin, written to be read.

WHAT IT DOES
For every flag, it looks at the same place, method and victim sex in the years just
before and just after the flagged period, and adds a note to the flag:

    Before (1975-1984): 81% of 42 solved. During: 22% of 27. After (1995-2004): 79% of 38.
    Solve rates were higher on both sides, so the drop is confined to these years.

That helps with triage. A drop with normal years on both sides fits a pattern that came and
went. Low rates on both sides point to a long-running problem solving these cases, which is a
question about the agency more than about one group of killings. Neither is evidence that
cases are linked.

HOW IT GETS ADDED (any one of these)
1. In the app (`coldmap open`): Plugins > Add the example plugin. coldmap copies this file
   into your plugins folder (~/.coldmap/plugins) and switches it on.
2. By hand: copy this file into ~/.coldmap/plugins. coldmap loads every .py file there.
3. As a package other people can `pip install`: see examples/coldmap-streak, which is wired
   in with one entry point in its pyproject.toml.

THE WHOLE CONTRACT
- Subclass Enricher (adds information to flags) or Detector (finds flags).
- Give it a unique `name` and a one-line `summary`; the app shows both.
- Register it with @ENRICHERS.register (or @DETECTORS.register) so coldmap finds it.
- Implement enrich(findings, data): add to each finding, then return the list.
- self.note(finding, title, text) attaches a plain-language note. The explorer shows it
  under "From plugins" on the flag's Why flagged tab, credited to this plugin.

RULES EVERY PLUGIN FOLLOWS (ETHICS.md)
Describe patterns, never people. A note must not call a flag a series or a "serial killer",
name anyone, or suggest contacting anyone.
"""

from __future__ import annotations

from coldmap import ENRICHERS, Enricher


@ENRICHERS.register
class BeforeAfter(Enricher):
    name = "before-after"
    summary = "Solve rates in the years just before and after each flag: a short drop, or a long-running problem?"

    years = 10      # years to look at on each side
    min_cases = 5   # fewer killings than this on a side is too few to compare

    def enrich(self, findings, data):
        if not findings:
            return findings
        # The detectors count victims aged 12 and over, plus those of unknown age (999).
        cases = data.cases[(data.cases.vic_age >= 12)]
        first, last = int(cases.year.min()), int(cases.year.max())

        # Count killings and solved ones per place, sex, method and year, once per level.
        # Filtering the national file separately for every flag would be far slower.
        tables = {}
        for f in findings:
            level = "county" if f.level == "region" or f.level not in cases.columns else f.level
            places = f.extras.get("counties") or [f.county if level == "county" and f.level != "county"
                                                  else f.place]
            if level not in tables:
                wanted = {p for g in findings for p in (g.extras.get("counties") or [g.place, g.county]) if p}
                sub = cases[cases[level].isin(wanted)]
                tables[level] = sub.groupby([level, "vic_sex", "weapon_group", "year"]).solved.agg(["size", "sum"])
            t = tables[level]

            def window(y0, y1):
                """(killings, solved) for this flag's places, sex and method in years y0..y1."""
                n = s = 0
                for place in places:
                    try:
                        rows = t.loc[(place, f.victim_sex, f.weapon)]
                    except KeyError:
                        continue
                    rows = rows[(rows.index >= y0) & (rows.index <= y1)]
                    n, s = n + int(rows["size"].sum()), s + int(rows["sum"].sum())
                return n, s

            before = (max(first, f.start - self.years), f.start - 1)
            after = (f.end + 1, min(last, f.end + self.years))
            nb, sb = window(*before) if before[0] <= before[1] else (0, 0)
            na, sa = window(*after) if after[0] <= after[1] else (0, 0)
            self.note(f, "Before and after", self._describe(f, before, nb, sb, after, na, sa, first, last))
        return findings

    def _describe(self, f, before, nb, sb, after, na, sa, first, last):
        def side(label, span, n, s):
            if span[0] > span[1]:
                edge = f"the data starts in {first}" if label == "Before" else f"the data ends in {last}"
                return f"{label}: no years to compare ({edge})."
            yrs = f"{span[0]}-{span[1]}" if span[0] != span[1] else str(span[0])
            return f"{label} ({yrs}): {s / n:.0%} of {n} solved." if n else f"{label} ({yrs}): no killings recorded."

        during = f.solve_rate
        text = " ".join([side("Before", before, nb, sb),
                         f"During: {during:.0%} of {f.total}.",
                         side("After", after, na, sa)])
        if nb < self.min_cases or na < self.min_cases:
            return text + " Too few killings on one side to compare."
        rb, ra = sb / nb, sa / na
        if rb >= during + 0.2 and ra >= during + 0.2:
            return text + " Solve rates were higher on both sides, so the drop is confined to these years."
        if rb <= during + 0.1 and ra <= during + 0.1:
            return text + (" Solve rates were also low before and after, which points to a long-running "
                           "problem solving these cases rather than a short drop.")
        return text + " The years on each side differ; read them before deciding what this is."
