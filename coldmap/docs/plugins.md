# Plugins

A plugin adds something to coldmap without changing coldmap itself. The kinds you're most likely to write:

- **Detector**: a new way to find flags (places, methods and years where killings were solved less often than expected).
- **Enricher**: more context on each flag. It can attach a plain-language note that the explorer shows under **From plugins** on the flag's *Why flagged* tab.

Data sources, data fixes, quality checks, region sets and presets are plugins too; [CONTRIBUTING.md](../../CONTRIBUTING.md) covers each one.

> A plugin is Python code that runs on your computer with your permissions. Add only plugins from people you trust, and read the file first.

## Add a plugin (no programming)

Run `coldmap open` and go to **Plugins**:

1. **Example: Before & after.** Adds the example plugin described below with one click.
2. **A file someone shared.** Pick a `.py` plugin file.
3. **From a link.** Paste a link to a `.py` file. GitHub file pages work.
4. **Write your own.** Creates a starter file with each part explained.

coldmap saves the file in your plugins folder (`~/.coldmap/plugins`), loads it and switches on what it provides. The switches on the same page turn any detector or enricher on or off. States rebuild with your choice the next time you open them, and the nationwide scan offers to run again.

You can also skip the app and copy a `.py` file into `~/.coldmap/plugins` yourself. coldmap loads every file there. (`COLDMAP_HOME` moves the whole folder.)

## The example, line by line

[`coldmap/examples/before_after.py`](../examples/before_after.py) is written to be read. For every flag it looks at the same place, method and victim sex in the 10 years before and after the flagged period, and adds a note:

> Before (1976–1984): 36% of 14 solved. During: 38% of 16. After (1989–1998): 79% of 19 solved. The years on each side differ; read them before deciding what this is.

The note helps with triage. A drop with normal years on both sides fits a pattern that came and went. Low rates on both sides point to a long-running problem solving these cases, which is a question about the agency. Neither is evidence that cases are linked.

The whole plugin is this shape:

```python
from coldmap import ENRICHERS, Enricher

@ENRICHERS.register                       # 1. register it, so coldmap can find it
class BeforeAfter(Enricher):
    name = "before-after"                 # 2. a unique name, shown in the app
    summary = "Solve rates in the years just before and after each flag"

    def enrich(self, findings, data):    # 3. add something to every flag
        for f in findings:
            ...                           #    count killings around f.start and f.end in data.cases
            self.note(f, "Before and after", text)
        return findings                   # 4. always return the findings
```

What you have to work with:

- `findings`: a list of `Finding`. Each has `place`, `level` (county, agency, region...), `county`, `victim_sex`, `weapon`, `start`, `end`, `total`, `solved`, `unsolved`, `solve_rate`, `confidence`, `kind`, and `extras`. A region finding lists its counties in `extras["counties"]`.
- `data.cases`: every case as a pandas table, with the columns listed in `coldmap/core/types.py` (`state`, `county`, `agency`, `year`, `vic_sex`, `vic_age`, `weapon_group`, `solved`, ...).
- `self.note(finding, title, text)`: attach a note. It appears in the explorer, on the Nationwide page and in `coldmap scan --explain`, credited to your plugin.

Two habits from the example are worth copying:

- **Group once, then look up.** The national file has about 900,000 cases. Filtering it again for every flag is slow, so the example counts once per call and looks each flag up.
- **Say when there's too little to go on.** Below 5 killings on a side, the note says so instead of drawing a conclusion.

## Write a detector

Same shape, different job: return new findings.

```python
from dataclasses import dataclass, field
from coldmap import DETECTORS, Detector, Finding

@DETECTORS.register
class Streak(Detector):
    name = "my-streak"
    summary = "Consecutive years with killings but none solved"
    tier = "sensitive"                    # "strict" only if it controls false alarms

    @dataclass
    class Params:
        min_years: int = field(default=3, metadata={"help": "Shortest streak to report"})

    def detect(self, data, query):
        d = data.select(query)            # always start here: state, sex, age, cut-off year
        ...
        return [Finding(self.name, place, "county", query.victim_sex, weapon,
                        start, end, total, solved, county=place)]
```

Leave `query.state` alone: it's `None` in a nationwide scan, and `data.select` handles both cases. Before you share a detector, run the benchmark and the false-alarm controls ([CONTRIBUTING.md](../../CONTRIBUTING.md#add-a-detector)). A detector that catches more but invents more isn't an improvement.

