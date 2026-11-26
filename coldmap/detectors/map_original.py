"""MAP's published algorithm (Hargrove, 2010-2017), ported faithfully.

Group by place, victim sex and raw weapon code over all years; keep groups
where 33% or fewer were solved; rank by unsolved count. Uses the raw solved
flag and ignores the query's age and weapon exclusions, as the original does.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.types import Finding
from . import DETECTORS
from .base import Detector


@DETECTORS.register
class MapOriginal(Detector):
    name = "map"
    summary = "MAP's original algorithm: place x victim sex x weapon, all years, <=33% solved"
    tier = "sensitive"

    @dataclass
    class Params:
        place: str = field(default="county", metadata={"help": "county or msa"})
        threshold: float = field(default=0.33, metadata={"help": "Flag at or below this solve rate"})
        use_fixes: bool = field(default=False, metadata={"help": "Use fixed data instead of raw (MAP uses raw)"})

    def detect(self, data, query):
        p = self.params
        d = data.select(query, use_query_age=False, use_exclusions=False)
        d = d[d[p.place].notna() & (d[p.place].astype(str) != "")]
        if p.place == "msa":
            d = d[~d.msa.astype(str).str.contains("Rural|Not in", case=False, na=False)]
        solved = "solved" if p.use_fixes else "solved_raw"
        g = (d.groupby([p.place, "weapon"])
               .agg(total=(solved, "size"), solved=(solved, "sum"), start=("year", "min"), end=("year", "max"))
               .reset_index())
        g = g[g.solved / g.total <= p.threshold]
        g = g.assign(uns=g.total - g.solved).sort_values("uns", ascending=False)
        return [Finding(self.name, r[p.place], p.place, query.victim_sex, r["weapon"], int(r["start"]),
                        int(r["end"]), int(r["total"]), int(r["solved"]), score=float(r["uns"]),
                        county=r[p.place] if p.place == "county" else None)
                for _, r in g.iterrows()]
