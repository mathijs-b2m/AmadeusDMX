"""djay Pro: what its window says, read like a screen reader would: through the macOS Accessibility API
(VoiceOver), or on Windows through UI Automation (Narrator).

djay has no API, no plugin interface and writes no playhead anywhere. But its deck controls are labelled for
VoiceOver: per deck the title, artist, elapsed time, play button, tempo, line volume, and the crossfader.
On macOS the process that runs this needs Accessibility permission (System Settings → Privacy & Security →
Accessibility): the Amadeus DMX app when it runs the show, or Terminal for `amadeus probe djay`. On Windows no
permission is needed (needs comtypes); the labels are the same words (shared below), read from djay Pro for
Windows' window only. Three kinds of calls, all read-only: find djay's window, find its deck controls by their
labels, read their values.

The elapsed time only shows whole seconds (rounded down) and djay redraws it about 10 times a second. So a
change from 01:06 to 01:07 means the playhead crossed 67.000 s at most ~100 ms before we saw it: each tick
is a sync point that can only be late, never early. Over the last ticks, the one predicting the furthest
position is the least late (the same idea as the Amadeus Link clock sync), which brings the playhead to
within some 10 ms. A tick that lands outside its window means the DJ jumped (seek, loop, nudge): we start
over from there, half a second uncertain until the next tick.

The track's file comes from djay's own library (MediaLibrary.db in Music/djay, read only), by title and artist.
djay only records a newly added file there once it plays; until then the file is looked up by its title in the folders
djay's known tracks are in (and the music folders), so a track is analysed as soon as it is loaded.

A deck on SYNC follows Ableton Link: then the deck also carries Link's beat phase, and live mode locks the
position to it (base.PhaseLock): the label picks the beat, Link gives the exact moment (needs aalink).

A track djay streams (Spotify) has no file. djay's library says which recording it is (Spotify id, ISRC,
length): we fetch a local copy of that same recording once (streamed.py, needs yt-dlp) and light it from that.
djay records a streamed track there only once it plays: one just loaded (no file, not in the library) is
looked for by its artist and title, its length from the deck's clocks, so its show is ready before play.

This is off unless switched on (Settings ▸ Integrations ▸ Streamed tracks in the Mac app, or `--opt streamed=1`):
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

from amadeus import system
from amadeus.show.sources.base import Deck, Source
from amadeus.show.sources.resolve import Resolver, length_of
from amadeus.show.sources.streamed import DjayStreams, Fetcher, enabled, guessed

BUNDLE = "com.algoriddim.djay"
# djay's labels for its deck controls: VoiceOver's on macOS, Narrator's (UI Automation names) on Windows
DECKS = "Decks"  # the group they are in
ELAPSED, REMAINING, PLAY, TITLE, ARTIST = "Elapsed time", "Remaining time", "Play / Pause", "Title", "Artist"
VOLUME, TEMPO, SYNC, CROSSFADER = "Line volume", "Tempo", "Sync", "Crossfader"
ACTIVE = "Active"  # a pressed play or sync button
ELAPSED_RE = re.compile(r"Elapsed time, Deck (\d+)")


def label(control: str, deck: int) -> str:
    """'Elapsed time', 1 → 'Elapsed time, Deck 1'."""
    return f"{control}, Deck {deck}"


def library_places(windows: bool = system.WINDOWS) -> list[Path]:
    """Where djay keeps its library: the Music folder's djay folder (macOS; Windows: the Music folder Windows
    knows, also when it moved), in its bundle or (djay Pro for Windows) a plain folder."""
    djay = system.user_folder("Music") / "djay" if windows else Path.home() / "Music/djay"
    return [djay / "djay Media Library.djayMediaLibrary/MediaLibrary.db", djay / "djay Media Library/MediaLibrary.db"]


def library_file(windows: bool = system.WINDOWS) -> Path:
    places = library_places(windows)
    return next((p for p in places if p.is_file()), places[0])


LIBRARY = library_file()
LATE_S = 0.15  # a label is at most this late (djay redraws ~10× a second, plus our polling)
OFF = "dark (to light it: Settings ▸ Integrations ▸ Streamed tracks, or --opt streamed=1)"
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
                    self.files[(title, artist)] = system.file_url_path(url)
            if self.found:
                self.found({str(Path(f).parent) for f in self.files.values()})
        except (sqlite3.Error, ValueError, IndexError) as e:
            print(f"  ⚠ djay library: {e}", flush=True)

    def find(self, title: str, artist: str) -> str:
        if (title, artist) not in self.files and time.monotonic() - self.read_at > 2.0:
            self._read()  # a track djay hasn't told us about yet: it may have just been added
        return self.files.get((title, artist)) or next((f for (t, _), f in self.files.items() if t == title), "")


class Controls:
    """djay's deck controls by their labels ('Elapsed time, Deck 1', …): `scan` finds them in djay's window,
    `read` gives one control's value as text, the way the system's accessibility API says it."""

    def __init__(self):
        self.controls: dict[str, list] = {}

    def attach(self):
        """Called first on every thread that reads (Windows: COM)."""

    def value(self, label: str):
        es = self.controls.get(label)
        return self.read(es[0]) if es else None

    def read(self, e):
        raise NotImplementedError

    def decks(self) -> list[int]:
        return decks_in(self.controls)

    def bpm(self, n: int) -> float:
        return bpm_in(self.controls, n)


def decks_in(labels) -> list[int]:
    """The decks there are: those with an elapsed-time label."""
    return sorted({int(m.group(1)) for k in labels if (m := ELAPSED_RE.fullmatch(k))})


def bpm_in(labels, n: int) -> float:
    """The tempo button's label is the tempo itself: '125.0, Deck 1'."""
    for k in labels:
        m = re.fullmatch(rf"(\d+(?:\.\d+)?), Deck {n}", k)
        if m:
            return float(m.group(1))
    return 0.0


