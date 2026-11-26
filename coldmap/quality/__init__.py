"""Data-quality checks, as plugins.

A check scans a Dataset (optionally one state) and returns rows describing
anything suspicious: where, when, what, how big. Checks never change data;
when a check finds a real, systematic problem, the fix belongs in a Fix plugin
and DATA_ISSUES.md. The 2021 relationship-coding problem is the model: found by
accident, then confirmed and fixed. These checks look for the next one on purpose.

Add a check:

    from coldmap.quality import CHECKS, Check

    @CHECKS.register
    class MyCheck(Check):
        name = "my-check"
        summary = "What it looks for"
        def run(self, data, state=None):
            return pd.DataFrame([...])   # columns: where, when, detail, size (+ any extras)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from ..core.registry import Registry
from ..core.types import Dataset


class Check(ABC):
    name: str = ""
    summary: str = ""
    needs_clearance: bool = False

    @abstractmethod
    def run(self, data: Dataset, state: str | None = None) -> pd.DataFrame:
        ...


CHECKS: Registry[type[Check]] = Registry("check", "coldmap.checks")


def report(data: Dataset, state: str | None = None, checks: list[str] | None = None,
           top: int = 15) -> dict[str, pd.DataFrame]:
    """Run checks; returns {check name: findings frame}. Skips clearance checks without clearance data."""
    out = {}
    for name in checks or CHECKS.names():
        cls = CHECKS.get(name)
        if cls.needs_clearance and data.clearance is None:
            continue
        out[name] = cls().run(data, state).head(top)
    return out


from . import builtin  # noqa: E402,F401
