# coldmap

An open toolkit for finding clusters of unsolved homicides in public U.S. homicide data, built on the [Murder Accountability Project](https://www.murderdata.org) (MAP) files.

Homicide investigations are local. When one offender kills in several jurisdictions, or over many years, no single detective sees the pattern ("linkage blindness"). MAP showed that a simple statistical screen of national data can surface those patterns. coldmap makes that screen easy to run, test, extend and use from an AI assistant.

> **A flag is a pattern worth review, never evidence that cases are linked.** Read [ETHICS.md](ETHICS.md) before sharing anything this tool produces.

## What's inside

| Part | What it does |
|---|---|
| `coldmap.load` | Loads MAP's case file (`SHR76_25a.csv` or `.zip`) and clearance file (`UCR65_25.csv`) into one normalized schema |
| `coldmap.issues` | Registry of known data problems and the fixes applied (see [DATA_ISSUES.md](DATA_ISSUES.md)) |
| `coldmap.detect` | `map_algorithm`: faithful port of MAP's published algorithm. `sliding_window`: rolling time windows, grouped weapons and a binomial test against each group's long-run solve rate |
| `coldmap.validate` | Checks detectors against known, adjudicated serial cases |
| `coldmap.explorer` | Builds an interactive web explorer (heatmap, ranked flags, case file) for any state |
| `coldmap.mcp_server` | MCP server so Claude or any MCP client can run scans and pull case records |

## Quick start

```bash
pip install -e ".[mcp,dev]"

# Get the data: download SHR76_25a.csv from https://www.murderdata.org/p/data-docs.html

coldmap scan SHR76_25a.csv --state California --max-p 0.01
coldmap validate SHR76_25a.csv
coldmap issues
coldmap explorer SHR76_25a.csv --state California --out-dir site && cd site && python -m http.server
```

In Python:

```python
from coldmap import load_shr, sliding_window
from coldmap.detect import cases_for

df = load_shr("SHR76_25a.csv")
flags = sliding_window(df, state="California", window=4, threshold=0.4, min_cases=8)
print(flags[0].to_dict())
print(cases_for(df, flags[0]))
```

## Validation

`coldmap validate` runs the window detector against known series. Current results on MAP's August 2026 file:

| Series | Detected | Best flag |
|---|---|---|
| William Suff, Riverside County 1986–1991 | Yes | Other/unknown 1988–1991: 2 of 11 solved |
| Hillside Stranglers, Los Angeles 1977–1978 | Yes | Strangulation 1977–1980: 25 of 73 solved |
| Golden State Killer, Orange County 1980–1981 | Yes | Beating 1977–1980: 10 of 28 solved |
| Green River Killer, King County WA 1982–1984 | Yes | Other/unknown 1981–1984: 2 of 31 solved |
| Darren Vann, Gary IN 1994–2014 | **No (known gap)** | Slow series spread over 20 years slip under 4-year windows |

The Gary miss is deliberate to keep: it's the first problem a contributor could take on (multi-scale windows, or MSA-level grouping as MAP uses).

## Using it from an AI assistant (MCP)

```json
{
  "mcpServers": {
    "coldmap": {
      "command": "coldmap-mcp",
      "env": { "COLDMAP_SHR": "/path/to/SHR76_25a.csv" }
    }
  }
}
```

Tools: `scan_clusters`, `get_flag_cases`, `query_cases`, `data_issues`, `validation_report`. Every scan result carries the ethics notice so the assistant passes it on.

## Tests

```bash
pytest                                   # synthetic tests
COLDMAP_SHR=/path/to/SHR76_25a.csv pytest  # adds real-data and validation tests
```

## Roadmap

- Multi-scale windows to catch slow series (fixes the Gary gap)
- MSA and multi-county grouping for killers who cross jurisdiction lines
- More known series in the validation set, each with a public source
- Victim-profile features (age bands, race, circumstance) as optional grouping keys
- AI flag triage: check each flag against the issues registry and public news, then draft an evidence summary for human review
- Loaders for Jacob Kaplan's concatenated FBI SHR files

## Credits and license

The cluster algorithm was created by Thomas Hargrove and the Murder Accountability Project (copyright 2010, 2016, 2017). The data is MAP's, compiled from FBI Supplementary Homicide Reports and MAP's own public-records requests. coldmap is an independent project and is not affiliated with or endorsed by MAP.

Licensed under GPL-3.0-or-later, matching the existing open implementation of MAP's algorithm.
