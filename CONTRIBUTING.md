# Contributing

Thanks for helping. Read [ETHICS.md](ETHICS.md) first. Then pick the kind of plugin you're adding.

New to plugins? [PLUGINS.md](PLUGINS.md) is the friendly guide: adding plugins in the app, a line-by-line example, and writing your own as a single file.

## Add a detector

```python
from dataclasses import dataclass, field
from coldmap import Detector, Finding
from coldmap.detectors import DETECTORS

@DETECTORS.register              # or expose it through an entry point (below)
class ProfileDetector(Detector):
    name = "profile"
    summary = "Unsolved killings of women 15-40 with undetermined circumstances"
    tier = "sensitive"           # "strict" only if it controls false alarms

    @dataclass
    class Params:
        min_cases: int = field(default=6, metadata={"help": "Minimum killings"})

    def detect(self, data, query):
        d = data.select(query)   # always start here: applies state, sex, age, as_of
        ...
        return [Finding(self.name, place, "county", query.victim_sex, weapon,
                        start, end, total, solved, county=place)]
```

Checklist:
- Start from `data.select(query)` and never read years after `query.as_of`.
- Use `weapon_group` values for `Finding.weapon` so the ensemble can match you with other detectors.
- Set `county` for agency- or metro-level findings, or let the `county` enricher do it.
- Run `coldmap benchmark CASES -d yourname -d ensemble --backtest` and include the table in your pull request, misses included.
- Run `coldmap controls CASES --state <a few states> -d yourname` and include the false-alarm numbers. A detector that catches more but invents more isn't an improvement.
- Add a synthetic test that plants a cluster your detector should find and checks it stays quiet on null data.

## Add a source

Subclass `coldmap.sources.Source`, implement `load_cases(path)` returning every column in `CASE_COLUMNS` (and `load_clearance` if it has counts), and register it. Add the source's name to any fix's `sources` that applies to it.

## Add a data fix

Register a `coldmap.fixes.Fix` with an `apply(df) -> df` function that changes `solved` (or other columns) only where the problem is. Document it in [DATA_ISSUES.md](DATA_ISSUES.md): what, where found, size, likely cause, fix. Add a test that fails if the problem's signature disappears from the data.

## Add a data-quality check

Subclass `coldmap.quality.Check`, implement `run(data, state=None)` returning a frame with `where`, `when`, `detail` and `size`, and register it with `CHECKS`. Set `needs_clearance = True` if it uses the clearance file.

## Add an enricher

Subclass `coldmap.enrichers.Enricher`, implement `enrich(findings, data)`, register it. Enrichers must not drop findings. Use `self.note(finding, title, text)` to attach a plain-language note; `explain()`, the explorer and the Nationwide page show it under "From plugins". See [`coldmap/examples/before_after.py`](coldmap/examples/before_after.py).

## Add a region set

Write a JSON file (`name`, `state`, `regions`: region name to list of county labels as they appear in the data, e.g. `"Harris, TX"`) and load it with `coldmap.load_regions`, or register a `RegionSet` in a plugin through the `coldmap.regions` entry point. Base regions on established planning or metro regions and say so in `note`.

## Add a preset

Register a `coldmap.presets.Preset(name, summary, detectors, params)`. Say who it's for and benchmark it.

## Add a known series

Append to `coldmap/benchmarks/known_series.json`. Only publicly adjudicated series (conviction, guilty plea or official attribution), with a `note` stating the basis. Series that detectors miss are as valuable as ones they catch: they show where the blind spots are.

## Package a plugin

```toml
# your plugin's pyproject.toml
[project.entry-points."coldmap.detectors"]
profile = "coldmap_profile:ProfileDetector"
```

`pip install` it and `coldmap plugins` will list it. See [`examples/coldmap-streak`](examples/coldmap-streak).

Or skip packaging: a single `.py` file in `~/.coldmap/plugins` is loaded too, and the `coldmap open` app adds files there from a file picker or a link ([PLUGINS.md](PLUGINS.md)).

## Tests

```bash
pytest                                        # synthetic tests
COLDMAP_CASES=/path/SHR76_25a.csv pytest      # adds real-data benchmarks
```
