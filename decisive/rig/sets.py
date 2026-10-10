"""Sets: several rigs side by side (your real setup, a big test rig, a venue), one of them active.

Each set is a rig file `config/sets/<name>.json`; `config/active-set` holds the name of the active one.
Commands use the active set unless given --set NAME (or --rig FILE). A running show keeps the set it
was started with. The first time, `config/sets` starts with copies of the example sets (examples/sets).
An older single `config/rig.json` becomes the set "home" on first use.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from decisive import paths

SETS_DIR = paths.CONFIG / "sets"
ACTIVE_FILE = paths.CONFIG / "active-set"
LEGACY = paths.CONFIG / "rig.json"


EXAMPLE_SETS = paths.EXAMPLES / "sets"
FIRST_SET = "showcase"


def _migrate():
    if not SETS_DIR.exists() and LEGACY.exists():
        SETS_DIR.mkdir(parents=True)
        shutil.move(str(LEGACY), SETS_DIR / "home.json")
        ACTIVE_FILE.write_text("home\n")
    if not any(SETS_DIR.glob("*.json")) and EXAMPLE_SETS.exists():  # a fresh checkout: start with the examples
        SETS_DIR.mkdir(parents=True, exist_ok=True)
        for example in EXAMPLE_SETS.glob("*.json"):
            shutil.copy(example, SETS_DIR / example.name)
        if not ACTIVE_FILE.exists() and (SETS_DIR / f"{FIRST_SET}.json").exists():
            ACTIVE_FILE.write_text(FIRST_SET + "\n")


def names() -> list[str]:
    _migrate()
    return sorted(p.stem for p in SETS_DIR.glob("*.json"))


def active_name() -> str:
    _migrate()
    name = ACTIVE_FILE.read_text().strip() if ACTIVE_FILE.exists() else ""
    available = names()
    if name not in available:
        name = "home" if "home" in available else (available[0] if available else "home")
    return name


def path(name: str | None = None) -> Path:
    return SETS_DIR / f"{name or active_name()}.json"


def resolve(rig: Path | None) -> Path:
    """--rig if given, else the active set's file."""
    return rig if rig is not None else path()


def switch(name: str) -> Path:
    if name not in names():
        raise SystemExit(f"No set '{name}'. Sets: {', '.join(names())}")
    ACTIVE_FILE.write_text(name + "\n")
    return path(name)


def safe_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9_-]+", "-", name.strip().lower()).strip("-")
    if not n:
        raise ValueError("empty set name")
    return n


def save(name: str, rig: dict) -> Path:
    SETS_DIR.mkdir(parents=True, exist_ok=True)
    p = path(safe_name(name))
    p.write_text(json.dumps(rig, indent=2))
    return p


def info() -> list[dict]:
    """Name, fixture count and a short summary of every set."""
    from decisive.dmx import outputs

    out = []
    for n in names():
        try:
            rig = json.loads(path(n).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        kinds: dict[str, int] = {}
        for f in rig.get("fixtures", []):
            kinds[f["fixture"]] = kinds.get(f["fixture"], 0) + 1
        out.append(
            {
                "name": n,
                "active": n == active_name(),
                "fixtures": len(rig.get("fixtures", [])),
                "summary": ", ".join(f"{c}× {k.split('/')[-1]}" for k, c in kinds.items()),
                "artnet": rig.get("artnet", {}).get("ip"),
                "output": outputs.describe(rig),
                "description": rig.get("description", ""),
            }
        )
    return out
