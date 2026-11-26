"""`coldmap open`: a local app that walks you from nothing to the explorer.

The command starts a small server on this computer and opens the browser straight away, on a home
page that guides each step and shows its progress: download MAP's public files (or check them for
updates), pick a state, build its explorer, open it. Nothing heavy runs before the page is up, and
nothing is published. Builds are cached until the data or coldmap changes.
"""

from __future__ import annotations

import difflib
import http.server
import json
import os
import re
import shutil
import threading
import time
import urllib.request
import uuid
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import click

DATA_PAGE = "https://www.murderdata.org/p/data-docs.html"
# Download links from MAP's data page (files updated August 2026). If MAP moves them, the app
# shows manual steps; override with COLDMAP_CASES_URL / COLDMAP_CLEARANCE_URL.
MAP_FILES = {
    "cases": ("SHR76_25a.csv", "COLDMAP_CASES_URL",
              "https://www.dropbox.com/scl/fi/1c82yyrg7s7dpfkbsk1hn/SHR76_25a.csv"
              "?rlkey=4nrhqqp729bgk4od2xnyu1ukm&dl=1"),
    "clearance": ("UCR65_25.csv", "COLDMAP_CLEARANCE_URL",
                  "https://www.dropbox.com/scl/fi/4y2a6yy0pv4lxffm7sa4v/UCR65_25.csv"
                  "?rlkey=jhs7ktqhb9h3dnml1wety4nhb&dl=1"),
}
LABELS = {"cases": "case file", "clearance": "clearance file"}
SHELL = Path(__file__).with_name("explorer") / "shell.html"


from ..plugins import home  # noqa: E402  (data, builds, plugins and settings live here)


def _url(key: str) -> str:
    name, env, url = MAP_FILES[key]
    return os.environ.get(env) or url


