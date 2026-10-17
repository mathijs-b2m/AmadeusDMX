"""Streamed tracks (Spotify in djay Pro and VirtualDJ): a local copy of the same recording, so it can be
analysed and lit.

A streamed track has no file to analyse. But the DJ software knows exactly which recording it plays: djay's
library keeps, for every Spotify track it has seen, the Spotify id, the ISRC (the recording's own code, the
same on every service) and the length. The same recording is nearly always on YouTube too, uploaded by the
label ("Artist - Topic"), and a YouTube search for the ISRC finds it. We download that audio once (yt-dlp) and
keep it in the cache; the deck's show is then prepared from it like from any local file, and played at the
position the DJ software reports. No second player: the lights follow djay's playhead, as with a local file.

The copy must be the *same* recording, or the lights land beside the music: a copy is only taken when its
length matches the streamed track's within LENGTH_MATCH_S (an edit, a radio version, a video with an intro
are seconds off), preferably within EXACT_S. A search by ISRC first; else by artist and title, the label's own
upload preferred. Only tracks loaded on a deck are fetched, one request at a time, GAP_S apart.

djay only records a streamed track in its library once it plays. So a track the DJ has just loaded, that is
neither a file on this computer nor in djay's library yet, is looked for by its artist and title, its length
read from the deck's clock (to the second): a guess (`guessed`). When djay then records it, with its ISRC
and exact length, the guess's copy is checked against that: the same length, and it is kept (the show made
from it plays on); another version, and the copy is fetched again by ISRC.

Needs yt-dlp (`pip install -e '.[streamed]'`); copies are M4A, which macOS and Windows decode themselves (ffmpeg
only for the WebM a few videos come in). Only fetch audio you are allowed to copy; the copy is
for analysis on this computer, the music the audience hears is the DJ software's own stream.
"""

from __future__ import annotations

import glob
import hashlib
import json
import queue
import re
import sqlite3
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from amadeus import paths, system
from amadeus.show.sources.resolve import words

FOLDER = paths.CACHE / "streamed"
LENGTH_MATCH_S = 1.0  # the copy's length vs the stream's: further off is another version (edit, intro, …)
GUESS_SLACK_S = 1.0  # more for a guess: its length comes from the deck's clock, to the second
EXACT_S = 0.1  # this close: the same master (most are within 30 ms); between the two, try one more candidate
DOWNLOADS = 2  # at most this many candidates downloaded per track
GAP_S = 3.0  # at least this long between two requests to YouTube (search or download)
OFFLINE_RETRY_S = 30.0  # a fetch that failed for want of a connection: tried again this much later
WANTED_S = 10.0  # a queued track no deck has asked for in this long is skipped
# M4A (AAC, ~128 kbps) first: macOS and Windows read it without ffmpeg (afconvert, Media Foundation); WebM/Opus
# needs ffmpeg to be analysed
QUALITY = "bestaudio[ext=m4a]/bestaudio[abr<=80]/worstaudio[abr>=40]/bestaudio"
SEARCH = 8  # results to consider per search
SHUNNED = {"live", "cover", "karaoke", "instrumental", "acapella", "slowed", "sped", "nightcore", "reverb",
           "8d", "loop", "hour", "1hour", "mashup", "reaction", "tutorial", "lyrics", "lyric"}  # fmt: skip


@dataclass
class Stream:
    """A streamed track as the DJ software knows it."""

    service: str  # "spotify"
    id: str  # the service's own id ("5fPoYOwYZek6N4QSLP6xjD")
    title: str
    artist: str
    isrc: str = ""
    length: float = 0.0  # seconds
    bpm: float = 0.0  # the DJ software's own tempo for it, when it has analysed it
    grid: tuple[float, float] | None = None  # the DJ software's beat grid of the stream: (a beat's time, seconds/beat)
    guess: bool = False  # known from the deck only (not in the DJ software's library yet): no ISRC, length to the s

    @property
    def name(self) -> str:
        return f"{self.artist} - {self.title}".strip(" -")

    @property
    def slack(self) -> float:
        """How far a copy's length may be off this one's and still be the same recording."""
        return LENGTH_MATCH_S + (GUESS_SLACK_S if self.guess else 0.0)


