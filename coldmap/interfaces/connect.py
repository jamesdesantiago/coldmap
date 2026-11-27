"""Connect an AI assistant to coldmap with one click: test the MCP server, add it to Claude
Desktop's config (finding the file, backing it up, repairing it if it holds more than one JSON
object), and add it to Claude Code. Used by the app's AI assistants page."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

NAME = "coldmap"


# ---- Claude Desktop ----------------------------------------------------------------------------
def desktop_candidates() -> list[Path]:
    """Where Claude Desktop keeps claude_desktop_config.json on this computer, most likely first."""
    home = Path.home()
    out: list[Path] = []
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        # Current Claude Desktop builds keep settings in %LOCALAPPDATA%\Claude-Data\claude_<id> (its
        # README: "your settings, your sign-in, and your Cowork tasks").
        out += sorted((local / "Claude-Data").glob("claude_*/claude_desktop_config.json"))
        out += [p / "claude_desktop_config.json" for p in sorted((local / "Claude-Data").glob("claude_*")) if p.is_dir()]
        # Older Microsoft Store builds used a per-app folder.
        out += sorted((local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude/claude_desktop_config.json"))
        out += [p / "claude_desktop_config.json" for p in (local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude")]
        out.append(appdata / "Claude" / "claude_desktop_config.json")
    elif sys.platform == "darwin":
        out.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    else:
        out.append(Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "Claude" / "claude_desktop_config.json")
    seen, uniq = set(), []
    for p in out:
        if str(p).lower() not in seen:
            seen.add(str(p).lower())
            uniq.append(p)
    return uniq


def desktop_path() -> Path:
    """The config file to use: the first one that exists, in the order Claude Desktop builds
    prefer, else where the installed app will look."""
    cands = desktop_candidates()
    existing = [p for p in cands if p.exists()]
    if existing:
        return existing[0]
    for p in cands:  # the app's folder exists but has no config yet
        if p.parent.exists():
            return p
    return cands[-1]


def load_lenient(text: str) -> tuple[dict, bool]:
    """Read a config, repairing the common mistake of pasting a second {...} after the first:
    every top-level object is merged. Returns (config, repaired)."""
    text = text.strip()
    if not text:
        return {}, False
    try:
        obj = json.loads(text)
        if not isinstance(obj, dict):
            raise ValueError("The config file should hold one JSON object.")
        return obj, False
    except json.JSONDecodeError:
        pass
    dec, i, merged, n = json.JSONDecoder(), 0, {}, 0
    while i < len(text):
        while i < len(text) and text[i] in " \t\r\n,":
            i += 1
        if i >= len(text):
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except json.JSONDecodeError as e:
            raise ValueError(f"Claude's config file isn't valid JSON (line {e.lineno}, column {e.colno}) and "
                             "couldn't be repaired automatically. Open it from Claude: Settings > Developer > "
                             "Edit Config.") from None
        if not isinstance(obj, dict):
            raise ValueError("The config file should hold JSON objects.")
        for k, v in obj.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        n += 1
    return merged, n > 1


def desktop_status(server: dict) -> dict:
    p = desktop_path()
    st = {"path": str(p), "exists": p.exists(), "candidates": [str(c) for c in desktop_candidates()],
          "connected": False, "current": False, "problem": None}
    if p.exists():
        try:
            cfg, repaired = load_lenient(p.read_text(encoding="utf-8"))
            mine = (cfg.get("mcpServers") or {}).get(NAME)
            st["connected"] = mine is not None
            st["current"] = mine == server
            if repaired:
                st["problem"] = "The file holds more than one JSON object, so Claude can't read it. Connecting fixes it."
        except (OSError, ValueError) as e:
            st["problem"] = str(e)
    return st


def connect_desktop(server: dict) -> dict:
    """Add (or update) coldmap in Claude Desktop's config. The old file is kept as a backup."""
    p = desktop_path()
    backup, repaired, cfg = None, False, {}
    if p.exists():
        cfg, repaired = load_lenient(p.read_text(encoding="utf-8"))
        backup = p.with_name(f"claude_desktop_config.backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
        shutil.copy2(p, backup)
    servers = cfg.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    servers[NAME] = server
    cfg["mcpServers"] = servers
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return {"path": str(p), "backup": str(backup) if backup else None, "repaired": repaired}


# ---- testing the server ------------------------------------------------------------------------
def test_server(server: dict, timeout: float = 60) -> dict:
    """Start the MCP server the way Claude would (from the home folder), list its tools and ask
    it for one flag. Returns {"ok", "tools", "flags", "error"}."""
    env = {**os.environ, **server.get("env", {})}
    try:
        proc = subprocess.Popen([server["command"], *server.get("args", [])], cwd=str(Path.home()), env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": f"Couldn't start the server: {e}"}
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [lines.put(x) for x in proc.stdout], daemon=True).start()
    err: list[str] = []
    threading.Thread(target=lambda: [err.append(x) for x in proc.stderr], daemon=True).start()

    def ask(msg_id, method, params=None):
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = json.loads(lines.get(timeout=max(0.1, end - time.time())))
            except queue.Empty:
                break
            except ValueError:
                continue
            if msg.get("id") == msg_id:
                return msg
        raise TimeoutError

    try:
        ask(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "coldmap-check", "version": "1"}})
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        tools = [t["name"] for t in ask(2, "tools/list")["result"]["tools"]]
        res = ask(3, "tools/call", {"name": "research_flags", "arguments": {"top": 1}})
        text = res.get("result", {}).get("content", [{}])[0].get("text", "{}")
        try:
            matching = json.loads(text).get("matching")
        except ValueError:
            matching = None
        return {"ok": True, "tools": tools, "flags": matching}
    except (TimeoutError, KeyError, BrokenPipeError, OSError):
        time.sleep(0.3)
        tail = "".join(err)[-600:].strip()
        return {"ok": False, "error": tail or "The server didn't answer in time."}
    finally:
        proc.kill()


# ---- Claude Code ---------------------------------------------------------------------------------
def claude_code_add(server: dict) -> dict:
    exe = shutil.which("claude")
    if not exe:
        return {"ok": False, "missing": True, "error": "Claude Code isn't installed on this computer (no `claude` command)."}
    subprocess.run([exe, "mcp", "remove", "--scope", "user", NAME], capture_output=True, text=True, timeout=60)
    cmd = [exe, "mcp", "add", "--scope", "user", NAME]
    for k, v in server.get("env", {}).items():
        cmd += ["-e", f"{k}={v}"]
    cmd += ["--", server["command"], *server.get("args", [])]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip()
    return {"ok": r.returncode == 0, "output": out[-800:]}
