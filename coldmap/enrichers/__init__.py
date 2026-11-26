"""Enrichers, as plugins: steps that add information to findings after detection.

An Enricher takes findings and the Dataset and returns findings (usually the same
objects with fields filled in). Built-ins:

county    sets `county` for agency- and metro-level findings (needed for matching)
kind      labels each finding serial-pattern or accountability
coverage  share of the place's reported murders present in the case file
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


ENRICHERS: Registry[type[Enricher]] = Registry("enricher", "coldmap.enrichers")
DEFAULT_ENRICHERS = ("county", "kind", "coverage")


def enrich(findings: list[Finding], data: Dataset, names=DEFAULT_ENRICHERS) -> list[Finding]:
    for n in names:
        findings = ENRICHERS.get(n)().enrich(findings, data)
    return findings


from . import builtin  # noqa: E402,F401
