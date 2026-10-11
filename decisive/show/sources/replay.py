"""A recorded source played back in real time: test live mode and its timing without the DJ software.

The recording is JSON lines, one per reading: {"t": seconds since the start, "master": n, "decks": [...]}
with the decks as `decisive probe --emit` sends them (the DecisiveLink plugin's format, plus title/artist).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from decisive.show.sources.base import Deck, Source


def reading(msg: dict, now: float) -> list[Deck]:
    return [
        Deck(
            d["deck"],
            d.get("file", ""),
            d["pos"],
            d.get("len", 0.0),
            bool(d["play"]),
            d.get("bpm", 0.0),
            d.get("bpm0", 0.0),
            d.get("vol", 1.0),
            now,
            d.get("title", ""),
            d.get("artist", ""),
            d.get("id", ""),
        )
        for d in msg.get("decks", [])
    ]


class Replay(Source):
    label = "Replay"

    def __init__(self, file: str, loop: int = 0):
        super().__init__()
        self.lines = [json.loads(x) for x in Path(file).read_text().splitlines() if x.strip()]
        self.name = f"replay of {Path(file).name}"
        self.loop = bool(loop)
        self.done = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:
            t0 = time.monotonic()
            for msg in self.lines:
                time.sleep(max(0.0, t0 + msg["t"] - time.monotonic()))
                now = time.monotonic()
                self.received(reading(msg, now), int(msg.get("master", 0)), now)
            if not self.loop:
                self.done.set()
                return
