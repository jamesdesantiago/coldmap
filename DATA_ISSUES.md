# Known data issues

coldmap applies fixes automatically and reports which ones ran. Each issue here is a `Fix` plugin in `coldmap/fixes/` and has a test.

## solved-at-report (caveat, no fix)

MAP marks a case solved if the offender's sex was known when the agency filed its report. Cases solved later stay unsolved in the data. That's why known, convicted serial killers still show up as unsolved clusters, and why they make a good validation set.

## 2021-relationship-coding (fixed)

**Found:** November 2026, while scanning California. **Refined:** the first version also counted "Stranger" as an identifying relationship; it isn't, since police can judge a killing was by a stranger without knowing who.

In 2021, about 700 reports nationally (629 in California) list the offender as unknown, so MAP reads them as unsolved, while naming a relationship that implies police knew who the offender was: wife, girlfriend, acquaintance, "known to victim" and so on. In California that's 29% of the state's "unsolved" 2021 cases, against about 2% in typical years.

**Likely cause:** the FBI's 2021 move from summary reporting to NIBRS.

**Fix:** 2021 cases with an identifying relationship count as solved. Skip it with `--skip-fix 2021-relationship-coding`.

Even after the fix, `coldmap quality` shows California's 2021 solve rate at 38% against 59% in the surrounding years, so the transition likely caused more problems than this fix catches. Treat 2021 findings with caution.

**To do:** report to MAP and confirm the cause.

## california-1983-1995-relationship (open, not fixed)

**Found:** November 2026 by `coldmap quality`.

From 1983 to 1995, 12–33% of California's unsolved cases name a relationship that identifies the offender, mostly "Other - known to victim," against about 2% elsewhere. Most come from Los Angeles agencies. Unlike 2021 there may be a legitimate reason (for example, a suspect known to police but not charged), so coldmap doesn't change the data. California solve rates in this period may be understated. **To do:** ask MAP.

## new-york-2021-weapons (caveat)

All 488 New York City cases in 2021 have no weapon recorded, as do several other New York agencies that year. Detectors exclude "Not reported" weapons, so these cases are invisible to method-based detection.

## duval-county-missing (caveat)

Duval County, Florida (Jacksonville) reported 4,429 murders to the clearance file since 1976 with no case records in the case file. Washington, D.C. (7 years since 1996), Omaha (18 years) and others have smaller gaps. `coldmap quality --clearance` lists them.

## case-file-coverage (caveat, measured per flag)

The case file only contains murders agencies reported in detail. Some places report summary counts to the clearance file but few or no case details. Examples in the 2000s: Kane County, Illinois (1% of reported murders in the case file), Will County (2%), Peoria County (7%). Clusters in those places cannot be detected. `coldmap coverage` lists the gaps; the `coverage` enricher attaches a coverage figure to each finding when clearance data is loaded.

## dade-county-name (fixed)

The clearance file uses both "Dade, FL" and "Miami-Dade, FL"; the case file uses only "Miami-Dade, FL". `load_clearance` merges them so coverage isn't misread as zero.

## Finding new issues

`coldmap quality` runs every registered check. Checks are plugins (`coldmap.quality.CHECKS`): add one when you find a new kind of problem, so the next release looks for it everywhere.

## Adding an issue

1. Register a `Fix` in `coldmap/fixes/` (or `apply=None` for a caveat).
2. List the sources it applies to.
3. Document it here: what, where found, size, likely cause, fix.
4. Add a test that fails if the fix stops working.
