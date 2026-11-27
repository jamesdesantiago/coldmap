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
  Your own datasets in the app describe places and times; coldmap leaves out columns that identify people (names, addresses, phone numbers, emails, IP addresses, dates of birth, biometric or DNA records, licence plates, exact coordinates).
- Use the tool to profile neighborhoods or groups of people.

## City data with locations

Some newsrooms and cities publish one row per killing with a location. coldmap can scan such data for areas within a city where killings were solved far less often than in the rest of it, under stricter rules:

- Locations become grid cells of about 1 km on import. Exact coordinates, addresses, names, race, age and exact dates are never written to disk, and the app lists every column it left out and why.
- Cells with fewer than 3 killings are never shown, and cities with fewer than 3 killings are skipped, so no single killing can be picked out on a map.
- Respect the publisher's terms. The Washington Post's data is CC BY-NC-SA 4.0: non-commercial use, with credit. coldmap never bundles it; you add your own copy, and the app shows the source.
- An area is a pattern worth review. Low clearance across a neighbourhood usually reflects how cases there are investigated and resourced, not one offender. Never present an area as evidence that killings are linked, and never use it to characterise the people who live there.

## For AI integrations

Tools built on coldmap must pass the ethics notice through to users, cite the data rows behind any claim, and never describe cases as linked. A person reviews every lead before it leaves the project.
