"""Claude Desktop starts `amadeus mcp` itself: its config file names the server (`amadeus mcp --claude-desktop on`).

The entry runs this same Python and engine with this same data folder, so it is written by the engine the apps
run (Settings › Integrations › Your AI assistant), and written again when the app finds it out of date (the app
moved, an update put the engine elsewhere). The rest of Claude's config is kept as it is; the file as it was
before the first change is kept beside it (.before-amadeus). A config that isn't valid JSON is left alone.

Where Claude Desktop keeps it: macOS ~/Library/Application Support/Claude; Windows %APPDATA%\\Claude, or for the
Microsoft Store app the same folder inside its package (%LOCALAPPDATA%\\Packages\\Claude_…\\LocalCache\\Roaming).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from amadeus import paths

NAME = "amadeus-dmx"
FILE = "claude_desktop_config.json"
# what the apps hand the engine that it needs as well when Claude starts it (Workspace.environment)
PASS_ON = ("PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE")


def folders(env=None, home: Path | None = None, windows: bool = sys.platform == "win32") -> list[Path]:
    """Claude Desktop's config folders on this computer: the ones that exist, else where it would make one."""
    env = os.environ if env is None else env
    home = home or Path.home()
    if not windows:
        return [home / "Library" / "Application Support" / "Claude"]
    roaming = Path(env.get("APPDATA") or home / "AppData" / "Roaming") / "Claude"
    local = Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local")
    store = (
        sorted((local / "Packages").glob("Claude_*/LocalCache/Roaming/Claude")) if (local / "Packages").exists() else []
    )
    found = [p for p in [roaming, *store] if p.is_dir()]
    return found or [roaming]


def entry(env=None) -> dict:
    """The server entry for this engine: its Python, its code and its data folder."""
    env = os.environ if env is None else env
    root, data = str(paths.ROOT), str(paths.DATA)
    extra = {k: env[k] for k in PASS_ON if env.get(k)}
    return {
        "command": sys.executable,
        "args": ["-m", "amadeus", "mcp"],
        "env": {"PYTHONPATH": root, "AMADEUS_ROOT": root, "AMADEUS_DATA": data, "PYTHONIOENCODING": "utf-8", **extra},
    }


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8") or "{}")  # not JSON: raises, nothing is written
    if not isinstance(doc, dict):
        raise ValueError(f"{path} is not a JSON object")
    return doc


def _write(path: Path, doc: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = path.with_name(FILE + ".before-amadeus")
    if path.exists() and not keep.exists():
        keep.write_bytes(path.read_bytes())
    tmp = path.with_name(FILE + ".amadeus-tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def status(env=None, where: list[Path] | None = None) -> dict:
    """installed: Claude Desktop has a config folder here; on: our server is in its config; current: as this
    engine would write it."""
    where = folders(env) if where is None else where
    want, on, current, problem = entry(env), False, True, ""
    for folder in where:
        try:
            servers = _read(folder / FILE).get("mcpServers") or {}
        except (OSError, ValueError) as e:
            problem = f"Claude Desktop's config can't be read: {e}"
            continue
        mine = servers.get(NAME)
        on = on or mine is not None
        current = current and mine == want
    return {
        "installed": any(f.is_dir() for f in where),
        "on": on,
        "current": on and current,
        "config": str(where[0] / FILE),
        "problem": problem,
    }


def switch(on: bool, env=None, where: list[Path] | None = None) -> dict:
    """Put our server into Claude Desktop's config (every copy of it), or take it out."""
    where = folders(env) if where is None else where
    for folder in where:
        path = folder / FILE
        doc = _read(path)
        servers = doc.get("mcpServers") if isinstance(doc.get("mcpServers"), dict) else {}
        if on:
            servers[NAME] = entry(env)
            doc["mcpServers"] = servers
        elif NAME in servers:
            del servers[NAME]
            if not servers:
                doc.pop("mcpServers", None)
        else:
            continue
        _write(path, doc)
    return status(env, where)
