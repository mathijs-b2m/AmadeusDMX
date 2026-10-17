"""Rock's drum kit: the kick and the snare as the lights play them, read from the separated drums.

In a rock mix the drums sit under a wall of guitars: the band filters of the analysis hear the snare's crack
masked by the distorted chords (Guns N' Roses' "Paradise City": one snare a bar found in its loud outro, where
the drummer hits it on every beat). The separated drums (Demucs, amadeus/audio/stems.py) have no guitars, and
there the two drums are told apart by where their energy sits when they hit:

- the **kick**: the low end (35–120 Hz) well above the snare's body (150–400 Hz), the **snare** the other way
  round: the hits fall into two clusters, split in the middle (where they don't, a dense mix with cymbals over
  everything, the stem can't tell them apart and the analysis' own onsets are used);
- how long the snare **rings**: the time its crack and
  its reverb (1–6 kHz) take to die away, or the next hit cuts it. A big 80s snare rings for half a second, and
  the light rings with it;
- ghost notes (far under the loud hits of their drum) and hits too close to the one before are left out: the
  lights play the beat, not every stroke (no flicker).

Without the separated drums the kit comes from the analysis' own kick and snare onsets, with a typical ring.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from amadeus import system

VERSION = 5
HOP = 128  # ~6 ms at the stems' 22 kHz
LOW, BODY, CRACK = (35, 120), (150, 400), (1000, 6000)  # Hz
RISE_S = 0.03  # a hit: the bands rise over this long …
ONSET_DB = 8.0  # … by this many dB together
LOOK_S = 0.06  # a hit's level: the loudest of each band in this long after it
SPLIT_DB = 12.0  # kicks and snares: two clusters of (low end − body) this far apart, else the stem can't tell
SEPARATE = 3.5  # … and that clearly separate (Ashman's D)
MARGIN_DB = 2.0  # … and a hit this far on its side of the middle between them
GHOST_DB = 10.0  # hits this far under the loud hits of their drum (within LOCAL_S) are ghost notes
LOCAL_S = 8.0
RING_DB = 20.0  # the snare rings until its crack and reverb have fallen this far
RING_MAX_S = 1.0
DEFAULT_RING_S = 0.35  # a snare's ring when it can't be measured (no separated drums)
KICK_GAP_S, SNARE_GAP_S = 0.35, 0.3  # the lights play hits at least this far apart (the stronger one wins)
ALIGN_S = 0.08  # stem kicks this close to the analysis' kicks are the same hits (to put both on one clock)


@dataclass
class Kit:
    kick_t: np.ndarray
    kick_s: np.ndarray  # 0..1
    snare_t: np.ndarray
    snare_s: np.ndarray
    snare_ring: np.ndarray  # seconds the snare rings
    source: str = "mix"  # "stem": from the separated drums; "mix": the analysis' own onsets

    @staticmethod
    def empty() -> Kit:
        z = np.zeros(0)
        return Kit(z, z, z, z, z)


def _thin(t: np.ndarray, s: np.ndarray, gap: float) -> np.ndarray:
    """Indices of the hits to play: at least `gap` apart, the stronger hit first."""
    kept: list[int] = []
    for k in np.argsort(-s, kind="stable"):
        j = np.searchsorted(t[kept], t[k]) if kept else 0
        if all(abs(t[kept[x]] - t[k]) >= gap for x in (j - 1, j) if 0 <= x < len(kept)):
            kept.insert(j, int(k))
    return np.array(kept, dtype=int)


def _strength(t: np.ndarray, level: np.ndarray) -> np.ndarray:
    """0..1 by how close a hit is to the loud hits of its drum around it (a soft verse is played softly, not
    with ghost notes); NaN for ghost notes."""
    if not len(level):
        return level
    lo, hi = np.searchsorted(t, t - LOCAL_S), np.searchsorted(t, t + LOCAL_S)
    ref = np.array([np.percentile(level[a:b], 90) for a, b in zip(lo, hi)])
    s = 1.0 - (ref - level) / GHOST_DB
    return np.where(s > 0, np.clip(s, 0.3, 1.0), np.nan)


def _split(d: np.ndarray, loud: np.ndarray) -> float | None:
    """Where kicks (low end over body) and snares (body over low end) part, in dB of low end − body: the middle
    between the two clusters of the louder hits; None when there aren't two (a dense mix: cymbals over all)."""
    d = d[loud > np.percentile(loud, 40)] if len(loud) >= 32 else np.zeros(0)
    if len(d) < 32:
        return None
    lo, hi = np.percentile(d, [20, 80])
    for _ in range(30):  # two means in one dimension
        mid = (lo + hi) / 2
        if not (d < mid).any() or not (d >= mid).any():
            return None
        lo, hi = float(d[d < mid].mean()), float(d[d >= mid].mean())
    a, b = d[d < mid], d[d >= mid]
    apart = (hi - lo) * np.sqrt(2) / np.sqrt(a.var() + b.var() + 1e-9)  # Ashman's D: two clusters, not one wide
    share = len(b) / len(d)
    return mid if hi - lo >= SPLIT_DB and apart >= SEPARATE and 0.15 <= share <= 0.85 else None


