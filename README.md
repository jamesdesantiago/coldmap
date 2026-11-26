# coldmap

An open toolkit for finding clusters of unsolved homicides in public U.S. homicide data, built on the [Murder Accountability Project](https://www.murderdata.org) (MAP) files.

Homicide investigations are local. When one offender kills in several jurisdictions, or over many years, no single detective sees the pattern ("linkage blindness"). MAP showed that a simple statistical screen of national data can surface those patterns. coldmap makes that screen easy to run, test, extend and use from an AI assistant.

> **A flag is a pattern worth review, never evidence that cases are linked.** Read [ETHICS.md](ETHICS.md) before sharing anything this tool produces.

## What's inside

| Part | What it does |
|---|---|
| `coldmap.load` | Loads MAP's case file (`SHR76_25a.csv` or `.zip`) and clearance file (`UCR65_25.csv`) into one normalized schema |
| `coldmap.issues` | Registry of known data problems and the fixes applied (see [DATA_ISSUES.md](DATA_ISSUES.md)) |
| `coldmap.scan` | **Recommended detector.** Searches every time window from 1 to 25 years at agency, county or metro level, compares each with the rest of the state in the same years, tests significance by Monte Carlo simulation, and controls the false discovery rate across all groups. Labels each flag `serial-pattern` or `accountability` |
| `coldmap.detect` | `map_algorithm`: faithful port of MAP's published algorithm. `sliding_window`: fixed rolling windows, more sensitive but no multiple-testing control |
| `coldmap.coverage` | Compares the case file with the clearance file to show how much of each place's murders the case file actually holds. Low coverage = blind spot |
| `coldmap.validate` | Validation and backtesting against known, adjudicated serial cases |
| `coldmap.explorer` | Builds an interactive web explorer (heatmap, ranked flags, case file) for any state |
| `coldmap.mcp_server` | MCP server so Claude or any MCP client can run scans and pull case records |

## Quick start

```bash
pip install -e ".[mcp,dev]"

# Get the data: download SHR76_25a.csv from https://www.murderdata.org/p/data-docs.html

coldmap scan SHR76_25a.csv --state Indiana --level agency --clearance UCR65_25.csv
coldmap validate SHR76_25a.csv
coldmap backtest SHR76_25a.csv
coldmap coverage SHR76_25a.csv UCR65_25.csv --state Illinois
coldmap issues
coldmap explorer SHR76_25a.csv --state California --out-dir site && cd site && python -m http.server
```

In Python:

```python
from coldmap import load_shr
from coldmap.scan import scan
from coldmap.detect import cases_for

df = load_shr("SHR76_25a.csv")
flags = scan(df, state="Indiana", place="agency", max_q=0.10)
print(flags[0].to_dict())          # p_value, q_value, kind, baseline, ...
print(cases_for(df, flags[0]))      # the case rows behind it
```

## How it works

For each place, victim sex and method, `scan` tries every time window and finds where solved cases fell furthest below the **rest of the state** in the same years. Comparing with the rest of the state, year by year, accounts for the long national decline in clearance and stops a big county like Los Angeles from being compared with itself. Monte Carlo simulation (999 runs by default) gives each flag a p-value that already accounts for having tried every window, and the Benjamini-Hochberg procedure gives a q-value across all groups: at `q <= 0.10`, about 1 in 10 flags is expected to be noise.

Flags are labeled:
- **serial-pattern**: strangulation, beating, knife, fire or unknown method, in a group small enough to be one offender's work
- **accountability**: guns or large groups, where the likelier story is a place solving fewer cases overall

## Validation

`coldmap validate` runs both detectors against known series (MAP file, August 2026):

| Series | Window detector | Scan detector |
|---|---|---|
| William Suff, Riverside County 1986–1991 | Caught | Caught (Riverside County Sheriff, 1 of 22 solved) |
| Hillside Stranglers, Los Angeles 1977–1978 | Caught | Missed |
| Golden State Killer, Orange County 1980–1981 | Caught | Missed |
| Green River Killer, King County WA 1982–1984 | Caught | Caught |
| Darren Vann, Gary IN 1994–2014 | Missed | Caught (Lake County, 3 of 19 solved, 1988–2007) |

The two detectors complement each other. The scan is stricter: it holds false alarms down, which costs it the Los Angeles and Orange County series, where the victims were a small share of a large county's cases. The window detector is more sensitive but has no false-alarm control. Use the scan to rank, the window detector to look wider.

## Backtesting

`coldmap backtest` asks: using only data available at the time, when would each detector first have flagged the series?

| Series | Arrest | First flagged (scan) | First flagged (window) |
|---|---|---|---|
| William Suff | 1992 | 1988 | 1986 |
| Green River Killer | 2001 | 1982 | 1982 |
| Darren Vann | 2014 | 1998 | never |
| Hillside Stranglers | 1979 | never | 1979 |
| Golden State Killer (Orange County) | 2018 | never | 1980 |

Treat these lead times as optimistic: any flag overlapping the series' years counts, and earlier unrelated cases can contribute to a flag. They show the method has signal, not that police would have acted.

## Reporting coverage

The case file only includes murders agencies reported in detail. `coldmap coverage` compares it with the clearance file to find blind spots. Examples: in the 2000s the case file holds about 1% of Kane County, Illinois's reported murders, 2% of Will County's and 7% of Peoria County's. Clusters there are invisible to any detector. Pass `--clearance` to `scan` to attach coverage to each flag.

## Using it from an AI assistant (MCP)

```json
{
  "mcpServers": {
    "coldmap": {
      "command": "coldmap-mcp",
      "env": {
        "COLDMAP_SHR": "/path/to/SHR76_25a.csv",
        "COLDMAP_CLEARANCE": "/path/to/UCR65_25.csv"
      }
    }
  }
}
```

Tools: `scan_clusters`, `get_flag_cases`, `query_cases`, `data_issues`, `coverage_gaps`, `validation_report`. Every scan result carries the ethics notice so the assistant passes it on.

## Tests

```bash
pytest                                   # synthetic tests
COLDMAP_SHR=/path/to/SHR76_25a.csv pytest  # adds real-data and validation tests
```

## Roadmap

- Spatial scanning across neighboring counties (needs county adjacency or centroids)
- Combine both detectors' strengths: catch the Los Angeles and Orange County series without more false alarms
- More known series in the validation set, each with a public source
- Victim-profile features (age bands, race, circumstance) as optional grouping keys
- AI flag triage: check each flag against the issues registry and public news, then draft an evidence summary for human review
- Loaders for Jacob Kaplan's concatenated FBI SHR files

## Credits and license

The cluster algorithm was created by Thomas Hargrove and the Murder Accountability Project (copyright 2010, 2016, 2017). The data is MAP's, compiled from FBI Supplementary Homicide Reports and MAP's own public-records requests. coldmap is an independent project and is not affiliated with or endorsed by MAP.

Licensed under GPL-3.0-or-later, matching the existing open implementation of MAP's algorithm.