def download(url: str, dest: Path, label: str, progress=None) -> dict:
    """Download to dest (via a .part file). progress(done, total) is called as bytes arrive;
    without it a terminal progress bar is shown. Returns the server's size and ETag."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "coldmap"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
        size = int(r.headers.get("Content-Length") or 0) or None
        info = {"size": size, "etag": r.headers.get("ETag")}
        if progress:
            done = 0
            progress(0, size)
            while chunk := r.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                progress(done, size)
        else:
            with click.progressbar(length=size, label=label, show_pos=size is None) as bar:
                while chunk := r.read(1 << 20):
                    out.write(chunk)
                    bar.update(len(chunk))
    with open(part, "rb") as f:
        head = f.read(200).lower()
    if head.lstrip().startswith((b"<!doctype", b"<html")):
        part.unlink()
        raise OSError("the link returned a web page instead of the data file")
    part.replace(dest)
    return info


def remote_info(url: str) -> dict:
    """Size and ETag of the file at url, fetching one byte rather than the whole file."""
    req = urllib.request.Request(url, headers={"User-Agent": "coldmap", "Range": "bytes=0-0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        total = (r.headers.get("Content-Range") or "").rpartition("/")[2]
        size = int(total) if total.isdigit() else int(r.headers.get("Content-Length") or 0) or None
        return {"size": size, "etag": r.headers.get("ETag")}


def fetch_plugin(url: str) -> tuple[str, str]:
    """Download a plugin .py file from a link (GitHub file pages are turned into raw links)."""
    url = url.strip()
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/(.+)$", url)
    if m:
        url = f"https://raw.githubusercontent.com/{m[1]}/{m[2]}/{m[3]}"
    if not url.startswith("https://"):
        raise ValueError("Use an https:// link to a .py file, for example a file on GitHub.")
    name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    if not name.endswith(".py"):
        raise ValueError("The link should point to a single .py file.")
    req = urllib.request.Request(url, headers={"User-Agent": "coldmap"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(512 * 1024 + 1)
    except Exception as e:
        raise ValueError(f"Couldn't download that link: {e}") from None
    try:
        return name, raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("That link isn't a text .py file.") from None


def _sources_file() -> Path:
    return home() / "data" / "sources.json"


def _sources() -> dict:
    try:
        return json.loads(_sources_file().read_text())
    except (OSError, ValueError):
        return {}


def _remember(key: str, info: dict) -> None:
    s = _sources()
    s[key] = {**info, "downloaded": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _sources_file().write_text(json.dumps(s, indent=1))


def manual_route(name: str) -> str:
    return (f"Download it yourself from {DATA_PAGE} (the CSV link next to 'Supplementary Homicide "
            f"Report'), then run: coldmap open --cases path/to/{name}")


def ensure_data(refresh: bool = False) -> tuple[Path, Path | None]:
    """Terminal route (scripts): return (cases, clearance), downloading MAP's files if missing.
    The clearance file is optional: if it fails, the explorer still builds without coverage."""
    data = home() / "data"
    paths = {}
    for key, (name, _env, _u) in MAP_FILES.items():
        dest = data / name
        if refresh or not dest.exists():
            click.echo(f"Downloading {name} from the Murder Accountability Project...")
            try:
                _remember(key, download(_url(key), dest, name))
            except Exception as e:  # network, moved link, disk
                if key == "clearance":
                    click.echo(f"  Skipped the clearance file ({e}). Coverage figures will be missing.")
                    paths[key] = None
                    continue
                raise click.ClickException(f"Couldn't download {name}: {e}\n\n{manual_route(name)}")
        paths[key] = dest
    return paths["cases"], paths["clearance"]


def _data_stamp(*files: Path | None) -> str:
    """Identifies the data files (and coldmap version): enough for the list of states."""
    from .. import __version__
    return "|".join([__version__] + [f"{f.resolve()}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files if f])


def _stamp(*files: Path | None) -> str:
    """Identifies everything a build depends on: data, coldmap, the page template and plugins."""
    from .. import plugins
    from .explorer import build as b
    page = str(Path(b.__file__).with_name("index.html").stat().st_mtime_ns)
    return "|".join([_data_stamp(*files), page, plugins.fingerprint()])


def slugify(state: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", state.lower()).strip("-")


def _match_state(state: str, states: list[str]) -> str:
    by_key = {s.lower(): s for s in states} | {slugify(s): s for s in states}
    if state.lower() in by_key:
        return by_key[state.lower()]
    near = difflib.get_close_matches(state, states, n=3, cutoff=0.6)
    hint = f" Did you mean {' or '.join(near)}?" if near else f" States in the file: {', '.join(sorted(states))}."
    raise click.ClickException(f"No state called {state!r} in the data.{hint}")


class Library:
    """Explorer sites for every state in one case file, built on request and cached in
    COLDMAP_HOME/sites until the data or coldmap changes. The case file is loaded at most
    once per run, and only when something needs it."""

    def __init__(self, cases: Path, clearance: Path | None = None, rebuild: bool = False):
        self.cases = Path(cases)
        self.clearance = Path(clearance) if clearance else None
        self.rebuild = rebuild
        self.root = home() / "sites"
        self._data = None
        self._states: list[str] | None = None
        self.counts: dict[str, int] = {}
        self._lock = threading.RLock()
        self._fresh: set[str] = set()  # built during this run (so --rebuild applies once per state)

    @property
    def stamp(self) -> str:
        """Identifies the data, coldmap and plugins a build came from (cheap to recompute)."""
        return _stamp(self.cases, self.clearance)

    @property
    def loaded(self) -> bool:
        return self._data is not None

    def data(self):
        with self._lock:
            if self._data is None:
                from .. import load
                self._data = load(self.cases, clearance_path=self.clearance)
            return self._data

    def cached_states(self) -> list[str] | None:
        """The state list if it is known without loading the case file."""
        if self._states is None:
            try:
                saved = json.loads((self.root / "states.json").read_text())
                if saved["stamp"] == _data_stamp(self.cases, self.clearance):
                    self._states, self.counts = saved["states"], saved.get("counts", {})
            except (OSError, ValueError, KeyError):
                pass
        return self._states

    def states(self) -> list[str]:
        """Every state in the case file. Cached next to the sites so a warm start skips loading."""
        if self.cached_states() is not None:
            return self._states
        d = self.data().cases
        n = d.loc[d.county.notna()].groupby("state").size()
        self._states, self.counts = sorted(n.index.tolist()), {k: int(v) for k, v in n.items()}
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "states.json").write_text(
            json.dumps({"stamp": _data_stamp(self.cases, self.clearance), "states": self._states,
                        "counts": self.counts}))
        return self._states

    def resolve(self, state: str) -> str:
        return _match_state(state, self.states())

    def site(self, state: str) -> Path:
        return self.root / slugify(state)

    def is_built(self, state: str, stamp: str | None = None) -> bool:
        """Built for the current data, coldmap and plugins. Pass `stamp` when checking many states."""
        if self.rebuild and state not in self._fresh:
            return False
        f = self.site(state) / ".coldmap-build"
        return f.exists() and f.read_text() == (stamp or self.stamp)

    @property
    def national_dir(self) -> Path:
        return self.root / "_national"

    def national_summary(self, stamp: str | None = None) -> dict | None:
        """What the last nationwide scan found, if it is current."""
        d = self.national_dir
        try:
            if (d / ".coldmap-build").read_text() != (stamp or self.stamp):
                return None
            return json.loads((d / "summary.json").read_text())
        except (OSError, ValueError):
            return None

    def build_national(self, progress=None) -> dict:
        from .. import plugins
        from .explorer.national import build_national
        with self._lock:
            stamp = self.stamp
            if (s := self.national_summary(stamp)) and not self.rebuild:
                return s
            on = plugins.enabled()
            tmp = self.root / "_national.building"
            if tmp.exists():
                shutil.rmtree(tmp)
            out = build_national(self.data(), tmp, detectors=tuple(on["detectors"]),
                                 enrichers=tuple(on["enrichers"]), progress=progress)
            body = json.loads(out.read_text())
            conf: dict[str, int] = {}
            for r in body["findings"]:
                conf[r["confidence"]] = conf.get(r["confidence"], 0) + 1
            summary = {"generated": body["meta"]["generated"], "findings": len(body["findings"]),
                       "states": len(body["meta"]["states"]), "confidence": conf}
            (tmp / "summary.json").write_text(json.dumps(summary))
            (tmp / ".coldmap-build").write_text(stamp)
            if self.national_dir.exists():
                shutil.rmtree(self.national_dir)
            tmp.replace(self.national_dir)
            return summary

    def build(self, state: str, progress=None) -> Path:
        """Build (or reuse) the explorer for a state and return its folder.
        progress is passed to build_site (called with each BUILD_STEPS key)."""
        state = self.resolve(state)
        with self._lock:
            out = self.site(state)
            if self.is_built(state):
                return out
            from .. import plugins
            from .explorer.build import build_site
            data = self.data()
            on = plugins.enabled()
            tmp = out.with_name(out.name + ".building")
            if tmp.exists():
                shutil.rmtree(tmp)
            build_site(data, state, tmp, detectors=tuple(on["detectors"]), enrichers=tuple(on["enrichers"]),
                       progress=progress)
            (tmp / ".coldmap-build").write_text(self.stamp)
            if out.exists():
                shutil.rmtree(out)
            tmp.replace(out)
            self._fresh.add(state)
            return out


def prepare(state: str, cases: Path, clearance: Path | None, rebuild: bool = False) -> Path:
    """Build (or reuse) one state's explorer and return its folder."""
    return Library(cases, clearance, rebuild).build(state)


