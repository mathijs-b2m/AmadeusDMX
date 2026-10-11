"""Which file on this computer a DJ software's track is.

Most DJ software reports a path; some only an artist, a title and a length (or a path from another
computer). The show needs the audio itself, so we look for it: the path as given, then a file of that name,
then a file whose name holds the artist and the title, its length deciding between look-alikes.

Where to look: DECISIVE_MUSIC (folders separated by ':'), else ~/Music.
"""

from __future__ import annotations

import os
import re
import threading
import unicodedata
from pathlib import Path

AUDIO = {".mp3", ".wav", ".flac", ".aiff", ".aif", ".m4a", ".aac", ".ogg", ".opus", ".alac"}
LENGTH_TOLERANCE_S = 2.5


def roots() -> list[Path]:
    env = os.environ.get("DECISIVE_MUSIC")
    return [Path(p).expanduser() for p in env.split(":") if p] if env else [Path.home() / "Music"]


def words(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return [w for w in re.split(r"[^a-z0-9]+", s) if w]


def length_of(path: Path) -> float | None:
    try:
        import soundfile as sf

        info = sf.info(str(path))
        return info.frames / info.samplerate
    except Exception:
        return None


class Resolver:
    """Finds tracks in the music folders; the folders are indexed once, in the background."""

    def __init__(self, folders: list[Path] | None = None):
        self.folders = folders if folders is not None else roots()
        self.files: list[Path] = []
        self.by_name: dict[str, list[Path]] = {}
        self.ready = threading.Event()
        self.memo: dict[tuple, str | None] = {}
        threading.Thread(target=self._index, daemon=True).start()

    def _index(self):
        files = []
        for root in self.folders:
            for dirpath, dirnames, names in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                files += [Path(dirpath) / n for n in names if Path(n).suffix.lower() in AUDIO]
        self.files = files
        for f in files:
            self.by_name.setdefault(f.name.lower(), []).append(f)
        self.ready.set()

    def find(self, path: str = "", artist: str = "", title: str = "", length: float = 0.0, wait: float = 0.0) -> str:
        """The local file, or "" (unknown, or the music folders are still being indexed)."""
        key = (path, artist, title, round(length))
        if key in self.memo:
            return self.memo[key] or ""
        if path and Path(path).is_file():
            self.memo[key] = path
            return path
        if not self.ready.wait(wait):
            return ""
        found = self._by_name(path, length) or self._by_words(artist, title, length)
        self.memo[key] = found
        return found or ""

    def _by_name(self, path: str, length: float) -> str | None:
        name = Path(path.replace("\\", "/")).name.lower() if path else ""
        same = self.by_name.get(name, []) if name else []
        return str(self._closest(same, length)) if same else None

    def _by_words(self, artist: str, title: str, length: float) -> str | None:
        want_title, want_artist = set(words(title)), set(words(artist))
        if not want_title:
            return None
        hits = []
        for f in self.files:
            have = set(words(f.stem)) | set(words(f.parent.name))
            if want_title <= have:
                hits.append((len(want_artist & have), f))
        if not hits:
            return None
        best = max(n for n, _ in hits)
        return str(self._closest([f for n, f in hits if n == best], length))

    def _closest(self, files: list[Path], length: float) -> Path:
        if len(files) == 1 or not length:
            return files[0]
        scored = [(abs((length_of(f) or 0) - length), f) for f in files]
        diff, f = min(scored, key=lambda x: x[0])
        return f if diff < LENGTH_TOLERANCE_S else files[0]
