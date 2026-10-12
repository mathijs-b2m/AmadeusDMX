"""djay Pro (macOS): what its window says, read through the macOS Accessibility API, like VoiceOver would.

djay has no API, no plugin interface and writes no playhead anywhere. But its deck controls are labelled for
VoiceOver: per deck the title, artist, elapsed time, play button, tempo, line volume, and the crossfader.
The process that runs this needs Accessibility permission (System Settings → Privacy & Security →
Accessibility): the Decisive Lightning app when it runs the show, or Terminal for `decisive probe djay`.

The elapsed time only shows whole seconds (rounded down) and djay redraws it about 10 times a second. So a
change from 01:06 to 01:07 means the playhead crossed 67.000 s at most ~100 ms before we saw it: each tick
is a sync point that can only be late, never early. Over the last ticks, the one predicting the furthest
position is the least late (the same idea as the Decisive Link clock sync), which brings the playhead to
within some 10 ms. A tick that lands outside its window means the DJ jumped (seek, loop, nudge): we start
over from there, half a second uncertain until the next tick.

The track's file comes from djay's own library (MediaLibrary.db, read only), by title and artist. djay only
records a newly added file there once it plays; until then the file is looked up by its title in the folders
djay's known tracks are in (and the music folders), so a track is analysed as soon as it is loaded.

A deck on SYNC follows Ableton Link: then the deck also carries Link's beat phase, and live mode locks the
position to it (base.PhaseLock): the label picks the beat, Link gives the exact moment (needs aalink).

A track djay streams (Spotify) has no file. djay's library says which recording it is (Spotify id, ISRC,
length): we fetch a local copy of that same recording once (streamed.py, needs yt-dlp) and light it from that.

This is off unless switched on (Settings ▸ Integrations ▸ djay Pro in the Mac app, or `--opt streamed=1`):
it downloads from YouTube, which is the user's own call to make.

Options: poll (readings per second, default 200), link (0: don't listen to Ableton Link), streamed (1: fetch
copies of streamed tracks).
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlparse

from decisive.show.sources.base import Deck, Source
from decisive.show.sources.resolve import Resolver, length_of
from decisive.show.sources.streamed import DjayStreams, Fetcher

BUNDLE = "com.algoriddim.djay"
LIBRARY = Path.home() / "Music/djay/djay Media Library.djayMediaLibrary/MediaLibrary.db"
LATE_S = 0.15  # a label is at most this late (djay redraws ~10× a second, plus our polling)
OFF = "dark (to light it: Settings ▸ Integrations ▸ djay Pro, or --opt streamed=1)"
NO_YTDLP = "dark (yt-dlp isn't installed: pip install -e '.[streamed]')"
KEEP = 8  # ticks to keep: the least late of them anchors the playhead
SCAN_S = 2.0  # look for djay's controls again this often (tracks load, decks are added)


def clock(text: str) -> int | None:
    """'01:07' → 67, '1:02:03' → 3723; anything else → None."""
    m = re.fullmatch(r"-?(?:(\d+):)?(\d+):(\d\d)", (text or "").strip())
    if not m:
        return None
    h, mm, ss = m.groups()
    return int(h or 0) * 3600 + int(mm) * 60 + int(ss)


def percent(text) -> float | None:
    try:
        return float(str(text).strip().rstrip("%")) / 100
    except ValueError:
        return None


class Playhead:
    """One deck's position from its whole-second label: ticks are late by 0..LATE_S, never early."""

    def __init__(self):
        self.ticks: deque[tuple[float, float]] = deque(maxlen=KEEP)  # (seen at, position then)
        self.coarse: tuple[float, float] | None = None  # after a jump: (when, position ± 0.5 s)
        self.label: int | None = None
        self.speed = 1.0
        self.play = False
        self.frozen = 0.0  # where it stopped (while paused)

    def at(self, t: float) -> float:
        speed = self.speed if self.play else 0.0
        if self.ticks:
            return max(p + (t - seen) * speed for seen, p in self.ticks)
        if self.coarse:
            seen, p = self.coarse
            return p + (t - seen) * speed
        return self.frozen

    def rebase(self, t: float):
        """Speed or play state changes: what we know becomes one anchor at the current position."""
        exact = bool(self.ticks)
        pos = self.at(t)
        self.ticks.clear()
        if exact:
            self.ticks.append((t, pos))
            self.coarse = None
        else:
            self.coarse = (t, pos)
        self.frozen = pos

    def set_play(self, play: bool, t: float):
        if play != self.play:
            self.rebase(t)
            self.play = play

    def set_speed(self, speed: float, t: float):
        if abs(speed - self.speed) > 1e-4:
            self.rebase(t)
            self.speed = speed

    def seen(self, label: int, t: float) -> str:
        """A new label value. → "tick" (a sync point), "jump" (seek, loop) or "" (the first one)."""
        old, self.label = self.label, label
        if old is None:
            self.coarse, self.frozen = (t, label + 0.5), label + 0.5
            return ""
        if label == old + 1:  # the playhead crossed a whole second: exact, at most LATE_S ago
            if self.ticks and not -0.05 <= self.at(t) - label <= LATE_S + 0.05:
                self.ticks.clear()  # it doesn't fit the earlier ticks: the DJ nudged or jumped meanwhile
            self.ticks.append((t, float(label)))
            self.coarse, self.frozen = None, float(label)
            return "tick"
        self.ticks.clear()  # anything else: the DJ moved the playhead (seek, loop, back-spin)
        self.coarse, self.frozen = (t, label + 0.5), label + 0.5
        return "jump"


