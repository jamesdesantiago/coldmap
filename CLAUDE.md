# coldmap: notes for Claude Code

coldmap is an open-source framework (GPL-3.0) for finding clusters of unsolved homicides in the Murder Accountability Project (MAP) data. Owner: James De Santiago. Read README.md, ARCHITECTURE.md, ETHICS.md and DATA_ISSUES.md before changing behavior.

## Ground rules (do not relax these)

- A finding is a pattern worth review, never evidence that cases are linked. Keep that wording in every interface.
- Leads go to MAP or the investigating agency. Never contact families, witnesses or possible suspects, and never write code or text that does.
- Never store names or contact details from NamUs. Sources drop identifying columns on load (`coldmap/sources/namus.py`); keep it that way.
- No race or circumstance profile splits. Race is excluded on ethics grounds; circumstance is circular with solved status. Only `age_band` is allowed.
- Don't deploy the explorer publicly without James's explicit approval (plan: keep it private until MAP reviews it).
- Ask James before merging pull requests or pushing to `main`. Work on a branch.

## Data (not in git)

- `SHR76_25a.csv` (or `.zip`): MAP case file, ~906k murders 1976–2025. "Solved" means an offender was known when the report was filed.
- `UCR65_25.csv`: agency clearance file.
- Download from https://www.murderdata.org/p/data-docs.html and keep them in `data/` (CSV and ZIP files are git-ignored).
- No real data? `coldmap sample` builds a fictional state with a planted series.

## Setup and commands

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows; on macOS/Linux: source .venv/bin/activate
pip install -e ".[mcp,dev]"
python -m pytest -q                                  # 48 tests
coldmap plugins
coldmap scan data/SHR76_25a.csv --state California --preset balanced --explain 3
coldmap benchmark data/SHR76_25a.csv --backtest --json bench.json
coldmap controls data/SHR76_25a.csv --state California --json controls.json
coldmap quality data/SHR76_25a.csv --clearance data/UCR65_25.csv
coldmap explorer data/SHR76_25a.csv --state California --clearance data/UCR65_25.csv --benchmark-json bench.json --controls-json controls.json -o site
```

Loading the full case file is slow. Some tests read a cached dataset if `COLDMAP_DATASET_PICKLE` points to a pickled `Dataset`. Building the California explorer takes about 5 minutes.

## Where things are

- Plugin registries: sources, fixes, detectors, enrichers, checks (`coldmap/quality`), presets, regions. Third parties register through entry points (example: `examples/coldmap-streak`).
- Detectors: `scan` (strict; Kulldorff-style scan, leave-one-out baseline, shrink=20, Monte Carlo + BH q-values, region_max_len=12), `window` (sensitive), `map` (MAP's original algorithm).
- `coldmap/ensemble.py`: Matcher decides agreement; confidence is high (detectors agree), strong (strict only), possible (sensitive only). Region and county findings are never merged.
- `coldmap/benchmarks/`: 9 known solved series in `known_series.json`; `controls.py` shuffles solved labels to estimate false alarms.
- `coldmap/interfaces/`: CLI, MCP server, explorer (`explorer/build.py` writes agg.json, cases.json; `explorer/index.html` is the app).

## Current results (California, balanced preset)

- Benchmark: combined detectors catch 9 of 9 known series (7 full, 2 partial); MAP's original algorithm catches 0 of 9.
- False alarms: findings where detectors agree, 18 real vs 2.6 by chance (women), 34 vs 0 (men). Sensitive-only findings are mostly noise.
- Data problems: California 2021 relationship coding (fixed); California 1983–1995 identifying relationships on unsolved cases (open question); Duval County FL and NYC 2021 gaps.

## Ideas not yet built

- Missing-to-unidentified NamUs matcher (waiting on NamUs exports).
- Better baselines for states where one county dominates (Washington, Illinois).
- Detection of gun series.
- Private, password-protected hosting of the explorer.
- An email to MAP sharing the leads and benchmark.
