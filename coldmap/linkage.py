"""Case links: which unsolved cases in a flag resemble each other enough to read side by side.

A long flag ("30 years of unsolved strangulations here") mixes a slow decline in clearance with,
possibly, a tight group of cases that look alike. This module scores how alike two unsolved cases
are and pulls out groups, so a reviewer can tell the two apart before marking anything for review.

Similarity, for two cases (standard practice in case linkage: shared *rare* details count more):
- same agency, same detailed weapon, same circumstance, same relationship: each adds
  -ln(share of the reference cases with that value), so a rare shared detail weighs more;
- victim ages within 2 years (or 5, for half): -ln(share of reference cases in that age range);
- time: up to TIME_W points, falling off over about two years;
- place: PROX_SAME points for the same county, PROX_NEAR for a county that borders it (from the
  Census county shapes). The FBI's case file has no location finer than the agency and county, so
  this is the closest proximity it allows.
"Undetermined", "not stated" and similar values never count as a match, and victim race is never
used. The reference is every case of the same state, victims and method.

Each pair's score is turned into a percentile against random pairs of unsolved cases from the same
place and method in any year: "stronger than 99% of random pairs from this place". That is a
similarity, NOT a probability that the cases share an offender: the case file doesn't mark which
cases were later linked, so no such probability can be calibrated from it.

Tested on the 9 adjudicated series (November 2026, with county proximity): in 8 of 9, one of the
flag's three largest groups falls mostly inside the series' years (Los Angeles 1987-1998: a group of
18 cases, 1987-1992, 94% coded "rape" against 26% across the flag). But the largest group fell in the
series' years 48% of the time, against 45% for the flag's cases overall, and no other ranking (size,
tightness, how distinctive the shared details are) did reliably better.
So groups are listed by date for a person to read, never ranked as "the" pattern.

Groups come from average-linkage clustering: every group's average pair is stronger than GROUP_PCT of
random pairs, so one case can't chain a group across decades. Links drawn are pairs at LINK_PCT. Similar unsolved cases
just outside the flag (neighbouring counties, a few years either side) are added when they link to
a group, since a pattern can cross a county line.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

LINK_PCT = 0.99        # a link: stronger than 99% of random pairs from the same place
GROUP_PCT = 0.95       # a group: its average pair is stronger than 95% of random pairs
MAX_CASES = 1500       # unsolved cases linked at once; narrow the years beyond that
TIME_W = 3.0
PROX_SAME = 1.0
PROX_NEAR = 0.5
NULL_PAIRS = 20000
UNINFORMATIVE = {"", "nan", "none", "unknown", "other", "other or type unknown", "firearm, type not stated",
                 "relationship not determined", "circumstances undetermined", "other - not specified",
                 "not recorded", "not reported", "undetermined", "other/unknown"}
# Victim sex and the method group count too: they add nothing when the view is one sex and one method
# (every case shares them, so their weight is -ln(1) = 0), and they matter when it's both or all.
FIELDS = ("agency", "weapon", "circumstance", "relationship", "vic_sex", "weapon_group")


def _col(d: pd.DataFrame, f: str) -> np.ndarray:
    return d[f].astype(str).to_numpy() if f in d else np.full(len(d), "nan", dtype=object)


def _informative(v) -> bool:
    return str(v).strip().lower() not in UNINFORMATIVE


class Scorer:
    """Rarity weights from a reference set of cases, and pairwise scores."""

    def __init__(self, ref: pd.DataFrame):
        self.w = {}
        for f in FIELDS:
            share = pd.Series(_col(ref, f)).value_counts(normalize=True)
            self.w[f] = {k: float(-np.log(max(v, 1e-4))) for k, v in share.items() if _informative(k)}
        ages = pd.to_numeric(ref.vic_age, errors="coerce").dropna().astype(int)
        hist = np.bincount(ages.clip(0, 110), minlength=111).astype(float)
        hist /= max(hist.sum(), 1)
        cum = np.concatenate([[0], np.cumsum(hist)])
        self.age_w2 = np.array([-np.log(max(cum[min(111, a + 3)] - cum[max(0, a - 2)], 1e-4)) for a in range(111)])
        self.age_w5 = np.array([-np.log(max(cum[min(111, a + 6)] - cum[max(0, a - 5)], 1e-4)) for a in range(111)])

    def pairs(self, a: pd.DataFrame, b: pd.DataFrame) -> np.ndarray:
        """Scores of a[k] with b[k] for each k (same length)."""
        s = np.zeros(len(a))
        for f in FIELDS:
            va, vb = _col(a, f), _col(b, f)
            wa = np.nan_to_num(pd.Series(va).map(self.w[f]).to_numpy(dtype=float))
            s += np.where(va == vb, wa, 0.0)
        aa = pd.to_numeric(a.vic_age, errors="coerce").to_numpy(dtype=float)
        ab = pd.to_numeric(b.vic_age, errors="coerce").to_numpy(dtype=float)
        gap = np.abs(aa - ab)
        idx = np.clip(np.nan_to_num(aa, nan=0), 0, 110).astype(int)
        known = ~np.isnan(gap)
        s += np.where(known & (gap <= 2), self.age_w2[idx], np.where(known & (gap <= 5), 0.5 * self.age_w5[idx], 0.0))
        s += TIME_W * np.exp(-np.abs(_t(a) - _t(b)) / 24.0)
        s += _proximity(_counties(a), _counties(b), pairwise=True)
        return s

    def matrix(self, a: pd.DataFrame, b: pd.DataFrame) -> np.ndarray:
        """Scores between every case in a and every case in b."""
        s = np.zeros((len(a), len(b)))
        for f in FIELDS:
            va, vb = _col(a, f), _col(b, f)
            codes, uniq = pd.factorize(np.concatenate([va, vb]))
            ca, cb = codes[:len(va)], codes[len(va):]
            w = np.array([self.w[f].get(u, 0.0) for u in uniq] + [0.0])
            s += np.where(ca[:, None] == cb[None, :], w[ca][:, None], 0.0)
        aa = pd.to_numeric(a.vic_age, errors="coerce").to_numpy(dtype=float)
        ab = pd.to_numeric(b.vic_age, errors="coerce").to_numpy(dtype=float)
        gap = np.abs(aa[:, None] - ab[None, :])
        idx = np.clip(np.nan_to_num(aa, nan=0), 0, 110).astype(int)
        known = ~np.isnan(gap)
        s += np.where(known & (gap <= 2), self.age_w2[idx][:, None],
                      np.where(known & (gap <= 5), 0.5 * self.age_w5[idx][:, None], 0.0))
        s += TIME_W * np.exp(-np.abs(_t(a)[:, None] - _t(b)[None, :]) / 24.0)
        s += _proximity(_counties(a), _counties(b))
        return s


def _counties(d: pd.DataFrame) -> np.ndarray:
    return d["county"].to_numpy() if "county" in d else np.full(len(d), None, dtype=object)


def _proximity(ca, cb, pairwise: bool = False) -> np.ndarray:
    """PROX_SAME for the same county, PROX_NEAR for bordering counties, else 0 (matrix, or element-wise)."""
    from .detectors.neighbours import adjacency
    from .interfaces.research import county_fips
    labels = sorted({str(x) for x in np.concatenate([ca, cb]) if isinstance(x, str)})
    idx = {lb: k for k, lb in enumerate(labels)}
    codes = [county_fips(lb) for lb in labels]
    adj = adjacency()
    m = np.zeros((len(labels) + 1, len(labels) + 1))   # last row/column: no county
    for i, ci in enumerate(codes):
        m[i, i] = PROX_SAME
        if ci:
            near = adj.get(ci, ())
            for j, cj in enumerate(codes):
                if cj and cj in near:
                    m[i, j] = PROX_NEAR
    ia = np.array([idx.get(x, len(labels)) if isinstance(x, str) else len(labels) for x in ca])
    ib = np.array([idx.get(x, len(labels)) if isinstance(x, str) else len(labels) for x in cb])
    return m[ia, ib] if pairwise else m[np.ix_(ia, ib)]


def _t(d: pd.DataFrame) -> np.ndarray:
    """Months since year 0; a missing month counts as mid-year."""
    m = d.month.to_numpy()
    return (d.year.to_numpy() * 12 + np.where(m > 0, m, 6)).astype(float)


def _null(scorer: Scorer, pool: pd.DataFrame, rng) -> np.ndarray:
    """Scores of random pairs of different cases from pool, sorted."""
    n = len(pool)
    if n < 2:
        return np.array([0.0])
    i = rng.integers(0, n, NULL_PAIRS)
    j = rng.integers(0, n - 1, NULL_PAIRS)
    j = j + (j >= i)
    return np.sort(scorer.pairs(pool.iloc[i], pool.iloc[j]))


def _pct(null: np.ndarray, s: np.ndarray) -> np.ndarray:
    return np.searchsorted(null, s, side="left") / len(null)


def _groups(P: np.ndarray, level: float) -> list[list[int]]:
    """Groups (size >= 3) whose cases resemble each other on average: average-linkage clustering on
    1 - percentile, cut where the average pair in a group is at least `level`. Unlike chaining
    single links, this doesn't let one case at a time pull a group across decades."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform
    n = len(P)
    if n < 3:
        return []
    D = 1.0 - P
    np.fill_diagonal(D, 0)
    Z = linkage(squareform(D, checks=False), method="average")
    lab = fcluster(Z, t=1.0 - level, criterion="distance")
    out = [sorted(np.flatnonzero(lab == k).tolist()) for k in np.unique(lab)]
    return [g for g in out if len(g) >= 3]


