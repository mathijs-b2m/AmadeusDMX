"""Reggaeton's kick runs: the moments the kick leaves the dembow and plays "boom boom boom boom", eighths, often
speeding up into sixteenths, mostly right after a short gap and leading into the next part.

The analysis's frames (~23 ms) and its low end (sub and bass together) can't hear these: the 808 rings on
between the kicks, so the level barely rises on the next one, and a sixteenth after an eighth falls in the same
few frames. This pass reads the track's own audio again, only the kick's band (30–100 Hz) at ~7 ms, and finds
each kick by its jump out of the ring before it (the 808 is struck again: its level jumps well above the tail).

A run is three or more kicks in a row at most RUN_GAP_BEATS apart (eighths or faster), lasting at most
RUN_MAX_BEATS (longer: a groove that plays eighths, not a run), and standing out from the bars around it: a kick
that plays a syncopated figure every bar (plenty of reggaeton does) plays its groove, and the boom follows that.
Its landing is the kick that follows it on the beat, when there is one.
"""

from __future__ import annotations

import bisect
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from amadeus import paths, system

VERSION = 1
SR = 2205  # the kick's band needs no more (the audio is resampled down to this first: fast)
HOP = 16  # ~7 ms
BAND_HZ = (30.0, 100.0)
KICK_JUMP_DB = 6.0  # a kick: the level jumps at least this much over its lowest point in the PRE_S before …
PRE_S = 0.06
KICK_LEVEL_DB = 8.0  # … to within this much of a typical kick's peak (a bass note isn't one)
MIN_GAP_S = 0.09  # two kicks closer than this are one
RUN_GAP_BEATS = 0.6  # kicks this close (eighths or faster) chain into a run
RUN_MIN_KICKS = 3
RUN_MAX_BEATS = 8.0  # a run lasts at most two bars
LAND_BEATS = 1.25  # the kick after a run, at most this far after its last one, lands it
CALM_BEFORE_BEATS = 8.0  # a run stands out: the kick plays no more than CALM_FAST eighths in the beats before …
CALM_AFTER_BEATS = 4.0  # … and after it (a kick that plays such figures every bar is the groove, not a run)
CALM_FAST = 1


@dataclass
class KickRun:
    t: np.ndarray  # the run's kicks (seconds)
    s: np.ndarray  # their strengths 0..1
    land: float | None = None  # the kick the run lands on (None: it ends in a gap)

    @property
    def start(self) -> float:
        return float(self.t[0])

    @property
    def end(self) -> float:
        return float(self.t[-1])


@dataclass
class KickRuns:
    runs: list[KickRun] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.runs)

    def at(self, t: float, tail: float) -> tuple[int, KickRun] | None:
        """The run playing at time t, from its first kick to `tail` after its landing (or its last kick), and
        its index in the track."""
        i = bisect.bisect_right(self._starts, t + 0.001) - 1
        if i >= 0:
            r = self.runs[i]
            if t < (r.land if r.land is not None else r.end) + tail:
                return i, r
        return None

    @property
    def _starts(self) -> list[float]:
        if "_s" not in self.__dict__:
            self._s = [r.start for r in self.runs]
        return self._s