class Library:
    """djay's library: a track's file by its title (and artist), read only."""

    def __init__(self, path: Path = LIBRARY, found=None):
        self.path = path
        self.found = found  # called with the folders of the files djay knows
        self.files: dict[tuple[str, str], str] = {}
        self.read_at = 0.0

    def _read(self):
        self.read_at = time.monotonic()
        try:
            with sqlite3.connect(f"file:{self.path}?mode=ro", uri=True) as db:
                rows = db.execute("SELECT data FROM database2 WHERE collection = 'localMediaItemLocations'")
                for (data,) in rows:
                    s = [x.decode("utf-8", "replace") for x in re.findall(rb"\x08([^\x00]{1,1000})\x00", data)]
                    url = next((x for x in s if x.startswith("file://")), None)
                    if not url:
                        continue
                    title = s[s.index("title") - 1] if "title" in s else ""
                    artist = s[s.index("artist") - 1] if "artist" in s else ""
                    self.files[(title, artist)] = unquote(urlparse(url).path)
            if self.found:
                self.found({str(Path(f).parent) for f in self.files.values()})
        except (sqlite3.Error, ValueError, IndexError) as e:
            print(f"  ⚠ djay library: {e}", flush=True)

    def find(self, title: str, artist: str) -> str:
        if (title, artist) not in self.files and time.monotonic() - self.read_at > 2.0:
            self._read()  # a track djay hasn't told us about yet: it may have just been added
        return self.files.get((title, artist)) or next((f for (t, _), f in self.files.items() if t == title), "")


class Window:
    """djay's deck controls, found by their VoiceOver labels ('Elapsed time, Deck 1', …)."""

    def __init__(self):
        import ApplicationServices as AS
        from AppKit import NSWorkspace

        self.AS = AS
        if not AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}):
            raise SystemExit(
                "djay: this app may not read other apps' windows yet. System Settings → Privacy & Security → "
                "Accessibility: switch on the app that runs Decisive Lightning (or Terminal), then start again."
            )
        self.workspace = NSWorkspace.sharedWorkspace()
        self.controls: dict[str, list] = {}
        self.pid = None

    def attr(self, e, name: str):
        err, v = self.AS.AXUIElementCopyAttributeValue(e, name, None)
        return v if err == 0 else None

    def scan(self) -> bool:
        app = next(
            (a for a in self.workspace.runningApplications() if (a.bundleIdentifier() or "").startswith(BUNDLE)),
            None,
        )
        if app is None:
            self.controls = {}
            return False
        root = self.AS.AXUIElementCreateApplication(app.processIdentifier())
        controls: dict[str, list] = {}
        for win in self.attr(root, "AXWindows") or []:
            for group in self.attr(win, "AXChildren") or []:
                if self.attr(group, "AXDescription") != "Decks":
                    continue
                for e in self.attr(group, "AXChildren") or []:
                    controls.setdefault(self.attr(e, "AXDescription") or "", []).append(e)
        self.controls = controls  # one assignment: the reader sees the old or the new set, never half
        return bool(controls)

    def value(self, label: str):
        es = self.controls.get(label)
        return self.attr(es[0], "AXValue") if es else None

    def decks(self) -> list[int]:
        return sorted({int(m.group(1)) for k in self.controls if (m := re.fullmatch(r"Elapsed time, Deck (\d+)", k))})

    def bpm(self, n: int) -> float:
        """The tempo button's label is the tempo itself: '125.0, Deck 1'."""
        for k in self.controls:
            m = re.fullmatch(rf"(\d+(?:\.\d+)?), Deck {n}", k)
            if m:
                return float(m.group(1))
        return 0.0


