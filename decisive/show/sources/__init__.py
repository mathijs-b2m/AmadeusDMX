"""DJ software integrations: one `Source` per DJ software, picked by name.

    open_source("vdj")                       VirtualDJ on this computer (the DecisiveLink plugin)
    open_source("replay", file="cap.jsonl")  a recording made with `decisive probe NAME --record`

Each integration lives in its own module and is listed in sources.json: its module, its class, what it needs
and how good its position is (see Source.position). The Mac app reads the same list for its Start menu.
Options come from the command line as `--opt key=value` and are passed to the class as keyword arguments.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path

from decisive.show.sources.base import Deck, DeckBook, Event, Source

__all__ = ["SOURCES", "Deck", "DeckBook", "Event", "Source", "open_source"]


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


# sources.json: the one list of integrations, read by the engine and the Mac app alike
SOURCES: dict[str, Entry] = {
    e["name"]: Entry(**{"cls" if k == "class" else k: v for k, v in e.items()})
    for e in json.loads((Path(__file__).parent / "sources.json").read_text())
}


def open_source(name: str, **opts) -> Source:
    if name not in SOURCES:
        raise SystemExit(f"Unknown DJ software '{name}'. Known: {', '.join(SOURCES)}")
    e = SOURCES[name]
    cls = getattr(importlib.import_module(e.module), e.cls)
    return cls(**opts)


def parse_opts(items: list[str] | None) -> dict:
    """['port=50002', 'host=10.0.0.5'] → {'port': 50002, 'host': '10.0.0.5'}."""
    out = {}
    for item in items or []:
        k, _, v = item.partition("=")
        out[k.strip()] = int(v) if v.strip().lstrip("-").isdigit() else v.strip()
    return out
