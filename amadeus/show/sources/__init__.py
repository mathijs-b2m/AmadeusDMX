"""DJ software integrations: one `Source` per DJ software, picked by name.

    open_source("vdj")                       VirtualDJ on this computer (the AmadeusLink plugin)
    open_source("replay", file="cap.jsonl")  a recording made with `amadeus probe NAME --record`

Each integration lives in its own module and is listed in sources.json: its module, its class, what it needs
and how good its position is (see Source.position). The Mac and Windows apps read the same list for their Start
menu; an entry's "windows" block says what differs there (about, verified, waiting), applied here on Windows.
Options come from the command line as `--opt key=value` and are passed to the class as keyword arguments,
except `latency` (ms, every source): how much later than reported the DJ software is heard (its audio buffer).
Settings kept per integration in config/integrations.json (the Mac app's Settings ▸ Integrations writes them)
come first; `--opt` on the command line overrides them.
"""

from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from amadeus import paths
from amadeus.show.sources.base import Deck, DeckBook, Event, Source

__all__ = ["SOURCES", "Deck", "DeckBook", "Event", "Source", "open_source", "settings"]

SETTINGS = paths.CONFIG / "integrations.json"


@dataclass(frozen=True)
class Entry:
    name: str
    app: str  # the DJ software's name, for people
    module: str
    cls: str
    about: str
    position: str  # exact | beat | metadata
    verified: str  # what has been tested for real, and on what
    menu: bool = True  # offered in the Mac app's Start menu
    waiting: str = ""  # what to do while the show waits for it (the Mac app shows it)
    windows: dict = field(default_factory=dict)  # what differs on Windows: about, verified, waiting


def load(path: Path = Path(__file__).parent / "sources.json", windows: bool = sys.platform == "win32") -> dict:
    """sources.json: the one list of integrations, read by the engine and the apps alike."""
    out = {}
    for e in json.loads(path.read_text(encoding="utf-8")):
        fields = {"cls" if k == "class" else k: v for k, v in e.items()}
        if windows:
            fields.update(e.get("windows", {}))
        out[e["name"]] = Entry(**fields)
    return out


SOURCES: dict[str, Entry] = load()


def settings(name: str, path: Path | None = None) -> dict:
    """One integration's saved settings ({"djay": {"streamed": true}} → {"streamed": 1}); {} when none."""
    try:
        saved = json.loads((path or SETTINGS).read_text(encoding="utf-8")).get(name) or {}
    except (OSError, ValueError, AttributeError):
        return {}
    plain = {k: v for k, v in saved.items() if isinstance(v, bool | int | float | str)}
    return {k: int(v) if isinstance(v, bool) else v for k, v in plain.items()}


def open_source(name: str, **opts) -> Source:
    if name not in SOURCES:
        raise SystemExit(f"Unknown DJ software '{name}'. Known: {', '.join(SOURCES)}")
    e = SOURCES[name]
    opts = {**settings(name), **opts}  # the command line wins
    latency = float(opts.pop("latency", 0))
    src = getattr(importlib.import_module(e.module), e.cls)(**opts)
    src.latency = latency / 1000
    return src


def parse_opts(items: list[str] | None) -> dict:
    """['port=50002', 'host=10.0.0.5'] → {'port': 50002, 'host': '10.0.0.5'}."""
    out = {}
    for item in items or []:
        k, _, v = item.partition("=")
        out[k.strip()] = int(v) if v.strip().lstrip("-").isdigit() else v.strip()
    return out
