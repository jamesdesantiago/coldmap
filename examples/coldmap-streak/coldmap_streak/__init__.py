"""Example third-party detector for coldmap.

Flags runs of consecutive years in which a place had killings by one method
and solved none of them. Deliberately simple: it shows the whole plugin
contract in about 40 lines.

Install with `pip install -e examples/coldmap-streak`, then:

    coldmap plugins                       # 'streak' is listed
    coldmap scan SHR76_25a.csv --state California -d scan -d window -d streak
"""

from __future__ import annotations

from dataclasses import dataclass, field

from coldmap import Detector, Finding


class StreakDetector(Detector):
    name = "streak"
    summary = "Consecutive years with killings but none solved"
    tier = "sensitive"

    @dataclass
    class Params:
        place: str = field(default="county", metadata={"help": "county or agency"})
        min_years: int = field(default=3, metadata={"help": "Shortest streak to report"})
        min_cases: int = field(default=5, metadata={"help": "Minimum killings in the streak"})

    def detect(self, data, query):
        p = self.params
        d = data.select(query)
        out = []
        yearly = d.groupby([p.place, "weapon_group", "year"]).solved.agg(["size", "sum"])
        for (place, weapon), g in yearly.groupby(level=[0, 1]):
            g = g.droplevel([0, 1])
            run = []
            for year, row in list(g.iterrows()) + [(None, None)]:
                if row is not None and row["sum"] == 0 and (not run or year == run[-1][0] + 1):
                    run.append((year, int(row["size"])))
                    continue
                total = sum(n for _, n in run)
                if len(run) >= p.min_years and total >= p.min_cases:
                    out.append(Finding(self.name, place, p.place, query.victim_sex, weapon,
                                       run[0][0], run[-1][0], total, 0, score=float(total),
                                       county=place if p.place == "county" else None))
                run = [(year, int(row["size"]))] if row is not None and row["sum"] == 0 else []
        return sorted(out, key=lambda f: f.total, reverse=True)
