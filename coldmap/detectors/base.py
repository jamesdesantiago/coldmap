"""The Detector interface.

A detector reads a Dataset for a Query and returns Findings. That's the whole
contract. To add one:

    from dataclasses import dataclass, field
    from coldmap.detectors import DETECTORS, Detector
    from coldmap.core import Finding

    @DETECTORS.register
    class MyDetector(Detector):
        name = "mine"
        summary = "One line on what it looks for"
        tier = "sensitive"          # or "strict" if it controls false alarms

        @dataclass
        class Params:
            threshold: float = field(default=0.4, metadata={"help": "Flag at or below this solve rate"})

        def detect(self, data, query):
            cases = data.select(query)
            ...
            return [Finding(detector=self.name, ...)]

Params are typed dataclasses, so every interface (CLI, MCP, explorer) can list
and validate them without knowing the detector.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import MISSING, dataclass, fields
from typing import ClassVar

from ..core.types import Dataset, Finding, Query

TIERS = ("strict", "sensitive")


class Detector(ABC):
    name: ClassVar[str] = ""
    summary: ClassVar[str] = ""
    tier: ClassVar[str] = "sensitive"   # strict: controls false alarms; sensitive: catches more

    @dataclass
    class Params:
        pass

    def __init__(self, **params):
        known = {f.name for f in fields(self.Params)}
        unknown = set(params) - known
        if unknown:
            raise TypeError(f"{self.name} has no parameter(s) {sorted(unknown)}; "
                            f"available: {sorted(known)}")
        self.params = self.Params(**params)

    @abstractmethod
    def detect(self, data: Dataset, query: Query) -> list[Finding]:
        """Return findings for the query. Must not modify `data`."""

    @classmethod
    def describe(cls) -> dict:
        params = []
        for f in fields(cls.Params):
            default = (f.default if f.default is not MISSING
                       else f.default_factory() if f.default_factory is not MISSING else None)
            params.append({"name": f.name, "default": default, "type": getattr(f.type, "__name__", str(f.type)),
                           "help": f.metadata.get("help", "")})
        return {"name": cls.name, "summary": cls.summary, "tier": cls.tier, "params": params}

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.params})"
