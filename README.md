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
| source | `namus-missing`, `namus-unidentified` | NamUs Missing and Unidentified Persons CSV exports (names dropped on load) |
| fix | `2021-relationship-coding` | Corrects ~630 California 2021 cases wrongly read as unsolved ([DATA_ISSUES.md](DATA_ISSUES.md)) |
| detector | `scan` (strict) | Every window length at county and agency level vs the rest of the state; Monte Carlo p-values, false-discovery-rate q-values |
| detector | `window` (sensitive) | Fixed rolling windows below a solve-rate threshold |
| detector | `map` (sensitive) | Faithful port of MAP's original algorithm |
| enricher | `county`, `kind`, `coverage`, `namus` | County for agency findings; serial-pattern vs accountability; share of murders present in the case file; NamUs missing and unidentified counts vs typical |
| check | 5 data-quality checks | Reporting anomalies, gaps and suspicious years (`coldmap quality`) |

An example third-party detector lives in [`examples/coldmap-streak`](examples/coldmap-streak).

## Quick start

```bash
pip install -e ".[mcp,dev]"
# Data: download SHR76_25a.csv (and optionally UCR65_25.csv) from https://www.murderdata.org/p/data-docs.html

coldmap plugins                                               # what's installed, with every parameter
coldmap scan SHR76_25a.csv --state California --kind serial-pattern
coldmap scan SHR76_25a.csv --state California --preset strict --explain 3   # plain-language triage
coldmap scan SHR76_25a.csv --state Indiana -d scan -p scan.levels=agency
coldmap scan SHR76_25a.csv --state California -d scan -d window -d map   # any combination
coldmap benchmark SHR76_25a.csv --backtest
coldmap controls SHR76_25a.csv --state California                       # false-alarm estimate
coldmap quality SHR76_25a.csv --clearance UCR65_25.csv                   # data-quality report
coldmap scan SHR76_25a.csv --state California --namus-missing missing.csv --namus-unidentified uid.csv
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

## Presets

| Preset | What it runs | Use it for |
|---|---|---|
| `strict` | Strict detector only, 5% false discovery rate, at least 5 unsolved | Leads to send someone |
| `balanced` (default) | Strict + sensitive, labeled by agreement | Everyday use |
| `profiles` | Balanced, split by victim age band (12–17, 18–29, 30–44, 45+) | Offenders who target one age group |
| `exploratory` | Looser thresholds, metro areas, MAP's original method | Research; expect noise |

Explicit `-d` and `-p` options override a preset. Presets are a registry too, so a plugin can ship its own.

**Why only age bands?** Race and ethnicity are left out on purpose: race-based clusters risk spotlighting communities and are easy to misuse. Circumstance is left out because it is circular: police record "circumstances undetermined" largely *because* a case is unsolved, so splitting on it manufactures clusters, and false-alarm tests can't catch that.

## Why was this flagged?

`coldmap.explain(finding, data)`, `coldmap scan --explain N`, the MCP `triage_finding` tool and the explorer's panel all give the same plain-language triage: the numbers against what was expected, which detectors agree and how much that level of confidence is worth, statistics, data problems that touch that state and period, coverage, NamUs context, who the victims were in aggregate, and next steps.

## Ensembles and confidence

No single model catches everything, so detectors are combined. The ensemble runs any set of detectors and a `Matcher` decides which findings agree (default: same county, victim sex and method, overlapping years). Each finding gets `found_by` and a confidence:

| Confidence | Meaning |
|---|---|
| high | Two or more detectors agree |
| strong | One strict detector (false alarms controlled) |
| possible | One sensitive detector |

Swap in a different `Matcher` to define agreement another way (neighboring counties, similar victim profiles).

## Benchmarks

`coldmap benchmark` scores any detector, preset or the ensemble against known adjudicated series in [`coldmap/benchmarks/known_series.json`](coldmap/benchmarks/known_series.json). A hit is **full** if the finding covers at least half the series' years without being much longer, and **partial** if it touches the series but mostly describes something else. Results on MAP's August 2026 file:

| Series | window | scan | balanced | profiles |
|---|---|---|---|---|
| William Suff, Riverside County 1986–1991 | full | partial | full (high) | missed |
| Hillside Stranglers, Los Angeles 1977–1978 | full | missed | full (high) | full (high) |
| Golden State Killer, Orange County 1980–1981 | full | missed | full (possible) | missed |
| Green River Killer, King County WA 1982–1984 | full | full | full (high) | full (high) |
| Darren Vann, Gary IN 1994–2014 | missed | full | full (strong) | full (strong) |
| Chester Turner, Los Angeles 1987–1998 | partial | full | full (high) | full (high) |
| Lonnie Franklin Jr., Los Angeles 1985–2007 | partial | missed | partial (high) | partial (high) |
| Randy Kraft, Orange County 1976–1983 (male victims) | missed | missed | missed | missed |
| Andre Crawford, Chicago 1993–1999 | missed | partial | partial (high) | full (strong) |
| **Recovered** | 4 full, 2 partial | 3 full, 2 partial | **6 full, 2 partial** | 5 full, 1 partial |

What the table says:
- **No detector or preset catches everything,** which is why they're combined, and why `profiles` is worth running alongside `balanced` (it's the only one that fully catches Chicago).
- **Overlapping series blur together.** Turner, Franklin and others were active in South Los Angeles at the same time, so one finding can touch several series.
- **Gun series are a blind spot.** Franklin shot most of his victims; gun findings are labeled accountability because most gun clusters are not serial.
- **Male victims are a blind spot.** Kraft is missed by everything. Killings of men are dominated by other patterns, and improving this is on the roadmap.

MAP's original method pools all 50 years for a county, which dilutes these series; it was designed for national screening with expert review, and its strongest flags (such as strangulations of women in Fulton County, Georgia) are reproduced exactly.

`--backtest` reports the first year each would have been flagged using only data available then (Suff: 1986, arrest 1992; Green River: 1982, arrest 2001; Gary: 1998, arrest 2014). Lead times are optimistic: any finding overlapping the series' years counts.

A new detector earns its place by catching what others miss without adding noise. The benchmark and the negative controls are how you show both.

## How often is it wrong?

Benchmarks measure what a detector catches; **negative controls** measure what it invents. `coldmap controls` shuffles solved and unsolved labels across places within each state, victim sex, method and year. That keeps every statewide trend but destroys real clusters, so any finding on the shuffled data is a false alarm. Serial-pattern findings for women, MAP file August 2026, average of 5 shuffles:

| Confidence | California real / by chance | Indiana | Illinois | Washington |
|---|---|---|---|---|
| high (detectors agree) | 12 / 0.0 | 3 / 0.6 | 6 / 3.8 | 7 / 4.4 |
| strong (strict only) | 1 / 0.0 | 3 / 0.2 | 4 / 0.4 | 2 / 0.6 |
| possible (sensitive only) | 38 / 25.4 | 3 / 5.0 | 3 / 2.2 | 4 / 4.2 |

What this says:
- **"Possible" findings are mostly noise.** Treat them as weak leads at best.
- **"Strong" findings hold up** across all four states.
- **"High" is clean in California and Indiana but not in Illinois or Washington,** where one county (Cook, King) holds most of the state's cases. Comparing that county with "the rest of the state" leaves a thin baseline, and both detectors fire on it by chance. Fixing that (for example, comparing with similar counties in other states) is on the roadmap.
- **Always run `coldmap controls` for the state you're studying** before trusting its findings.

## Data quality

`coldmap quality` runs pluggable checks for problems that can create or hide findings. Highlights from the national file (details in [DATA_ISSUES.md](DATA_ISSUES.md)):

- **California 1983–1995:** 12–33% of "unsolved" cases name a relationship that identifies the offender, against about 2% elsewhere (open question, not auto-fixed)
- **Duval County, Florida (Jacksonville):** 4,429 murders reported since 1976 with no case records at all
- **New York City, 2021:** all 488 cases have no weapon recorded
- **Orleans Parish, Louisiana, 2020s:** the case file holds 49% of reported murders; **Hinds County, Mississippi**, 34%

## NamUs: the victims homicide data can't see

Serial victims are often never found (missing persons) or found but never named (unidentified remains). Neither appears in homicide data. NamUs data isn't openly downloadable, but any registered user (free) can export Advanced Search results to CSV. Pass the exports with `--namus-missing` and `--namus-unidentified`, and the `namus` enricher adds, for each finding, how many open missing and unidentified cases match the same county, years and sex, against that county's typical count. Names and contact fields are dropped on load. Counts are context, not evidence: NamUs coverage is uneven by state and era.

## AI assistants (MCP)

```json
{ "mcpServers": { "coldmap": {
    "command": "coldmap-mcp",
    "env": { "COLDMAP_CASES": "/path/SHR76_25a.csv", "COLDMAP_CLEARANCE": "/path/UCR65_25.csv",
             "COLDMAP_NAMUS_MISSING": "/path/missing.csv", "COLDMAP_NAMUS_UNIDENTIFIED": "/path/uid.csv" } } } }