## Add a page or a section to the app

A **view** adds to the app itself: a new page in the sidebar (`place = "page"`), or a new section on every flag's page (`place = "flag"`). You write it in Python and return building blocks; the app draws them in its own style, so a view needs no web code and can't run scripts in the app.

```python
from coldmap import VIEWS, View, blocks as b

@VIEWS.register
class Agencies(View):
    name = "agencies"
    title = "Agencies"                                   # what the sidebar shows
    summary = "Police agencies ranked by their gap below the state"
    place = "page"                                       # or "flag"
    group = "Research"                                   # or "Extend"
    inputs = [b.state(default="Ohio"), b.choice("victims", ["Female", "Male"], "Female")]

    def render(self, ctx, state="Ohio", victims="Female"):
        c = ctx.cases[(ctx.cases.state == state) & (ctx.cases.vic_sex == victims)]
        g = c.groupby("agency").solved.agg(["size", "mean"]).sort_values("mean").head(10)
        return [
            b.stats([("Agencies", len(g)), ("Killings", len(c))]),
            b.bars([(a, round(r * 100)) for a, r in g["mean"].items()], title="Share solved", unit="%"),
            b.table(["Agency", "Killings"], [[a, int(n)] for a, n in g["size"].items()]),
        ]
```

- **Inputs** (`b.state`, `b.choice`, `b.number`, `b.text_input`) become controls at the top of the page; their values are passed to `render()`.
- **Blocks**: `b.heading`, `b.text` (with **bold** and `code`), `b.note`, `b.stats`, `b.table` (give `flag_ids` to make rows open a flag), `b.bars`, `b.line`, `b.flags`.
- **ctx** has `ctx.cases` (the case table), `ctx.flags` (the ranked flags), `ctx.decisions` (the shortlist) and `ctx.datasets` (your datasets). A flag section's `render(self, ctx, flag)` also gets the flag.
- If a view fails, the app shows its error in place of its content; nothing else breaks.
- Views can be switched on and off on the Models page, and doing so never makes your flags out of date. AI assistants can run your pages too (the `app_views` tool).

The example [`agency_report.py`](../examples/agency_report.py) adds both: an Agencies page and an "Agency record" section on every flag. In the app: Models > Add a model > Example: Agency report, or start from Models > Add a model > Page starter.

## Use your own data

On the **Data** page you can add datasets of your own: a CSV keyed by a place (county, agency or state) and a time (a year or a date), with any measures or notes beside them. coldmap keeps a cleaned copy on this computer and hands it to every model:

```python
@ENRICHERS.register
class MissingNearby(Enricher):
    name = "missing-nearby"
    summary = "Missing-person reports in the flag's county and years, from my dataset"

    def enrich(self, findings, data):
        reports = data.aux.get("dataset:missing-reports")   # columns: place, level, year, month, then yours
        if reports is None:
            return findings
        for f in findings:
            rows = reports[(reports.place == f.county) & reports.year.between(f.start, f.end)]
            if len(rows):
                self.note(f, "Missing-person reports", f"{int(rows['Missing reports'].sum())} in these years.")
        return findings
```

Datasets describe places and times, never people. Columns that identify individuals (names, addresses, phone numbers, emails, IP addresses, dates of birth, biometric or DNA records, licence plates, exact coordinates) are left out when a file is added, and never stored.

## Try your changes

Save the file, then build a state in the app; coldmap notices the plugin changed and rebuilds. If the file has an error, the Plugins page shows it next to the file name, and nothing else breaks. From a terminal:

```bash
coldmap plugins                                     # is it listed?
coldmap scan SHR76_25a.csv --state Oregon --explain 1
```

## Share it

- **As a file:** put the `.py` file on GitHub and send the link. People add it with **From a link**.
- **As a package** others can `pip install`: add one entry point to your `pyproject.toml`. See [`examples/coldmap-streak`](../../examples/coldmap-streak).

```toml
[project.entry-points."coldmap.enrichers"]
before-after = "coldmap_before_after:BeforeAfter"
```

## Rules every plugin follows

From [ETHICS.md](../../ETHICS.md): describe patterns, never people. A plugin must not call a flag a series or a "serial killer", name anyone, suggest contacting families, witnesses or possible suspects, or profile neighborhoods or groups. Notes say what the numbers show and how much they can bear.
