# Known data issues

coldmap applies fixes automatically and reports which ones ran. Each issue here is a `Fix` plugin in `coldmap/fixes/` and has a test.

## solved-at-report (caveat, no fix)

MAP marks a case solved if the offender's sex was known when the agency filed its report. Cases solved later stay unsolved in the data. That's why known, convicted serial killers still show up as unsolved clusters, and why they make a good validation set.

## 2021-relationship-coding (fixed)

**Found:** November 2026, while scanning California.

In 2021, about 1,300 reports nationally list the offender as unknown (so MAP reads them as unsolved) but still name the relationship to the victim: wife, girlfriend, acquaintance and so on. About 1,100 of them are from California, where they make up 51% of the state's "unsolved" 2021 cases, against roughly 2% in other years. Louisiana and Illinois show smaller versions.

A named relationship implies police knew who the offender was. Without a fix, California's 2021 clearance looks far worse than it was, and the detectors fire on 2018–2023 windows across the state.

**Likely cause:** the FBI's 2021 move from summary reporting to NIBRS, which changed how offender details are converted into the Supplementary Homicide Report format.

**Fix:** 2021 cases with a named relationship count as solved. Skip it with `--skip-fix 2021-relationship-coding` or `coldmap.load(..., skip_fixes=("2021-relationship-coding",))`.

**To do:** report to MAP and confirm the cause.

## case-file-coverage (caveat, measured per flag)

The case file only contains murders agencies reported in detail. Some places report summary counts to the clearance file but few or no case details. Examples in the 2000s: Kane County, Illinois (1% of reported murders in the case file), Will County (2%), Peoria County (7%). Clusters in those places cannot be detected. `coldmap coverage` lists the gaps; the `coverage` enricher attaches a coverage figure to each finding when clearance data is loaded.

## dade-county-name (fixed)

The clearance file uses both "Dade, FL" and "Miami-Dade, FL"; the case file uses only "Miami-Dade, FL". `load_clearance` merges them so coverage isn't misread as zero.

## Adding an issue

1. Register a `Fix` in `coldmap/fixes/` (or `apply=None` for a caveat).
2. List the sources it applies to.
3. Document it here: what, where found, size, likely cause, fix.
4. Add a test that fails if the fix stops working.