def wanted(label: str) -> bool:
    """A label of one of the controls we read (the rest of djay's window is left alone)."""
    return label == CROSSFADER or ", Deck " in label


class MacWindow(Controls):
    """macOS: djay's controls through the Accessibility API, as VoiceOver reads them."""

    def __init__(self):
        import ApplicationServices as AS
        from AppKit import NSWorkspace

        super().__init__()
        self.AS = AS
        if not AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}):
            raise SystemExit(
                "djay: this app may not read other apps' windows yet. System Settings → Privacy & Security → "
                "Accessibility: switch on the app that runs Amadeus DMX (or Terminal), then start again."
            )
        self.workspace = NSWorkspace.sharedWorkspace()
        self.pid = None

    def attr(self, e, name: str):
        err, v = self.AS.AXUIElementCopyAttributeValue(e, name, None)
        return v if err == 0 else None

    def read(self, e):
        return self.attr(e, "AXValue")

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
                if self.attr(group, "AXDescription") != DECKS:
                    continue
                for e in self.attr(group, "AXChildren") or []:
                    controls.setdefault(self.attr(e, "AXDescription") or "", []).append(e)
        self.controls = controls  # one assignment: the reader sees the old or the new set, never half
        return bool(controls)


# UI Automation's ids (UIAutomationClient.h)
UIA_NAME = 30005
UIA_VALUE, UIA_RANGE_VALUE, UIA_TEXT, UIA_TOGGLE, UIA_LEGACY = 10002, 10003, 10014, 10015, 10018
SCOPE_CHILDREN, SCOPE_DESCENDANTS = 2, 4


def uia_text(value=None, toggle=None, rng=None, label: str = "") -> str | None:
    """A control's value in the words macOS's Accessibility API uses, from what UI Automation gives: its value
    text as it is; a toggle (play, sync) as 'Active'; a fader as a percentage (the tempo fader in its own
    percent, the others as the share of their range)."""
    if value:
        return value
    if toggle is not None:
        return ACTIVE if toggle == 1 else "Inactive"
    if rng is not None:
        v, lo, hi = rng
        if label.startswith(TEMPO):
            return f"{v:g}%"
        return f"{100 * (v - lo) / (hi - lo):g}%" if hi > lo else None
    return None


