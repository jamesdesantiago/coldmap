"""Plugin files and which plugins are switched on.

The easy way to add a plugin is a single .py file in the plugins folder
(COLDMAP_HOME/plugins, default ~/.coldmap/plugins). coldmap imports every file there the
first time it looks for plugins; whatever the file registers (@DETECTORS.register,
@ENRICHERS.register, ...) becomes available like a built-in. The `coldmap open` app adds,
lists and removes these files, and switches detectors and enrichers on or off.

Packages still work too: `pip install` one that declares a coldmap entry point
(examples/coldmap-streak). See the plugin guide (in the app: Plugins > Plugin guide; in the code: coldmap/docs/plugins.md) for both routes.

A plugin is Python code and runs with your permissions. Add only files you trust.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
from pathlib import Path

EXAMPLE = Path(__file__).with_name("examples") / "before_after.py"
GUIDE = Path(__file__).with_name("docs") / "plugins.md"  # shown in the app at /guide
LOCKED_ENRICHERS = ("county", "kind")  # other steps rely on these
MAX_BYTES = 512 * 1024
_FILE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}\.py$")
_lock = threading.RLock()
_state: dict = {"loaded": None, "files": {}}  # file name -> {"regs": [(registry, name)], "error": str | None}


def home() -> Path:
    """Where coldmap keeps its data, builds, plugins and settings (COLDMAP_HOME, default ~/.coldmap)."""
    return Path(os.environ.get("COLDMAP_HOME") or Path.home() / ".coldmap")


def folder() -> Path:
    return home() / "plugins"


def _registries():
    from . import quality  # noqa: F401  (make sure every registry exists before diffing)
    from .core.registry import Registry
    return Registry.ALL


# ---- loading ---------------------------------------------------------------------------------
def load_local(force: bool = False) -> None:
    """Import every plugin file once (again with force=True, after files change)."""
    with _lock:
        if _state["loaded"] == str(folder()) and not force:
            return
        _state["loaded"] = str(folder())  # reload if COLDMAP_HOME changes (tests, other sessions)
        for name in list(_state["files"]):
            _unload(name)
        if folder().is_dir():
            for f in sorted(folder().glob("*.py")):
                if not f.name.startswith("_"):
                    _load(f)


def _load(path: Path) -> None:
    regs = _registries()
    before = {id(r): set(r._items) for r in regs}
    module = "coldmap_plugin_" + re.sub(r"\W", "_", path.stem)
    error = None
    try:
        spec = importlib.util.spec_from_file_location(module, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module] = mod
        spec.loader.exec_module(mod)
    except Exception as e:  # a broken plugin must not break coldmap
        error = f"{type(e).__name__}: {e}"
    added = [(r, n) for r in regs for n in sorted(set(r._items) - before[id(r)])]
    if error:
        for r, n in added:
            r.unregister(n)
        sys.modules.pop(module, None)
        added = []
    elif not added:
        error = ("It didn't register anything. Put @DETECTORS.register or @ENRICHERS.register "
                 "(from coldmap) above the plugin class.")
    for r, n in added:
        r._origin[n] = f"file {path.name}"
    _state["files"][path.name] = {"regs": added, "error": error, "module": module}


def _unload(name: str) -> None:
    entry = _state["files"].pop(name, None)
    if entry:
        for r, n in entry["regs"]:
            r.unregister(n)
        sys.modules.pop(entry["module"], None)


def files() -> list[dict]:
    """Plugin files in the folder: what each registered, or why it couldn't load."""
    load_local()
    return [{"file": name, "error": e["error"],
             "provides": [{"kind": r.kind, "name": n} for r, n in e["regs"]]}
            for name, e in sorted(_state["files"].items())]


# ---- adding and removing ---------------------------------------------------------------------
def add(filename: str, text: str, enable: bool = True) -> dict:
    """Save a plugin file, load it and (by default) switch on what it provides.
    Raises ValueError with a plain message if the file is unusable; nothing is kept then."""
    filename = filename.strip()
    if not _FILE.match(filename):
        raise ValueError("Plugin files need a simple name ending in .py: letters, numbers and "
                         "underscores, starting with a letter (for example my_plugin.py).")
    if len(text.encode()) > MAX_BYTES:
        raise ValueError("That file is too big for a plugin (over 512 KB).")
    try:
        ast.parse(text, filename)
    except SyntaxError as e:
        raise ValueError(f"That isn't valid Python (line {e.lineno}: {e.msg}).") from None
    with _lock:
        folder().mkdir(parents=True, exist_ok=True)
        path = folder() / filename
        old = path.read_text(encoding="utf-8") if path.exists() else None
        path.write_text(text, encoding="utf-8")
        load_local(force=True)
        entry = _state["files"].get(filename, {})
        if entry.get("error"):
            if old is None:
                path.unlink()
            else:
                path.write_text(old, encoding="utf-8")
            load_local(force=True)
            raise ValueError(f"coldmap couldn't load {filename}. {entry['error']}")
        if enable:
            for r, n in entry["regs"]:
                if r.kind in ("detector", "enricher"):
                    set_enabled(r.kind, n, True)
        return next(f for f in files() if f["file"] == filename)


