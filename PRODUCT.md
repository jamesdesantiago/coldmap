# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

coldmap serves four audiences, all confirmed:

- **Independent researchers**: data-literate volunteers who screen public homicide data for clusters and pass vetted leads to the Murder Accountability Project (MAP).
- **Journalists**: reporters investigating unsolved homicides, clearance rates and police accountability.
- **MAP and investigators**: MAP's board (including retired homicide investigators) and cold-case units, who judge whether a flag deserves police attention.
- **Developers and academics**: people writing detector, source, fix or enricher plugins, or studying the statistical method.

The shared job is the same for all of them: to see whether, in one place and period, an unusually low share of killings by one method went unsolved, and to decide whether that pattern deserves a closer human look.

## Product Purpose

coldmap is an extensible framework for finding clusters of unsolved homicides in public U.S. homicide data (MAP's Supplementary Homicide Report file). It addresses "linkage blindness": no single local investigator sees a pattern that crosses jurisdictions or spans years. Success means real patterns surface with an honest measure of how often a flag of that kind is noise, and every lead is reviewed by a person before it leaves the project.

## Positioning

It isn't one detector. It's a plugin pipeline (sources, fixes, detectors, enrichers, combined by an ensemble) that is **scored in public**. Benchmarks against known adjudicated series measure what it catches, negative controls (shuffled labels) measure what it invents, and data-quality checks expose artifacts. Every finding carries a confidence label (high, strong or possible) grounded in that evidence. The same plain-language triage reaches every interface: Python, CLI, MCP server and the web explorer.

## Operating Context

- Users download MAP's `SHR76_25a.csv` and optionally `UCR65_25.csv`, plus optional NamUs CSV exports, then run coldmap locally.
- The workflow is scan → triage ("why flagged") → read the case rows → check data issues and public news → second-person review → hand off to MAP or the agency tip line (ETHICS.md).
- `coldmap explorer` builds a static web app for one state. It has a findings queue with confidence filters, a workspace with a solve-rate heatmap by year and method, a "why flagged" tab, case records, and overview, benchmark, reliability, data-quality and plugin sections. It works on phones and in light or dark mode.
- Design surfaces in scope: the **explorer app**, a **project/landing site** (not built yet) and **docs** (README, ARCHITECTURE, ETHICS, DATA_ISSUES).

## Capabilities and Constraints

- Python ≥3.10 package (pandas, numpy, scipy, click), GPL-3.0-or-later. The explorer is a single static HTML template filled by `coldmap/interfaces/explorer/build.py`.
- Terminology: *finding* or *flag* (never "case link"); confidence *high / strong / possible*; kind *serial-pattern / accountability*; detectors *scan* (strict), *window* and *map* (sensitive); presets *strict / balanced / profiles / exploratory*; *regions*; *solved* means an offender was identified when the report was filed.
- Subgroups are split by victim age band only. Race and ethnicity are excluded on purpose, and circumstance is excluded because it is circular.
- Explorer case lists cover women only (MAP's focus); detectors run for both sexes.
- Interfaces read plugin and detector names from data, so new plugins must appear without UI changes.

## Brand Commitments

- Name: **coldmap** (lowercase).
- Voice: plain, careful, exact. It states uncertainty and corrections openly (the README publishes its own benchmark-bug correction).
- **Ethics rules are binding on every surface** (ETHICS.md): a flag is a pattern worth review, never evidence that cases are linked. Never present a flag as a "serial killer", never name suspects, never invite contact with families, witnesses or suspects, and never profile neighborhoods or groups. AI-facing surfaces pass the ethics notice through and cite data rows.

## Evidence on Hand

- Benchmark results against 9 known series on MAP's August 2026 file (README, `coldmap/benchmarks/known_series.json`).
- Negative-control false-alarm rates for California, Indiana, Illinois and Washington (README).
- Documented data issues (DATA_ISSUES.md).
- A synthetic sample dataset (`coldmap sample`, the fictional "Samplestate" with a planted series). Use it for any demo or screenshot.
- Absent, and must not be fabricated: user testimonials, press coverage, case studies of leads that led to arrests, or endorsements from MAP or any agency.

## Product Principles

1. **A pattern, not a verdict.** Every surface frames findings as worth review, with the reason and the caveats beside the claim.
2. **Show how often it's wrong.** Confidence, false-alarm rates and data problems stay visible, not buried.
3. **Victims are people.** Restraint over sensationalism: no thrill, no true-crime styling, no spectacle of the data.
4. **Same truth everywhere.** Python, CLI, MCP and explorer give the same triage. Plugins appear without bespoke UI.
5. **Human review before handoff.** Design nudges toward checking data issues, reading rows and a second reviewer.

## Accessibility & Inclusion

Must meet **WCAG 2.2 AA**: contrast, full keyboard operation and screen-reader support. Charts and heatmaps need non-color encodings and text equivalents.
