"""Attach NamUs context to findings: missing people and unidentified remains in the
same county, period and sex.

Serial victims are often never found (missing persons) or found but never
named (unidentified remains); neither shows up in homicide data. For each
finding this adds, per NamUs table loaded:

    count      open NamUs cases in the finding's county and years (matching sex, age >= 12)
    typical    what that county averages for a period of the same length
    ratio      count / typical (above ~2 is worth a look)

Counts are context, not evidence. NamUs entry is voluntary and uneven: more
recent cases and some states are far better represented.
"""

from __future__ import annotations

from . import ENRICHERS, Enricher

TABLES = ("namus-missing", "namus-unidentified")


@ENRICHERS.register
class NamUsEnricher(Enricher):
    name = "namus"
    summary = "Missing people and unidentified remains from NamUs in the finding's county and years"

    def __init__(self, min_age: int = 12):
        self.min_age = min_age

    def enrich(self, findings, data):
        for table in TABLES:
            t = getattr(data, "aux", {}).get(table)
            if t is None or t.empty:
                continue
            for f in findings:
                if not f.county:
                    continue
                rows = t[(t.county == f.county) & t.sex.isin([f.victim_sex, "Unknown"])]
                rows = rows[rows.age.isna() | (rows.age >= self.min_age)]
                if rows.empty:
                    f.extras[table] = {"count": 0, "typical": 0.0, "ratio": None}
                    continue
                span_years = rows.year.max() - rows.year.min() + 1
                typical = len(rows) / span_years * f.span
                count = int(rows.year.between(f.start, f.end).sum())
                f.extras[table] = {"count": count, "typical": round(typical, 1),
                                   "ratio": round(count / typical, 2) if typical else None}
        return findings
