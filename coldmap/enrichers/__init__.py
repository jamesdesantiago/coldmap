"""Enrichers, as plugins: steps that add information to findings after detection.

An Enricher takes findings and the Dataset and returns findings (usually the same
objects with fields filled in). Built-ins:

county    sets `county` for agency- and metro-level findings (needed for matching)
kind      labels each finding serial-pattern or accountability
coverage  share of the place's reported murders present in the case file
namus     missing people and unidentified remains in the same county and years (if loaded)
ruleouts  checks each flag against ordinary explanations (known series, reporting gaps, clearances, coding)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.registry import Registry
from ..core.types import Dataset, Finding


class Enricher(ABC):
    name: str = ""
    summary: str = ""

    @abstractmethod
    def enrich(self, findings: list[Finding], data: Dataset) -> list[Finding]:
        ...

    def note(self, finding: Finding, title: str, text: str) -> None:
        """Add a plain-language note to a finding. explain() and the explorer show it under
        "From plugins", credited to this enricher. Describe patterns, never people (ETHICS.md)."""
        finding.extras.setdefault("notes", []).append({"by": self.name, "title": title, "text": text})


ENRICHERS: Registry[type[Enricher]] = Registry("enricher", "coldmap.enrichers")
DEFAULT_ENRICHERS = ("county", "kind", "coverage", "namus", "ruleouts")


def enrich(findings: list[Finding], data: Dataset, names=DEFAULT_ENRICHERS) -> list[Finding]:
    for n in names:
        findings = ENRICHERS.get(n)().enrich(findings, data)
    return findings


from . import builtin, namus, ruleouts  # noqa: E402,F401