def _case(r, pct_best=None) -> dict:
    return {"id": str(r.case_id), "solved": bool(r.solved), "sex": str(r.vic_sex), "year": int(r.year),
            "month": int(r.month) if r.month > 0 else None,
            "age": None if pd.isna(r.vic_age) else int(r.vic_age), "agency": str(r.agency), "county": r.county,
            "weapon": str(r.weapon), "circumstance": str(r.circumstance), "relationship": str(r.relationship)}


def links(data, flag: dict, start: int | None = None, end: int | None = None, seed: int = 0,
          min_pct: float = LINK_PCT, focus: str | None = None, solved: bool = False) -> dict:
    """Unsolved cases of a flag (optionally narrowed to start..end), the links between them, groups,
    and similar unsolved cases just outside the flag."""
    from .interfaces.research import _mask
    c = data.cases
    start = int(start if start is not None else flag["start"])
    end = int(end if end is not None else flag["end"])
    place_all = c[scope_mask(c, flag) if flag.get("kind") == "place" else _mask(c, flag, by_year=True)]
    inside = place_all[place_all.year.between(start, end) & ~place_all.solved]
    min_pct = float(min_pct) if np.isfinite(min_pct) else LINK_PCT
    min_pct = min(max(min_pct, 0.95), 0.999)   # links shown: 95th to 99.9th percentile
    out = {"start": start, "end": end, "unsolved": int(len(inside)), "link_pct": LINK_PCT, "min_pct": min_pct,
           "max_cases": MAX_CASES}
    if len(inside) > MAX_CASES:
        return {**out, "too_many": True}
    if len(inside) < 3:
        return {**out, "cases": [], "links": [], "groups": [], "nearby": []}
    rm = c.state.isin(flag.get("states") or [flag["state"]])
    if flag["sex"] != "all":
        rm &= c.vic_sex == flag["sex"]
    if flag["weapon"] != "all":
        rm &= c.weapon_group == flag["weapon"]
    ref = c[rm]
    scorer = Scorer(ref)
    rng = np.random.default_rng(seed)
    pool = place_all[~place_all.solved]
    if len(pool) < 30:
        pool = ref[~ref.solved]
    null = _null(scorer, pool, rng)
    inside = inside.sort_values(["year", "month"])
    S = scorer.matrix(inside, inside)
    P = _pct(null, S)
    np.fill_diagonal(P, 0)
    strong = P >= min_pct
    groups = _groups(P, GROUP_PCT)
    groups.sort(key=lambda g: -len(g))
    # similar unsolved cases outside the flag: neighbouring counties, a few years either side
    near_df = _nearby(data, flag, start, end, inside)
    nearby, near_links = [], []
    if len(near_df):
        Sn = scorer.matrix(near_df, inside)
        Pn = _pct(null, Sn)
        for k, r in enumerate(near_df.itertuples(index=False)):
            hits = np.flatnonzero(Pn[k] >= max(min_pct, LINK_PCT))
            if len(hits):
                nearby.append({**_case(r), "outside": True})
                near_links += [[len(inside) + len(nearby) - 1, int(m), round(float(Pn[k, m]), 4)] for m in hits]
    cases = [_case(r) for r in inside.itertuples(index=False)]
    links_ = [[int(i), int(j), round(float(P[i, j]), 4)] for i, j in zip(*np.nonzero(np.triu(strong, 1)))]
    # a searched case that isn't among them (solved, outside the years, or another place): add it, with
    # its links to the cases shown (at the loosest strength, closest 15)
    focus_i = None
    if focus:
        known = [k for k, x in enumerate(cases + nearby) if x["id"] == focus]
        if known:
            focus_i = known[0]
        else:
            row = c[c.case_id == focus]
            if len(row):
                pf = _pct(null, scorer.matrix(row.iloc[[0]], inside))[0]
                focus_i = len(cases) + len(nearby)
                nearby.append({**_case(next(row.iloc[[0]].itertuples(index=False))), "outside": True, "focus": True})
                top = [m for m in np.argsort(-pf)[:15] if pf[m] >= 0.95]
                near_links += [[focus_i, int(m), round(float(pf[m]), 4)] for m in top]
    # solved cases from the same place and years that resemble the unsolved ones (context only: they
    # never join a group, and the data names no offenders)
    solved_n = 0
    if solved:
        sv = place_all[place_all.year.between(start, end) & place_all.solved]
        if focus:
            sv = sv[sv.case_id != focus]
        if len(sv):
            Ps = _pct(null, scorer.matrix(sv, inside))
            best = Ps.max(1)
            for k in np.argsort(-best)[:200]:
                if best[k] < min_pct:
                    break
                i = len(cases) + len(nearby)
                nearby.append({**_case(next(sv.iloc[[k]].itertuples(index=False))), "outside": False,
                               "context": True})
                hits = np.flatnonzero(Ps[k] >= min_pct)
                near_links += [[i, int(m), round(float(Ps[k, m]), 4)] for m in hits[np.argsort(-Ps[k, hits])][:8]]
                solved_n += 1
    gsum = []
    for g in groups:
        sub = inside.iloc[g]
        pair = P[np.ix_(g, g)][np.triu_indices(len(g), 1)]
        attached = sorted({a for a, b, _ in near_links if b in g})
        gsum.append({"members": g, "size": len(g), "start": int(sub.year.min()), "end": int(sub.year.max()),
                     "cohesion": round(float(pair.mean()), 3), "shared": shared(sub, inside),
                     "distinct": distinct(sub, inside),
                     "agencies": sub.agency.astype(str).value_counts().head(3).to_dict(),
                     "weapons": sub.weapon.astype(str).value_counts().head(2).to_dict(),
                     "ages": [None if sub.vic_age.isna().all() else int(sub.vic_age.min()),
                              None if sub.vic_age.isna().all() else int(sub.vic_age.max())],
                     "linked_share": round(float((pair >= LINK_PCT).mean()), 2), "nearby": attached})
    gsum.sort(key=lambda x: (x["start"], x["end"]))   # by date: no ranking reliably puts a real series first
    return {**out, "cases": cases + nearby, "links": links_ + near_links, "groups": gsum,
            "grouped": int(sum(len(g) for g in groups)),
            "nearby_count": sum(1 for x in nearby if x.get("outside") and not x.get("focus")),
            "solved_count": solved_n, "focus": focus_i}