def guessed(title: str, artist: str, length: float) -> Stream:
    """A track on a deck the DJ software's library doesn't know yet (djay records a streamed track only once it
    plays), with its length from the deck's clock: looked for by artist and title until the library knows it."""
    key = hashlib.sha1(f"{artist}\n{title}".encode()).hexdigest()[:12]
    return Stream("streamed", key, title, artist, length=length, guess=True)


def enabled() -> bool:
    """Whether copies of streamed tracks may be fetched: the user's own call, off unless switched on (Settings ▸
    Integrations ▸ Streamed tracks: {"streamed": {"on": true}}; before, djay's own {"djay": {"streamed": true}})."""
    from amadeus.show.sources import settings

    return bool(settings("streamed").get("on") or settings("djay").get("streamed"))


def from_packet(d: dict) -> Stream | None:
    """A deck in the plugin's packet format that streams ({"stream": {"service", "id", "isrc"}, "title", "artist",
    "len"}): Amadeus Link sends these for tracks that have no file on the DJ laptop."""
    s = d.get("stream")
    if not isinstance(s, dict) or not s.get("id"):
        return None
    return Stream(str(s.get("service") or "spotify"), str(s["id"]), str(d.get("title") or ""),
                  str(d.get("artist") or ""), str(s.get("isrc") or ""), float(d.get("len") or 0.0))  # fmt: skip


# --- djay's library -----------------------------------------------------------------------------------------
# Its records are a key/value archive ("TSAF"): each value is followed by its key, strings as 0x08 + text + 0x00,
# 32-bit floats as 0x13, zero padding to a 4-byte boundary, then 4 bytes (little endian).

TEXT = {"title", "artist", "isrc"}
KEYS = TEXT | {"duration", "uuid", "titleIDs", "titleID", "sourceURIs", "type", "bpm"}  # a key is never a value
_STR = re.compile(rb"\x08([^\x00]{0,1000})\x00")


def _fields(data: bytes) -> dict:
    """The strings and floats of one record, by key (the first of each key: the record's own, not a nested one)."""
    out: dict = {}
    strings = [(m.start(), m.end(), m.group(1).decode("utf-8", "replace")) for m in _STR.finditer(data)]
    for (_, end, value), (start, _, key) in zip(strings, strings[1:], strict=False):
        if start == end and key in TEXT and value not in KEYS:  # a value directly followed by its key
            out.setdefault(key, value)
    for key in ("duration", "bpm"):
        i = data.find(b"\x08" + key.encode() + b"\x00")
        if i >= 8 and data[i - 8 : i - 4].rstrip(b"\x00").endswith(b"\x13"):  # the float ends where its key starts
            out[key] = struct.unpack("<f", data[i - 4 : i])[0]
    out["uris"] = [s for _, _, s in strings if re.fullmatch(r"[a-z]+:track:[A-Za-z0-9]+", s)]
    return out


def djay_streams(db: Path) -> dict[tuple[str, str], Stream]:
    """Every streamed track djay knows, by (title, artist) as its decks show them (read only)."""
    found: dict[tuple[str, str], Stream] = {}
    bpm: dict[str, float] = {}
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as con:
        for key, data in con.execute("SELECT key, data FROM database2 WHERE collection = 'mediaItemAnalyzedData'"):
            f = _fields(data or b"")
            if f.get("bpm"):
                bpm[key] = float(f["bpm"])
        rows = con.execute("SELECT key, data FROM database2 WHERE collection = 'globalMediaItemLocations'")
        for key, data in rows:
            f = _fields(data or b"")
            uri = next((u for u in f["uris"] if u.startswith("spotify:track:")), None)
            if not uri or not f.get("title"):
                continue
            title, artist = f["title"], f.get("artist", "")
            found[(title, artist)] = Stream(
                "spotify", uri.rsplit(":", 1)[1], title, artist, f.get("isrc", ""),
                float(f.get("duration") or 0.0), bpm.get(key, 0.0),
            )  # fmt: skip
    return found


