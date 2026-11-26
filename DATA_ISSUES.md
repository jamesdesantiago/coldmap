# Known data issues

coldmap applies fixes automatically and reports which ones ran. Each issue here has an entry in `coldmap/issues.py` and a test.

## solved-at-report (caveat, no fix)

MAP marks a case solved if the offender's sex was known when the agency filed its report. Cases solved later stay unsolved in the data. That's why known, convicted serial killers still show up as unsolved clusters, and why they make a good validation set.

## 2021-relationship-coding (fixed)

**Found:** November 2026, while scanning California.

In 2021, about 1,300 reports nationally list the offender as unknown (so MAP reads them as unsolved) but still name the relationship to the victim: wife, girlfriend, acquaintance and so on. About 1,100 of them are from California, where they make up 51% of the state's "unsolved" 2021 cases, against roughly 2% in other years. Louisiana and Illinois show smaller versions.

A named relationship implies police knew who the offender was. Without a fix, California's 2021 clearance looks far worse than it was, and the detectors fire on 2018–2023 windows across the state.

**Likely cause:** the FBI's 2021 move from summary reporting to NIBRS, which changed how offender details are converted into the Supplementary Homicide Report format.

**Fix:** 2021 cases with a named relationship count as solved. Turn it off with `--no-fixes` or `apply_fixes(df, skip=("2021-relationship-coding",))`.

**To do:** report to MAP and confirm the cause.

## Adding an issue

1. Write a fix function in `coldmap/issues.py` (or `fix=None` for a caveat).
2. Add an `Issue` entry.
3. Document it here: what, where found, size, likely cause, fix.
4. Add a test that fails if the fix stops working.
