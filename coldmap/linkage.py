"""Case links: which unsolved cases in a flag resemble each other enough to read side by side.

A long flag ("30 years of unsolved strangulations here") mixes a slow decline in clearance with,
possibly, a tight group of cases that look alike. This module scores how alike two unsolved cases
are and pulls out groups, so a reviewer can tell the two apart before marking anything for review.

Similarity, for two cases (standard practice in case linkage: shared *rare* details count more):
- same agency, same detailed weapon, same circumstance, same relationship: each adds
  -ln(share of the reference cases with that value), so a rare shared detail weighs more;
- victim ages within 2 years (or 5, for half): -ln(share of reference cases in that age range);
- time: up to TIME_W points, falling off over about two years.
"Undetermined", "not stated" and similar values never count as a match, and victim race is never
used. The reference is every case of the same state, victims and method.

Each pair's score is turned into a percentile against random pairs of unsolved cases from the same
place and method in any year: "stronger than 99% of random pairs from this place". That is a
similarity, NOT a probability that the cases share an offender: the case file doesn't mark which
cases were later linked, so no such probability can be calibrated from it.

Tested on the 9 adjudicated series (November 2026): in 6 of 9, one of the flag's three largest
groups falls mostly inside the series' years (Los Angeles 1987-1998: a group of 18 cases, 1987-1992,
94% coded "rape" against 26% across the flag). But no way of ranking groups (size, tightness, how
distinctive their shared details are) put the series' group first more often than chance would: the
top group fell in the series' years 33-41% of the time, against 45% for the flag's cases overall.
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
MAX_CASES = 600        # unsolved cases linked at once; narrow the years beyond that
TIME_W = 3.0
NULL_PAIRS = 20000
UNINFORMATIVE = {"", "nan", "none", "unknown", "other", "other or type unknown", "firearm, type not stated",
                 "relationship not determined", "circumstances undetermined", "other - not specified",
                 "not recorded", "not reported", "undetermined"}
FIELDS = ("agency", "weapon", "circumstance", "relationship")


def _informative(v) -> bool:
    return str(v).strip().lower() not in UNINFORMATIVE


class Scorer:
    """Rarity weights from a reference set of cases, and pairwise scores."""

    def __init__(self, ref: pd.DataFrame):
        self.w = {}
        for f in FIELDS:
            share = ref[f].astype(str).value_counts(normalize=True)
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
            va, vb = a[f].astype(str).to_numpy(), b[f].astype(str).to_numpy()
            wa = np.nan_to_num(pd.Series(va).map(self.w[f]).to_numpy(dtype=float))
            s += np.where(va == vb, wa, 0.0)
        aa = pd.to_numeric(a.vic_age, errors="coerce").to_numpy(dtype=float)
        ab = pd.to_numeric(b.vic_age, errors="coerce").to_numpy(dtype=float)
        gap = np.abs(aa - ab)
        idx = np.clip(np.nan_to_num(aa, nan=0), 0, 110).astype(int)
        known = ~np.isnan(gap)
        s += np.where(known & (gap <= 2), self.age_w2[idx], np.where(known & (gap <= 5), 0.5 * self.age_w5[idx], 0.0))
        s += TIME_W * np.exp(-np.abs(_t(a) - _t(b)) / 24.0)
        return s

    def matrix(self, a: pd.DataFrame, b: pd.DataFrame) -> np.ndarray:
        """Scores between every case in a and every case in b."""
        s = np.zeros((len(a), len(b)))
        for f in FIELDS:
            wa = a[f].astype(str).map(self.w[f]).to_numpy(dtype=float)
            va, vb = a[f].astype(str).to_numpy(), b[f].astype(str).to_numpy()
            same = va[:, None] == vb[None, :]
            s += np.where(same, np.nan_to_num(wa)[:, None], 0.0)
        aa = pd.to_numeric(a.vic_age, errors="coerce").to_numpy(dtype=float)
        ab = pd.to_numeric(b.vic_age, errors="coerce").to_numpy(dtype=float)
        gap = np.abs(aa[:, None] - ab[None, :])
        idx = np.clip(np.nan_to_num(aa, nan=0), 0, 110).astype(int)
        known = ~np.isnan(gap)
        s += np.where(known & (gap <= 2), self.age_w2[idx][:, None],
                      np.where(known & (gap <= 5), 0.5 * self.age_w5[idx][:, None], 0.0))
        s += TIME_W * np.exp(-np.abs(_t(a)[:, None] - _t(b)[None, :]) / 24.0)
        return s


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
    return {"id": str(r.case_id), "year": int(r.year), "month": int(r.month) if r.month > 0 else None,
            "age": None if pd.isna(r.vic_age) else int(r.vic_age), "agency": str(r.agency), "county": r.county,
            "weapon": str(r.weapon), "circumstance": str(r.circumstance), "relationship": str(r.relationship)}


def links(data, flag: dict, start: int | None = None, end: int | None = None, seed: int = 0,
          min_pct: float = LINK_PCT) -> dict:
    """Unsolved cases of a flag (optionally narrowed to start..end), the links between them, groups,
    and similar unsolved cases just outside the flag."""
    from .interfaces.research import _mask
    c = data.cases
    start = int(start if start is not None else flag["start"])
    end = int(end if end is not None else flag["end"])
    place_all = c[_mask(c, flag, by_year=True)]
    inside = place_all[place_all.year.between(start, end) & ~place_all.solved]
    min_pct = float(min_pct) if np.isfinite(min_pct) else LINK_PCT
    min_pct = min(max(min_pct, 0.95), 0.999)   # links shown: 95th to 99.9th percentile
    out = {"start": start, "end": end, "unsolved": int(len(inside)), "link_pct": LINK_PCT, "min_pct": min_pct,
           "max_cases": MAX_CASES}
    if len(inside) > MAX_CASES:
        return {**out, "too_many": True}
    if len(inside) < 3:
        return {**out, "cases": [], "links": [], "groups": [], "nearby": []}
    ref = c[(c.state == flag["state"]) & (c.vic_sex == flag["sex"]) & (c.weapon_group == flag["weapon"])]
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
            "grouped": int(sum(len(g) for g in groups)), "nearby_count": len(nearby)}


DISTINCT_LIFT = 0.50   # a detail at least 50 points more common in the group than in the flag...
DISTINCT_RARE = 0.30   # ...and held by at most 30% of the flag's unsolved cases
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
            out.append(f"{label} {v}: {vc.iloc[0]:.0%} of the group, {rest:.0%} of the flag's unsolved cases")
    ages = pd.to_numeric(sub.vic_age, errors="coerce").dropna()
    if len(ages) >= 3:
        lo, hi = int(ages.quantile(0.25)), int(ages.quantile(0.75))
        all_ages = pd.to_numeric(everyone.vic_age, errors="coerce").dropna()
        rest = float(all_ages.between(lo, hi).mean()) if len(all_ages) else 0.0
        if hi - lo <= 8:
            out.append(f"victims mostly aged {lo}–{hi}: {float(ages.between(lo, hi).mean()):.0%} of the group, "
                       f"{rest:.0%} of the flag's unsolved cases")
    t = _t(sub)
    span = (t.max() - t.min()) / 12
    out.append(f"within {span:.1f} years" if span >= 1 else f"within {int(t.max() - t.min()) + 1} months")
    return out


def _nearby(data, flag: dict, start: int, end: int, inside: pd.DataFrame) -> pd.DataFrame:
    from .detectors.neighbours import adjacency
    from .interfaces.research import county_fips
    c = data.cases
    counties = set(flag.get("counties") or ([flag["county"]] if flag.get("county") else []))
    codes = {county_fips(k) for k in counties} - {None}
    adj = adjacency()
    near_codes = set().union(*(adj.get(x, set()) for x in codes)) - codes if codes else set()
    m = (c.state == flag["state"]) & (c.vic_sex == flag["sex"]) & (c.weapon_group == flag["weapon"]) & \
        (c.vic_age >= 12) & ~c.solved & c.year.between(start - 3, end + 3)
    cand = c[m]
    if not len(cand):
        return cand
    fips = cand.county.map(lambda k: county_fips(k) if isinstance(k, str) else None)
    cand = cand[fips.isin(near_codes) | (cand.county.isin(counties) & ~cand.case_id.isin(inside.case_id))]
    return cand.head(400)


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