class DjayStreams:
    """djay's streamed tracks, read again (at most every 2 s) when a deck shows one we don't know yet."""

    def __init__(self, db: Path):
        self.db = db
        self.known: dict[tuple[str, str], Stream] = {}
        self.read_at = 0.0

    def find(self, title: str, artist: str) -> Stream | None:
        if (title, artist) not in self.known and time.monotonic() - self.read_at > 2.0:
            self.read_at = time.monotonic()
            try:
                self.known = djay_streams(self.db)
            except (sqlite3.Error, ValueError) as e:
                print(f"  ⚠ djay library (streamed tracks): {e}", flush=True)
        return self.known.get((title, artist)) or next(
            (s for (t, _), s in self.known.items() if t == title and title), None
        )


# --- VirtualDJ's database -----------------------------------------------------------------------------------
# VirtualDJ names a streamed track "netsearch://" + a two-letter service + the service's own id
# ("netsearch://sp1fI4E7jeOiyfa3LmwNnD0o": Spotify). Its database.xml keeps, per track it has seen, the artist,
# the title and the length (<Tags Author= Title=>, <Infos SongLength=>); no ISRC.

NETSEARCH = re.compile(r"netsearch://([a-z]{2})([A-Za-z0-9]+)")
SERVICES = {"sp": "spotify", "td": "tidal", "dz": "deezer", "sc": "soundcloud", "bp": "beatport", "bs": "beatsource"}


def vdj_homes(windows: bool = system.WINDOWS) -> list[Path]:
    """Where VirtualDJ keeps its home folder (settings, database.xml): on macOS in Application Support; on Windows
    in Documents (the Documents folder Windows knows: also when it moved into OneDrive), on some installations
    in AppData."""
    if not windows:
        return [Path.home() / "Library/Application Support/VirtualDJ", Path.home() / "Documents/VirtualDJ"]
    import os

    appdata = [Path(os.environ[k]) / "VirtualDJ" for k in ("LOCALAPPDATA", "APPDATA") if os.environ.get(k)]
    return [system.user_folder("Documents") / "VirtualDJ", *appdata]


def vdj_database(windows: bool = system.WINDOWS) -> Path:
    """VirtualDJ's database.xml: the first home folder that has one (else where it will be)."""
    homes = vdj_homes(windows)
    return next((h / "database.xml" for h in homes if (h / "database.xml").is_file()), homes[0] / "database.xml")


VDJ_DATABASE = vdj_database()


def vdj_length(text: str) -> float:
    """A track's length from VirtualDJ's database. A whole number of seconds is VirtualDJ's guess before it has
    the stream itself (240.0): unknown, so it can't turn the right copy down (the search still checks the title)."""
    try:
        length = float(text)
    except ValueError:
        return 0.0
    return 0.0 if length == int(length) else length


def vdj_grid(scan) -> tuple[float, float] | None:
    """VirtualDJ's beat grid from its <Scan>: Phase is a beat's time (s), Bpm the seconds per beat."""
    try:
        anchor, period = float(scan.get("Phase")), float(scan.get("Bpm"))
    except (AttributeError, TypeError, ValueError):
        return None
    return (anchor, period) if 0.2 < period < 1.5 else None


# --- lining the copy up with the stream ---------------------------------------------------------------------
#
# A copy from YouTube is the same recording, but rarely cut the same: a few ms to half a second more or less
# at the start (another upload, its own encoder's padding). Played at the stream's position, every hit then
# lands that much late (or early). The DJ software's beat grid of the stream says where its beats are: the
# copy's own beats (the analysis) against it give the offset. Trusted only when it is clear: the grid steady
# against our beats, the same tempo (or the grid at half of ours), and an offset the two lengths allow (the
# extra or missing audio is at the start or the end, so the offset lies between 0 and the length difference).

