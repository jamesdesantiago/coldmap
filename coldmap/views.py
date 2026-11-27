"""Views: plugins that add to the coldmap app itself.

A View is a new page in the app's sidebar (place = "page"), or a new section on every flag's
page (place = "flag"). It is written in Python and returns building blocks, which the app draws in
its own style: no HTML or JavaScript, so a plugin can add features without touching the app and
without being able to run scripts in it.

    from coldmap import VIEWS, View, blocks as b

    @VIEWS.register
    class Agencies(View):
        name = "agencies"
        title = "Agencies"
        summary = "Police agencies ranked by unsolved killings"
        place = "page"                    # or "flag" for a section on each flag
        group = "Research"                # where the page sits in the sidebar
        inputs = [b.state(), b.choice("victims", ["Female", "Male"], "Female")]

        def render(self, ctx, state=None, victims="Female"):
            d = ctx.cases[ctx.cases.vic_sex == victims]
            ...
            return [b.text("..."), b.table(["Agency", "Killings", "Solved"], rows)]

ctx gives a view what the app knows: ctx.data (the Dataset), ctx.cases (its case table),
ctx.flags (the ranked national flags), ctx.decisions (the shortlist) and ctx.datasets (your own
datasets). A flag section's render(ctx, flag) also gets the flag (a dict, as on the Flags page).

Views follow the same rules as every plugin (ETHICS.md): describe patterns, never people.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from .core.registry import Registry


class View:
    name: ClassVar[str] = ""
    title: ClassVar[str] = ""
    summary: ClassVar[str] = ""
    place: ClassVar[str] = "page"     # "page": a page in the sidebar; "flag": a section on each flag
    group: ClassVar[str] = "Research"  # sidebar group for pages: "Research" or "Extend"
    inputs: ClassVar[list] = []

    def render(self, ctx, *args, **inputs) -> list[dict]:
        raise NotImplementedError

    @classmethod
    def describe(cls) -> dict:
        return {"name": cls.name, "title": cls.title or cls.name, "summary": cls.summary, "place": cls.place,
                "group": cls.group if cls.group in ("Research", "Extend") else "Research",
                "inputs": list(cls.inputs)}


VIEWS: Registry[type[View]] = Registry("view", "coldmap.views")


@dataclass
class Context:
    """What the app hands a view."""
    data: Any
    flags: list[dict] = field(default_factory=list)
    decisions: dict = field(default_factory=dict)

    @property
    def cases(self):
        return self.data.cases

    @property
    def datasets(self) -> dict:
        return {k.split(":", 1)[1]: v for k, v in self.data.aux.items() if k.startswith("dataset:")}


# ---- building blocks ------------------------------------------------------------------------------
class blocks:  # noqa: N801  (used as a namespace: `from coldmap import blocks as b`)
    """Everything a view can show. Values are plain Python; the app escapes all text."""

    # inputs: controls at the top of a page; their values are passed to render()
    @staticmethod
    def state(name: str = "state", label: str = "State", default: str | None = None) -> dict:
        return {"name": name, "type": "state", "label": label, "default": default}

    @staticmethod
    def choice(name: str, options: list, default=None, label: str | None = None) -> dict:
        opts = [o if isinstance(o, (list, tuple)) else [o, o] for o in options]
        return {"name": name, "type": "choice", "label": label or name.replace("_", " ").capitalize(),
                "options": [[str(v), str(t)] for v, t in opts], "default": default if default is not None else opts[0][0]}

    @staticmethod
    def number(name: str, default: float, label: str | None = None, min=None, max=None, step=None) -> dict:
        return {"name": name, "type": "number", "label": label or name.replace("_", " ").capitalize(),
                "default": default, "min": min, "max": max, "step": step}

    @staticmethod
    def text_input(name: str, default: str = "", label: str | None = None, placeholder: str = "") -> dict:
        return {"name": name, "type": "text", "label": label or name.replace("_", " ").capitalize(),
                "default": default, "placeholder": placeholder}

    # blocks: what render() returns, in order
    @staticmethod
    def heading(text: str) -> dict:
        return {"type": "heading", "text": str(text)}

    @staticmethod
    def text(text: str) -> dict:
        """A paragraph. **bold** and `code` work."""
        return {"type": "text", "text": str(text)}

    @staticmethod
    def note(text: str, tone: str = "info") -> dict:
        """A boxed note; tone is info, warn or ok."""
        return {"type": "note", "text": str(text), "tone": tone if tone in ("info", "warn", "ok") else "info"}

    @staticmethod
    def stats(items: list) -> dict:
        """Headline numbers: [(label, value), ...] or [(label, value, "neg"), ...]."""
        return {"type": "stats", "items": [[str(i[0]), _plain(i[1]), i[2] if len(i) > 2 else ""] for i in items]}

    @staticmethod
    def table(columns: list[str], rows: list[list], flag_ids: list[str | None] | None = None,
              numeric: list[str] | None = None) -> dict:
        """A table. flag_ids (one per row) makes rows open that flag; numeric names right-aligned columns."""
        return {"type": "table", "columns": [str(c) for c in columns], "rows": [[_plain(v) for v in r] for r in rows],
                "flags": flag_ids, "numeric": numeric or []}

    @staticmethod
    def bars(data: list, title: str = "", unit: str = "") -> dict:
        """Horizontal bars: [(label, value), ...]."""
        return {"type": "bars", "title": title, "unit": unit, "data": [[str(k), _plain(v)] for k, v in data]}

    @staticmethod
    def line(x: list, series: dict, title: str = "", unit: str = "") -> dict:
        """Lines over x: series = {"name": [values...], ...}."""
        return {"type": "line", "title": title, "unit": unit, "x": [_plain(v) for v in x],
                "series": [[str(k), [_plain(v) for v in vals]] for k, vals in series.items()]}

    @staticmethod
    def flags(ids: list[str], title: str = "") -> dict:
        """A list of flags (ids from ctx.flags) that open on click."""
        return {"type": "flags", "title": title, "ids": [str(i) for i in ids]}


def _plain(v):
    """JSON-safe values (numpy numbers, NaN)."""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    return v


def render(view: type[View], ctx: Context, *args, **inputs) -> list[dict]:
    """Run a view and check what it returned."""
    out = view().render(ctx, *args, **inputs)
    if out is None:
        return []
    if isinstance(out, dict):
        out = [out]
    if not isinstance(out, list) or not all(isinstance(b, dict) and "type" in b for b in out):
        raise TypeError("A view's render() must return a list of blocks (coldmap.blocks).")
    return out