DISTINCT_LIFT = 0.50   # a detail at least 50 points more common in the group than in the flag...
DISTINCT_RARE = 0.30   # ...and held by at most 30% of the unsolved cases shown
DISTINCT_MIN = 4       # in a group of at least 4


def distinct(sub: pd.DataFrame, everyone: pd.DataFrame) -> list[str]:
    """Details (not place or time) far more common in the group than across the flag's cases, and rare
    across the flag. Groups are formed from cases that share details, so nearly every group shares
    something; these thresholds keep only what stands out (0-14 groups per flag on MAP's file,
    none for flags held together only by place and time)."""
    out = []
    if len(sub) < DISTINCT_MIN:
        return out
    for f in ("weapon", "circumstance", "relationship"):
        vc = sub[f].astype(str).value_counts(normalize=True)
        for v, sh in vc.items():
            base = float((everyone[f].astype(str) == v).mean())
            if _informative(v) and base <= DISTINCT_RARE and sh - base >= DISTINCT_LIFT:
                out.append(f"{f} {v}")
    ages = pd.to_numeric(sub.vic_age, errors="coerce").dropna()
    all_ages = pd.to_numeric(everyone.vic_age, errors="coerce").dropna()
    if len(ages) >= 3 and len(all_ages):
        lo, hi = int(ages.quantile(0.25)), int(ages.quantile(0.75))
        base = float(all_ages.between(lo, hi).mean())
        if hi - lo <= 8 and base <= DISTINCT_RARE and float(ages.between(lo, hi).mean()) - base >= DISTINCT_LIFT:
            out.append(f"victims aged {lo}–{hi}")
    return out