GRID_SPREAD_S = 0.03  # our beats scatter at most this much around the grid's: the same beats
GRID_SLACK_S = 0.04  # the offset may lie this far outside 0 … the length difference (a length is a little off)
GRID_TEMPO = 0.01  # the grid's tempo within this much of ours (or of half of it)


def copy_offset(beats, copy_length: float, stream: Stream) -> float | None:
    """How much later in the copy the same moment comes than in the stream (s): play the copy at the stream's
    position + this. None: not known (no grid, not clear): play it at the stream's position."""
    import numpy as np

    beats = np.asarray(beats, float)
    if stream.grid is None or len(beats) < 16:
        return None
    anchor, period = stream.grid
    ours = float(np.median(np.diff(beats)))
    if not any(abs(period / ours - k) <= GRID_TEMPO * k for k in (1, 2)):
        return None
    angle = 2 * np.pi * (beats - anchor) / ours  # each beat's place in the grid's beat, as an angle
    mean = np.mean(np.exp(1j * angle))
    if abs(mean) < 1e-6 or ours / (2 * np.pi) * np.sqrt(-2 * np.log(min(abs(mean), 1.0))) > GRID_SPREAD_S:
        return None  # (the circular spread of our beats around the grid's)
    offset = float(np.angle(mean)) / (2 * np.pi) * ours  # within ± half a beat
    if not stream.length or not copy_length:
        return offset if abs(offset) <= GRID_SLACK_S else None
    diff = copy_length - stream.length
    lo, hi = min(0.0, diff) - GRID_SLACK_S, max(0.0, diff) + GRID_SLACK_S
    fits = [c for c in (offset + k * ours for k in range(-3, 4)) if lo <= c <= hi]
    return min(fits, key=abs) if fits else None


def vdj_streams(db: Path) -> dict[str, Stream]:
    """Every streamed track VirtualDJ's database knows, by the path its decks report ("netsearch://sp…").
    VirtualDJ can leave bytes of a longer, older file after its closing tag (a NUL, "e>"): those are ignored."""
    import io
    import xml.etree.ElementTree as ET

    data = db.read_bytes()
    end = data.rfind(b"</VirtualDJ_Database>")
    if end >= 0:
        data = data[: end + len(b"</VirtualDJ_Database>")]
    found: dict[str, Stream] = {}
    for _, song in ET.iterparse(io.BytesIO(data), events=("end",)):
        if song.tag != "Song":
            continue
        m = NETSEARCH.fullmatch(song.get("FilePath") or "")
        tags, infos = song.find("Tags"), song.find("Infos")
        if m and tags is not None and tags.get("Title"):
            found[m.group(0)] = Stream(
                SERVICES.get(m.group(1), m.group(1)), m.group(2), tags.get("Title", ""), tags.get("Author", ""),
                length=vdj_length(infos.get("SongLength", "") if infos is not None else ""),
                grid=vdj_grid(song.find("Scan")),
            )  # fmt: skip
        song.clear()
    return found


class VdjStreams:
    """VirtualDJ's streamed tracks, read again when a deck reports one we don't know and the database changed."""

    def __init__(self, db: Path = VDJ_DATABASE):
        self.db = db
        self.known: dict[str, Stream] = {}
        self.mtime = 0.0

    def find(self, file: str) -> Stream | None:
        if not NETSEARCH.fullmatch(file or ""):
            return None
        if file not in self.known or not self.known[file].length:  # VirtualDJ writes the real length later
            try:
                mtime = self.db.stat().st_mtime
                if mtime != self.mtime:
                    self.mtime = mtime  # a database that doesn't read is tried again when it changes, not every packet
                    self.known = vdj_streams(self.db)
            except (OSError, ValueError, SyntaxError) as e:  # SyntaxError: ElementTree's ParseError
                print(f"  ⚠ VirtualDJ database: {e}", flush=True)
        return self.known.get(file)