def kick_envelope(path: str | Path) -> tuple[np.ndarray, float]:
    """The kick band's level (dB) at ~7 ms, and its frame rate."""
    import soundfile as sf
    from scipy import signal

    y, sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    g = np.gcd(int(sr), SR)
    y = signal.resample_poly(y, SR // g, int(sr) // g).astype(np.float32)
    sos = signal.butter(4, BAND_HZ, btype="band", fs=SR, output="sos")
    x = signal.sosfiltfilt(sos, y)
    n = len(x) // HOP
    db = 10 * np.log10((x[: n * HOP].reshape(n, HOP) ** 2).mean(axis=1) + 1e-12)
    return db.astype(np.float32), SR / HOP


def _cached_envelope(path: Path, cache_dir: Path) -> tuple[np.ndarray, float]:
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{VERSION}".encode()).hexdigest()[:12]
    f = Path(cache_dir) / f"{path.stem}.{key}.kick.npz"
    if f.exists():
        z = np.load(f)
        return z["db"], float(z["fps"])
    db, fps = kick_envelope(path)
    system.save_npz(f, db=db, fps=fps)
    return db, fps


def kicks(db: np.ndarray, fps: float, beats: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Every kick in the kick band's level: (times at the jump, strengths 0..1)."""
    if len(db) < 16 or len(beats) < 8:
        return np.zeros(0), np.zeros(0, np.float32)
    pre = max(2, int(round(PRE_S * fps)))
    from scipy.ndimage import maximum_filter1d, minimum_filter1d

    low = minimum_filter1d(db, pre, origin=(pre - 1) // 2)  # the lowest point in the PRE_S up to each frame
    ahead = maximum_filter1d(db, 4, origin=-2)  # the level reached in the next few frames
    jump = ahead - low
    on = [int(b * fps) for b in beats if int(b * fps) < len(db) - 30]
    peaks = [float(db[f : f + int(0.12 * fps)].max()) for f in on]  # a typical kick's peak: on the beats
    ref = float(np.median(peaks)) if peaks else float(db.max())
    cand = np.flatnonzero((jump >= KICK_JUMP_DB) & (ahead >= ref - KICK_LEVEL_DB))
    out_t, out_s, last = [], [], -1e9
    gap = int(MIN_GAP_S * fps)
    k = 0
    while k < len(cand):
        f = cand[k]
        e = k
        while e + 1 < len(cand) and cand[e + 1] - cand[e] <= 2:
            e += 1
        if f - last >= gap:  # the kick starts where the level itself has jumped (the jump looks a few frames ahead)
            seg = slice(f, min(len(db), cand[e] + 4))
            up = np.flatnonzero(db[seg] - low[f] >= KICK_JUMP_DB)
            f = f + int(up[0]) if len(up) else f
            out_t.append(f / fps)
            out_s.append(min(1.0, max(0.0, 1.0 - (ref - float(db[seg].max())) / (2 * KICK_LEVEL_DB))))
            last = f
        k = e + 1
    return np.array(out_t), np.array(out_s, np.float32)


def _fast(kt: np.ndarray, lo: float, hi: float, beat: float) -> int:
    """How many kicks in [lo, hi) follow the one before them as an eighth or faster."""
    w = kt[(kt >= lo) & (kt < hi)]
    return int((np.diff(w) <= RUN_GAP_BEATS * beat).sum())


def find_runs(kt: np.ndarray, ks: np.ndarray, beat: float) -> list[KickRun]:
    """The runs in a track's kicks (see the module's text)."""
    runs: list[KickRun] = []
    k = 0
    while k < len(kt):
        e = k
        while e + 1 < len(kt) and kt[e + 1] - kt[e] <= RUN_GAP_BEATS * beat:
            e += 1
        n = e - k + 1
        after = kt[e] + 0.6 * beat
        calm = (
            _fast(kt, kt[k] - CALM_BEFORE_BEATS * beat, kt[k] - 0.05, beat) <= CALM_FAST
            and _fast(kt, after, after + CALM_AFTER_BEATS * beat, beat) <= CALM_FAST
        )
        if n >= RUN_MIN_KICKS and kt[e] - kt[k] <= RUN_MAX_BEATS * beat and calm:
            land = float(kt[e + 1]) if e + 1 < len(kt) and kt[e + 1] - kt[e] <= LAND_BEATS * beat else None
            runs.append(KickRun(kt[k : e + 1].copy(), ks[k : e + 1].copy(), land))
        k = e + 1
    return runs


def kick_runs(a, cache_dir: Path = paths.CACHE) -> KickRuns:
    """The track's kick runs, from its audio (cached next to the analysis). Without the audio: none."""
    path = Path(getattr(a, "path", "") or "")
    if not path.is_file() or len(a.beats) < 8:
        return KickRuns()
    try:
        db, fps = _cached_envelope(path, cache_dir)
    except Exception:  # an unreadable file: the show plays without the runs
        return KickRuns()
    beat = float(np.median(np.diff(a.beats)))
    kt, ks = kicks(db, fps, a.beats)
    return KickRuns(find_runs(kt, ks, beat))
