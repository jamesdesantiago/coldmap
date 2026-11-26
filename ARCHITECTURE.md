# Architecture

coldmap is built so that new data, new corrections and new models can be added without touching the core.

## Layout

```
coldmap/
  core/            shared types (Dataset, Query, Finding) and the Registry
  sources/         Source plugins: files/APIs -> normalized cases      registry: SOURCES
  fixes/           Fix plugins: known data problems, applied on load    registry: FIXES
  detectors/       Detector plugins: the models                         registry: DETECTORS
  enrichers/       Enricher plugins: add info to findings               registry: ENRICHERS
  stats/           shared statistics (scan likelihood, Monte Carlo, FDR)
  ensemble.py      run detectors together; Matcher decides agreement
  benchmarks/      known series (JSON) + evaluate/backtest any detector
  interfaces/      cli.py, mcp_server.py, explorer/ (use only the public API)
examples/
  coldmap-streak/  a third-party detector packaged as a plugin
```

## Contracts

**Dataset** holds cases in one schema (`coldmap.core.types.CASE_COLUMNS`), a `solved` column after fixes, optional clearance counts, and the list of fixes applied. `Dataset.select(query)` applies the shared filters so every detector treats state, sex, age, cutoff year and excluded methods the same way.

**Query** is what to analyze: `state`, `victim_sex`, `min_age`, `as_of` (backtesting), `exclude_weapons`. Detectors must respect `as_of`; otherwise backtests leak the future.

**Detector** has `name`, `summary`, `tier` (`strict` if it controls false alarms, otherwise `sensitive`), a typed `Params` dataclass, and `detect(data, query) -> list[Finding]`. Params carry help text in field metadata, which is how the CLI, MCP server and explorer describe any detector without knowing it.

**Finding** is the common output: place, level, method, years, totals, plus optional `expected`, `p_value`, `q_value`, `score`. Enrichers fill `county`, `kind` and `coverage`; the ensemble fills `found_by` and `confidence`. Anything detector-specific goes in `extras`.

**Enricher** takes findings and the dataset and returns findings. Order matters: `county` runs first because matching uses it.

**Matcher** decides when two findings agree (`agree`) and when they're duplicates (`duplicate`). The default compares county, sex, method and overlapping years, and treats findings as duplicates only when their spans are within 2x, so a short burst is never absorbed into a long trend.

## Plugin discovery

Each registry has an entry-point group:

| Registry | Entry-point group |
|---|---|
| SOURCES | `coldmap.sources` |
| FIXES | `coldmap.fixes` |
| DETECTORS | `coldmap.detectors` |
| ENRICHERS | `coldmap.enrichers` |

Built-ins register on import. Entry points load the first time a registry is queried.

## Design rules

1. Interfaces only use the public API, so a plugin shows up everywhere at once.
2. Data corrections live in fixes, never inside detectors, and every fix is documented and tested.
3. Every detector is scored by the same benchmark. A claim that a model is better needs benchmark results, including what it misses.
4. No finding is ever described as a link between cases. The ethics notice travels with results.
