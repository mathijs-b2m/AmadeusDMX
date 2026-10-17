"""Mixxx: its official controller scripting, through a MIDI port of our own.

A controller script can't open a network socket, but it can talk MIDI. We create a virtual MIDI device,
"Amadeus DMX" (on Windows, which can't, we open the port of that name the Windows app made: winmidi.py); in
Mixxx (Preferences → Controllers) it gets the "Amadeus DMX" mapping
(mixxx/ in this repository, copied into Mixxx's controllers folder for you), whose script sends every deck's
position, length, sample rate, speed, tempo, volume, loop state and the crossfader 50 times a second as
SysEx (format in mixxx/Amadeus-DMX-scripts.js).

A script can't read a track's title or file, so we find the track in Mixxx's own library (read only) by
its exact length in samples and its sample rate.

Options: port (the MIDI device's name; an existing port, like the IAC bus, is used as it is), library
(mixxxdb.sqlite, default: Mixxx's own).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

from amadeus import paths, system
from amadeus.show.sources.base import Deck, Source
from amadeus.show.sources.resolve import Resolver
from amadeus.show.sources.winmidi import matching

NAME = "Amadeus DMX"
HEADER = [0xF0, 0x7D, 0x44, 0x4C, 0x01]
LOADING_S = 0.3  # while Mixxx loads a track its position is briefly meaningless (half-way, then 0)
MAPPING = paths.ROOT / "mixxx"
SETTINGS = [  # where Mixxx keeps its settings: sandboxed (the macOS download), not sandboxed, Linux, Windows
    Path.home() / "Library/Containers/org.mixxx.mixxx/Data/Library/Application Support/Mixxx",
    Path.home() / "Library/Application Support/Mixxx",
    Path.home() / ".mixxx",
    system.local_app_data() / "Mixxx",
]
NO_PORT = (
    "No MIDI port '{port}' on this computer. Windows can't make one for a program: the Amadeus DMX app makes it "
    "(Windows MIDI Services, in Windows 11 24H2 and later), or make a port called "
    "'{port}' in loopMIDI (tobias-erichsen.de); then start Mixxx and the show again."
)


def settings_dir() -> Path | None:
    return next((p for p in SETTINGS if p.is_dir()), None)


def install_mapping() -> Path | None:
    """Copy our mapping into Mixxx's controllers folder (Mixxx reads it at its next start)."""
    folder = settings_dir()
    if folder is None:
        return None
    dest = folder / "controllers"
    dest.mkdir(exist_ok=True)
    for f in MAPPING.iterdir():
        if f.suffix in (".xml", ".js") and (
            not (dest / f.name).exists() or (dest / f.name).read_bytes() != f.read_bytes()
        ):
            shutil.copy2(f, dest / f.name)
    return dest


def u7(data: list[int], i: int, n: int) -> int:
    v = 0
    for b in data[i : i + n]:
        v = v * 128 + b
    return v


def decode(msg: list[int]) -> dict | None:
    """One SysEx message from the script → {"deck": …} or {"xfader": …}."""
    if msg[: len(HEADER)] != HEADER or msg[-1] != 0xF7:
        return None
    body = msg[len(HEADER) : -1]
    if body[0] == 0x02 and len(body) >= 3:
        return {"xfader": u7(body, 1, 2) / 16383 * 2 - 1}
    if body[0] != 0x01 or len(body) < 28:
        return None
    flags = body[2]
    return {
        "deck": body[1],
        "play": bool(flags & 1),
        "loop": bool(flags & 4),
        "orientation": (flags >> 3) & 3,
        "pos": (u7(body, 3, 5) - 2**30) / 1000,
        "samples": u7(body, 8, 5),
        "rate": u7(body, 13, 3),
        "ratio": (u7(body, 16, 4) - 2**27) / 1e6,
        "bpm": u7(body, 20, 4) / 1000,
        "vol": u7(body, 24, 2) / 16383,
        "seq": u7(body, 26, 2),
    }


def xfade_gain(x: float, orientation: int) -> float:
    """Mixxx's crossfader (-1 left .. 1 right) → a deck's gain; orientation 0 left, 1 centre, 2 right."""
    if orientation == 1:
        return 1.0
    x = x if orientation == 0 else -x  # how far towards the other side
    return min(1.0, 1.0 - x) if x > 0 else 1.0