class Busy(Exception):
    pass


class Job:
    """One piece of background work with named steps, shown live on the home page."""

    def __init__(self, kind: str, title: str, steps: list[tuple[str, str]]):
        self.id = uuid.uuid4().hex[:12]
        self.kind, self.title = kind, title
        self.steps = [{"key": k, "label": label, "state": "pending"} for k, label in steps]
        self.bytes: list | None = None
        self.count: list | None = None   # [done, total] within the current step
        self.notes: list[str] = []
        self.error: str | None = None
        self.result: dict | None = None
        self.started = time.time()
        self.ended: float | None = None

    def step(self, key: str, done: int | None = None, total: int | None = None) -> None:
        """Mark `key` as running and every step before it as done; done/total count within it."""
        self.count = [done, total] if done is not None else None
        hit = False
        for s in self.steps:
            if s["key"] == key:
                s["state"], hit = "active", True
            elif not hit:
                s["state"] = "done"
        self.bytes = None

    def finish(self, result: dict | None = None) -> None:
        for s in self.steps:
            s["state"] = "done"
        self.result, self.ended = result or {}, time.time()

    def fail(self, message: str) -> None:
        for s in self.steps:
            if s["state"] == "active":
                s["state"] = "error"
        self.error, self.ended = message, time.time()

    @property
    def running(self) -> bool:
        return self.ended is None

    def view(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "steps": self.steps,
                "bytes": self.bytes, "count": self.count, "notes": self.notes, "error": self.error, "result": self.result,
                "running": self.running, "elapsed": round((self.ended or time.time()) - self.started, 1)}


