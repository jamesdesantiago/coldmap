"""Presets: named, documented bundles of detectors and settings.

    coldmap scan CASES --state California --preset strict
    coldmap.run(data, query, preset="profiles")

Explicit detectors/params passed alongside a preset override it. Add your own
with PRESETS.register(Preset(...)); a plugin package can ship presets through
the `coldmap.presets` entry point.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .core.registry import Registry


@dataclass(frozen=True)
class Preset:
    name: str
    summary: str
    detectors: tuple[str, ...]
    params: dict = field(default_factory=dict)


PRESETS: Registry[Preset] = Registry("preset", "coldmap.presets")

PRESETS.register(Preset(
    "strict", "Fewest false alarms: strict detector only, 5% false discovery rate, at least 5 unsolved",
    ("scan",), {"scan": {"max_q": 0.05, "min_unsolved": 5}}))
PRESETS.register(Preset(
    "balanced", "Default: strict + sensitive detectors combined, labeled by agreement",
    ("scan", "window")))
PRESETS.register(Preset(
    "profiles", "Balanced, split by victim age band (12-17, 18-29, 30-44, 45+) for sharper patterns",
    ("scan", "window"), {"scan": {"split_by": ("age_band",)}, "window": {"split_by": ("age_band",)}}))
PRESETS.register(Preset(
    "exploratory", "Cast a wide net for research: looser thresholds and MAP's original method; expect noise",
    ("scan", "window", "map"),
    {"scan": {"max_q": 0.25, "levels": ("county", "agency", "msa")}, "window": {"threshold": 0.5, "min_cases": 6}}))


def resolve(preset: str | None, detectors=None, params: dict | None = None):
    """Merge a preset with explicit choices (explicit wins). Returns (detectors, params)."""
    if not preset:
        return detectors, params or {}
    p = PRESETS.get(preset)
    merged = {k: dict(v) for k, v in p.params.items()}
    for det, kv in (params or {}).items():
        merged.setdefault(det, {}).update(kv)
    return (tuple(detectors) if detectors else p.detectors), merged