class UiaWindow(Controls):
    """Windows: djay Pro for Windows' controls through UI Automation, as Narrator reads them. Needs comtypes.
    Only reads, and only djay's window; no permission to ask for (djay runs as the same user)."""

    def __init__(self):
        super().__init__()
        self.said = False
        # on a thread of its own: COM may be set up single-threaded on the caller's thread already (audio does),
        # and importing comtypes there would fail; the reader threads join the multithreaded apartment
        failed = []
        t = threading.Thread(target=self._setup, args=(failed,), name="djay-uia-setup")
        t.start()
        t.join()
        if failed:
            raise failed[0]

    def _setup(self, failed):
        import sys

        try:
            if "comtypes" not in sys.modules:
                sys.coinit_flags = 0  # COINIT_MULTITHREADED: the reader threads share the UI Automation objects
            try:
                import comtypes
                import comtypes.client
            except ImportError:
                raise SystemExit("djay on Windows needs comtypes (pip install comtypes)") from None
            self.comtypes = comtypes
            self.attach()
            self.ui = comtypes.client.GetModule("UIAutomationCore.dll")
            self.uia = comtypes.CoCreateInstance(
                self.ui.CUIAutomation._reg_clsid_, interface=self.ui.IUIAutomation, clsctx=comtypes.CLSCTX_INPROC_SERVER
            )
            self.everything = self.uia.CreateTrueCondition()
        except BaseException as e:  # noqa: BLE001 - raised again on the caller's thread
            failed.append(e)

    def attach(self):
        try:
            self.comtypes.CoInitializeEx(0)  # COINIT_MULTITHREADED
        except OSError:
            pass  # already initialised on this thread

    def _djay(self):
        """djay's top-level window: by its title, or by its program's name (djay.exe and the like)."""
        from amadeus.system import processes

        pids = {pid for pid, cmd in processes() if "djay" in cmd.lower() and "amadeus" not in cmd.lower()}
        wins = self.uia.GetRootElement().FindAll(SCOPE_CHILDREN, self.everything)
        for i in range(wins.Length):
            w = wins.GetElement(i)
            if (w.CurrentName or "").lower().startswith("djay") or w.CurrentProcessId in pids:
                return w
        return None

    def scan(self) -> bool:
        try:
            win = self._djay()
            if win is None:
                self.controls = {}
                return False
            group = win.FindFirst(SCOPE_DESCENDANTS, self.uia.CreatePropertyCondition(UIA_NAME, DECKS))
            found = (group or win).FindAll(SCOPE_DESCENDANTS, self.everything)
            controls: dict[str, list] = {}
            for i in range(found.Length):
                e = found.GetElement(i)
                name = e.CurrentName or ""
                if wanted(name):
                    controls.setdefault(name, []).append(e)
        except self.comtypes.COMError as e:  # djay quit or redrew its window meanwhile
            controls = {}
            if not self.said:
                print(f"  ⚠ djay: its window can't be read ({e})", flush=True)
                self.said = True
        if not controls and not self.said:
            print("  ⚠ djay: its window shows no deck controls Amadeus DMX knows (djay Pro for Windows 5 and later "
                  "label them for Narrator)", flush=True)  # fmt: skip
            self.said = True
        self.controls = controls
        return bool(controls)

    def read(self, e):
        ui = self.ui
        try:
            name = e.CurrentName or ""
            value = toggle = rng = None
            if p := e.GetCurrentPattern(UIA_VALUE):
                value = p.QueryInterface(ui.IUIAutomationValuePattern).CurrentValue
            if not value and (p := e.GetCurrentPattern(UIA_TOGGLE)):
                toggle = p.QueryInterface(ui.IUIAutomationTogglePattern).CurrentToggleState
            if not value and toggle is None and (p := e.GetCurrentPattern(UIA_RANGE_VALUE)):
                r = p.QueryInterface(ui.IUIAutomationRangeValuePattern)
                rng = (r.CurrentValue, r.CurrentMinimum, r.CurrentMaximum)
            if not value and toggle is None and rng is None and (p := e.GetCurrentPattern(UIA_TEXT)):
                value = p.QueryInterface(ui.IUIAutomationTextPattern).DocumentRange.GetText(-1)
            if not value and toggle is None and rng is None and (p := e.GetCurrentPattern(UIA_LEGACY)):
                value = p.QueryInterface(ui.IUIAutomationLegacyIAccessiblePattern).CurrentValue
            return uia_text(value, toggle, rng, name)
        except self.comtypes.COMError:
            return None


def open_window() -> Controls:
    """djay's window, read the way this system can."""
    return UiaWindow() if system.WINDOWS else MacWindow()


