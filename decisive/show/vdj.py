"""VirtualDJ on this computer: the DecisiveLink plugin streams every deck's state over UDP (127.0.0.1:9123)."""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass

UDP_PORT = 9123


STALE_S = 1.0  # no packet for this long: VirtualDJ (or the plugin) stopped


FROZEN_S = 0.5  # "playing" but the position hasn't moved for this long: treat as stopped


@dataclass
class Deck:
    deck: int
    file: str
    pos: float
    length: float
    play: bool
    bpm: float
    bpm0: float
    vol: float
    received: float

    def now(self, t: float) -> float:
        """Track position right now: last reported position + time since, at the current playback speed."""
        if not self.play:
            return self.pos
        speed = self.bpm / self.bpm0 if self.bpm0 > 1 else 1.0
        return self.pos + (t - self.received) * speed


class Listener:
    """Receives the plugin's UDP packets; keeps the latest state per deck."""

    def __init__(self, port: int = UDP_PORT):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", port))
        self.decks: dict[int, Deck] = {}
        self.master = 0
        self.last = 0.0
        self.moved: dict[int, tuple[float, float]] = {}  # deck → (last position, when it last changed)
        self.packets = 0  # received, for --health
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            data, _ = self.sock.recvfrom(65535)
            now = time.monotonic()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            self.master, self.last = int(msg.get("master", 0)), now
            self.packets += 1
            decks, seen = {}, set()
            for d in sorted(msg.get("decks", []), key=lambda x: x["deck"]):
                sig = (d["file"], round(d["pos"], 2), round(d["vol"], 3), d["play"])
                if sig in seen:  # a non-existent deck mirroring a real one (VirtualDJ does this for master effects)
                    continue
                seen.add(sig)
                last_pos, changed = self.moved.get(d["deck"], (None, now))
                if last_pos is None or abs(d["pos"] - last_pos) > 1e-3:
                    changed = now
                self.moved[d["deck"]] = (d["pos"], changed)
                playing = bool(d["play"]) and now - changed < FROZEN_S  # "playing" with a frozen position = stalled
                decks[d["deck"]] = Deck(
                    d["deck"], d["file"], d["pos"], d["len"], playing, d["bpm"], d["bpm0"], d["vol"], now
                )
            self.decks = decks

    def alive(self) -> bool:
        return time.monotonic() - self.last < STALE_S