def shared(sub: pd.DataFrame, everyone: pd.DataFrame) -> list[str]:
    """What most of a group's cases have in common that the rest of the flag's cases mostly don't:
    the data's own words, with the shares."""
    out = []
    names = {"agency": "agency", "weapon": "weapon", "circumstance": "circumstance", "relationship": "relationship"}
    for f, label in names.items():
        vc = sub[f].astype(str).value_counts(normalize=True)
        vc = vc[[_informative(k) for k in vc.index]]
        if len(vc) and vc.iloc[0] >= 0.6:
            v = vc.index[0]
            rest = float((everyone[f].astype(str) == v).mean())
            out.append(f"{label} {v}: {vc.iloc[0]:.0%} of the group, {rest:.0%} of the unsolved cases shown")
    ages = pd.to_numeric(sub.vic_age, errors="coerce").dropna()
    if len(ages) >= 3:
        lo, hi = int(ages.quantile(0.25)), int(ages.quantile(0.75))
        all_ages = pd.to_numeric(everyone.vic_age, errors="coerce").dropna()
        rest = float(all_ages.between(lo, hi).mean()) if len(all_ages) else 0.0
        if hi - lo <= 8:
            out.append(f"victims mostly aged {lo}–{hi}: {float(ages.between(lo, hi).mean()):.0%} of the group, "
                       f"{rest:.0%} of the unsolved cases shown")
    t = _t(sub)
    span = (t.max() - t.min()) / 12
    out.append(f"within {span:.1f} years" if span >= 1 else f"within {int(t.max() - t.min()) + 1} months")
    return out