# --- finding and fetching a copy ----------------------------------------------------------------------------


def score(stream: Stream, hit: dict) -> float | None:
    """How likely a search result is the streamed recording itself; None: it isn't (wrong length, or a version)."""
    length = hit.get("duration")
    if not length or (stream.length and abs(length - stream.length) > stream.slack + 1.0):
        return None  # search results round to whole seconds: the download is checked exactly
    title = set(words(hit.get("title") or ""))
    want = set(words(stream.title))
    if want and len(want & title) < max(1, len(want) // 2):
        return None
    extra = (title - want - set(words(stream.artist))) & SHUNNED
    if extra:
        return None  # "live", "slowed", "1 hour", … that the streamed title doesn't have
    channel = hit.get("channel") or hit.get("uploader") or ""
    s = len(want & title) / max(1, len(want))
    s += 1.0 if channel.endswith(" - Topic") else 0.0  # the label's own upload: the master itself
    s += 0.5 if set(words(stream.artist.split(",")[0])) & set(words(channel)) else 0.0  # the artist's channel
    s -= abs(length - stream.length) / 10 if stream.length else 0.0
    return s


class Fetcher:
    """Local copies of streamed tracks, kept in the cache. Gentle on YouTube: one search or download at a time,
    GAP_S apart, and only for tracks on a deck (a track the DJ has unloaded again by its turn is skipped)."""

    def __init__(self, folder: Path = FOLDER):
        import yt_dlp  # noqa: F401 (fail here, at start, when it isn't installed)

        self.folder = folder
        self.queue: queue.Queue[Stream] = queue.Queue()
        self.state: dict[str, str] = {}  # stream id → "waiting" | "running" | "done" | "failed"
        self.why: dict[str, str] = {}
        self.offline_at: dict[str, float] = {}  # stream id → when its fetch failed for want of a connection
        self.asked: dict[str, float] = {}  # stream id → when a deck last asked for it
        self.last = 0.0  # when we last asked YouTube anything
        self.lock = threading.Lock()
        threading.Thread(target=self._work, daemon=True, name="fetch").start()

    def _stem(self, s: Stream) -> str:
        safe = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", s.name)[:150]
        return f"{safe} [{s.service}-{s.id}]"

    def cached(self, s: Stream) -> str:
        if self.folder.is_dir():
            for f in self.folder.glob(glob.escape(self._stem(s)) + ".*"):
                if f.suffix not in {".json", ".part", ".ytdl"} and f.stem == self._stem(s):
                    return str(f)
        return ""

    def file(self, s: Stream) -> str:
        """The copy's path; "" while it is being fetched (or couldn't be): then this queues the fetch."""
        self.asked[s.id] = time.monotonic()
        if (self.state.get(s.id) == "done" or s.id not in self.state) and (f := self.cached(s)):
            self.state[s.id] = "done"
            return f
        if not s.guess and s.id not in self.state:  # perhaps found by its title before the library knew it
            g = guessed(s.title, s.artist, s.length)
            if self.state.get(g.id) in ("waiting", "running"):
                self.asked[g.id] = time.monotonic()
                return ""  # that copy is on its way: checked against this one when it is in
            if f := self._adopt(s, g):
                return f
        with self.lock:
            if s.id in self.offline_at and time.monotonic() - self.offline_at[s.id] > OFFLINE_RETRY_S:
                del self.offline_at[s.id], self.state[s.id]  # perhaps back online: once more
            if s.id not in self.state:
                self.state[s.id] = "waiting"
                self.queue.put(s)
        return ""

    def _adopt(self, s: Stream, g: Stream) -> str:
        """The guess's copy, when it is the same recording as `s` (its length): kept under its own name (the
        show made from it plays on), and linked under s's (found next time). "": none, or another version."""
        f = self.cached(g)
        if not f:
            return ""
        f = Path(f)
        try:
            length = float(json.loads(f.with_suffix(".json").read_text(encoding="utf-8")).get("length") or 0.0)
        except (OSError, ValueError):
            length = 0.0
        if s.length and length and abs(length - s.length) > LENGTH_MATCH_S:
            print(f"  ⚠ {s.name}: the copy found by its title is another version ({length - s.length:+.1f} s vs "
                  f"{s.service.title()}): looking again by ISRC", flush=True)  # fmt: skip
            f.unlink(missing_ok=True)
            f.with_suffix(".json").unlink(missing_ok=True)
            self.state.pop(g.id, None)
            return ""
        link = f.with_name(self._stem(s) + f.suffix)
        link.unlink(missing_ok=True)
        system.link_or_copy(f, link)
        meta = {"stream": s.__dict__, "copy_of": f.name, "length": length,
                "fetched": time.strftime("%Y-%m-%d %H:%M:%S")}  # fmt: skip
        link.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        self.state[s.id] = "done"
        delta = f"{(length - s.length) * 1000:+.0f} ms vs {s.service.title()}" if s.length and length else "same"
        print(f"  ✓ {s.name}: the copy found by its title is the same recording ({delta})", flush=True)
        return str(f)

    def _work(self):
        while True:
            s = self.queue.get()
            if time.monotonic() - self.asked.get(s.id, 0.0) > WANTED_S:
                with self.lock:  # no longer on a deck: forget it (it is queued again if it comes back)
                    self.state.pop(s.id, None)
                continue
            self.state[s.id] = "running"
            self._fetch(s)

    def _polite(self):
        """At most one request to YouTube every GAP_S."""
        time.sleep(max(0.0, self.last + GAP_S - time.monotonic()))
        self.last = time.monotonic()

    def _fetch(self, s: Stream):
        t0 = time.monotonic()
        try:
            how = "not in the library yet, by artist and title" if s.guess else f"streamed from {s.service.title()}"
            print(f"  ⇣ {s.name}: {how}, looking for the same recording …", flush=True)
            hits = self._search(s)
            if not hits:
                raise LookupError("no copy of the same length found")
            best = None  # (how far off, file, hit, length)
            for hit in hits[:DOWNLOADS]:
                got = self._download(s, hit)
                if got is None:
                    continue
                f, length = got
                off = abs(length - s.length) if s.length else 0.0
                if off <= s.slack and (best is None or off < best[0]):
                    if best:
                        best[1].unlink(missing_ok=True)
                    best = (off, f, hit, length)
                else:
                    f.unlink(missing_ok=True)  # another version after all
                if best and best[0] <= (s.slack if s.guess else EXACT_S):
                    break  # the same length to the frame (a guess: to the second): the same recording
            if best is None:
                raise LookupError("no download of the same length")
            off, f, hit, length = best
            keep = f.with_name(self._stem(s) + f.suffix)
            f.replace(keep)
            vs = "the deck's clock" if s.guess else s.service.title()
            delta = f"{(length - s.length) * 1000:+.0f} ms vs {vs}" if s.length else "length unknown"
            print(f"  ✓ {s.name}: copy from YouTube {hit['id']} ({delta}, {time.monotonic() - t0:.1f} s)", flush=True)
            if off > EXACT_S and not s.guess:
                print("    (its length differs a little: a slightly different master; on SYNC the beat corrects it)")
            meta = {"stream": s.__dict__, "youtube": hit["id"], "channel": hit.get("channel"),
                    "length": length, "fetched": time.strftime("%Y-%m-%d %H:%M:%S")}  # fmt: skip
            keep.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
            self.state[s.id] = "done"
        except Exception as e:  # a failed fetch leaves the deck dark, as before; say why once
            self.state[s.id], self.why[s.id] = "failed", str(e)
            if offline(e):
                self.offline_at[s.id] = time.monotonic()
                print(f"  ⚠ {s.name}: no copy: no internet connection? (trying again in 30 s)", flush=True)
            else:
                print(f"  ⚠ {s.name}: no copy to light it with ({e})", flush=True)

    def _search(self, s: Stream) -> list[dict]:
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "playlistend": SEARCH}
        found: dict[str, tuple[float, dict]] = {}
        queries = ([s.isrc] if s.isrc else []) + [f"{s.artist.split(',')[0]} {s.title}", f"{s.name} audio"]
        with yt_dlp.YoutubeDL(opts) as y:
            for q in queries:
                self._polite()
                for hit in (y.extract_info(f"ytsearch{SEARCH}:{q}", download=False) or {}).get("entries") or []:
                    sc = score(s, hit)
                    if sc is not None and hit.get("id"):
                        sc += 2.0 if q == s.isrc else 0.0  # found by the recording's own code
                        found[hit["id"]] = max(found.get(hit["id"], (sc, hit)), (sc, hit), key=lambda x: x[0])
                if any(sc >= 2.0 for sc, _ in found.values()):
                    break  # the label's upload (or an ISRC hit): no need to look further
        return [h for _, h in sorted(found.values(), key=lambda x: -x[0])][:3]

    def _download(self, s: Stream, hit: dict) -> tuple[Path, float] | None:
        import yt_dlp

        from amadeus.show.sources.resolve import length_of

        self.folder.mkdir(parents=True, exist_ok=True)
        opts = {"quiet": True, "no_warnings": True, "noprogress": True, "format": QUALITY, "noplaylist": True,
                "outtmpl": str(self.folder / f"{self._stem(s)}.{hit['id']}.%(ext)s")}  # fmt: skip
        for wait in (2.0, 5.0, None):  # YouTube refuses a download now and then (403): again, a bit later
            self._polite()
            try:
                with yt_dlp.YoutubeDL(opts) as y:
                    info = y.extract_info(f"https://www.youtube.com/watch?v={hit['id']}", download=True)
                    f = Path(y.prepare_filename(info))
                return f, length_of(f) or _probe_length(f) or float(info.get("duration") or 0)
            except Exception as e:
                if offline(e):
                    raise  # no connection: the next candidate won't come either
                if wait is None:
                    print(f"  ⚠ {s.name}: YouTube {hit['id']}: {e}", flush=True)
                    return None
                time.sleep(wait)
        return None

    def status(self, s: Stream) -> str:
        return self.state.get(s.id, "")


