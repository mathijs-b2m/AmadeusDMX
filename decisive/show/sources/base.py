"""What every DJ software integration has in common: decks, their events, and how alive the source is.

A source (VirtualDJ's plugin, a DJ laptop over Decisive Link, Serato, StageLinQ, …) keeps `decks` up to
date from its own thread. Live mode only reads `decks`, `master`, `last`, `packets` and `alive()`; how a
source gets its numbers is its own business. `DeckBook` turns raw readings into decks the same way for all
of them: mirrored decks dropped, a "playing" deck whose position stopped moving counted as stopped, and
events (track loaded, started, stopped, seek, loop) derived from one reading to the next.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

STALE_S = 1.0  # no reading for this long: the DJ software (or its plugin) stopped
FROZEN_S = 0.5  # "playing" but the position hasn't moved for this long: treat as stopped
SEEK_S = 0.25  # the position is this far from where it should be: the DJ jumped
LOOP_MATCH_S = 0.05  # two backward jumps landing this close together: a loop


@dataclass
class Deck:
    deck: int
    file: str  # the track on this computer ("" while unknown: the deck is listed but not lit)
    pos: float  # seconds, at `received`
    length: float
    play: bool
    bpm: float
    bpm0: float
    vol: float  # what reaches the master: channel fader × crossfader, 0..1
    received: float  # time.monotonic() of the reading
    title: str = ""
    artist: str = ""
    track_id: str = ""  # the DJ software's own id for the track, when it has one
    rate: float = 0.0  # playback speed when the DJ software reports it (else from the tempo: bpm / bpm0)

    def now(self, t: float) -> float:
        """Track position right now: last reported position + time since, at the current playback speed."""
        if not self.play:
            return self.pos
        return self.pos + (t - self.received) * self.speed

    @property
    def speed(self) -> float:
        if self.rate:
            return self.rate
        return self.bpm / self.bpm0 if self.bpm0 > 1 and self.bpm > 1 else 1.0


@dataclass
class Event:
    t: float  # time.monotonic()
    deck: int
    kind: str  # track_loaded | playback_started | playback_stopped | seek | loop
    data: dict = field(default_factory=dict)
    n: int = 0  # running number: a reader picks up where it left off


class DeckBook:
    """Readings → decks and events. `update` takes every deck of one reading (a packet, a poll)."""

    def __init__(self, dedupe_mirrors: bool = False):
        self.dedupe = dedupe_mirrors
        self.decks: dict[int, Deck] = {}
        self.moved: dict[int, tuple] = {}  # deck → (last position, when it last changed, its reading's time)
        self.back: dict[int, float] = {}  # deck → where its last backward jump landed (loop detection)
        self.events: deque[Event] = deque(maxlen=256)
        self.count = 0

    def update(self, readings: list[Deck], now: float | None = None) -> dict[int, Deck]:
        now = time.monotonic() if now is None else now
        decks, seen = {}, set()
        for d in sorted(readings, key=lambda x: x.deck):
            if self.dedupe:
                sig = (d.file, round(d.pos, 2), round(d.vol, 3), d.play)
                if sig in seen:  # a non-existent deck mirroring a real one (VirtualDJ does this)
                    continue
                seen.add(sig)
            last_pos, changed, at = self.moved.get(d.deck, (None, now, None))
            if last_pos is None or abs(d.pos - last_pos) > 1e-3 or d.received == at:
                changed = now  # moved, or the same reading again (another deck's news): not frozen
            self.moved[d.deck] = (d.pos, changed, d.received)
            d.play = d.play and now - changed < FROZEN_S  # "playing" with a frozen position = stalled
            self._events(self.decks.get(d.deck), d)
            decks[d.deck] = d
        self.decks = decks
        return decks

    def _events(self, old: Deck | None, d: Deck):
        ident = d.track_id or d.file or f"{d.artist} - {d.title}"
        if old is None or ident != (old.track_id or old.file or f"{old.artist} - {old.title}"):
            if ident.strip(" -"):
                self.emit(d.deck, "track_loaded", file=d.file, title=d.title, artist=d.artist, length=d.length)
            self.back.pop(d.deck, None)
            if d.play:
                self.emit(d.deck, "playback_started", pos=round(d.pos, 3))
            return
        if d.play != old.play:
            self.emit(d.deck, "playback_started" if d.play else "playback_stopped", pos=round(d.pos, 3))
        expected = old.now(d.received)
        jump = d.pos - expected
        if abs(jump) > SEEK_S and (old.play or abs(d.pos - old.pos) > SEEK_S):
            self.emit(d.deck, "seek", frm=round(expected, 3), to=round(d.pos, 3))
            if jump < 0:
                landed = self.back.get(d.deck)
                if landed is not None and abs(landed - d.pos) < LOOP_MATCH_S:
                    self.emit(d.deck, "loop", start=round(d.pos, 3), length=round(expected - d.pos, 3))
                self.back[d.deck] = d.pos

    def emit(self, deck: int, kind: str, **data):
        self.count += 1
        self.events.append(Event(time.monotonic(), deck, kind, data, self.count))


class Source:
    """A DJ software integration. Subclasses fill `decks` (via a DeckBook) from their own thread."""

    label = "DJ software"  # for messages: "VirtualDJ silent: lights dark"
    # how good its position is: "exact" (the playhead itself), "beat" (tempo and phase, not where in the
    # track), "metadata" (which track only): live mode lights only decks with an exact position
    position = "exact"

    def __init__(self):
        self.book = DeckBook()
        self.master = 0
        self.last = 0.0
        self.packets = 0
        self.name = self.label

    @property
    def decks(self) -> dict[int, Deck]:
        return self.book.decks

    @property
    def events(self) -> deque[Event]:
        return self.book.events

    def received(self, readings: list[Deck], master: int = 0, now: float | None = None):
        """One reading from the DJ software: every deck it reported."""
        now = time.monotonic() if now is None else now
        self.book.update(readings, now)
        self.master = master or self._loudest()
        self.last = now
        self.packets += 1

    def _loudest(self) -> int:
        playing = [d for d in self.decks.values() if d.play]
        return max(playing, key=lambda d: d.vol).deck if playing else 0

    def alive(self) -> bool:
        return time.monotonic() - self.last < STALE_S

    def status(self) -> dict:
        return {"name": self.name, "source": self.label, "up": self.alive(), "packets": self.packets}

    def close(self):
        pass