def _nearby(data, flag: dict, start: int, end: int, inside: pd.DataFrame) -> pd.DataFrame:
    """Unsolved cases in counties that border the view (in any state), a few years either side."""
    c = data.cases
    remember_counties(data)
    counties = set(flag.get("counties") or ([flag["county"]] if flag.get("county") else []))
    near = set().union(*(bordering(k) for k in counties)) - counties if counties else set()
    if not near:
        return c.iloc[0:0]
    m = c.county.isin(near) & (c.vic_age >= 12) & ~c.solved & c.year.between(start - 3, end + 3)
    if flag["sex"] != "all":
        m &= c.vic_sex == flag["sex"]
    if flag["weapon"] != "all":
        m &= c.weapon_group == flag["weapon"]
    return c[m].head(400)


def scope(state: str, county: str, sex: str, weapon: str, start: int, end: int, neighbours: bool = False,
          agency: str | None = None) -> dict:
    """Any place (a county, one agency in it, or a county with the counties that border it, across
    state lines too), victims (Female, Male or all) and method (a group or all), and years."""
    counties = [county] + (bordering(county) if neighbours and not agency else [])
    states = sorted({state} | {_STATE_OF.get(k, state) for k in counties})
    label = agency or county
    if neighbours and not agency:
        label = f"{county} and {len(counties) - 1} bordering count{'y' if len(counties) == 2 else 'ies'}"
    return {"kind": "place", "state": state, "states": states, "place": label, "county": county,
            "counties": counties, "agency": agency, "sex": sex, "weapon": weapon, "start": int(start),
            "end": int(end), "neighbours": bool(neighbours and not agency)}


