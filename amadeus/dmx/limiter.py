"""The brightness limiter: a ceiling on every light's output, for testing and setting up without eye strain.

It limits, it doesn't scale: at 70 %, a light the show plays at 50 % still plays at 50 %, one at 100 % plays at
70 %. Colours keep their hue (a head's emitters come down together). Smoke isn't light and isn't limited.

One value for every process that sends DMX (the live show, the light test, Identify, the setup tools), kept in
config/limiter.json ({"level": 0.7}); the Mac app and the web setup page write it, and a running engine picks a
change up within a quarter of a second. No file, or 100 %: off. For a show it belongs at 100 %.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from amadeus import paths, system

FILE = paths.CONFIG / "limiter.json"
MIN_LEVEL = 0.05  # never fully dark: a limiter at 0 would look like a broken rig
RECHECK_S = 0.25

_cached = {"at": -1e9, "level": 1.0}


def _clamp(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 1.0
    return 1.0 if v != v else min(max(v, MIN_LEVEL), 1.0)  # NaN: off


def use(path) -> None:
    """Keep the level in another file (the tests: never the one set while testing the rig)."""
    global FILE
    FILE = Path(path)
    _cached["at"] = -1e9


def read() -> float:
    """The level on disk, 0.05..1 (1: off)."""
    try:
        return _clamp(json.loads(FILE.read_text(encoding="utf-8")).get("level", 1.0))
    except (OSError, ValueError, AttributeError):
        return 1.0


def level() -> float:
    """The current level, cheap enough for every fixture in every frame."""
    now = time.monotonic()
    if now - _cached["at"] >= RECHECK_S:
        _cached["at"], _cached["level"] = now, read()
    return _cached["level"]


def save(value: float) -> float:
    v = _clamp(value)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"level": round(v, 3)}) + "\n", encoding="utf-8")
    system.replace(tmp, FILE)  # other engines read it meanwhile
    _cached["at"], _cached["level"] = time.monotonic(), v
    return v