def offline(e: Exception) -> bool:
    """The error of a request that couldn't reach YouTube at all (no connection, no name lookup)."""
    text = str(e).lower()
    return any(w in text for w in ("nodename nor servname", "name or service not known", "getaddrinfo",
                                   "network is unreachable", "no route to host", "timed out", "connection refused",
                                   "temporary failure in name resolution", "internet connection"))  # fmt: skip


def _probe_length(f: Path) -> float | None:
    """Length of a file soundfile can't read (WebM, M4A): ffprobe (next to ffmpeg), else the system's own
    (macOS's afinfo, Windows' Media Foundation)."""
    import subprocess
    import sys

    from amadeus.audio.analysis import ffmpeg

    tool = ffmpeg()
    try:
        if tool:
            probe = Path(tool).with_name("ffprobe" + Path(tool).suffix)  # ffprobe.exe on Windows
            out = subprocess.run(
                [str(probe), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL,
                **({"creationflags": 0x08000000} if sys.platform == "win32" else {}),  # no console window
            )  # fmt: skip
            return float(out.stdout.strip())
        if sys.platform == "win32":
            from amadeus.audio import winmf

            return winmf.duration(f)
        out = subprocess.run(["/usr/bin/afinfo", str(f)], capture_output=True, text=True, timeout=20)
        m = re.search(r"estimated duration: ([\d.]+)", out.stdout)
        return float(m.group(1)) if m else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