class Djay(Source):
    label = "djay Pro"

    def __init__(self, poll: int = 200, link: int = 1, streamed: int = 0):
        super().__init__()
        self.link = None
        if link:
            try:
                from decisive.show.sources.ableton import LinkClock

                self.link = LinkClock()
            except ImportError:
                print("  djay: no Ableton Link (pip install aalink): positions from djay's window only", flush=True)
        self.streams = DjayStreams(LIBRARY)
        self.fetcher = None
        self.streamed = bool(streamed)
        if streamed:
            try:
                self.fetcher = Fetcher()
            except ImportError:
                print(f"  djay: streamed tracks (Spotify) stay {NO_YTDLP}", flush=True)
        self.window = Window()
        self.resolver = Resolver()
        self.library = Library(found=self.resolver.add)
        self.library._read()  # now: the folders it knows are indexed before the first track is loaded
        self.period = 1.0 / poll
        self.heads: dict[int, Playhead] = {}
        self.info: dict[int, dict] = {}
        self.xfader = 0.5
        self.name = "djay Pro (its window, via Accessibility)"
        self.running = True
        self.window.scan()
        threading.Thread(target=self._scan, daemon=True).start()
        threading.Thread(target=self._run, daemon=True).start()

    def _scan(self):  # finding the controls takes ~0.1 s: never in the way of the playhead
        while self.running:
            time.sleep(SCAN_S if self.window.controls else 0.5)
            self.window.scan()

    def _run(self):
        slow, sent = 0.0, 0.0
        while self.running:
            now = time.monotonic()
            if not self.window.controls:  # djay isn't running (yet)
                time.sleep(0.2)
                continue
            if now - slow > 0.2:  # what changes slowly: track, tempo, faders
                slow = now
                self._slow(now)
            for n in self.window.decks():  # what must be on time: the playhead
                head = self.heads.setdefault(n, Playhead())
                head.set_play(self.window.value(f"Play / Pause, Deck {n}") == "Active", now)
                secs = clock(self.window.value(f"Elapsed time, Deck {n}"))
                if secs is not None and secs != head.label:
                    head.seen(secs, time.monotonic())
            if now - sent >= 0.02:  # 50 readings a second
                sent = now
                self._reading(now)
            time.sleep(self.period)

    def _slow(self, now: float):
        w = self.window
        x = percent(w.value("Crossfader"))
        if x is not None:
            self.xfader = x
        for n in w.decks():
            title, artist = w.value(f"Title, Deck {n}") or "", w.value(f"Artist, Deck {n}") or ""
            info = self.info.setdefault(n, {})
            if (title, artist) != (info.get("title"), info.get("artist")) or (title and not info.get("file")):
                file = self.library.find(title, artist) if title else ""
                file = self.resolver.find(file, artist, title)
                stream = self.streams.find(title, artist) if title and not file else None
                if stream and self.fetcher:
                    file = self.fetcher.file(stream)  # "" while the copy is being fetched
                if stream and stream.id != getattr(info.get("stream"), "id", None):  # said once per track
                    how = "fetching a copy to light it" if self.fetcher else NO_YTDLP if self.streamed else OFF
                    print(f"  deck {n}: {stream.name} streams from {stream.service.title()}: {how}", flush=True)
                length = (stream.length if stream else 0.0) or ((length_of(file) or 0.0) if file else 0.0)
                info.update(title=title, artist=artist, file=file, length=length, stream=stream)
            if (stream := info.get("stream")) and self.fetcher:
                info["copy"] = self.fetcher.status(stream)
            info["vol"] = percent(w.value(f"Line volume, Deck {n}"))
            tempo = percent(w.value(f"Tempo, Deck {n}")) or 0.0
            info["bpm"] = w.bpm(n)
            info["sync"] = w.value(f"Sync, Deck {n}") == "Active"
            self.heads.setdefault(n, Playhead()).set_speed(1.0 + tempo, now)

    def _reading(self, now: float):
        readings = []
        for n, head in sorted(self.heads.items()):
            info = self.info.get(n)
            if not info or not info.get("title"):
                continue
            side = -1 if n % 2 == 1 else 1  # decks 1/3 on the left of the crossfader, 2/4 on the right
            x = self.xfader if side < 0 else 1.0 - self.xfader
            gain = min(1.0, 2.0 * (1.0 - x))
            vol = (info["vol"] if info.get("vol") is not None else 1.0) * gain
            bpm = info.get("bpm", 0.0)
            phase = None  # on SYNC, at Link's tempo: the deck's beats are Link's beats
            if self.link and head.play and info.get("sync") and self.link.peers and abs(self.link.tempo - bpm) < 0.1:
                phase = self.link.phase()
            readings.append(
                Deck(
                    n, info["file"], head.at(now), info["length"], head.play, bpm, bpm / head.speed if bpm else 0.0,
                    vol, now, info["title"], info["artist"], rate=head.speed if head.play else 0.0, phase=phase,
                    stream=info["stream"].service if info.get("stream") else "", copy=info.get("copy", ""),
                )
            )  # fmt: skip
        self.received(readings, now=now)

    def alive(self) -> bool:
        return bool(self.window.controls) and super().alive()

    def close(self):
        self.running = False
