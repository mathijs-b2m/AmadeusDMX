"""Dubstep's growl: the bass and synth leads of a drop, pulse by pulse, as the light plays them.

A brostep drop (Skrillex: "Scary Monsters and Nice Sprites", "First of the Year", "Bangarang") is carried by one
thing: a distorted bass that talks, growls and wobbles, its filter opened and closed by an LFO in 1/4, 1/8, 1/16 or
triplets, cut into stabs and yoys, a new sound every half bar. Under it the drums play half time (the kick on
the one, the snare on the three) and the growl ducks out of their way. The light that follows a drop follows that
growl: each pulse of it is a note, hit when the sound bites, held while it does, let go as the filter closes.

The growl lives in the separated bass and "other" stems (Demucs, amadeus/audio/stems.py): together they are the
synths without the drums and the voice. Its **bite** is their level from 250 Hz to 8 kHz at ~5 ms (the sub under
it hardly moves; the wobble is in the mids and highs, where the filter opens). A **pulse** starts where the bite
jumps JUMP_DB out of the dip before it to within NEAR_DB of the loud level around it, and lets go where it falls
DROP_DB from its peak (or the next pulse starts). Its **patch** counts the sounds: a pulse whose spectrum differs
from the patch's (its last pulses') by PATCH_DB (the bands' shape, not their level) is a new sound, the way a drop
swaps growls.

Measured on six Skrillex tracks (2026-11-26): wobbles in 1/8 and 1/16 (First of the Year 74–75 s: a 1/16 LFO,
9.7 Hz at 145 BPM), talking growls of 2–6 pulses a beat, the synths ducking 6–15 dB under every kick and snare.
Without the stems there is no growl (the mix's drums would be read as its pulses).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from amadeus import paths, system

VERSION = 2  # (2: pulses at least MIN_GAP_S apart with a DIP_DB dip, patches by their mean sound)
HOP = 110  # ~5 ms at the stems' 22 kHz
NFFT = 512
BITE = (250.0, 8000.0)  # Hz: where the growl's filter moves
PROFILE_EDGES = (250, 500, 1000, 2000, 4000, 8000)  # its sound: the level in these bands, relative to each other
LOUD_S = 4.0  # the loud level around a moment: the bite's LOUD_PCT percentile over this long
LOUD_PCT = 95
JUMP_DB = 5.0  # a pulse: the bite jumps this much over its lowest point in the PRE_S before …
PRE_S = 0.04
NEAR_DB = 9.0  # … to within this much of the loud level around it
DROP_DB = 6.0  # a pulse lets go where the bite falls this far from its peak
MIN_GAP_S = 0.06  # two pulses closer than this are one (1/32 at 140 BPM is 0.107 s, 1/16 triplets 0.071)
DIP_DB = 4.0  # … and between two pulses the bite dips at least this much
MAX_NOTE_S = 2.0  # a held growl lets go after this long at most (the light holds, then breathes)
QUIET_DB = 24.0  # a growl this far under the loud level of the whole track is no growl (a breakdown's pad)
PATCH_DB = 4.5  # a pulse whose sound differs this much (RMS over the bands' shape) from the patch's is a new patch
PATCH_MIN_S = 0.05  # (a pulse shorter than this keeps the patch: too short to tell)
PATCH_MEMORY = 8  # the patch's sound: the mean of its last this many pulses


@dataclass
class Growl:
    on: np.ndarray  # pulse onsets, seconds
    off: np.ndarray  # where each lets go
    s: np.ndarray  # strength 0..1
    patch: np.ndarray  # which sound (counts up as the drop swaps growls)
    source: str = "stem"  # "stem", or "" (no separated stems: no growl)

    @staticmethod
    def empty() -> Growl:
        z = np.zeros(0)
        return Growl(z, z, z, np.zeros(0, int), "")

    def __len__(self) -> int:
        return len(self.on)

    def between(self, lo: float, hi: float) -> np.ndarray:
        """Indices of the pulses starting in [lo, hi)."""
        return np.arange(np.searchsorted(self.on, lo), np.searchsorted(self.on, hi))

    def rate(self, lo: float, hi: float) -> float:
        """Pulses a second in [lo, hi) (where it growls: the gaps between its notes don't count)."""
        k = self.between(lo, hi)
        if len(k) < 2:
            return 0.0
        gaps = np.diff(self.on[k])
        gaps = gaps[gaps < 0.5]
        return float(1.0 / np.median(gaps)) if len(gaps) else 0.0


def bands(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, float]:
    """The bite (dB per frame), the sound's profile (dB per PROFILE band per frame) and the frame rate."""
    from scipy.signal import stft

    f, _, z = stft(x.astype(np.float32), sr, nperseg=NFFT, noverlap=NFFT - HOP, boundary=None, padded=False)
    p = np.abs(z) ** 2
    bite = 10 * np.log10(p[(f >= BITE[0]) & (f < BITE[1])].sum(0) + 1e-10)
    prof = np.stack(
        [10 * np.log10(p[(f >= lo) & (f < hi)].sum(0) + 1e-10) for lo, hi in zip(PROFILE_EDGES, PROFILE_EDGES[1:])]
    )
    return bite.astype(np.float32), prof.astype(np.float32), sr / HOP


def pulses(bite: np.ndarray, prof: np.ndarray, fps: float, t0: float = 0.0) -> Growl:
    """The growl's pulses in its bite (see the module's text); t0: the time of frame 0 (the frame's centre)."""
    from scipy.ndimage import maximum_filter1d, median_filter, minimum_filter1d, percentile_filter

    n = len(bite)
    if n < int(2 * fps):
        return Growl.empty()
    b = median_filter(bite, 3)
    stride = max(1, int(0.05 * fps))  # the loud level moves slowly: worked out on every 50 ms, then spread
    coarse = percentile_filter(b[::stride], LOUD_PCT, size=max(3, int(LOUD_S * fps / stride)))
    loud = np.interp(np.arange(n), np.arange(len(coarse)) * stride, coarse)
    floor = float(np.percentile(b, 99)) - QUIET_DB
    pre = max(2, int(round(PRE_S * fps)))
    low = minimum_filter1d(b, pre, origin=(pre - 1) // 2)
    ahead = maximum_filter1d(b, 3, origin=-1)
    cand = np.flatnonzero((ahead - low >= JUMP_DB) & (ahead >= loud - NEAR_DB) & (ahead >= floor))
    gap = max(1, int(MIN_GAP_S * fps))
    starts: list[int] = []
    for f in cand:
        if starts and f - starts[-1] < gap:
            continue
        if starts:  # a new pulse needs a dip after the last one's peak: a slow rise is one pulse, not two
            seg = b[starts[-1] : f + 1]
            top = int(np.argmax(seg))
            if seg[top] - seg[top:].min() < DIP_DB:
                continue
        starts.append(int(f))
    on, off, s, shapes = [], [], [], []
    longest = int(MAX_NOTE_S * fps)
    for k, f in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else min(n, f + longest)
        end = min(end, f + longest)
        seg = b[f:end]
        if not len(seg):
            continue
        top = np.maximum.accumulate(seg)
        fall = np.flatnonzero(seg < top - DROP_DB)
        stop = f + (int(fall[0]) if len(fall) else len(seg))
        peak = float(seg[: max(1, stop - f)].max())
        on.append(t0 + f / fps)
        off.append(t0 + max(stop, f + 1) / fps)
        s.append(float(np.clip(1.0 - (loud[f] - peak) / (2 * NEAR_DB), 0.3, 1.0)))
        shape = prof[:, f : max(stop, f + 1)].mean(1)
        shapes.append(shape - shape.mean())
    patch = np.zeros(len(on), int)
    sound, heard = (shapes[0], 1) if shapes else (None, 0)  # the current patch's sound: the mean of its pulses
    for k in range(1, len(on)):
        patch[k] = patch[k - 1]
        if off[k] - on[k] < PATCH_MIN_S:  # too short to tell its sound
            continue
        if float(np.sqrt(np.mean((shapes[k] - sound) ** 2))) >= PATCH_DB:
            patch[k] += 1
            sound, heard = shapes[k], 1
        else:
            sound, heard = (sound * heard + shapes[k]) / (heard + 1), min(heard + 1, PATCH_MEMORY)
    return Growl(np.array(on), np.array(off), np.array(s, np.float32), patch)


def _cache_file(path: Path, cache_dir: Path) -> Path:
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{VERSION}".encode()).hexdigest()[:12]
    return Path(cache_dir) / f"{path.stem}.{key}.growl.npz"


def growl(a, cache_dir: Path = paths.CACHE) -> Growl:
    """The track's growl, from its separated bass and synths (cached next to the analysis). Not separated yet:
    none (the show plays without it)."""
    from amadeus.audio import stems

    path = Path(getattr(a, "path", "") or "")
    if not path.is_file():
        return Growl.empty()
    try:
        f = _cache_file(path, cache_dir)
        if f.exists():
            z = np.load(f)
            return Growl(z["on"], z["off"], z["s"], z["patch"], str(z["source"]))
        bass, other = stems.cached_part(path, "bass"), stems.cached_part(path, "other")
        if bass is None or other is None:
            return Growl.empty()
        n = min(len(bass), len(other))
        bite, prof, fps = bands(bass[:n] + other[:n], stems.STEM_SR)
        g = pulses(bite, prof, fps, t0=0.5 * NFFT / stems.STEM_SR)
        system.save_npz(f, on=g.on, off=g.off, s=g.s, patch=g.patch, source=np.array(g.source))
        return g
    except (OSError, ValueError):
        return Growl.empty()
