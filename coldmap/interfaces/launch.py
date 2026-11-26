"""`coldmap open`: one command from nothing to the explorer in a browser.

Downloads MAP's public files on first use, builds the explorer for the first state, serves it on
this computer only and opens the browser. Every other state in the file is built the first time
someone picks it from the page's state menu. Builds are cached until the data or coldmap changes.
"""

from __future__ import annotations

import difflib
import html
import http.server
import json
import os
import re
import shutil
import threading
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

import click

DATA_PAGE = "https://www.murderdata.org/p/data-docs.html"
# Download links from MAP's data page (files updated August 2026). If MAP moves them, the
# command prints manual steps; override with COLDMAP_CASES_URL / COLDMAP_CLEARANCE_URL.
MAP_FILES = {
    "cases": ("SHR76_25a.csv", "COLDMAP_CASES_URL",
              "https://www.dropbox.com/scl/fi/1c82yyrg7s7dpfkbsk1hn/SHR76_25a.csv"
              "?rlkey=4nrhqqp729bgk4od2xnyu1ukm&dl=1"),
    "clearance": ("UCR65_25.csv", "COLDMAP_CLEARANCE_URL",
                  "https://www.dropbox.com/scl/fi/4y2a6yy0pv4lxffm7sa4v/UCR65_25.csv"
                  "?rlkey=jhs7ktqhb9h3dnml1wety4nhb&dl=1"),
}


def home() -> Path:
    """Where coldmap keeps downloaded data and built sites (COLDMAP_HOME, default ~/.coldmap)."""
    return Path(os.environ.get("COLDMAP_HOME") or Path.home() / ".coldmap")


def download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "coldmap"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
        size = int(r.headers.get("Content-Length") or 0) or None
        with click.progressbar(length=size, label=label, show_pos=size is None) as bar:
            while chunk := r.read(1 << 20):
                out.write(chunk)
                bar.update(len(chunk))
    head = part.read_bytes()[:200].lower()
    if head.lstrip().startswith((b"<!doctype", b"<html")):
        part.unlink()
        raise OSError("the link returned a web page instead of the data file")
    part.replace(dest)


def ensure_data(refresh: bool = False) -> tuple[Path, Path | None]:
    """Return (cases, clearance) paths, downloading MAP's files if they aren't here yet.
    The clearance file is optional: if it fails, the explorer still builds without coverage."""
    data = home() / "data"
    paths = {}
    for key, (name, env, url) in MAP_FILES.items():
        dest = data / name
        if refresh or not dest.exists():
            click.echo(f"Downloading {name} from the Murder Accountability Project (first run only)...")
            try:
                download(os.environ.get(env) or url, dest, name)
            except Exception as e:  # network, moved link, disk
                if key == "clearance":
                    click.echo(f"  Skipped the clearance file ({e}). Coverage figures will be missing.")
                    paths[key] = None
                    continue
                raise click.ClickException(
                    f"Couldn't download {name}: {e}\n\n"
                    f"Download it yourself from {DATA_PAGE} (the CSV link next to "
                    f"'Supplementary Homicide Report'), then run:\n"
                    f'  coldmap open "<state>" --cases path/to/{name}')
        paths[key] = dest
    return paths["cases"], paths["clearance"]


