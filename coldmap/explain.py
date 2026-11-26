"""Explain a finding in plain language: why it was flagged and how much to trust it.

explain(finding, data) returns a dict of sections plus `text` (Markdown) that a
non-statistician can act on:

    what        the numbers: killings, unsolved, expected solve rate
    agreement   which detectors found it and what that confidence level means
    statistics  p and q values, if the detector computed them
    data        caveats and fixes that touch this state and period, coverage,
                missing weapons, unsolved cases that still name a known offender
    cases       who the victims were in aggregate (no names exist in the data)
    namus       missing / unidentified context, if NamUs data is loaded
    next        what to do with it
"""

from __future__ import annotations

from .core.types import Dataset, Finding, Query
from .fixes import FIXES, NOT_IDENTIFYING

CONFIDENCE = {
    "high": "Two or more detectors agree. In false-alarm tests these rarely appear by chance in most "
            "states, but they can where one county holds most of the state's cases (run `coldmap controls`).",
    "strong": "Only the strict detector found it. It passed a false-discovery correction; in false-alarm "
              "tests these rarely appear by chance.",
    "possible": "Only a sensitive detector found it. In false-alarm tests most findings like this appear "
                "by chance. Treat it as a weak lead.",
}


def _state_of(f: Finding, data: Dataset) -> str | None:
    col = f.level if f.level in data.cases.columns else "county"
    s = data.cases.loc[data.cases[col] == f.place, "state"]
    return s.mode().iat[0] if len(s) else None


def finding_cases(f: Finding, data: Dataset, min_age: int | None = 12):
    col = f.level if f.level in data.cases.columns else "county"
    c = data.cases
    m = (c[col] == f.place) & (c.vic_sex == f.victim_sex) & c.year.between(f.start, f.end)
    m &= (c.weapon_group == f.weapon) | (c.weapon == f.weapon)
    if min_age is not None:
        m &= c.vic_age >= min_age
    for k, v in f.extras.get("profile", {}).items():
        if k == "age_band":
            from .core.profile import add_profile
            return add_profile(c[m], ("age_band",)).query("age_band == @v")
    return c[m]


def explain(f: Finding, data: Dataset) -> dict:
    who = {"Female": "women", "Male": "men"}.get(f.victim_sex, "victims")
    where = f"{f.place} ({f.county})" if f.county and f.county != f.place else f.place
    prof = f.extras.get("profile", {})
    prof_txt = f", aged {prof['age_band']}" if "age_band" in prof else ""
    rate = f.solve_rate
    out: dict = {}
    exp_txt = f", against {f.expected:.0%} expected" if f.expected is not None else ""
    out["what"] = (f"{where}: {f.total} killings of {who}{prof_txt} by {f.weapon.lower()} in "
                   f"{f.start}–{f.end}; {f.unsolved} unsolved, {f.solved} solved ({rate:.0%}){exp_txt}.")

    by = ", ".join(f.found_by or (f.detector,))
    out["agreement"] = f"Found by {by}. Confidence: {f.confidence or 'n/a'}. " + CONFIDENCE.get(f.confidence, "")

    stats = []
    if f.p_value is not None:
        stats.append(f"p = {f.p_value:.4f}" + (" (one window, not corrected)" if f.q_value is None else ""))
    if f.q_value is not None:
        stats.append(f"q = {f.q_value:.3f}: about {f.q_value:.0%} of findings at this level are expected to be noise")
    out["statistics"] = "; ".join(stats) or "No significance test for this detector."

    state = _state_of(f, data)
    notes = [f"{fx.title}: {fx.summary}" for _, fx in FIXES
             if fx.name != "solved-at-report" and fx.applies_to(state, f.start, f.end)]
    notes.append("Solved means solved when the report was filed; later arrests don't show, so a solved "
                 "series can still appear here.")
    if f.coverage is not None and f.coverage < 0.8:
        notes.append(f"The case file holds only {f.coverage:.0%} of murders reported here in these years; "
                     "the real picture may differ.")
    cases = finding_cases(f, data)
    unsolved = cases[~cases.solved]
    if len(unsolved):
        named = (~unsolved.relationship.isin(NOT_IDENTIFYING)).mean()
        if named >= 0.2:
            notes.append(f"{named:.0%} of the unsolved cases still name a relationship that identifies the "
                         "offender; some may actually be solved.")
    out["data"] = notes

    if len(cases):
        ages = cases.vic_age[cases.vic_age < 999]
        unknown_age = int((cases.vic_age >= 999).sum())
        agencies = cases.agency.value_counts().head(3)
        circ = unsolved.circumstance.replace("", "not recorded").value_counts().head(2)
        out["cases"] = (
            f"Victim ages {int(ages.min())}–{int(ages.max())}, median {int(ages.median())}"
            if len(ages) else "Victim ages not recorded")
        if unknown_age:
            out["cases"] += f"; {unknown_age} of unknown age (often unidentified when reported)"
        out["cases"] += (". Agencies: " + ", ".join(f"{a} ({n})" for a, n in agencies.items()) +
                         ". Most common circumstance among unsolved: " +
                         ", ".join(f"{c.lower()} ({n})" for c, n in circ.items()) + ".")

    nm = []
    for key, label in (("namus-missing", "missing"), ("namus-unidentified", "unidentified")):
        v = f.extras.get(key)
        if v:
            r = f" ({v['ratio']}x typical)" if v.get("ratio") else ""
            nm.append(f"{v['count']} open {label} cases in NamUs for this county, period and sex, "
                      f"against about {v['typical']} typical{r}.")
    if nm:
        out["namus"] = " ".join(nm)

    out["next"] = [
        f"Search public news and court records for {f.weapon.lower()} killings of {who} in {f.county or f.place}, "
        f"{f.start}–{f.end}, to see whether a series is already known or solved.",
        "Read the case rows: do dates, ages and circumstances actually resemble each other?",
        "If it still looks unexplained, send it to the Murder Accountability Project with these numbers. "
        "Never contact families, witnesses or possible suspects.",
    ]

    lines = [f"**{out['what']}**", "", out["agreement"], "", f"Statistics: {out['statistics']}", "",
             "Data notes:", *[f"- {n}" for n in out["data"]]]
    if "cases" in out:
        lines += ["", f"Cases: {out['cases']}"]
    if "namus" in out:
        lines += ["", f"NamUs: {out['namus']}"]
    lines += ["", "Next steps:", *[f"{i}. {s}" for i, s in enumerate(out["next"], 1)],
              "", "_A finding is a pattern worth review, not evidence that cases are linked._"]
    out["text"] = "\n".join(lines)
    return out
