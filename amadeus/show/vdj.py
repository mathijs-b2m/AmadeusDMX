"""VirtualDJ on this computer: the AmadeusLink plugin streams every deck's state over UDP (127.0.0.1:9123).

A track VirtualDJ streams (Spotify) is reported as "netsearch://sp…": VirtualDJ's database names it, and a local
copy of the same recording is fetched to light it, when switched on (streamed.py, Settings ▸ Integrations).
"""

from __future__ import annotations

import json
import socket
import threading
import time

from amadeus.show.sources.base import FROZEN_S, STALE_S, Deck, DeckBook, Source  # noqa: F401  (Deck: used by link)
from amadeus.show.sources.streamed import Fetcher, VdjStreams, enabled

UDP_PORT = 9123


def plugin_decks(msg: dict, now: float) -> list[Deck]:
    """The decks in one of the plugin's packets (also the format `amadeus probe --emit` sends)."""
    return [
        Deck(d["deck"], d["file"], d["pos"], d["len"], bool(d["play"]), d["bpm"], d["bpm0"], d["vol"], now,
             phase=d.get("phase"))  # phase: from `amadeus probe --emit`, for DJ software synced to Link
        for d in msg.get("decks", [])
    ]  # fmt: skip


class Listener(Source):
    """Receives the plugin's UDP packets; keeps the latest state per deck."""

    label = "VirtualDJ"

    def __init__(self, port: int = UDP_PORT, host: str = "127.0.0.1"):
        super().__init__()
        self.book = DeckBook(dedupe_mirrors=True)  # VirtualDJ reports copies of real decks to master effects
        self.streams = VdjStreams()
        self.fetcher = None  # copies of streamed tracks (None: not needed yet, False: not allowed or no yt-dlp)
        self.said: set[str] = set()
        self.copies: dict[str, str] = {}  # "netsearch://…" → its copy, once there (not looked up 50× a second)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no other program can bind it over ours
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
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
            except ValueError:  # not JSON, or not UTF-8
                continue
            decks = plugin_decks(msg, now)
            for d in decks:
                if d.file.startswith("netsearch://"):
                    self._streamed(d)
            self.received(decks, int(msg.get("master", 0)), now)
            self.master = int(msg.get("master", 0))  # the plugin's own word, even 0

    def _streamed(self, d: Deck):
        """A deck playing a stream: lit from a local copy of the same recording, else listed but dark."""
        path, d.file = d.file, ""
        s = self.streams.find(path) if path not in self.copies else self.streams.known.get(path)
        if s is None:
            self._say(path, f"deck {d.deck}: {path} streams, but VirtualDJ's database doesn't name it yet: dark")
            return
        d.title, d.artist, d.stream, d.stream_info = s.title, s.artist, s.service, s
        if self.fetcher is None:
            self.fetcher = False
            if enabled():
                try:
                    self.fetcher = Fetcher()
                except ImportError:
                    self._say("yt-dlp", "streamed tracks stay dark: yt-dlp isn't installed (Optional packs)")
        if not self.fetcher:
            self._say(path, f"deck {d.deck}: {s.name} streams from {s.service.title()}: dark "
                      "(to light it: Settings ▸ Integrations ▸ Streamed tracks)")  # fmt: skip
            return
        d.file = self.copies.get(path) or self.fetcher.file(s)
        d.copy = "done" if d.file else self.fetcher.status(s)
        if d.file:
            self.copies[path] = d.file
        else:
            self._say(path, f"deck {d.deck}: {s.name} streams from {s.service.title()}: fetching a copy to light it")

    def _say(self, key: str, text: str):
        if key not in self.said:
            self.said.add(key)
            print(f"  {text}", flush=True)

    def close(self):
        self.sock.close()