class Djay(Source):
    label = "djay Pro"

    def __init__(self, poll: int = 200, link: int = 1, streamed: int = 0):
        super().__init__()
        self.link = None
        if link:
            try:
                from amadeus.show.sources.ableton import LinkClock

                self.link = LinkClock()
            except ImportError:
                print("  djay: no Ableton Link (pip install aalink): positions from djay's window only", flush=True)
        self.streams = DjayStreams(LIBRARY)
        self.fetcher = None
        self.streamed = bool(streamed) or enabled()
        if streamed:
            try:
                self.fetcher = Fetcher()
            except ImportError:
                print(f"  djay: streamed tracks (Spotify) stay {NO_YTDLP}", flush=True)
        self.window = open_window()
        self.resolver = Resolver()
        self.library = Library(found=self.resolver.add)
        self.library._read()  # now: the folders it knows are indexed before the first track is loaded
        self.period = 1.0 / poll
        self.heads: dict[int, Playhead] = {}
        self.info: dict[int, dict] = {}
        self.xfader = 0.5
        self.name = f"djay Pro (its window, via {'UI Automation' if system.WINDOWS else 'Accessibility'})"
        self.running = True
        self.window.scan()
        threading.Thread(target=self._scan, daemon=True).start()
        threading.Thread(target=self._run, daemon=True).start()

    def _scan(self):  # finding the controls takes ~0.1 s: never in the way of the playhead
        self.window.attach()
        while self.running:
            time.sleep(SCAN_S if self.window.controls else 0.5)
            self.window.scan()

    def _run(self):
        self.window.attach()
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
                head.set_play(self.window.value(label(PLAY, n)) == ACTIVE, now)
                secs = clock(self.window.value(label(ELAPSED, n)))
                if secs is not None and secs != head.label:
                    head.seen(secs, time.monotonic())
            if now - sent >= 0.02:  # 50 readings a second
                sent = now
                self._reading(now)
            time.sleep(self.period)

    def _slow(self, now: float):
        w = self.window
        x = percent(w.value(CROSSFADER))
        if x is not None:
            self.xfader = x
        for n in w.decks():
            title, artist = w.value(label(TITLE, n)) or "", w.value(label(ARTIST, n)) or ""
            info = self.info.setdefault(n, {})
            guess = getattr(info.get("stream"), "guess", False)  # until djay's library knows it: asked again
            if (title, artist) != (info.get("title"), info.get("artist")) or (title and not info.get("file")) or guess:
                known = self.library.find(title, artist) if title else ""
                file = self.resolver.find(known, artist, title)
                stream = self.streams.find(title, artist) if title and not file else None
                if stream is None and title and not (known or file) and self.fetcher and self.resolver.ready.is_set():
                    stream = self._guess(n, title, artist)  # loaded, not played yet: not in djay's library yet
                if stream and self.fetcher:
                    file = self.fetcher.file(stream)  # "" while the copy is being fetched
                if stream and stream.id != getattr(info.get("stream"), "id", None):  # said once per track
                    how = "fetching a copy to light it" if self.fetcher else NO_YTDLP if self.streamed else OFF
                    how = "lit from its copy" if file and self.fetcher else how
                    if stream.guess:
                        why = "isn't on this computer nor in djay's library yet (streamed, not played yet?)"
                        print(f"  deck {n}: {stream.name} {why}: looking for a copy by artist and title", flush=True)
                    else:
                        print(f"  deck {n}: {stream.name} streams from {stream.service.title()}: {how}", flush=True)
                length = (stream.length if stream else 0.0) or ((length_of(file) or 0.0) if file else 0.0)
                info.update(title=title, artist=artist, file=file, length=length, stream=stream)
            if (stream := info.get("stream")) and self.fetcher:
                info["copy"] = self.fetcher.status(stream)
            info["vol"] = percent(w.value(label(VOLUME, n)))
            tempo = percent(w.value(label(TEMPO, n))) or 0.0
            info["bpm"] = w.bpm(n)
            info["sync"] = w.value(label(SYNC, n)) == ACTIVE
            self.heads.setdefault(n, Playhead()).set_speed(1.0 + tempo, now)

    def _guess(self, n: int, title: str, artist: str):
        """The deck's track as far as its window tells: title, artist and its length (elapsed + remaining)."""
        elapsed = clock(self.window.value(label(ELAPSED, n)))
        remaining = self.window.value(label(REMAINING, n)) or ""
        left = clock(remaining) if remaining.strip().startswith("-") else None
        if elapsed is None or not left:
            return None
        old = self.info.get(n, {}).get("stream")
        if old is not None and old.guess and (old.title, old.artist) == (title, artist):
            return old  # the same guess: its length as first read
        return guessed(title, artist, float(elapsed + left))

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
