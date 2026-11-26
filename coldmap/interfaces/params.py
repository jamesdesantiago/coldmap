"""Parse `detector.param=value` overrides from the command line or JSON."""

from __future__ import annotations

import ast


def parse_overrides(items: list[str] | tuple[str, ...]) -> dict[str, dict]:
    """['scan.reps=499', 'scan.levels=("agency",)', 'window.window=6'] -> {'scan': {...}, ...}"""
    out: dict[str, dict] = {}
    for item in items:
        if "=" not in item or "." not in item.split("=", 1)[0]:
            raise ValueError(f"Expected detector.param=value, got {item!r}")
        key, raw = item.split("=", 1)
        det, param = key.split(".", 1)
        try:
            value = ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            value = raw
        if param == "levels" and isinstance(value, str):
            value = tuple(v.strip() for v in value.split(","))
        out.setdefault(det, {})[param] = value
    return out
