"""Plugin registries.

Every extension point in coldmap (sources, fixes, detectors, enrichers) is a
Registry. Built-in plugins register with a decorator; third-party packages
register through Python entry points, so `pip install coldmap-yourplugin` is
enough for coldmap to find them:

    # in the plugin's pyproject.toml
    [project.entry-points."coldmap.detectors"]
    streak = "coldmap_streak:StreakDetector"
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Generic, Iterator, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, kind: str, group: str):
        self.kind = kind
        self.group = group          # entry-point group, e.g. "coldmap.detectors"
        self._items: dict[str, T] = {}
        self._loaded_entry_points = False

    def register(self, obj: T | None = None, *, name: str | None = None):
        """Use as @registry.register or registry.register(obj, name=...)."""
        def add(o: T) -> T:
            key = name or getattr(o, "name", None)
            if not key:
                raise ValueError(f"{self.kind} plugin {o!r} needs a `name`")
            if key in self._items and self._items[key] is not o:
                raise ValueError(f"A {self.kind} named {key!r} is already registered")
            self._items[key] = o
            return o
        return add(obj) if obj is not None else add

    def _load_plugins(self) -> None:
        if self._loaded_entry_points:
            return
        self._loaded_entry_points = True
        for ep in entry_points(group=self.group):
            if ep.name not in self._items:
                self.register(ep.load(), name=ep.name)

    def unregister(self, name: str) -> None:
        self._items.pop(name, None)

    def get(self, name: str) -> T:
        self._load_plugins()
        try:
            return self._items[name]
        except KeyError:
            raise KeyError(f"No {self.kind} named {name!r}. Available: {', '.join(self.names())}") from None

    def names(self) -> list[str]:
        self._load_plugins()
        return sorted(self._items)

    def __iter__(self) -> Iterator[tuple[str, T]]:
        self._load_plugins()
        return iter(sorted(self._items.items()))

    def __contains__(self, name: str) -> bool:
        self._load_plugins()
        return name in self._items
