"""Combine any number of detectors.

The ensemble runs each detector, enriches the findings, then asks a Matcher
which findings from different detectors describe the same thing. Each finding
gets `found_by` (every detector that agrees) and a `confidence`:

high      two or more detectors agree
strong    one strict detector (false-alarm controlled)
possible  one sensitive detector

Near-duplicates (same group, overlapping years, similar length) are merged into
the finding from the strictest detector. A short burst inside a much longer
window is kept as its own finding, so a 2-year series isn't absorbed into a
24-year trend.

Matchers are swappable: subclass Matcher to define agreement differently
(neighboring counties, similar victim profiles, ...).
"""

from __future__ import annotations

from dataclasses import dataclass

from .core.types import Dataset, Finding, Query
from .detectors import DETECTORS, Detector
from .enrichers import DEFAULT_ENRICHERS, enrich

DEFAULT_DETECTORS = ("scan", "window")
_TIER_LABEL = {"strict": "strong", "sensitive": "possible"}
_RANK = {"high": 0, "strong": 1, "possible": 2}


class Matcher:
    """Same area (counties overlap; a region covers its member counties), victim sex and method,
    overlapping years, compatible victim profiles."""

    def area(self, f: Finding) -> set[str]:
        """Counties a finding covers: its county, or a region's member counties."""
        return set(f.extras.get("counties") or [f.county or f.place])

    def agree(self, a: Finding, b: Finding) -> bool:
        if (a.victim_sex, a.weapon) != (b.victim_sex, b.weapon) or a.start > b.end or b.start > a.end:
            return False
        if not self.area(a) & self.area(b):
            return False
        # Profiles must not contradict: a split finding agrees with an unsplit one,
        # but not with a finding for a different age band or circumstance.
        pa, pb = a.extras.get("profile", {}), b.extras.get("profile", {})
        return all(pa[k] == pb[k] for k in pa.keys() & pb.keys())

    def duplicate(self, a: Finding, b: Finding, span_ratio: float = 2.0) -> bool:
        # A region finding and a county finding say different things; never merge them.
        if (a.level == "region") != (b.level == "region"):
            return False
        return self.agree(a, b) and max(a.span, b.span) <= span_ratio * min(a.span, b.span)


@dataclass
class Ensemble:
    detectors: list[Detector]
    matcher: Matcher = None
    enrichers: tuple[str, ...] = DEFAULT_ENRICHERS
    dedupe: bool = True

    def __post_init__(self):
        self.matcher = self.matcher or Matcher()

    @classmethod
    def from_names(cls, names=DEFAULT_DETECTORS, params: dict[str, dict] | None = None, **kw) -> "Ensemble":
        params = params or {}
        return cls([DETECTORS.get(n)(**params.get(n, {})) for n in names], **kw)

    def run(self, data: Dataset, query: Query, kind: str | None = None) -> list[Finding]:
        found = {det.name: enrich(det.detect(data, query), data, self.enrichers) for det in self.detectors}
        return self.combine(found, kind=kind)

    def combine(self, found: dict[str, list[Finding]], kind: str | None = None) -> list[Finding]:
        """Merge already-enriched findings keyed by detector name (lets callers reuse runs)."""
        tier = {d.name: d.tier for d in self.detectors}
        all_f = [f for name in found for f in found[name]]
        for f in all_f:
            agree = {f.detector} | {g.detector for g in all_f
                                    if g.detector != f.detector and self.matcher.agree(f, g)}
            f.found_by = tuple(sorted(agree))
            f.extras["agreement"] = round(len(agree) / max(len(found), 1), 2)
            f.confidence = "high" if len(agree) >= 2 else _TIER_LABEL.get(tier.get(f.detector), "possible")

        if self.dedupe:
            order = sorted(all_f, key=lambda f: (tier.get(f.detector) != "strict", _RANK[f.confidence],
                                                 -f.unsolved))
            kept: list[Finding] = []
            for f in order:
                if not any(self.matcher.duplicate(k, f) for k in kept):
                    kept.append(f)
            all_f = kept

        if kind:
            all_f = [f for f in all_f if f.kind == kind]
        return sorted(all_f, key=lambda f: (_RANK[f.confidence], -f.unsolved))


def run(data: Dataset, query: Query | None = None, detectors=None,
        params: dict[str, dict] | None = None, kind: str | None = None, preset: str | None = None,
        **ensemble_kw) -> list[Finding]:
    """One call to run any set of registered detectors as an ensemble, optionally from a preset."""
    from .presets import resolve
    detectors, params = resolve(preset, detectors, params)
    return Ensemble.from_names(detectors or DEFAULT_DETECTORS, params, **ensemble_kw).run(
        data, query or Query(), kind=kind)
