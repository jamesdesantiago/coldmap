---
version: 1
slug: "coldmap-interfaces-explorer-app-html"
primary_target: "coldmap/interfaces/explorer/app.html"
related_targets: []
---

# coldmap research app (coldmap open)

Scope: the whole local app (app.html): setup gate, Flags, Flag page, Shortlist, Places, Models, AI assistants, Methods, Data. Mode: Operate.
Audience: researchers, journalists, MAP and investigators, developers (PRODUCT.md).
Job: find flags, check one, keep or dismiss, second review, export for MAP; extend with models and AI.

## Direction contract

THESIS: A research application, not a dashboard: one path from a ranked list of flags to a reviewed lead for MAP. Refuses the centered, card-stacked "app home" and separate per-state sites.

OWN-WORLD: Light by default (dark optional). Cool neutral ground, white work surfaces, a grey sidebar; ink-black primary actions; red for unsolved and negative gaps, teal for solved; highlighter yellow marks kept flags (research as marking up evidence). Archivo for UI, condensed for headers; JetBrains Mono for every number. 5px corners, hairline rows, dense tables.

STORY: Setup happens once. Then the researcher scans flags, opens one, reads the evidence, keeps it, gets a second review and exports it; extends the tool with models and an AI assistant.

FIRST VIEWPORT: Sidebar (Research: Flags, Shortlist, Places; Extend: Models, AI assistants, Methods; Data, theme). Flags: filter toolbar over a split view, list left (conf, place, solved vs expected bar, gap, unsolved), the flag right (quote strip, keep or dismiss, trend chart with flagged years highlighted, why, plugins, data notes, case rows). Status bar.

FORM: Pinned by the user ("needs to feel like an application ... helping research from top to bottom"; light, easy to navigate). seed: none (pinned)

SIGNATURE: The gap column with a solved-vs-expected bar; kept flags highlighted like marked evidence; the three-step review strip (Kept, Second review, Sent to MAP).