```

Tools: `list_plugins`, `scan_clusters` (any detectors, parameters or preset), `triage_finding`, `get_cases`, `coverage_gaps`, `data_quality`, `false_alarms`, `benchmark`. Every result carries the ethics notice.

## Explorer

`coldmap explorer` builds a static site for one state: a heatmap of solve rates by year and method, findings from every detector you ran (alone or combined), a "why this was flagged" panel, and the case records behind each. The page reads detector names from the data, so new plugins appear automatically.

## Extending

[CONTRIBUTING.md](CONTRIBUTING.md) walks through adding a detector, source, fix or enricher, and packaging it as a plugin. Ideas on the roadmap:

- Better baselines for states dominated by one county (compare with similar counties nationally)
- Detection for male victims and gun series (the two blind spots in the benchmark)
- A missing-to-unidentified matcher using NamUs exports, with resolved cases as its benchmark
- Spatial scan across neighboring counties (needs county centroids or adjacency)
- Victim-profile detectors (age band, circumstance) and a matcher that compares profiles
- Sources: Jacob Kaplan's FBI SHR files, city open-data portals
- A NamUs-based detector: clusters of missing women with no matching homicides
- AI triage enricher: check each finding against public news and draft an evidence summary for human review

## Credits and license

The cluster algorithm was created by Thomas Hargrove and the Murder Accountability Project (copyright 2010, 2016, 2017). The data is MAP's, compiled from FBI Supplementary Homicide Reports and MAP's public-records requests. coldmap is independent and not affiliated with or endorsed by MAP. Licensed GPL-3.0-or-later.