def detect(drums: np.ndarray, sr: int) -> Kit:
    """The kick and the snare in a separated drum track (times on its own clock)."""
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import find_peaks, stft

    f, t, Z = stft(drums.astype(np.float32), sr, nperseg=1024, noverlap=1024 - HOP)
    power = np.abs(Z) ** 2
    del Z
    fps = sr / HOP

    low, body, crack = (10 * np.log10(power[(f >= lo) & (f < hi)].sum(0) + 1e-10) for lo, hi in (LOW, BODY, CRACK))
    del power
    k = max(1, int(RISE_S * fps))

    def rise(e):
        r = np.zeros_like(e)
        r[k:] = e[k:] - e[:-k]
        return np.maximum(r, 0)

    peaks, _ = find_peaks(rise(low) + rise(body) + rise(crack), height=ONSET_DB, distance=max(1, int(0.08 * fps)))
    if not len(peaks):
        return Kit.empty()
    look = max(1, int(LOOK_S * fps))
    lvl = {n: np.array([e[p : p + look].max() for p in peaks]) for n, e in (("low", low), ("body", body))}
    mid = _split(lvl["low"] - lvl["body"], np.maximum(lvl["low"], lvl["body"]))
    if mid is None:
        return Kit.empty()
    is_kick = lvl["low"] - lvl["body"] >= mid + MARGIN_DB
    is_snare = lvl["low"] - lvl["body"] <= mid - MARGIN_DB
    on = t[peaks]

    def drum(mask, level, gap):
        idx = np.flatnonzero(mask)
        s = _strength(on[idx], level[idx])
        idx, s = idx[~np.isnan(s)], s[~np.isnan(s)]
        keep = _thin(on[idx], s, gap)
        return idx[keep], s[keep]

    ki, ks = drum(is_kick, lvl["low"], KICK_GAP_S)
    si, ss = drum(is_snare, lvl["body"], SNARE_GAP_S)
    rings = []
    crack = uniform_filter1d(crack, max(1, int(RISE_S * fps)))  # the reverb's level, not its grain
    nxt_snare = np.r_[peaks[si[1:]], len(crack)]
    for i, nxt in zip(si, nxt_snare):  # until the crack and its reverb have died away, or the next snare
        p = peaks[i]
        top = crack[p : p + look].max()
        tail = crack[p : min(nxt, p + int(RING_MAX_S * fps))]
        below = np.flatnonzero(tail < top - RING_DB)
        rings.append((below[0] if len(below) else len(tail)) / fps)
    return Kit(on[ki], ks.astype(np.float32), on[si], ss.astype(np.float32), np.array(rings, np.float32), "stem")


def _cached(path: Path) -> Kit | None:
    """The kit of a separated track (detected once, cached next to its parts); None if not separated."""
    from amadeus.audio import stems

    d = stems._dir(path)
    f = d / "kit.npz"
    if f.exists():
        z = np.load(f)
        if int(z["version"]) == VERSION:
            return Kit(z["kick_t"], z["kick_s"], z["snare_t"], z["snare_s"], z["snare_ring"], "stem")
    drums = stems.cached_part(path, "drums")
    if drums is None:
        return None
    kit = detect(drums, stems.STEM_SR)
    system.save_npz(f, version=VERSION, kick_t=kit.kick_t, kick_s=kit.kick_s, snare_t=kit.snare_t,
                        snare_s=kit.snare_s, snare_ring=kit.snare_ring)  # fmt: skip
    return kit


def _from_mix(a) -> Kit:
    kt, ks = a.onsets.get("kick", (np.zeros(0), np.zeros(0)))
    st, ss = a.onsets.get("snare", (np.zeros(0), np.zeros(0)))
    kt, ks, st, ss = (np.asarray(x, float) for x in (kt, ks, st, ss))
    ki, si = _thin(kt, ks, KICK_GAP_S), _thin(st, ss, SNARE_GAP_S)
    return Kit(kt[ki], ks[ki], st[si], ss[si], np.full(len(si), DEFAULT_RING_S, np.float32))


def kit(a) -> Kit:
    """The kick and snare the lights play: from the separated drums when the track has been separated, put on
    the analysis' clock (its kicks are dated as heard), else from the analysis' own onsets."""
    try:
        got = _cached(Path(a.path)) if a.path else None
    except (OSError, ValueError):
        got = None
    if got is None or len(got.kick_t) + len(got.snare_t) < 16:
        return _from_mix(a)
    kt = np.asarray(a.onsets.get("kick", (np.zeros(0),))[0], float)
    shift = 0.0
    if len(kt) and len(got.kick_t):
        j = np.clip(np.searchsorted(kt, got.kick_t), 1, len(kt) - 1) if len(kt) > 1 else np.zeros(len(got.kick_t), int)
        near = np.where(np.abs(kt[j - 1] - got.kick_t) < np.abs(kt[j] - got.kick_t), j - 1, j) if len(kt) > 1 else j
        d = kt[near] - got.kick_t
        d = d[np.abs(d) < ALIGN_S]
        if len(d) >= 8:
            shift = float(np.median(d))
    return Kit(got.kick_t + shift, got.kick_s, got.snare_t + shift, got.snare_s, got.snare_ring, "stem")