def remove(filename: str) -> None:
    with _lock:
        path = folder() / filename
        if not _FILE.match(filename) or not path.exists():
            raise ValueError(f"There's no plugin file called {filename}.")
        path.unlink()
        load_local(force=True)


def example() -> tuple[str, str]:
    """The bundled example plugin: (file name, source)."""
    return EXAMPLE.name, EXAMPLE.read_text(encoding="utf-8")


def starter() -> tuple[str, str]:
    """A new, unused starter plugin: (file name, source) for someone writing their own."""
    taken = {p.name for p in folder().glob("*.py")} if folder().is_dir() else set()
    n = next(i for i in range(1, 1000) if (f"my_plugin{'' if i == 1 else f'_{i}'}.py") not in taken)
    suffix = "" if n == 1 else f"_{n}"
    return f"my_plugin{suffix}.py", STARTER.replace("my-plugin", f"my-plugin{suffix.replace('_', '-')}")


# ---- which plugins are on --------------------------------------------------------------------
def _settings_path() -> Path:
    return home() / "settings.json"


def _settings() -> dict:
    try:
        return json.loads(_settings_path().read_text())
    except (OSError, ValueError):
        return {}


def _order(kind: str) -> list[str]:
    """Every registered detector or enricher, built-ins first in their pipeline order."""
    from .detectors import DETECTORS
    from .enrichers import DEFAULT_ENRICHERS, ENRICHERS
    from .ensemble import DEFAULT_DETECTORS
    reg, first = (DETECTORS, DEFAULT_DETECTORS) if kind == "detector" else (ENRICHERS, DEFAULT_ENRICHERS)
    names = reg.names()
    return [n for n in first if n in names] + [n for n in names if n not in first]


def enabled() -> dict[str, list[str]]:
    """Detectors and enrichers the app uses, in pipeline order. Defaults: the built-in
    defaults plus every enricher a plugin adds."""
    from .enrichers import DEFAULT_ENRICHERS
    from .ensemble import DEFAULT_DETECTORS
    s = _settings()
    dets = [n for n in _order("detector") if n in s.get("detectors", DEFAULT_DETECTORS)]
    enr_all = _order("enricher")
    want = s.get("enrichers", enr_all)
    enr = [n for n in enr_all if n in want or n in LOCKED_ENRICHERS]
    return {"detectors": dets or [n for n in DEFAULT_DETECTORS], "enrichers": enr or list(DEFAULT_ENRICHERS)}


def set_enabled(kind: str, name: str, on: bool) -> dict[str, list[str]]:
    if kind not in ("detector", "enricher") or name not in _order(kind):
        raise ValueError(f"There's no {kind} called {name!r}.")
    if kind == "enricher" and name in LOCKED_ENRICHERS and not on:
        raise ValueError(f"The {name} enricher can't be switched off: other steps rely on it.")
    cur = enabled()
    key = kind + "s"
    names = [n for n in cur[key] if n != name] + ([name] if on else [])
    if kind == "detector" and not names:
        raise ValueError("Keep at least one detector on.")
    s = _settings()
    s[key] = [n for n in _order(kind) if n in names]
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(s, indent=1))
    return enabled()


def fingerprint() -> str:
    """Changes whenever the plugins in use change, so cached builds are redone."""
    load_local()
    h = hashlib.sha1(json.dumps(enabled(), sort_keys=True).encode())
    for name in sorted(_state["files"]):
        h.update(name.encode() + (folder() / name).read_bytes())
    return h.hexdigest()[:12]


STARTER = '''"""My plugin: a starting point for your own coldmap plugin.

This file is in your plugins folder, so coldmap already loads it. Edit it, save, then
build a state again (the app rebuilds when a plugin changes) to see your note under
"From plugins" on any flag's Why flagged tab.

It's an enricher: it adds information to each flag. A detector, which finds new flags,
has the same shape; see the plugin guide (in the app: Plugins > Plugin guide)
and coldmap/examples/before_after.py.

Rules every plugin follows (ETHICS.md): describe patterns, never people. Don't call a flag
a series or a "serial killer", name anyone, or suggest contacting anyone.
"""

from coldmap import ENRICHERS, Enricher


@ENRICHERS.register                      # 1. register it, so coldmap can find it
class MyPlugin(Enricher):
    name = "my-plugin"                   # 2. a unique name (shown in the app)
    summary = "Unsolved killings per year in each flag (an example to change)"

    def enrich(self, findings, data):   # 3. add something to every flag
        for f in findings:
            per_year = f.unsolved / f.span
            self.note(f, "Unsolved per year",
                      f"{f.unsolved} unsolved over {f.span} years: about {per_year:.1f} a year.")
        return findings                  # 4. always return the findings
'''
