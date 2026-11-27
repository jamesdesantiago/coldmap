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
EXAMPLES = {"before_after.py": "Before & after", "agency_report.py": "Agency report"}
GUIDE = Path(__file__).with_name("docs") / "plugins.md"  # shown in the app at /guide
LOCKED_ENRICHERS = ("county", "kind")  # other steps rely on these
LEGACY_ENRICHERS = ("county", "kind", "coverage", "namus")  # built in before 0.6, when settings didn't record what was offered
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


# What to point out before someone installs a plugin: things a model about patterns rarely needs.
_RISKY = {
    "network": ("urllib", "requests", "http", "socket", "httpx", "aiohttp", "ftplib", "smtplib", "websocket"),
    "other programs": ("subprocess", "os.system", "os.popen", "os.exec", "os.spawn", "pty", "multiprocessing"),
    "code it builds at run time": ("eval", "exec", "compile", "__import__", "importlib", "marshal", "pickle"),
    "files outside coldmap": ("shutil", "os.remove", "os.unlink", "os.rmdir", "os.rename", "pathlib", "open"),
    "the system": ("ctypes", "winreg", "sys.modules", "builtins"),
}


def review(text: str) -> dict:
    """Read a plugin's source without running it: what it registers and what it reaches for."""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        return {"valid": False, "error": f"Line {e.lineno}: {e.msg}", "flags": [], "registers": []}
    names: set[str] = set()
    registers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
            elif isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                names.add(f"{f.value.id}.{f.attr}")
        elif isinstance(node, ast.ClassDef):
            for d in node.decorator_list:
                src = ast.unparse(d)
                if src.endswith(".register"):
                    registers.append({"registry": src.removesuffix(".register"), "class": node.name})
    # Changing coldmap itself: assigning to anything imported from coldmap (for example replacing
    # the dataset identifier filter or the review rules) or to its modules' attributes.
    from_coldmap = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                    and (n.module or "").startswith("coldmap") for a in n.names}
    from_coldmap |= {(a.asname or a.name).split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                     for a in n.names if a.name.startswith("coldmap")}
    patched = set()
    for n in ast.walk(tree):
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, (ast.AugAssign, ast.AnnAssign)) else []
        for t in targets:
            base = t
            while isinstance(base, ast.Attribute):
                base = base.value
            if isinstance(t, ast.Attribute) and isinstance(base, ast.Name) and base.id in from_coldmap:
                patched.add(ast.unparse(t))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("setattr", "delattr") and n.args \
                and isinstance(n.args[0], ast.Name) and n.args[0].id in from_coldmap:
            patched.add(f"{n.func.id}({n.args[0].id}, ...)")
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "unregister":
            patched.add(ast.unparse(n.func))
    flags = []
    if patched:
        flags.append({"what": "coldmap itself (it replaces or removes parts of coldmap, which could switch off its safeguards)",
                      "uses": sorted(patched)[:8]})
    for what, hints in _RISKY.items():
        hits = sorted({n for n in names for h in hints if n == h or n.startswith(h + ".")})
        if hits:
            flags.append({"what": what, "uses": hits[:8]})
    return {"valid": True, "flags": flags, "registers": registers, "lines": text.count("\n") + 1}


def remove(filename: str) -> None:
    with _lock:
        path = folder() / filename
        if not _FILE.match(filename) or not path.exists():
            raise ValueError(f"There's no plugin file called {filename}.")
        path.unlink()
        load_local(force=True)


def example(name: str | None = None) -> tuple[str, str]:
    """A bundled example plugin: (file name, source). Default: Before & after."""
    name = name or EXAMPLE.name
    if name not in EXAMPLES:
        raise ValueError(f"There's no example called {name!r}.")
    path = EXAMPLE.with_name(name)
    return path.name, path.read_text(encoding="utf-8")


def starter(kind: str = "enricher") -> tuple[str, str]:
    """A new, unused starter plugin: (file name, source). kind: "enricher" or "page"."""
    base, template, token = (("my_page", STARTER_PAGE, "my-page") if kind == "page" else ("my_plugin", STARTER, "my-plugin"))
    taken = {p.name for p in folder().glob("*.py")} if folder().is_dir() else set()
    n = next(i for i in range(1, 1000) if (f"{base}{'' if i == 1 else f'_{i}'}.py") not in taken)
    suffix = "" if n == 1 else f"_{n}"
    return f"{base}{suffix}.py", template.replace(token, f"{token}{suffix.replace('_', '-')}")


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
    want = list(s.get("enrichers", enr_all))
    if "enrichers" in s:
        # Built-in enrichers added in a later version start on: the saved list only records the
        # choices someone made among the enrichers that existed then.
        known = set(s.get("known_enrichers") or LEGACY_ENRICHERS) | set(s["enrichers"])
        want += [n for n in DEFAULT_ENRICHERS if n not in known]
    enr = [n for n in enr_all if n in want or n in LOCKED_ENRICHERS]
    dets = dets or [n for n in DEFAULT_DETECTORS]
    return {"detectors": dets, "enrichers": enr or list(DEFAULT_ENRICHERS),
            "params": {d: p for d, p in s.get("params", {}).items() if d in dets and p}}


def views_off() -> list[str]:
    """Views (app pages and flag sections) switched off. Kept apart from enabled(): views only
    display, so switching one never makes the national scan out of date."""
    return list(_settings().get("views_off", []))


