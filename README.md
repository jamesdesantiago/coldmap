# coldmap

**An extensible framework for finding clusters of unsolved homicides in public U.S. homicide data.**

Homicide investigations are local. When one offender kills across jurisdictions or over many years, no single detective sees the pattern ("linkage blindness"). The [Murder Accountability Project](https://www.murderdata.org) (MAP) showed that statistical screening of national data can surface those patterns. coldmap turns that idea into a framework: pluggable data sources, data fixes, detection models and enrichment steps, combined by an ensemble, scored against known cases, and usable from Python, the command line, an AI assistant (MCP) or a web explorer.

> **A finding is a pattern worth review, never evidence that cases are linked.** Read [ETHICS.md](ETHICS.md) before sharing anything coldmap produces.

## The pipeline

```
 Source ──► Fixes ──► Dataset ──► Detectors ──► Enrichers ──► Ensemble ──► Findings
 (plugin)   (plugin)              (plugins)     (plugins)     (matcher)        │
                                                                             ▼
                                         Benchmarks · CLI · MCP server · Explorer
```

Every box marked *plugin* is a registry. Built-ins register themselves; third-party packages register through Python entry points, so installing a plugin is all it takes for every interface to see it. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Built-in plugins

| Kind | Name | What it does |
|---|---|---|
| source | `map-shr` | MAP's case file (`SHR76_25a.csv` or `.zip`) |
| source | `map-clearance` | MAP's agency clearance file (`UCR65_25.csv`) |
| fix | `2021-relationship-coding` | Corrects ~1,100 California 2021 cases wrongly read as unsolved ([DATA_ISSUES.md](DATA_ISSUES.md)) |
| detector | `scan` (strict) | Every window length at county and agency level vs the rest of the state; Monte Carlo p-values, false-discovery-rate q-values |
| detector | `window` (sensitive) | Fixed rolling windows below a solve-rate threshold |
| detector | `map` (sensitive) | Faithful port of MAP's original algorithm |
| enricher | `county`, `kind`, `coverage` | County for agency findings; serial-pattern vs accountability; share of murders present in the case file |

An example third-party detector lives in [`examples/coldmap-streak`](examples/coldmap-streak).

## Quick start

```bash
pip install -e ".[mcp,dev]"
# Data: download SHR76_25a.csv (and optionally UCR65_25.csv) from https://www.murderdata.org/p/data-docs.html

coldmap plugins                                               # what's installed, with every parameter
coldmap scan SHR76_25a.csv --state California --kind serial-pattern
coldmap scan SHR76_25a.csv --state Indiana -d scan -p scan.levels=agency
coldmap scan SHR76_25a.csv --state California -d scan -d window -d map   # any combination
coldmap benchmark SHR76_25a.csv --backtest
coldmap coverage SHR76_25a.csv --clearance UCR65_25.csv --state Illinois
coldmap explorer SHR76_25a.csv --state California --out-dir site
```

```python
import coldmap

data = coldmap.load("SHR76_25a.csv", clearance_path="UCR65_25.csv")
findings = coldmap.run(data, coldmap.Query(state="California"), kind="serial-pattern")
findings = coldmap.run(data, coldmap.Query(state="Indiana"),
                       detectors=["scan", "window"], params={"scan": {"levels": ("agency",)}})
coldmap.findings_frame(findings)
```

## Ensembles and confidence

No single model catches everything, so detectors are combined. The ensemble runs any set of detectors and a `Matcher` decides which findings agree (default: same county, victim sex and method, overlapping years). Each finding gets `found_by` and a confidence:

| Confidence | Meaning |
|---|---|
| high | Two or more detectors agree |
| strong | One strict detector (false alarms controlled) |
| possible | One sensitive detector |

Swap in a different `Matcher` to define agreement another way (neighboring counties, similar victim profiles).

## Benchmarks

`coldmap benchmark` scores any detector, or the ensemble, against known adjudicated series stored in [`coldmap/benchmarks/known_series.json`](coldmap/benchmarks/known_series.json). Results on MAP's August 2026 file:

| Series | window | scan | map | ensemble |
|---|---|---|---|---|
| William Suff, Riverside County 1986–1991 | caught | caught | missed | high |
| Hillside Stranglers, Los Angeles 1977–1978 | caught | missed | missed | high |
| Golden State Killer, Orange County 1980–1981 | caught | missed | missed | possible |
| Green River Killer, King County WA 1982–1984 | caught | caught | missed | high |
| Darren Vann, Gary IN 1994–2014 | missed | caught | missed | strong |

MAP's original method pools all 50 years for a county, which dilutes these short series; it was designed for national screening with expert review, and its strongest flags (such as strangulations of women in Fulton County, Georgia) are reproduced exactly.

`--backtest` reports the first year each would have been flagged using only data available then (Suff: 1986, arrest 1992; Green River: 1982, arrest 2001; Gary: 1998, arrest 2014). Lead times are optimistic: any finding overlapping the series' years counts.

A new detector earns its place by catching what others miss without adding noise. The benchmark is how you show that.

## AI assistants (MCP)

```json
{ "mcpServers": { "coldmap": {
    "command": "coldmap-mcp",
    "env": { "COLDMAP_CASES": "/path/SHR76_25a.csv", "COLDMAP_CLEARANCE": "/path/UCR65_25.csv" } } } }
```

Tools: `list_plugins`, `scan_clusters` (any detectors, any parameters), `get_cases`, `coverage_gaps`, `benchmark`. Every result carries the ethics notice.

## Explorer

`coldmap explorer` builds a static site for one state: a heatmap of solve rates by year and method, findings from every detector you ran (alone or combined), and the case records behind each. The page reads detector names from the data, so new plugins appear automatically.

## Extending

[CONTRIBUTING.md](CONTRIBUTING.md) walks through adding a detector, source, fix or enricher, and packaging it as a plugin. Ideas on the roadmap:

- Spatial scan across neighboring counties (needs county centroids or adjacency)
- Victim-profile detectors (age band, circumstance) and a matcher that compares profiles
- Sources: Jacob Kaplan's FBI SHR files, NamUs missing and unidentified persons, city open-data portals
- AI triage enricher: check each finding against public news and draft an evidence summary for human review

## Credits and license

The cluster algorithm was created by Thomas Hargrove and the Murder Accountability Project (copyright 2010, 2016, 2017). The data is MAP's, compiled from FBI Supplementary Homicide Reports and MAP's public-records requests. coldmap is independent and not affiliated with or endorsed by MAP. Licensed GPL-3.0-or-later.
