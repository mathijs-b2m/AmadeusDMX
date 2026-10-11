"""VirtualDJ on this computer: the DecisiveLink plugin streams every deck's state over UDP (127.0.0.1:9123)."""

from __future__ import annotations

import json
import socket
import threading
import time

from decisive.show.sources.base import FROZEN_S, STALE_S, Deck, DeckBook, Source  # noqa: F401  (Deck: used by link)

UDP_PORT = 9123


def plugin_decks(msg: dict, now: float) -> list[Deck]:
    """The decks in one of the plugin's packets (also the format `decisive probe --emit` sends)."""
    return [
        Deck(d["deck"], d["file"], d["pos"], d["len"], bool(d["play"]), d["bpm"], d["bpm0"], d["vol"], now,
             phase=d.get("phase"))  # phase: from `decisive probe --emit`, for DJ software synced to Link
        for d in msg.get("decks", [])
    ]  # fmt: skip


class Listener(Source):
    """Receives the plugin's UDP packets; keeps the latest state per deck."""

    label = "VirtualDJ"

    def __init__(self, port: int = UDP_PORT, host: str = "127.0.0.1"):
        super().__init__()
        self.book = DeckBook(dedupe_mirrors=True)  # VirtualDJ reports copies of real decks to master effects
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except OSError:  # closed
                return
            now = time.monotonic()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue
            self.received(plugin_decks(msg, now), int(msg.get("master", 0)), now)
            self.master = int(msg.get("master", 0))  # the plugin's own word, even 0

    def close(self):
        self.sock.close()
