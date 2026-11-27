"""Agency report: an example of a plugin that adds to the coldmap app itself.

It adds two things, both written in Python, with no web code:

1. A page, "Agencies", in the sidebar: police agencies in a state ranked by how far their
   solve rate falls below the state's, with their unsolved killings and their flags.
2. A section on every flag, "Agency record": for each agency in the flag's place, how often it
   solved these killings in the flagged years compared with every other year.

HOW IT GETS ADDED
In the app: Models > Add a model > Example: Agency report. Or copy this file into
~/.coldmap/plugins. See the plugin guide (Models > Plugin guide) for more.

THE WHOLE CONTRACT FOR A VIEW
- Subclass View; give it a unique `name`, a `title` and a one-line `summary`.
- `place = "page"` adds a page (in the sidebar `group` "Research" or "Extend");
  `place = "flag"` adds a section to every flag's page.
- A page can declare `inputs` (b.state(), b.choice(), b.number(), b.text_input()); the app shows
  them as controls and passes their values to render().
- render() returns a list of blocks: b.heading, b.text, b.note, b.stats, b.table, b.bars,
  b.line, b.flags. The app draws them in its own style.
- ctx.cases is the case table; ctx.flags the ranked flags; ctx.datasets your own datasets.

RULES EVERY PLUGIN FOLLOWS (ETHICS.md)
Describe patterns, never people. A low solve rate is a question about workload, reporting and
resources as much as about any agency; say what the numbers show and no more.
"""

from __future__ import annotations

from coldmap import VIEWS, View, blocks as b


@VIEWS.register
class Agencies(View):
    name = "agencies"
    title = "Agencies"
    summary = "Police agencies in a state ranked by how far their solve rate falls below the state's"
    place = "page"
    group = "Research"
    inputs = [b.state(default="Ohio"),
              b.choice("victims", [["Female", "Women"], ["Male", "Men"], ["all", "Both"]], "Female"),
              b.number("min_killings", 25, label="At least this many killings", min=5, step=5)]

    def render(self, ctx, state="Ohio", victims="Female", min_killings=25):
        c = ctx.cases
        c = c[(c.state == state) & (c.vic_age >= 12)]
        if victims != "all":
            c = c[c.vic_sex == victims]
        if c.empty:
            return [b.note(f"No cases for {state}.", "warn")]
        state_rate = c.solved.mean()
        g = c.groupby("agency").solved.agg(["size", "sum"])
        g = g[g["size"] >= int(min_killings)]
        g["rate"] = g["sum"] / g["size"]
        g["gap"] = ((g["rate"] - state_rate) * 100).round().astype(int)
        g = g.sort_values("gap")

        # The strongest flag at each agency, so a row can open it.
        first_flag = {}
        for f in ctx.flags:
            if f["state"] == state and f["level"] == "agency" and f["place"] not in first_flag:
                first_flag[f["place"]] = f["id"]

        who = {"Female": "women", "Male": "men"}.get(victims, "victims")
        rows = [[a, int(n), f"{r:.0%}", f"{int(gap):+d}", int(n - s), "yes" if a in first_flag else ""]
                for a, n, s, r, gap in zip(g.index, g["size"], g["sum"], g["rate"], g["gap"])]
        worst = g.head(12)
        return [
            b.stats([("Agencies shown", len(g)), (f"{state} solve rate", f"{state_rate:.0%}"),
                     ("Unsolved here", int((c.solved == 0).sum()), "neg")]),
            b.text(f"Killings of {who} 12 and older in **{state}**, by reporting agency (at least "
                   f"{int(min_killings)} killings). The gap is the agency's solve rate minus the state's, in points."),
            b.bars([(a, int(gap)) for a, gap in worst["gap"].items()], title="Largest gaps below the state", unit="pts"),
            b.table(["Agency", "Killings", "Solved", "Gap, pts", "Unsolved", "Has a flag"], rows,
                    flag_ids=[first_flag.get(r[0]) for r in rows], numeric=["Killings", "Solved", "Gap, pts", "Unsolved"]),
            b.note("A low solve rate can reflect workload, reporting practice or resources as much as anything "
                   "else. It is a question to ask, not a finding about an agency.", "info"),
        ]


@VIEWS.register
class AgencyRecord(View):
    name = "agency-record"
    title = "Agency record"
    summary = "For each agency in a flag's place: solve rate in the flagged years against every other year"
    place = "flag"

    def render(self, ctx, flag):
        c = ctx.cases
        c = c[(c.state == flag["state"]) & (c.vic_sex == flag["sex"]) & (c.vic_age >= 12)
              & ((c.weapon_group == flag["weapon"]) | (c.weapon == flag["weapon"]))]
        if flag["level"] == "agency":
            c = c[c.agency == flag["place"]]
        elif flag.get("counties"):
            c = c[c.county.isin(flag["counties"])]
        else:
            c = c[c.county == (flag.get("county") or flag["place"])]
        inside = c.year.between(flag["start"], flag["end"])
        rows = []
        for agency, g in c.groupby("agency"):
            a, o = g[inside[g.index]], g[~inside[g.index]]
            if len(a) == 0:
                continue
            rows.append([agency, len(a), f"{a.solved.mean():.0%}", len(o), f"{o.solved.mean():.0%}" if len(o) else "—"])
        if not rows:
            return [b.text("No agency records for this flag.")]
        rows.sort(key=lambda r: -r[1])
        return [b.table(["Agency", "Killings, flagged years", "Solved", "Killings, other years", "Solved"], rows,
                        numeric=["Killings, flagged years", "Solved", "Killings, other years"])]
