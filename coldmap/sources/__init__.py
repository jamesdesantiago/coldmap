"""Data sources, as plugins.

A Source turns a file (or API, or database) into a Dataset in the shared schema
(see coldmap.core.types.CASE_COLUMNS). Detectors never see source formats.

Add one by subclassing Source, setting `name`, and implementing `load_cases`
(and optionally `load_clearance`), then registering it with SOURCES.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from ..core.registry import Registry
from ..core.types import Dataset
from ..fixes import apply_fixes


class Source(ABC):
    name: str = ""
    summary: str = ""

    @abstractmethod
    def load_cases(self, path: str | Path) -> pd.DataFrame:
        """Return case records with every column in CASE_COLUMNS."""

    def load_clearance(self, path: str | Path) -> pd.DataFrame | None:
        return None


SOURCES: Registry[type[Source]] = Registry("source", "coldmap.sources")


def load(cases_path: str | Path, source: str = "map-shr", clearance_path: str | Path | None = None,
         clearance_source: str = "map-clearance", skip_fixes: tuple[str, ...] = ()) -> Dataset:
    """Load a Dataset: read the cases, apply data fixes, optionally attach clearance counts."""
    src = SOURCES.get(source)()
    cases, applied = apply_fixes(src.load_cases(cases_path), source, skip_fixes)
    clearance = SOURCES.get(clearance_source)().load_clearance(clearance_path) if clearance_path else None
    return Dataset(cases, source=source, clearance=clearance, fixes=applied)


from . import map_files  # noqa: E402,F401  (registers built-in sources)