def _stamp(*files: Path | None) -> str:
    from .. import __version__
    from .explorer import build as b
    parts = [__version__, str(Path(b.__file__).with_name("index.html").stat().st_mtime_ns)]
    parts += [f"{f.resolve()}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files if f]
    return "|".join(parts)


def slugify(state: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", state.lower()).strip("-")


def _match_state(state: str, states: list[str]) -> str:
    by_lower = {s.lower(): s for s in states}
    if state.lower() in by_lower:
        return by_lower[state.lower()]
    near = difflib.get_close_matches(state, states, n=3, cutoff=0.6)
    hint = f" Did you mean {' or '.join(near)}?" if near else f" States in the file: {', '.join(sorted(states))}."
    raise click.ClickException(f"No state called {state!r} in the data.{hint}")


class Library:
    """Explorer sites for every state in one case file, built on first request and cached
    in COLDMAP_HOME/sites until the data or coldmap changes. The case file is loaded at most
    once per run, and only when something needs building."""

    def __init__(self, cases: Path, clearance: Path | None = None, rebuild: bool = False):
        self.cases = Path(cases)
        self.clearance = Path(clearance) if clearance else None
        self.rebuild = rebuild
        self.root = home() / "sites"
        self.stamp = _stamp(self.cases, self.clearance)
        self._data = None
        self._states: list[str] | None = None
        self._lock = threading.RLock()
        self._fresh: set[str] = set()  # built during this run (so --rebuild applies once per state)

    def data(self):
        with self._lock:
            if self._data is None:
                from .. import load
                click.echo("Loading the case file (this takes a minute for the national file)...")
                self._data = load(self.cases, clearance_path=self.clearance)
            return self._data

    def states(self) -> list[str]:
        """Every state in the case file. Cached next to the sites so a warm start skips loading."""
        if self._states is not None:
            return self._states
        cache = self.root / "states.json"
        try:
            saved = json.loads(cache.read_text())
            if saved["stamp"] == self.stamp:
                self._states = saved["states"]
                return self._states
        except (OSError, ValueError, KeyError):
            pass
        d = self.data().cases
        self._states = sorted(d.loc[d.county.notna(), "state"].dropna().unique().tolist())
        self.root.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"stamp": self.stamp, "states": self._states}))
        return self._states

    def resolve(self, state: str) -> str:
        return _match_state(state, self.states())

    def site(self, state: str) -> Path:
        return self.root / slugify(state)

    def is_built(self, state: str) -> bool:
        if self.rebuild and state not in self._fresh:
            return False
        f = self.site(state) / ".coldmap-build"
        return f.exists() and f.read_text() == self.stamp

    def build(self, state: str) -> Path:
        """Build (or reuse) the explorer for a state and return its folder."""
        state = self.resolve(state)
        with self._lock:
            out = self.site(state)
            if self.is_built(state):
                return out
            from .explorer.build import build_site
            data = self.data()
            click.echo(f"Searching {state} for clusters...")
            if out.exists():
                shutil.rmtree(out)
            build_site(data, state, out)
            (out / ".coldmap-build").write_text(self.stamp)
            self._fresh.add(state)
            return out


def prepare(state: str, cases: Path, clearance: Path | None, rebuild: bool = False) -> Path:
    """Build (or reuse) one state's explorer and return its folder."""
    return Library(cases, clearance, rebuild).build(state)


_BUILDING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Building {state} · coldmap</title>
<style>:root{{color-scheme:light dark}}body{{margin:0;min-height:100vh;display:grid;place-items:center;
font:15px/1.5 Inter,system-ui,sans-serif;background:light-dark(#eef1f4,#0b0f13);color:light-dark(#111820,#e6ebef)}}
main{{max-width:46ch;padding:24px}}h1{{font-size:22px;margin:0 0 6px}}p{{margin:0;color:light-dark(#5b6773,#8694a1)}}
a{{color:light-dark(#276887,#5fb0d6)}}</style>
</head><body><main role="status" aria-live="polite"><h1 id="h">Building {state}</h1><p id="p">Searching every
county for clusters. This takes a few seconds, longer the first time while the case file loads.</p></main>
<script>fetch("/build?state={q}",{{method:"POST"}})
.then(r=>r.ok?location.reload():r.text().then(t=>{{throw new Error(t)}}))
.catch(e=>{{document.getElementById("h").textContent="Couldn't build {state}";
document.getElementById("p").innerHTML="";document.getElementById("p").append(e.message+" ");
const a=document.createElement("a");a.href="/";a.textContent="Back to the explorer";document.getElementById("p").append(a)}})</script>
</body></html>"""


def _handler(lib: Library, first: str):
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

        def _redirect(self, to: str, code: int = 302):
            self.send_response(code)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            u = urlsplit(self.path)
            if u.path != "/build":
                return self._send(404, "Not found")
            state = (parse_qs(u.query).get("state") or [""])[0]
            try:
                lib.build(state)
            except click.ClickException as e:
                return self._send(400, e.message)
            except Exception as e:  # report it and keep serving the other states
                return self._send(500, f"Build failed: {e}")
            self._send(200, "ok")

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/":
                return self._redirect(f"/{slugify(first)}/")
            if path == "/states.json":
                body = {"states": [{"name": s, "slug": slugify(s)} for s in lib.states()]}
                return self._send(200, json.dumps(body), "application/json")
            slug, sep, rest = unquote(path).lstrip("/").partition("/")
            state = next((s for s in lib.states() if slugify(s) == slug), None)
            if state is None:
                return self._send(404, "No such state. Open / to go back to the explorer.")
            if not sep:
                return self._redirect(f"/{slug}/", 301)
            if not lib.is_built(state):
                return self._send(200, _BUILDING.format(state=html.escape(state), q=quote(state)),
                                  "text/html; charset=utf-8")
            self.directory = str(lib.site(state))
            self.path = "/" + rest
            return super().do_GET()

    return Handler


def serve(lib: Library, state: str, port: int, open_browser: bool) -> None:
    handler = _handler(lib, state)
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)  # port busy: pick a free one
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    click.echo(f"\nExplorer running at {url}  (only on this computer)\n"
               f"Switch states from the menu at the top of the page. Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        click.echo("\nStopped.")
    finally:
        httpd.server_close()
