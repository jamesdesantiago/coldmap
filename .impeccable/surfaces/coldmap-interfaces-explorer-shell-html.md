---
version: 1
slug: "coldmap-interfaces-explorer-shell-html"
primary_target: "coldmap/interfaces/explorer/shell.html"
related_targets: ["coldmap/interfaces/explorer/index.html"]
---

# coldmap app (home, Nationwide, Plugins) and state explorer

Scope: the local `coldmap open` app shell and the per-state explorer it opens. Mode: Operate.
Audience: independent researchers, journalists, MAP and investigators, developers (PRODUCT.md).
Job: get data, build or scan, then triage flags; long desk sessions, dense reading, comparison.
Constraints: ethics language on every surface; WCAG 2.2 AA; works offline (font fallbacks); phone usable.

## Direction contract

THESIS: A professional research desk for unsolved-homicide patterns, read like a markets data service: every flag is a quote line whose headline number is the solve-rate gap. Refuses the friendly rounded-card app look.

OWN-WORLD: Black ground (#050608), panels #0d1014, hairlines #232a31. Amber (#f5a524) carries structure: panel headers, keys, active tab, focus. Red #ff5a4e = unsolved / negative gap; cyan #4cc2e6 = solved; green #3ccf8e only for done states. Archivo (condensed widths) for labels, uppercase tracked panel headers; JetBrains Mono only for numbers and data, tabular. Square corners (2px max), 1px hairlines, 4/8 spacing, 12-13px base.

STORY: The visitor sees at once where things stand (data vintage, states built, scan status), picks a state or the national board, and reads flags as quotes: where, what, when, solved vs expected, gap.

FIRST VIEWPORT: Top bar: wordmark, tab strip (Home, Nationwide, Plugins), local-only status. Home: a three-step setup rail as compact numbered panels; states as a dense table (state, cases, status, action). Nationwide: filter strip over a quote table, gap column in red. Bottom status bar: data date, cases, plugins on, LOCAL ONLY.

FORM: Pinned by the user ("look like Bloomberg, a professional research service, not a Claude app"); financial data-terminal register as type, palette, density and one signature move only. Standard web navigation and controls; no command line, no function-key bar. seed: none (pinned)

SIGNATURE: The gap column: solved % vs expected %, the difference in points set like a price change (−46 pts, red), with a thin deficit bar.
