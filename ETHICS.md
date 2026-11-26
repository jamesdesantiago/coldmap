# Ethics and handoff guide

Every homicide in this data was a person. Their families are still here. Read this before you share anything coldmap produces.

## What a flag means

A flag means that, in one place and time, an unusually low share of killings by one method were solved. That is all. It does not mean:

- the cases are linked
- a serial offender exists
- the police did anything wrong

Many flags have ordinary explanations: data entry errors, gang conflicts, an agency that reported poorly that year, or a series that was solved after the reports were filed.

## Before you share a flag

1. **Check the data issues.** Run `coldmap plugins` to see the data fixes and caveats, read DATA_ISSUES.md, and confirm the finding is not an artifact.
2. **Check whether it's already known.** Search public news for the county, method and years. Many flags are solved series.
3. **Read the case rows.** Do the victims, dates and circumstances actually resemble each other?
4. **Have a second person review it.**

## Where leads go

- **The Murder Accountability Project** (murderdata.org). Their board includes retired homicide investigators who can judge whether a pattern deserves police attention.
- **The investigating agency**, through its cold case or tip line, if MAP advises it.

## Never

- Contact victims' families, witnesses or possible suspects.
- Publish a flag as a "serial killer" or name anyone as a suspect.
- Combine this data with other sources to identify private individuals.
- Use the tool to profile neighborhoods or groups of people.

## For AI integrations

Tools built on coldmap must pass the ethics notice through to users, cite the data rows behind any claim, and never describe cases as linked. A person reviews every lead before it leaves the project.
