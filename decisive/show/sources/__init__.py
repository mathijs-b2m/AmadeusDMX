"""DJ software integrations: one `Source` per DJ software, picked by name.

    open_source("vdj")                       VirtualDJ on this computer (the DecisiveLink plugin)
    open_source("replay", file="cap.jsonl")  a recording made with `decisive probe NAME --record`

Each integration lives in its own module and registers itself in SOURCES below: its module, its class, what
it needs and how good its position is (see Source.position). Options come from the command line as
`--opt key=value` and are passed to the class as keyword arguments.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

from decisive.show.sources.base import Deck, DeckBook, Event, Source

__all__ = ["SOURCES", "Deck", "DeckBook", "Event", "Source", "open_source"]


@dataclass(frozen=True)
class Entry:
    module: str
    cls: str
    about: str
    position: str  # exact | beat | metadata
    verified: str  # what has been tested for real, and on what


SOURCES: dict[str, Entry] = {
    "vdj": Entry(
        "decisive.show.vdj",
        "Listener",
        "VirtualDJ on this computer: the DecisiveLink plugin (UDP 9123)",
        "exact",
        "VirtualDJ 8.5 (macOS), live on a real rig",
    ),
    "mixxx": Entry(
        "decisive.show.sources.mixxx",
        "Mixxx",
        "Mixxx: its controller scripting, over a virtual MIDI device (needs python-rtmidi); opts port, library",
        "exact",
        "Mixxx 2.5.6 (macOS): 51 readings/s; engine vs Mixxx's playhead over Decisive Link p95 10 ms, max 13 ms",
    ),
    "replay": Entry(
        "decisive.show.sources.replay",
        "Replay",
        "a recording of any source (decisive probe NAME --record FILE): opt file=FILE",
        "exact",
        "unit tests",
    ),
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