def set_enabled(kind: str, name: str, on: bool) -> dict[str, list[str]]:
    if kind == "view":
        from .views import VIEWS
        if name not in VIEWS:
            raise ValueError(f"There's no view called {name!r}.")
        s = _settings()
        off = [v for v in s.get("views_off", []) if v != name] + ([] if on else [name])
        s["views_off"] = off
        _settings_path().parent.mkdir(parents=True, exist_ok=True)
        _settings_path().write_text(json.dumps(s, indent=1))
        return enabled()
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
    if kind == "enricher":
        s["known_enrichers"] = _order("enricher")  # what was offered when this choice was made
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(s, indent=1))
    return enabled()


def _coerce(raw: str, typ: str):
    """A setting typed in the app, as the detector's parameter type."""
    raw = str(raw).strip()
    optional = "None" in typ
    if optional and raw.lower() in ("", "none", "off"):
        return None
    base = typ.replace("| None", "").replace("None |", "").strip()
    try:
        if base.startswith("tuple") or base.startswith("list"):
            return [x.strip() for x in raw.split(",") if x.strip()]
        if base == "bool":
            return raw.lower() in ("1", "true", "yes", "on")
        if base == "int":
            return int(float(raw))
        if base == "float":
            return float(raw)
    except ValueError:
        raise ValueError(f"{raw!r} isn't a valid {base}.") from None
    return raw


def set_param(detector: str, name: str, raw: str | None) -> dict:
    """Change one detector setting (raw=None goes back to its default)."""
    from .detectors import DETECTORS
    if detector not in DETECTORS:
        raise ValueError(f"There's no detector called {detector!r}.")
    spec = {p["name"]: p for p in DETECTORS.get(detector).describe()["params"]}
    if name not in spec:
        raise ValueError(f"{detector} has no setting called {name!r}.")
    s = _settings()
    params = s.setdefault("params", {}).setdefault(detector, {})
    if raw is None:
        params.pop(name, None)
    else:
        value = _coerce(raw, spec[name]["type"])
        DETECTORS.get(detector)(**{**params, name: value})  # the detector accepts it
        params[name] = value
    if not params:
        s["params"].pop(detector, None)
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(s, indent=1))
    return enabled()


def reset_params(detector: str) -> dict:
    s = _settings()
    s.get("params", {}).pop(detector, None)
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(s, indent=1))
    return enabled()


def source(kind: str, name: str) -> dict:
    """A model's code: the whole file for plugin files, the class for built-ins and packages."""
    import inspect
    from .core.registry import Registry
    reg = next((r for r in Registry.ALL if r.kind == kind), None)
    if reg is None or name not in reg:
        raise ValueError(f"There's no {kind} called {name!r}.")
    origin = reg.origin(name)
    if origin.startswith("file "):
        path = folder() / origin[5:]
        return {"origin": origin, "path": str(path), "code": path.read_text(encoding="utf-8")}
    obj = reg.get(name)
    target = obj if inspect.isclass(obj) else type(obj)
    try:
        code, path = inspect.getsource(target), inspect.getsourcefile(target)
    except (OSError, TypeError):
        code, path = "# The source isn't available for this one.", None
    return {"origin": origin, "path": path, "code": code}


def open_path(filename: str | None = None) -> str:
    """Open a plugin file in the default editor, or the plugins folder, on this computer."""
    import subprocess
    if filename:
        if not _FILE.match(filename) or not (folder() / filename).exists():
            raise ValueError(f"There's no plugin file called {filename}.")
        target = folder() / filename
    else:
        target = folder()
        target.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        # "edit", not the default action: for a .py file the default is often to run it with Python.
        os.startfile(str(target), "edit" if filename else "open")  # noqa: S606 (the user's own file, on request)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return str(target)


def fingerprint() -> str:
    """Changes whenever the plugins in use change, so cached builds are redone."""
    load_local()
    h = hashlib.sha1(json.dumps(enabled(), sort_keys=True).encode())
    for name, entry in sorted(_state["files"].items()):
        # Only files that change what a scan finds; a file that only adds views doesn't.
        if entry["error"] or any(r.kind != "view" for r, _ in entry["regs"]):
            h.update(name.encode() + (folder() / name).read_bytes())
    return h.hexdigest()[:12]


STARTER_PAGE = '''"""My page: a starting point for adding your own page to the coldmap app.

This file is in your plugins folder, so coldmap already loads it: look for "My page" in the
sidebar. Change render(), save, then press Replace on the Models page (or restart coldmap) to see
your changes. Pages return building blocks; the app draws them in its own style.

Blocks: b.heading, b.text, b.note, b.stats, b.table, b.bars, b.line, b.flags.
Inputs: b.state, b.choice, b.number, b.text_input. See coldmap/examples/agency_report.py.

Rules every plugin follows (ETHICS.md): describe patterns, never people.
"""

from coldmap import VIEWS, View, blocks as b


@VIEWS.register                                  # 1. register it, so coldmap can find it
class MyPage(View):
    name = "my-page"                             # 2. a unique name
    title = "My page"                            #    what the sidebar shows
    summary = "Unsolved killings by year in a state (an example to change)"
    place = "page"                               #    "page", or "flag" for a section on each flag
    group = "Research"
    inputs = [b.state(default="Ohio")]           # 3. controls at the top of the page

    def render(self, ctx, state="Ohio"):         # 4. return blocks
        c = ctx.cases[(ctx.cases.state == state) & (ctx.cases.vic_age >= 12)]
        by_year = c.groupby("year").solved.agg(["size", "sum"])
        unsolved = by_year["size"] - by_year["sum"]
        return [
            b.stats([("Killings", len(c)), ("Unsolved", int(unsolved.sum()), "neg")]),
            b.line(list(by_year.index), {"Unsolved": list(unsolved)}, title=f"Unsolved killings in {state}, by year"),
        ]
'''


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
