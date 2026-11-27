"""`coldmap open`: the coldmap research app, served on this computer.

The command starts a small server and opens the browser straight away. The app guides setup
(download MAP's files, then scan every state once), then the research itself: a ranked list of
flags, each flag's evidence, places, a shortlist with second review and an export for MAP, plus
models (plugins), AI assistants (MCP) and methods. Nothing is published; the research workspace
lives in COLDMAP_HOME (see research.py).
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
from urllib.parse import parse_qs, unquote, urlsplit

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
APP_PAGE = Path(__file__).with_name("explorer") / "app.html"
_VENDOR = APP_PAGE.with_name("vendor")
STATIC = {"/static/app.js": APP_PAGE.with_name("app.js"), "/static/theme.js": APP_PAGE.with_name("theme.js"),
          "/static/fonts.css": APP_PAGE.with_name("fonts.css"),
          "/vendor/archivo-latin.woff2": _VENDOR / "archivo-latin.woff2",
          "/vendor/jetbrainsmono-latin.woff2": _VENDOR / "jetbrainsmono-latin.woff2",
          "/vendor/d3.v7.min.js": _VENDOR / "d3.v7.min.js",
          "/vendor/topojson-client.min.js": _VENDOR / "topojson-client.min.js",
          "/vendor/counties-10m.json": _VENDOR / "counties-10m.json"}


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
            if not r.geturl().startswith("https://"):  # a redirect to plain http could be tampered with
                raise ValueError("The link redirected to an insecure (http) address.")
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
                from .. import datasets, load
                self._data = load(self.cases, clearance_path=self.clearance)
                datasets.attach(self._data)  # your own datasets, for models
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

    @property
    def national_stamp(self) -> str:
        """The nationwide results depend on the data and plugins, not on the explorer page."""
        from .. import datasets, plugins
        return _data_stamp(self.cases, self.clearance) + "|" + plugins.fingerprint() + "|" + datasets.fingerprint()

    def national_summary(self, current_only: bool = False) -> dict | None:
        """What the last nationwide scan found, with `stale` set when the data or plugins changed
        since (current_only=True returns None instead)."""
        d = self.national_dir
        try:
            summary = json.loads((d / "summary.json").read_text())
            stale = (d / ".coldmap-build").read_text() != self.national_stamp
        except (OSError, ValueError):
            return None
        if stale and current_only:
            return None
        return {**summary, "stale": stale}

    def build_national(self, progress=None) -> dict:
        from .. import plugins
        from .explorer.national import build_national
        with self._lock:
            stamp = self.national_stamp
            if (s := self.national_summary(current_only=True)) and not self.rebuild:
                return s
            on = plugins.enabled()
            tmp = self.root / "_national.building"
            if tmp.exists():
                shutil.rmtree(tmp)
            out = build_national(self.data(), tmp, detectors=tuple(on["detectors"]),
                                 enrichers=tuple(on["enrichers"]), progress=progress, params=on["params"])
            body = json.loads(out.read_text())
            conf: dict[str, int] = {}
            for r in body["findings"]:
                conf[r["confidence"]] = conf.get(r["confidence"], 0) + 1
            # Compare with the last scan: new, continuing (growing/steady/shrinking) and gone flags.
            from . import history
            from .research import with_ids
            from .. import datasets
            rows = with_ids(body["findings"])
            hist = history.compare(rows, body["meta"]["generated"], _data_stamp(self.cases, self.clearance),
                                   plugins.fingerprint() + "|" + datasets.fingerprint())
            out.write_text(json.dumps(body, separators=(",", ":"), default=str))
            summary = {"generated": body["meta"]["generated"], "findings": len(body["findings"]),
                       "states": len(body["meta"]["states"]), "confidence": conf, "history": hist}
            (tmp / "summary.json").write_text(json.dumps(summary))
            (tmp / ".coldmap-build").write_text(stamp)
            if self.national_dir.exists():
                shutil.rmtree(self.national_dir)
            tmp.replace(self.national_dir)
            return {**summary, "stale": False}

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
                       params=on["params"], progress=progress)
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


STOPPABLE = {"controls"}


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
        self.stop = False   # set by "Stop"; long jobs check it between pieces of work

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
                "running": self.running, "stoppable": self.kind in STOPPABLE, "stopping": self.stop,
                "elapsed": round((self.ended or time.time()) - self.started, 1)}


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
        self._flags: tuple | None = None
        import secrets
        # Only the browser coldmap opens gets this, so other accounts and programs on this
        # computer can't use the server (they could otherwise add a plugin that runs as you).
        self.key = secrets.token_urlsafe(24)
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

    def _fetch(self, job: Job, want: list[str]) -> None:
        for key in want:
            name = MAP_FILES[key][0]
            job.step(f"dl-{key}")
            try:
                info = download(_url(key), home() / "data" / name, name,
                                progress=lambda done, total: setattr(job, "bytes", [done, total]))
                _remember(key, info)
            except Exception as e:
                if key == "clearance":
                    job.notes.append(f"Skipped the clearance file ({e}). Everything still works; "
                                     "coverage figures will be blank.")
                    continue
                raise click.ClickException(f"Couldn't download {name}: {e}. {manual_route(name)}")
        self.check = None
        self.reload()

    def setup(self) -> Job:
        """First run: get whatever data is missing, then scan every state once."""
        from .explorer.national import NATIONAL_STEPS
        want = [k for k, p in zip(MAP_FILES, self.paths()) if self.mode == "map" and not p.exists()]
        steps = [(f"dl-{k}", f"Download MAP's {LABELS[k]}") for k in want]
        steps += [("load", "Read the case file")] + NATIONAL_STEPS

        def work(job: Job):
            self._fetch(job, want)
            if self.lib is None:
                raise click.ClickException("No case file yet. Download it, or start coldmap with --cases.")
            job.step("load")
            self.lib.data()
            job.finish(self.lib.build_national(progress=job.step))
        return self.start("setup", "Preparing coldmap", steps, work)

    def download(self, refresh: bool = False) -> Job:
        if self.mode != "map":
            raise click.ClickException("This session uses your own files; there is nothing to download.")
        want = [k for k, p in zip(MAP_FILES, self.paths()) if refresh or not p.exists()]
        steps = [(f"dl-{k}", f"Download MAP's {LABELS[k]}") for k in want]

        def work(job: Job):
            self._fetch(job, want)
            job.finish({"files": want})
        return self.start("download", "Updating the data" if refresh else "Getting the data", steps, work)

    def national(self) -> Job:
        from .explorer.national import NATIONAL_STEPS
        if self.lib is None:
            raise click.ClickException("Get the data first.")
        lib = self.lib

        def work(job: Job):
            job.step("load")
            lib.data()
            job.finish(lib.build_national(progress=job.step))
        return self.start("national", "Scanning every state", [("load", "Read the case file")] + NATIONAL_STEPS,
                          work)

    def benchmark(self) -> Job:
        """Score the models in use against every known series (bundled and your own)."""
        from .. import plugins
        from ..benchmarks import evaluate_records, load_series
        if self.lib is None:
            raise click.ClickException("Get the data first.")
        lib, on = self.lib, plugins.enabled()
        series = load_series()
        dets = list(on["detectors"]) + ["ensemble"]
        params = {d: on["params"].get(d, {}) for d in on["detectors"]}
        params["ensemble"] = {"detectors": on["detectors"], "params": on["params"]}

        def work(job: Job):
            job.step("load")
            data = lib.data()
            job.step("score", 0, len(series))
            recs = []
            for i, s in enumerate(series, 1):
                recs += evaluate_records(data, dets, params, [s])
                job.step("score", i, len(series))
            for r, s in zip(recs, series):
                r.update(label=s.label, source=s.source)
            caught = {d: {"full": sum(1 for r in recs if (r["results"].get(d) or {}).get("grade") == "full"),
                          "partial": sum(1 for r in recs if (r["results"].get(d) or {}).get("grade") == "partial"),
                          "of": len(recs)} for d in dets}
            out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "detectors": dets,
                   "series": recs, "caught": caught, "stamp": lib.national_stamp}
            path = home() / "research" / "benchmark.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out), encoding="utf-8")
            job.finish({"caught": caught["ensemble"]})
        return self.start("benchmark", "Running the benchmark",
                          [("load", "Read the case file"), ("score", "Score each known series")], work)

    def city_scan(self, periods: bool = False) -> Job:
        """Look for areas within each imported city where killings went unsolved far more often."""
        from .. import cities
        if not cities.all_meta():
            raise click.ClickException("Add city data first.")

        def work(job: Job):
            job.step("scan", 0, 1)
            out = cities.scan(periods=periods, progress=lambda i, n, c: job.step("scan", i, n))
            job.finish({"areas": len(out["areas"])})
        return self.start("cities", "Scanning cities",
                          [("scan", "Compare areas with the rest of each city")], work)

    def city_get_wapo(self) -> Job:
        """Download The Washington Post's homicide data and import it as coarse cells. The download
        holds victims' names, so it goes to a temporary file that is deleted as soon as it's read."""
        import tempfile
        from .. import cities

        def work(job: Job):
            with tempfile.TemporaryDirectory(prefix="coldmap-") as tmp:
                raw = Path(tmp) / "homicide-data.csv"
                job.step("download", 0, None)
                download(cities.wapo_url(), raw, "The Washington Post's data",
                         progress=lambda d, t: job.step("download", d, t))
                text = cities.decode(raw.read_bytes())
                raw.unlink()
            job.step("import", 0, 1)
            meta = cities.add(cities.WAPO_NAME, text, cities.WAPO)
            job.step("import", 1, 1)
            job.finish({"rows": meta["rows"], "cities": meta["cities"]})
        return self.start("cities-get", "Getting The Washington Post's data",
                          [("download", "Download the data (about 4 MB)"),
                           ("import", "Keep only ~1 km cells, year, month, sex and solved")], work)

    def city_action(self, action: str, q: dict, b: dict) -> dict:
        from .. import cities
        if action == "preview":
            return cities.preview(str(b.get("text", "")))
        if action == "add":
            self._idle()
            return cities.add(str(b.get("name", "")), str(b.get("text", "")), str(b.get("source", "")))
        if action == "remove":
            self._idle()
            cities.remove(q.get("slug", ""))
            return {"ok": True}
        raise click.ClickException("Unknown city data action.")

    def cities_view(self) -> dict:
        from .. import cities
        metas = cities.all_meta()
        names = sorted(cities.load().city.unique()) if metas else []
        return {"datasets": metas, "cities": names, "results": cities.results(), "min_shown": cities.MIN_SHOWN,
                "folder": str(cities.folder())}

    def benchmark_view(self) -> dict:
        from ..benchmarks import load_local, load_series
        mine, problems = load_local()
        try:
            last = json.loads((home() / "research" / "benchmark.json").read_text(encoding="utf-8"))
            last["stale"] = bool(self.lib) and last.get("stamp") != self.lib.national_stamp
        except (OSError, ValueError):
            last = None
        return {"built_in": len(load_series(local=False)), "yours": len(mine), "problems": problems,
                "folder": str(home() / "benchmarks"), "last": last}

    # ---- research --------------------------------------------------------------------------
    def flags(self) -> tuple[dict | None, list[dict]]:
        """The ranked national list (with stable ids), cached until a new scan lands."""
        from .research import with_ids
        lib = self.lib
        s = lib.national_summary() if lib else None
        if not s:
            return None, []
        if self._flags and self._flags[0] == s["generated"]:
            return s, self._flags[1]
        rows = with_ids(json.loads((lib.national_dir / "national.json").read_text())["findings"])
        self._flags = (s["generated"], rows)
        return s, rows

    def flag(self, fid: str) -> dict:
        from . import research
        _, rows = self.flags()
        r = next((x for x in rows if x["id"] == fid), None)
        if r is None:
            saved = research.decisions().get(fid)
            if not saved:
                raise KeyError(fid)
            r = {**saved["flag"], "id": fid, "archived": True}
        from .. import datasets
        detail = research.flag_detail(self._data(), r)
        counties = r.get("counties") or ([r["county"]] if r.get("county") else [])
        places = {"county": counties, "state": [r["state"]] if r.get("state") else [],
                  "agency": [r["place"]] if r.get("level") == "agency" else []}
        mine = datasets.for_place(counties, places, (r["start"] - 10, r["end"] + 10))
        return {"flag": r, "decision": research.decisions().get(fid), **detail, "datasets": mine,
                "chance": self.chance_for(r),
                "sections": self.flag_sections(r)}

    def dataset_action(self, action: str, q: dict, b: dict) -> dict:
        from .. import datasets
        try:
            if action == "preview":
                return datasets.preview(str(b.get("text", "")), self._data())
            if action == "check":
                return datasets.check(str(b.get("text", "")), self._data(), b.get("place", ""), b.get("level", ""),
                                      b.get("time", ""))
            if action == "add":
                self._idle()
                return datasets.add(str(b.get("name", "")), str(b.get("text", "")), self._data(), b.get("place", ""),
                                    b.get("level", ""), b.get("time", ""), b.get("keep"),
                                    str(b.get("description", "")), str(b.get("source", "")))
            if action == "remove":
                self._idle()
                datasets.remove(q.get("slug", ""), self.lib._data if self.lib else None)
                return {"ok": True}
        except KeyError as e:
            raise click.ClickException(f"Missing column {e}.") from None
        raise click.ClickException("Unknown dataset action.")

    def views(self) -> list[dict]:
        """App pages and flag sections from plugins that are switched on."""
        from .. import plugins
        from ..views import VIEWS
        off = plugins.views_off()
        return [{**v.describe(), "origin": VIEWS.origin(n)} for n, v in VIEWS if n not in off]

    def view(self, name: str, q: dict) -> dict:
        from .. import plugins
        from ..views import VIEWS
        if name not in VIEWS or name in plugins.views_off():
            raise KeyError(name)
        v = VIEWS.get(name)
        if v.place != "page":
            raise KeyError(name)
        inputs = {}
        for spec in v.inputs:
            raw = q.get(spec["name"], spec.get("default"))
            if spec["type"] == "number" and raw not in (None, ""):
                f = float(raw)
                raw = int(f) if f.is_integer() else f
            inputs[spec["name"]] = raw if raw != "" else None
        return {"view": v.describe(), "blocks": self._run(v, inputs=inputs)}

    def _context(self):
        from . import research
        from ..views import Context
        return Context(self._data(), self.flags()[1], research.decisions())

    def _run(self, v, *args, inputs=None) -> list[dict]:
        """Run a view; a broken plugin shows its error instead of breaking the page."""
        from ..views import render
        try:
            return render(v, self._context(), *args, **(inputs or {}))
        except Exception as e:  # plugin code: report, don't crash
            return [{"type": "note", "tone": "warn", "text": f"This view failed: {type(e).__name__}: {e}"}]

    def flag_sections(self, r: dict) -> list[dict]:
        from .. import plugins
        from ..views import VIEWS
        off = plugins.views_off()
        return [{"name": n, "title": v.title or n, "origin": VIEWS.origin(n), "blocks": self._run(v, r)}
                for n, v in VIEWS if v.place == "flag" and n not in off]

    def _data(self):
        if self.lib is None:
            raise click.ClickException("Get the data first.")
        return self.lib.data()

    def ai_setup(self) -> dict:
        """How to connect an AI assistant to coldmap through MCP, with this computer's paths."""
        import importlib.util
        import sys
        cases, clearance = self.paths()
        env = {"COLDMAP_CASES": str(cases) if cases else "", "COLDMAP_HOME": str(home())}
        if clearance and clearance.exists():
            env["COLDMAP_CLEARANCE"] = str(clearance)
        # The installed coldmap-mcp program, not `python -m`: Claude starts servers from the user's home
        # folder, where a folder named coldmap (a clone of this project) would shadow the package.
        exe = Path(sys.executable).with_name("coldmap-mcp.exe" if os.name == "nt" else "coldmap-mcp")
        local = ({"command": str(exe), "args": [], "env": env} if exe.exists()
                 else {"command": sys.executable, "args": ["-m", "coldmap.interfaces.mcp_server"], "env": env})
        uvx = {"command": "uvx", "args": ["--from", "coldmap[mcp] @ https://github.com/jamesdesantiago/coldmap/"
                                          "archive/refs/tags/v0.5.0.zip", "coldmap-mcp"], "env": env}
        ready = importlib.util.find_spec("mcp") is not None
        server = local if ready else uvx
        from . import connect
        cli = " ".join(["claude mcp add coldmap", *[f'-e {k}="{v}"' for k, v in env.items()], "--",
                        f'"{server["command"]}"' if " " in server["command"] else server["command"],
                        *[f'"{a}"' if " " in a else a for a in server["args"]]])
        return {"sdk_installed": ready, "server": server, "desktop": {"mcpServers": {"coldmap": server}},
                "claude_code": cli, "desktop_status": connect.desktop_status(server),
                "claude_code_installed": shutil.which("claude") is not None,
                "tools": [
                    ["research_flags", "The ranked national list of flags this app shows, with filters"],
                    ["shortlist", "Your kept flags, notes and review status"],
                    ["local_datasets", "Your own datasets about places and times, and their rows for a place"],
                    ["app_views", "Pages your plugins add to the app, run with any inputs"],
                    ["triage_finding", "Why a place was flagged, in plain language"],
                    ["get_cases", "The case rows behind a flag (no names exist in the data)"],
                    ["scan_clusters", "Run any detectors or preset on a state"],
                    ["coverage_gaps", "Where the case file is missing reported murders"],
                    ["data_quality", "Known reporting problems by state"],
                    ["false_alarms", "How often a detector flags shuffled data"],
                    ["benchmark", "Which known, solved series each detector finds"],
                    ["list_plugins", "Installed models, enrichers, fixes and presets"]]}

    # ---- false alarms in every state --------------------------------------------------------------
    def _controls_path(self) -> Path:
        return home() / "research" / "controls.json"

    def controls_saved(self) -> dict | None:
        try:
            out = json.loads(self._controls_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        out["stale"] = bool(self.lib) and out.get("stamp") != self.lib.national_stamp
        return out

    def controls_all(self, runs: int = 2) -> Job:
        """Count flags on shuffled copies of every state's data (women and men), with the models in
        use. Saved after each state, so it can be stopped and picked up where it left off."""
        from .. import plugins
        from ..benchmarks.controls import false_alarms
        from ..core.types import Query
        if self.lib is None:
            raise click.ClickException("Get the data first.")
        lib, on = self.lib, plugins.enabled()
        params = {"ensemble": {"detectors": on["detectors"], "params": on["params"]}}
        stamp = lib.national_stamp
        saved = self.controls_saved()
        out = saved if saved and saved.get("stamp") == stamp and saved.get("runs") == runs else \
            {"stamp": stamp, "runs": runs, "states": {}}
        out.pop("stale", None)

        def work(job: Job):
            job.step("load")
            data = lib.data()
            todo = [(st, sx) for st in sorted(data.cases.state.dropna().unique()) for sx in ("Female", "Male")]
            job.step("measure", 0, len(todo))
            for i, (st, sx) in enumerate(todo, 1):
                if job.stop:
                    job.notes.append(f"Stopped after {i - 1} of {len(todo)}; run it again to continue.")
                    job.finish({"stopped": True})
                    return
                key = f"{st}|{sx}"
                if key not in out["states"]:
                    t = false_alarms(data, Query(state=st, victim_sex=sx), detectors=("ensemble",), params=params,
                                     runs=runs)
                    out["states"][key] = {r["detector"].replace("ensemble: ", "").replace("ensemble", "all"):
                                          {"real": int(r["real_findings"]), "chance": float(r["null_findings"])}
                                          for r in t.to_dict("records")}
                    out["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    self._controls_path().parent.mkdir(parents=True, exist_ok=True)
                    self._controls_path().write_text(json.dumps(out), encoding="utf-8")
                job.step("measure", i, len(todo))
            job.finish({"states": len(out["states"])})
        return self.start("controls", "Measuring false alarms in every state",
                          [("load", "Read the case file"),
                           ("measure", "Scan shuffled copies of each state (women, men)")], work)

    def stop_job(self) -> dict:
        job = self.job
        if job and job.running and job.kind in STOPPABLE:
            job.stop = True
        return {"ok": True}

    def chance_for(self, flag: dict) -> dict | None:
        """How often flags like this one (same state, victims, confidence) appear by chance."""
        saved = self.controls_saved()
        if not saved or flag.get("sex") not in ("Female", "Male"):
            return None
        row = saved["states"].get(f"{flag.get('state')}|{flag['sex']}")
        if not row:
            return None
        c = row.get(flag.get("confidence") or "all") or row.get("all")
        return {**c, "runs": saved["runs"], "stale": saved["stale"], "confidence": flag.get("confidence")}

    def methods(self) -> dict:
        from .. import FIXES
        from ..explain import CONFIDENCE
        return {"confidence": CONFIDENCE,
                "fixes": [{"name": n, "title": f.title, "summary": f.summary, "states": list(f.states)}
                          for n, f in FIXES]}

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
                if r.kind == "view":
                    item.update(obj.describe(), on=name not in plugins.views_off(), origin=r.origin(name))
                    item["summary"] = obj.summary
                if r.kind in ("detector", "enricher"):
                    import inspect
                    item["on"] = name in on[r.kind + "s"]
                    item["locked"] = r.kind == "enricher" and name in plugins.LOCKED_ENRICHERS
                    # The model's own words: its class docstring, else its module's (never one inherited from a base class).
                    doc = (obj.__dict__.get("__doc__") or "").strip()
                    if not doc:
                        mod = inspect.getmodule(obj)
                        doc = (mod.__doc__ or "").strip() if mod and mod.__name__ not in (
                            "coldmap.detectors.base", "coldmap.enrichers", "coldmap.enrichers.builtin") else ""
                    item["doc"] = inspect.cleandoc(doc) if doc else ""
                    if r.kind == "detector":
                        item["tier"] = getattr(obj, "tier", None)
                        mine = on["params"].get(name, {})
                        item["params"] = [{**p, "value": mine.get(p["name"], p["default"]), "changed": p["name"] in mine}
                                          for p in obj.describe()["params"]]
                items.append(item)
            groups.append({"kind": r.kind, "items": items})
        ex_name, _ = plugins.example()
        return {"groups": groups, "files": plugins.files(), "folder": str(plugins.folder()),
                "example": {"file": ex_name, "added": (plugins.folder() / ex_name).exists()},
                "examples": [{"file": f, "title": t, "added": (plugins.folder() / f).exists()}
                             for f, t in plugins.EXAMPLES.items()]}

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
            if action == "param":
                plugins.set_param(q.get("detector", ""), q.get("name", ""), q.get("value") if "value" in q else None)
                return self.plugins_view()
            if action == "reset":
                plugins.reset_params(q.get("detector", ""))
                return self.plugins_view()
            if action == "open":
                return {**self.plugins_view(), "opened": plugins.open_path(q.get("file") or None)}
            if action == "example":
                added = plugins.add(*plugins.example(q.get("name") or None))
            elif action == "starter":
                added = plugins.add(*plugins.starter(q.get("kind", "enricher")))
            elif action == "upload":
                j = json.loads(body or b"{}")
                added = plugins.add(str(j.get("file", "")), str(j.get("text", "")))
            elif action == "fetch":  # download for review; nothing is installed or run
                name, text = fetch_plugin(q.get("url", ""))
                return {"file": name, "text": text, "review": plugins.review(text)}
            elif action == "review":
                j = json.loads(body or b"{}")
                return {"review": plugins.review(str(j.get("text", "")))}
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
        from .. import datasets, plugins
        from . import research
        lib = self.lib
        on = plugins.enabled()
        dec = research.decisions().values()
        counts = {k: sum(1 for d in dec if d.get("status") == k) for k in research.STATUSES}
        return {"version": __version__, "mode": self.mode, "home": str(home()), "notice": NOTICE,
                "data": {"ready": lib is not None, "files": files, "check": self.check},
                "national": _slim(lib.national_summary()) if lib else None,
                "plugins": {"detectors": on["detectors"], "enrichers": on["enrichers"],
                            "files": len(plugins.files())},
                "decisions": counts,
                "datasets": len(datasets.all_meta()),
                "job": self.job.view() if self.job else None}


def _slim(summary: dict | None) -> dict | None:
    """The scan summary without the list of gone flags (served separately at /api/history)."""
    if not summary or not summary.get("history"):
        return summary
    return {**summary, "history": {k: v for k, v in summary["history"].items() if k != "gone_flags"}}


def _handler(app: App):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _origins(self) -> set[str]:
            port = self.server.server_address[1]
            return {f"127.0.0.1:{port}", f"localhost:{port}"}

        def _cookie_name(self) -> str:
            return f"coldmap_key_{self.server.server_address[1]}"  # cookies ignore ports; names don't

        def _has_key(self) -> bool:
            import hmac
            from http.cookies import SimpleCookie
            try:
                jar = SimpleCookie(self.headers.get("Cookie") or "")
            except Exception:
                return False
            got = jar.get(self._cookie_name())
            return bool(got) and hmac.compare_digest(got.value, app.key)

        def _key_gate(self) -> bool:
            """True when the request may go on. A ?key= link (the one coldmap opens) sets the cookie
            and redirects to the same page without the key in its address."""
            import hmac
            u = urlsplit(self.path)
            q = parse_qs(u.query)
            if "key" in q and hmac.compare_digest(q["key"][0], app.key):
                rest = "&".join(f"{k}={v}" for k, vs in q.items() if k != "key" for v in vs)
                self.send_response(303)
                self.send_header("Set-Cookie", f"{self._cookie_name()}={app.key}; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Location", u.path + (f"?{rest}" if rest else ""))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            if self._has_key():
                return True
            self._send(401, "<!doctype html><meta charset=utf-8><title>coldmap</title>"
                            "<body style='font:15px system-ui;padding:40px;max-width:60ch'><h1>Open coldmap from its link</h1>"
                            "<p>For your safety this page only opens from the link coldmap prints in its terminal window "
                            "(it contains a key for this session). Copy that link into this browser, or run <code>coldmap open</code> "
                            "again.</p>", "text/html; charset=utf-8")
            return False

        def _trusted(self, write: bool) -> bool:
            """Requests must name this server as their host, so a web page that re-points its own
            domain at 127.0.0.1 (DNS rebinding) is refused. Writes must also come from this app's
            own page: the Origin, when sent, must be this server, and the X-Coldmap header must be
            set (another site can't set it without a CORS preflight, which is never answered)."""
            if (self.headers.get("Host") or "").lower() not in self._origins():
                return False
            if write:
                origin = (self.headers.get("Origin") or "").lower()
                if origin and origin.removeprefix("http://") not in self._origins():
                    return False
                if self.headers.get("X-Coldmap") != "1":
                    return False
            return True

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            super().end_headers()

        def _send(self, code: int, body: str, ctype: str = "text/plain; charset=utf-8"):
            b = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            if ctype.startswith("text/html"):
                # Only what coldmap itself serves: no other site is contacted, nothing can frame the app.
                self.send_header("Content-Security-Policy",
                                 "default-src 'self'; script-src 'self'; "
                                 "style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; "
                                 "connect-src 'self'; object-src 'none'; base-uri 'none'; "
                                 "form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(b)

        def _json(self, code: int, obj):
            self._send(code, json.dumps(obj), "application/json")

        def _redirect(self, to: str, code: int = 302):
            self.send_response(code)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(n, 26 * 1024 * 1024)) if n else b""
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {}

        def _refuse(self):
            """Every method but GET and POST. The stdlib's HEAD would otherwise answer for files in the
            folder coldmap was started from, past the host check."""
            self.send_response(405)
            self.send_header("Allow", "GET, POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

        def do_POST(self):
            if not self._trusted(write=True):
                return self._send(403, "Forbidden")
            if not self._has_key():
                return self._send(401, "Open coldmap from the link in its terminal window.")
            from . import research
            u = urlsplit(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/setup":
                    return self._json(202, app.setup().view())
                if u.path == "/api/download":
                    return self._json(202, app.download(refresh=q.get("refresh") == "1").view())
                if u.path == "/api/check":
                    return self._json(200, app.check_updates())
                if u.path == "/api/national":
                    return self._json(202, app.national().view())
                if u.path == "/api/benchmark":
                    return self._json(202, app.benchmark().view())
                if u.path == "/api/controls":
                    return self._json(202, app.controls_all().view())
                if u.path == "/api/job/stop":
                    return self._json(200, app.stop_job())
                if u.path == "/api/cities/wapo":
                    return self._json(202, app.city_get_wapo().view())
                if u.path == "/api/cities/scan":
                    return self._json(202, app.city_scan(q.get("periods") == "1").view())
                if u.path.startswith("/api/cities/"):
                    return self._json(200, app.city_action(u.path.rsplit("/", 1)[1], q, self._body()))
                if u.path == "/api/decide":
                    b = self._body()
                    flag = b.get("flag")
                    if flag is None:
                        _, rows = app.flags()
                        flag = next((r for r in rows if r["id"] == b.get("id")), None)
                    return self._json(200, research.decide(str(b.get("id", "")), str(b.get("status", "")), flag,
                                                           b.get("note"), b.get("reviewer")))
                if u.path == "/api/note":
                    b = self._body()
                    return self._json(200, research.note(str(b.get("id", "")), str(b.get("note", ""))))
                if u.path == "/api/forget":
                    research.forget(q.get("id", ""))
                    return self._json(200, {"ok": True})
                if u.path in ("/api/ai/test", "/api/ai/connect", "/api/ai/claude-code"):
                    from . import connect
                    server = app.ai_setup()["server"]
                    if u.path.endswith("test"):
                        return self._json(200, connect.test_server(server))
                    if u.path.endswith("connect"):
                        return self._json(200, {**connect.connect_desktop(server), "status": connect.desktop_status(server)})
                    return self._json(200, connect.claude_code_add(server))
                if u.path.startswith("/api/datasets/"):
                    return self._json(200, app.dataset_action(u.path.rsplit("/", 1)[1], q, self._body()))
                if u.path.startswith("/api/plugins/"):
                    n = int(self.headers.get("Content-Length") or 0)
                    body = self.rfile.read(min(n, 2 * 1024 * 1024)) if n else b""
                    return self._json(200, app.plugin_action(u.path.rsplit("/", 1)[1], q, body))
            except Busy as e:
                return self._json(409, {"error": str(e)})
            except (click.ClickException, ValueError) as e:
                return self._json(400, {"error": getattr(e, "message", None) or str(e)})
            return self._json(404, {"error": "Not found"})

        def do_GET(self):
            from . import research
            if not self._trusted(write=False):
                return self._send(403, "Forbidden")
            if not self._key_gate():
                return
            u = urlsplit(self.path)
            path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
            if path == "/guide.md":
                from .. import plugins
                return self._send(200, plugins.GUIDE.read_text(encoding="utf-8"), "text/markdown; charset=utf-8")
            if path.startswith("/guide/") and path.endswith(".py"):  # the bundled examples' code
                from .. import plugins
                name = path.rsplit("/", 1)[1]
                if name in plugins.EXAMPLES:
                    return self._send(200, plugins.example(name)[1], "text/plain; charset=utf-8")
                return self._send(404, "Not found")
            if path in STATIC:  # the app's scripts, libraries and county shapes: a fixed list, nothing else
                f = STATIC[path]
                ctype = {".json": "application/json", ".css": "text/css; charset=utf-8", ".woff2": "font/woff2"}.get(
                    f.suffix, "text/javascript; charset=utf-8")
                b = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-cache" if path.startswith("/static/") else "max-age=86400")
                self.end_headers()
                self.wfile.write(b)
                return
            if path.startswith(("/static/", "/vendor/")):
                return self._send(404, "Not found")
            if not path.startswith("/api/"):
                return self._send(200, APP_PAGE.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            try:
                if path == "/api/status":
                    return self._json(200, app.status())
                if path == "/api/plugins":
                    return self._json(200, app.plugins_view())
                if path == "/api/plugins/source":
                    from .. import plugins
                    return self._json(200, plugins.source(q.get("kind", ""), q.get("name", "")))
                if path == "/api/flags":
                    summary, rows = app.flags()
                    return self._json(200, {"meta": summary, "flags": rows})
                if path.startswith("/api/flag/"):
                    return self._json(200, app.flag(unquote(path.rsplit("/", 1)[1])))
                if path == "/api/decisions":
                    return self._json(200, research.decisions())
                if path == "/api/export":
                    from .. import __version__
                    d = research.decisions().get(q.get("id", ""))
                    if not d:
                        raise KeyError(q.get("id"))
                    date = _sources().get("cases", {}).get("downloaded")
                    return self._send(200, research.export_markdown(d, __version__, date),
                                      "text/markdown; charset=utf-8")
                if path == "/api/places":
                    _, rows = app.flags()
                    return self._json(200, research.states_table(app._data(), rows, q.get("sex", "Female")))
                if path == "/api/place":
                    _, rows = app.flags()
                    if q.get("county"):
                        return self._json(200, research.county_profile(app._data(), q.get("state", ""),
                                                                       q["county"], q.get("sex", "Female")))
                    return self._json(200, research.state_profile(app._data(), rows, q.get("state", ""),
                                                                  q.get("sex", "Female")))
                if path == "/api/quality":
                    from ..quality import CHECKS, report
                    out = {n: {"summary": CHECKS.get(n).summary, "rows": json.loads(t.to_json(orient="records"))}
                           for n, t in report(app._data(), q.get("state") or None, top=10).items()}
                    return self._json(200, out)
                if path == "/api/views":
                    return self._json(200, app.views())
                if path.startswith("/api/view/"):
                    return self._json(200, app.view(unquote(path.rsplit("/", 1)[1]), q))
                if path == "/api/map":
                    return self._json(200, research.map_counties(app._data(), q.get("sex", "all")))
                if path == "/api/benchmark":
                    return self._json(200, app.benchmark_view())
                if path == "/api/controls":
                    return self._json(200, app.controls_saved() or {})
                if path == "/api/cities":
                    return self._json(200, app.cities_view())
                if path == "/api/cities/grid":
                    from .. import cities
                    return self._json(200, cities.grid(q.get("city", ""), q.get("sex", "all")))
                if path == "/api/history":
                    s = app.lib.national_summary() if app.lib else None
                    return self._json(200, (s or {}).get("history") or {})
                if path == "/api/datasets":
                    from .. import datasets
                    return self._json(200, datasets.all_meta())
                if path == "/api/ai":
                    return self._json(200, app.ai_setup())
                if path == "/api/methods":
                    return self._json(200, app.methods())
            except KeyError:
                return self._json(404, {"error": "Not found. It may be from an older scan."})
            except (click.ClickException, ValueError) as e:
                return self._json(409, {"error": getattr(e, "message", None) or str(e)})
            return self._json(404, {"error": "Not found"})

    return Handler


class _Server(http.server.ThreadingHTTPServer):
    # The stdlib default (SO_REUSEADDR) lets Windows bind a port another server already holds, so
    # the browser would reach that server instead. Refuse, and fall back to a free port.
    allow_reuse_address = False
    daemon_threads = True


def _opener(link: str) -> str:
    """A private local page that forwards to `link`. The browser is started with this file's
    address, not the link, because other users on the computer can read a program's command line
    (ps on Linux and Mac) and the link carries the session key. Like Jupyter's redirect file."""
    import html as _html
    f = home() / "open.html"
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # readable by this user only
    with os.fdopen(fd, "w", encoding="utf-8") as out:
        out.write(f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url={_html.escape(link)}">'
                  f'<title>Opening coldmap</title><p>Opening coldmap… <a href="{_html.escape(link)}">Continue</a></p>')
    return f.as_uri()


def serve(app: App, port: int, open_browser: bool, path: str = "/") -> None:
    handler = _handler(app)
    try:
        httpd = _Server(("127.0.0.1", port), handler)
    except OSError:
        httpd = _Server(("127.0.0.1", 0), handler)  # port busy: pick a free one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    sep = "&" if "?" in path else "?"
    link = url.rstrip("/") + path + f"{sep}key={app.key}"
    click.echo(f"\ncoldmap is running on this computer only. Open it with this link (it carries a key for this session):\n"
               f"  {link}\n"
               f"Everything else happens in the browser. Press Ctrl+C here to stop.")
    if open_browser:
        threading.Timer(0.3, webbrowser.open, args=(_opener(link),)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    finally:
        httpd.server_close()