def scope_mask(c: pd.DataFrame, sc: dict, by_year: bool = True) -> pd.Series:
    m = c.state.isin(sc["states"]) & c.county.isin(sc["counties"]) & (c.vic_age >= 12)
    if sc.get("agency"):
        m &= c.agency == sc["agency"]
    if sc["sex"] != "all":
        m &= c.vic_sex == sc["sex"]
    if sc["weapon"] != "all":
        m &= c.weapon_group == sc["weapon"]
    if not by_year:
        m &= c.year.between(sc["start"], sc["end"])
    return m


def bordering(county: str) -> list[str]:
    """Counties that share a border with this one, in any state (labels as the case file writes them)."""
    from .detectors.neighbours import adjacency
    from .interfaces.research import county_fips
    code = county_fips(county)
    if not code:
        return []
    near = adjacency().get(code, ())
    return sorted(lb for lb, c in _FIPS_OF.items() if c in near)


_STATE_OF: dict[str, str] = {}
_FIPS_OF: dict[str, str] = {}
_COUNTIES: dict[str, list[str]] = {}


def _state_counties(state: str) -> list[str]:
    return _COUNTIES.get(state, [])


def remember_counties(data) -> None:
    from .interfaces.research import county_fips
    if not _COUNTIES:
        for st, g in data.cases.dropna(subset=["county"]).groupby("state").county:
            _COUNTIES[st] = sorted(g.unique())
            for k in _COUNTIES[st]:
                _STATE_OF[k] = st
                code = county_fips(k)
                if code:
                    _FIPS_OF[k] = code


def checklist(flag: dict, result: dict, chance: dict | None) -> list[dict]:
    """Questions to answer before marking a flag for review, each answered from the data."""
    out = []
    g = result.get("groups") or []
    if result.get("too_many"):
        out.append({"ok": None, "text": f"{result['unsolved']} unsolved cases: too many to link at once. "
                                         "Select fewer years on the chart above."})
    elif g:
        dg = [x for x in g if x["distinct"]]
        out.append({"ok": bool(dg) or None,
                    "text": (f"{len(dg)} group{'s' if len(dg) != 1 else ''} share a distinctive detail (a circumstance, "
                             "relationship, age range or specific weapon far more common than across the flag): read "
                             "those first. " if dg else "No group shares a distinctive detail; the groups are held "
                             "together only by place, method and time. ")
                            + f"{len(g) - len(dg)} more group{'s' if len(g) - len(dg) != 1 else ''} share only place, "
                              "method and time."})
    else:
        out.append({"ok": False, "text": "No group of 3 or more cases resemble each other. This looks more like a "
                                         "long-run decline in clearance than a cluster."})
    if chance and chance.get("real"):
        share = min(1.0, chance["chance"] / chance["real"])
        out.append({"ok": share < 0.2, "text": f"About {share:.0%} of flags like this one in {flag['state']} "
                                               "appear by chance."})
    else:
        out.append({"ok": None, "text": "Chance rate not measured yet (Methods › Measure every state)."})
    v = flag.get("ruleout")
    out.append({"ok": (v == "clear") if v else None,
                "text": {"explains": "A known, adjudicated series explains it.",
                         "weakens": "An ordinary explanation weakens it (see the rule-out checks).",
                         "clear": "No ordinary explanation found."}.get(v, "Rule-out checks not run.")})
    cov = flag.get("coverage")
    if cov is not None:
        out.append({"ok": cov >= 0.7, "text": f"The case file holds {cov:.0%} of the murders reported here."})
    return out