class App:
    """State behind the home page: where the data comes from, the library of state sites,
    and the one background job (download, read, build) that may be running."""

    def __init__(self, mode: str = "map", cases: Path | None = None, clearance: Path | None = None,
                 rebuild: bool = False):
        self.mode = mode  # "map": MAP's files, downloaded here; "files": the user's own; "sample"
        self.rebuild = rebuild
        self._own = (Path(cases) if cases else None, Path(clearance) if clearance else None)
        self.job: Job | None = None
        self.check: dict | None = None
        self._lock = threading.Lock()
        self.lib: Library | None = None
        self.reload()

    def paths(self) -> tuple[Path | None, Path | None]:
        if self.mode == "map":
            d = home() / "data"
            return d / MAP_FILES["cases"][0], d / MAP_FILES["clearance"][0]
        return self._own

    def reload(self) -> None:
        cases, clearance = self.paths()
        self.lib = (Library(cases, clearance if clearance and clearance.exists() else None, self.rebuild)
                    if cases and cases.exists() else None)

    # ---- background work -------------------------------------------------------------------
    def start(self, kind: str, title: str, steps, work) -> Job:
        with self._lock:
            if self.job and self.job.running:
                raise Busy(f"Still working on: {self.job.title}")
            job = self.job = Job(kind, title, steps)

        def run():
            try:
                work(job)
                if job.running:
                    job.finish()
            except click.ClickException as e:
                job.fail(e.message)
            except Exception as e:  # report it on the page and keep serving
                job.fail(f"{type(e).__name__}: {e}")
        threading.Thread(target=run, daemon=True).start()
        return job

    def download(self, refresh: bool = False) -> Job:
        if self.mode != "map":
            raise click.ClickException("This session uses your own files; there is nothing to download.")
        want = [k for k, p in zip(MAP_FILES, self.paths()) if refresh or not p.exists()]
        steps = [(f"dl-{k}", f"Download the {LABELS[k]}") for k in want]
        steps.append(("index", "Read the case file and list the states"))

        def work(job: Job):
            for key in want:
                name = MAP_FILES[key][0]
                job.step(f"dl-{key}")
                try:
                    info = download(_url(key), home() / "data" / name, name,
                                    progress=lambda done, total: setattr(job, "bytes", [done, total]))
                    _remember(key, info)
                except Exception as e:
                    if key == "clearance":
                        job.notes.append(f"Skipped the clearance file ({e}). The explorer still works; "
                                         "coverage figures will be blank.")
                        continue
                    raise click.ClickException(f"Couldn't download {name}: {e}. {manual_route(name)}")
            self.check = None
            self.reload()
            job.step("index")
            job.finish({"states": len(self.lib.states())})
        return self.start("download", "Updating the data" if refresh else "Getting the data", steps, work)

    def index(self) -> Job:
        def work(job: Job):
            job.step("index")
            job.finish({"states": len(self.lib.states())})
        return self.start("index", "Reading the case file", [("index", "Read the case file and list the states")],
                          work)

    def build(self, state: str) -> Job:
        from .explorer.build import BUILD_STEPS
        if self.lib is None:
            raise click.ClickException("Get the data first.")
        state = self.lib.resolve(state)
        lib = self.lib

        def work(job: Job):
            job.step("load")
            lib.data()
            lib.build(state, progress=job.step)
            job.finish({"state": state, "slug": slugify(state)})
        return self.start("build", f"Building {state}", [("load", "Load the case file")] + BUILD_STEPS, work)

    def national(self) -> Job:
        from .explorer.national import NATIONAL_STEPS
        if self.lib is None:
            raise click.ClickException("Get the data first.")
        lib = self.lib

        def work(job: Job):
            job.step("load")
            lib.data()
            job.finish(lib.build_national(progress=job.step))
        return self.start("national", "Scanning every state", [("load", "Load the case file")] + NATIONAL_STEPS,
                          work)

    def _idle(self) -> None:
        if self.job and self.job.running:
            raise Busy(f"Wait until this finishes: {self.job.title}")

    def plugins_view(self) -> dict:
        from .. import plugins
        from ..core.registry import Registry
        on = plugins.enabled()
        groups = []
        for r in Registry.ALL:
            items = []
            for name, obj in r:
                summary = getattr(obj, "summary", "") or getattr(obj, "note", "") or getattr(obj, "title", "")
                item = {"name": name, "summary": summary, "origin": r.origin(name)}
                if r.kind in ("detector", "enricher"):
                    item["on"] = name in on[r.kind + "s"]
                    item["locked"] = r.kind == "enricher" and name in plugins.LOCKED_ENRICHERS
                    if r.kind == "detector":
                        item["tier"] = getattr(obj, "tier", None)
                items.append(item)
            groups.append({"kind": r.kind, "items": items})
        ex_name, _ = plugins.example()
        return {"groups": groups, "files": plugins.files(), "folder": str(plugins.folder()),
                "example": {"file": ex_name, "added": (plugins.folder() / ex_name).exists()}}

    def plugin_action(self, action: str, q: dict, body: bytes) -> dict:
        from .. import plugins
        self._idle()
        try:
            if action == "enable":
                plugins.set_enabled(q.get("kind", ""), q.get("name", ""), q.get("on") == "1")
                return self.plugins_view()
            if action == "remove":
                plugins.remove(q.get("file", ""))
                return self.plugins_view()
            if action == "example":
                added = plugins.add(*plugins.example())
            elif action == "starter":
                added = plugins.add(*plugins.starter())
            elif action == "upload":
                j = json.loads(body or b"{}")
                added = plugins.add(str(j.get("file", "")), str(j.get("text", "")))
            elif action == "link":
                name, text = fetch_plugin(q.get("url", ""))
                added = plugins.add(name, text)
            else:
                raise ValueError("Unknown plugin action.")
        except ValueError as e:
            raise click.ClickException(str(e)) from None
        return {**self.plugins_view(), "added": added, "path": str(plugins.folder() / added["file"])}

    def check_updates(self) -> dict:
        """Compare MAP's files with the downloaded copies without downloading them."""
        saved, files = _sources(), []
        for key, path in zip(MAP_FILES, self.paths()):
            name = MAP_FILES[key][0]
            try:
                r = remote_info(_url(key))
            except Exception as e:
                self.check = {"error": f"Couldn't reach the download link for {name}: {e}",
                              "at": time.time()}
                return self.check
            have = saved.get(key, {})
            local = path.stat().st_size if path.exists() else None
            if not path.exists():
                changed = True
            elif have.get("etag") and r["etag"]:
                changed = have["etag"] != r["etag"]
            else:
                changed = r["size"] is not None and r["size"] != local
            files.append({"key": key, "name": name, "changed": changed, "size": r["size"]})
        self.check = {"updates": any(f["changed"] for f in files), "files": files, "at": time.time()}
        return self.check

    # ---- what the page shows ---------------------------------------------------------------
    def status(self) -> dict:
        from .. import __version__
        from .cli import NOTICE
        saved, files = _sources(), []
        for key, path in zip(MAP_FILES, self.paths()):
            p = Path(path) if path else None
            present = bool(p and p.exists())
            st = p.stat() if present else None
            files.append({"key": key, "label": LABELS[key], "name": p.name if p else None,
                          "path": str(p) if p else None, "present": present,
                          "size": st.st_size if st else None,
                          "downloaded": saved.get(key, {}).get("downloaded") if self.mode == "map" else None})
        lib, states = self.lib, None
        if lib and lib.cached_states() is not None:
            stamp = lib.stamp
            states = [{"name": s, "slug": slugify(s), "built": lib.is_built(s, stamp), "cases": lib.counts.get(s)}
                      for s in lib.states()]
        elif lib and not (self.job and self.job.running):
            try:
                self.index()  # first run with this data: list the states in the background
            except Busy:
                pass
        from .. import plugins
        on = plugins.enabled()
        return {"version": __version__, "mode": self.mode, "home": str(home()), "notice": NOTICE,
                "data": {"ready": lib is not None, "files": files, "check": self.check},
                "states": states, "national": lib.national_summary() if lib else None,
                "plugins": {"detectors": on["detectors"], "enrichers": on["enrichers"],
                            "files": len(plugins.files())},
                "job": self.job.view() if self.job else None}


