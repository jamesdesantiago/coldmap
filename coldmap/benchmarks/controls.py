"""Negative controls: how often does a detector flag something when nothing is there?

The null data keeps everything about the real data except where unsolved cases
fall. Within each stratum (state x victim sex x weapon group x year) the
solved/unsolved labels are shuffled across places. Statewide solve rates by
method and year, case counts per place and year, and the decline in clearance
over time all stay exactly as they were; only place-specific clusters are
destroyed. Any finding on null data is a false alarm by construction.

    null_findings   average findings per shuffled run
    real_findings   findings on the real data
    noise_share     null_findings / real_findings: rough share of real findings
                    that would appear by chance

A strict detector should produce close to zero findings on null data; a
sensitive one will produce more, which is the price of its recall.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.types import Dataset, Query
from ..detectors import DETECTORS
from ..ensemble import DEFAULT_DETECTORS, Ensemble
from ..enrichers import enrich


def shuffle_solved(data: Dataset, query: Query, seed: int = 0) -> Dataset:
    """A null copy of the query's slice: solved labels permuted within state x sex x method x year."""
    rng = np.random.default_rng(seed)
    d = data.select(query, use_query_age=False, use_exclusions=False).copy()
    keys = ["state", "vic_sex", "weapon_group", "year"]
    solved = d.solved.to_numpy().copy()
    for idx in d.groupby(keys, sort=False).indices.values():
        solved[idx] = rng.permutation(solved[idx])
    d["solved"] = solved
    return Dataset(d, source=data.source + ":null", clearance=data.clearance, fixes=data.fixes)


def _run(name: str, params: dict, data: Dataset, q: Query, kind: str | None):
    if name == "ensemble":
        out = Ensemble.from_names(params.get("detectors", DEFAULT_DETECTORS), params.get("params")).run(data, q)
    else:
        out = enrich(DETECTORS.get(name)(**params).detect(data, q), data)
    return [f for f in out if kind is None or f.kind == kind]


def false_alarms(data: Dataset, query: Query, detectors=(*DEFAULT_DETECTORS, "ensemble"),
                 params: dict | None = None, runs: int = 5, kind: str | None = "serial-pattern",
                 seed: int = 0) -> pd.DataFrame:
    """Compare findings on real data with findings on `runs` shuffled copies."""
    params = params or {}
    nulls = [shuffle_solved(data, query, seed + i) for i in range(runs)]
    rows = []
    for name in detectors:
        p = params.get(name, {})
        real = _run(name, p, data, query, kind)
        null = [_run(name, p, n, query, kind) for n in nulls]
        views = [(name, lambda fs: fs)]
        if name == "ensemble":
            for conf in ("high", "strong", "possible"):
                views.append((f"ensemble: {conf}", lambda fs, c=conf: [f for f in fs if f.confidence == c]))
        for label, pick in views:
            r, counts = len(pick(real)), [len(pick(x)) for x in null]
            mean = float(np.mean(counts))
            rows.append({"detector": label, "real_findings": r, "null_findings": round(mean, 1),
                         "null_range": f"{min(counts)}-{max(counts)}",
                         "noise_share": round(min(mean / r, 1.0), 2) if r else None})
    return pd.DataFrame(rows)