class Library:
    """Mixxx's track library: which track is this many samples at this rate (read only)."""

    def __init__(self, path: Path | None):
        self.path = path
        self.memo: dict[tuple, tuple[str, str, str]] = {}

    def find(self, samples: int, rate: int, bpm: float) -> tuple[str, str, str]:
        """→ (file, artist, title); empty strings when Mixxx's library doesn't know it. Mixxx counts samples
        in stereo (frames × 2) whatever the file has."""
        key = (samples, rate)
        if key in self.memo:
            return self.memo[key]
        found = ("", "", "")
        if self.path and self.path.exists() and rate:
            try:
                with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
                    rows = db.execute(
                        "SELECT l.location, t.artist, t.title, t.bpm FROM library t "
                        "JOIN track_locations l ON l.id = t.location "
                        "WHERE t.samplerate = ? AND abs(t.duration - ?) < 0.05 AND t.mixxx_deleted = 0",
                        (rate, samples / 2 / rate),
                    ).fetchall()
                if rows:
                    best = min(rows, key=lambda r: abs((r[3] or 0) - bpm))
                    found = (best[0], best[1] or "", best[2] or "")
            except sqlite3.Error as e:
                print(f"  ⚠ Mixxx library: {e}", flush=True)
                return found
        self.memo[key] = found
        return found


class Mixxx(Source):
    label = "Mixxx"

    def __init__(self, port: str = NAME, library: str = ""):
        super().__init__()
        folder = settings_dir()
        self.library = Library(Path(library) if library else (folder / "mixxxdb.sqlite" if folder else None))
        self.resolver = Resolver()
        where = install_mapping()
        if where:
            print(f"  Mixxx mapping '{NAME}' is in {where}", flush=True)
        self.xfader = 0.0
        self.state: dict[int, dict] = {}
        self.lost = 0
        self.seq = -1
        if sys.platform == "win32":
            self._open_windows(port)
            return
        import rtmidi

        # Mixxx pairs a device's input and output by name: one of each. Mixxx only looks for MIDI devices
        # when it starts, so a device of our own means starting Mixxx after us; a port that is always there
        # (the IAC bus: --opt port="IAC Driver Bus 1") keeps working when we restart.
        self.inp = rtmidi.MidiIn()
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        existing = matching(self.inp.get_ports(), port, loose=False)
        if existing is not None:
            self.out = None
            self.inp.open_port(existing)
            self.name = f"Mixxx (MIDI port '{port}')"
        else:
            self.out = rtmidi.MidiOut()
            self.out.open_virtual_port(port)
            self.inp.open_virtual_port(port)
            self.name = f"Mixxx (MIDI device '{port}': start Mixxx after this)"
        self.inp.set_callback(self._midi)

    def _open_windows(self, port: str):
        """Windows: the input of the port Mixxx sends to (a loopback: what Mixxx sends comes back on it)."""
        from amadeus.show.sources import winmidi

        index = matching(winmidi.input_names(), port)
        if index is None:
            raise SystemExit(NO_PORT.format(port=port))
        self.out = None
        self.inp = winmidi.MidiIn(index, self._midi)
        self.name = f"Mixxx (MIDI port '{winmidi.input_names()[index]}')"

    def _midi(self, event, _=None):
        now = time.monotonic()
        msg = decode(event[0])
        if msg is None:
            return
        if "xfader" in msg:
            self.xfader = msg["xfader"]
            return
        if self.seq >= 0:
            self.lost += (msg["seq"] - self.seq - 1) % 16384
        self.seq = msg["seq"]
        msg["at"] = now
        old = self.state.get(msg["deck"])
        new_track = old is None or (old["samples"], old["rate"]) != (msg["samples"], msg["rate"])
        msg["since"] = now if new_track else old["since"]
        if old and not new_track and msg["loop"] != old["loop"]:
            self.book.emit(msg["deck"], "loop" if msg["loop"] else "loop_off", pos=round(msg["pos"], 3))
        self.state[msg["deck"]] = msg
        self._reading(now)

    def _reading(self, now: float):
        readings = []
        for n, m in sorted(self.state.items()):
            if now - m["at"] > 1.0 or now - m["since"] < LOADING_S:  # unloaded (no news), or still loading
                continue
            file, artist, title = self.library.find(m["samples"], m["rate"], m["bpm"])
            file = self.resolver.find(file, artist, title) if file else ""
            length = m["samples"] / 2 / m["rate"] if m["rate"] else 0.0
            ratio = m["ratio"] or 1.0
            readings.append(
                Deck(
                    n, file, m["pos"], length, m["play"], m["bpm"], m["bpm"] / ratio if m["bpm"] else 0.0,
                    m["vol"] * xfade_gain(self.xfader, m["orientation"]), m["at"], title, artist,
                    f"{m['samples']}@{m['rate']}", rate=ratio if m["play"] else 0.0,
                )
            )  # fmt: skip
        self.received(readings, now=now)

    def status(self) -> dict:
        return {**super().status(), "lost": self.lost}

    def close(self):
        if sys.platform == "win32":
            self.inp.close()
            return
        self.inp.close_port()
        if self.out:
            self.out.close_port()