def _handler(app: App):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8"):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj), "application/json")

        def _redirect(self, to: str, code: int = 302):
            self.send_response(code)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            # The page sends this header; another site can't without a CORS preflight we never answer.
            if self.headers.get("X-Coldmap") != "1":
                return self._send(403, "Forbidden")
            u = urlsplit(self.path)
            q = parse_qs(u.query)
            try:
                if u.path == "/api/download":
                    return self._json(202, app.download(refresh=q.get("refresh") == ["1"]).view())
                if u.path == "/api/build":
                    return self._json(202, app.build((q.get("state") or [""])[0]).view())
                if u.path == "/api/check":
                    return self._json(200, app.check_updates())
                if u.path == "/api/national":
                    return self._json(202, app.national().view())
                if u.path.startswith("/api/plugins/"):
                    n = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(min(n, 2 * 1024 * 1024)) if n else b""
                    flat = {k: v[0] for k, v in q.items()}
                    return self._json(200, app.plugin_action(u.path.rsplit("/", 1)[1], flat, body))
            except Busy as e:
                return self._json(409, {"error": str(e)})
            except click.ClickException as e:
                return self._json(400, {"error": e.message})
            return self._send(404, "Not found")

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ("/", "/index.html", "/plugins", "/national"):
                return self._send(200, SHELL.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            if path == "/api/status":
                return self._json(200, app.status())
            if path == "/api/plugins":
                return self._json(200, app.plugins_view())
            lib = app.lib
            if path == "/national.json":
                if not (lib and lib.national_summary()):
                    return self._json(404, {"error": "Run the nationwide scan first."})
                self.directory = str(lib.national_dir)
                self.path = "/national.json"
                return super().do_GET()
            if path == "/states.json":  # the explorer's state menu
                names = (lib.cached_states() if lib else None) or []
                stamp = lib.stamp if lib else None
                return self._json(200, {"states": [{"name": s, "slug": slugify(s), "built": lib.is_built(s, stamp)}
                                                   for s in names]})
            slug, sep, rest = unquote(path).lstrip("/").partition("/")
            names = (lib.cached_states() if lib else None) or []
            state = next((s for s in names if slugify(s) == slug), None)
            if state is None:
                return self._redirect("/")
            if not sep:
                return self._redirect(f"/{slug}/", 301)
            if not lib.is_built(state):
                return self._redirect(f"/?build={quote(slug)}")
            self.directory = str(lib.site(state))
            self.path = "/" + rest
            return super().do_GET()

    return Handler


class _Server(http.server.ThreadingHTTPServer):
    # The stdlib default (SO_REUSEADDR) lets Windows bind a port another server already holds, so
    # the browser would reach that server instead. Refuse, and fall back to a free port.
    allow_reuse_address = False
    daemon_threads = True


def serve(app: App, port: int, open_browser: bool, path: str = "/") -> None:
    handler = _handler(app)
    try:
        httpd = _Server(("127.0.0.1", port), handler)
    except OSError:
        httpd = _Server(("127.0.0.1", 0), handler)  # port busy: pick a free one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    click.echo(f"\ncoldmap is running at {url}  (only on this computer)\n"
               f"Everything else happens in the browser. Press Ctrl+C here to stop.")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(url.rstrip("/") + path,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    finally:
        httpd.server_close()
