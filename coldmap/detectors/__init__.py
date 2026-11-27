"""Detectors, as plugins. See base.py for the interface and how to add one."""

from __future__ import annotations

from ..core.registry import Registry
from .base import TIERS, Detector

DETECTORS: Registry[type[Detector]] = Registry("detector", "coldmap.detectors")


def make(name: str, **params) -> Detector:
    """Instantiate a registered detector by name."""
    return DETECTORS.get(name)(**params)


from . import burst, map_original, sliding_window, temporal_scan  # noqa: E402,F401  (built-ins)

__all__ = ["DETECTORS", "Detector", "TIERS", "make"]
