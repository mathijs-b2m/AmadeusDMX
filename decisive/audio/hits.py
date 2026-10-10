"""Every hit of a track at its exact time, sorted into voices: what the cinematic program plays.

Music without a steady groove (film scores, trailers) can't be lit from a beat grid. This pass finds each
accent where it really is, with no grid: spectral flux in nine log-spaced bands, peaks picked against
their own surroundings. Every hit gets:

- its time (to the analysis frame, ~21 ms), its strength (against the last few seconds, and how loud),
- how long it rings (the time its dominant band takes to fall 9 dB: a stab vs a boom),
- its spectral fingerprint, and from that a **voice**: hits that sound alike share one (k-means over the
  fingerprints). Voices are ordered from the lowest (booms) to the highest (ticks, shimmer), like the
  drums of a kit; the show gives each voice its own fixtures.
- **impacts**: the very biggest broadband hits (the whole rig plays them).

The low end gets its own detector (booms under dense music would drown in the total), and the sustained low
end (drones, rumble) is kept as an envelope for the floor glow.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import maximum_filter1d, median_filter

from decisive import paths

VERSION = 4
N_FFT, HOP = 2048, 512
EDGES_HZ = [30, 60, 120, 250, 500, 1000, 2000, 4000, 8000, 11000]  # nine bands, an octave each
LOW_BANDS = 2  # the first two (30–120 Hz): booms, sub drops
MIN_GAP_S = 0.07  # two hits closer than this are one
VOICES = 8
IMPACT_SHARE = 0.03  # the strongest 3% of broadband hits are impacts


@dataclass
class Hits:
    t: np.ndarray  # seconds
    strength: np.ndarray  # 0..1
    decay: np.ndarray  # seconds to fall 9 dB
    voice: np.ndarray  # 0 = lowest … VOICES - 1 = highest
    impact: np.ndarray  # bool
    pitch: np.ndarray  # 0..1: where the hit's energy sits, low → high (spectral centroid, log)
    low: np.ndarray  # per analysis frame, 0..1: the sustained low end (drones, rumble)
    fps: float

    def __len__(self) -> int:
        return len(self.t)


def _bands(path: Path):
    """Per frame, the log energy (dB) of each band, and the frame rate (as the analysis: 24 kHz, hop 512)."""
    info = sf.info(str(path))
    factor = 2 if info.samplerate >= 44100 else 1
    sr = info.samplerate // factor
    freqs = np.fft.rfftfreq(N_FFT, 1 / sr)
    masks = [(freqs >= lo) & (freqs < hi) for lo, hi in zip(EDGES_HZ[:-1], EDGES_HZ[1:])]
    lowpass = signal.firwin(101, 0.45 * sr, fs=info.samplerate) if factor > 1 else None
    window = np.hanning(N_FFT).astype(np.float32)
    rows, carry, zi = [], np.zeros(0, np.float32), None
    for block in sf.blocks(str(path), blocksize=info.samplerate * 20, dtype="float32", always_2d=True):
        mono = block.mean(axis=1)
        if lowpass is not None:
            if zi is None:
                zi = signal.lfilter_zi(lowpass, 1.0) * mono[0]
            mono, zi = signal.lfilter(lowpass, 1.0, mono, zi=zi)
            mono = mono[::factor]
        buf = np.concatenate([carry, mono.astype(np.float32)])
        n = (len(buf) - N_FFT) // HOP + 1
        if n <= 0:
            carry = buf
            continue
        frames = np.lib.stride_tricks.sliding_window_view(buf, N_FFT)[::HOP][:n]
        power = np.abs(np.fft.rfft(frames * window, axis=1)) ** 2
        carry = buf[n * HOP :]
        rows.append(np.stack([10 * np.log10(power[:, m].mean(axis=1) + 1e-10) for m in masks], axis=1))
    return np.concatenate(rows), sr / HOP


def _peaks(novelty: np.ndarray, fps: float, above: float) -> np.ndarray:
    """Frames where `novelty` peaks clearly (`above`) over its surroundings (a 1.5 s moving median)."""
    floor = median_filter(novelty, size=int(fps * 1.5) | 1, mode="nearest")
    local_max = novelty == maximum_filter1d(novelty, size=max(3, int(fps * MIN_GAP_S) * 2 + 1))
    cand = np.flatnonzero(local_max & (novelty > floor + above))
    keep, gap = [], int(fps * MIN_GAP_S)
    for c in cand:
        if not keep or c - keep[-1] >= gap:
            keep.append(c)
        elif novelty[c] > novelty[keep[-1]]:
            keep[-1] = c
    return np.array(keep, dtype=int)


def _kmeans(x: np.ndarray, k: int, iters: int = 40) -> np.ndarray:
    """Deterministic k-means (farthest-point start); returns each row's cluster."""
    k = min(k, len(x))
    centres = [x[np.argmin(x[:, 0])]]  # the lowest-sounding hit first
    for _ in range(1, k):
        d = np.min([np.sum((x - c) ** 2, axis=1) for c in centres], axis=0)
        centres.append(x[int(np.argmax(d))])
    c = np.array(centres)
    for _ in range(iters):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        new = np.array([x[lab == i].mean(axis=0) if np.any(lab == i) else c[i] for i in range(k)])
        if np.allclose(new, c):
            break
        c = new
    return lab


def detect(path: Path) -> Hits:
    E, fps = _bands(path)  # (frames, 9) dB
    n_frames = len(E)
    rise = np.maximum(0.0, np.diff(E, axis=0, prepend=E[:1]))  # dB each band jumped since the last frame
    broad = rise.sum(axis=1)
    lows = rise[:, :LOW_BANDS].sum(axis=1)
    frames = np.union1d(_peaks(broad, fps, 7.0), _peaks(lows, fps, 4.0))
    if len(frames) == 0:
        return Hits(*(np.zeros(0) for _ in range(6)), low=np.zeros(n_frames, np.float32), fps=fps)
    keep = [frames[0]]  # hits found by both detectors a frame or two apart are one
    for f in frames[1:]:
        if f - keep[-1] >= int(fps * MIN_GAP_S):
            keep.append(f)
    frames = np.array(keep)

    level = E.mean(axis=1)
    lo, hi = np.percentile(level, 5), np.percentile(level, 99)
    loud = np.clip((level - lo) / max(hi - lo, 1), 0, 1)
    top = np.percentile(broad[frames], 97) + 1e-9
    centres = np.sqrt(np.array(EDGES_HZ[:-1]) * np.array(EDGES_HZ[1:]))
    strength, decay, sig, pitch = [], [], [], []
    for k, f in enumerate(frames):
        r = rise[f] + rise[min(f + 1, n_frames - 1)]  # the onset can straddle two frames
        # strength: how big the jump is (against the track's biggest) and how loud it is there
        strength.append(float(np.clip(0.65 * broad[f] / top + 0.35 * loud[min(f + 2, n_frames - 1)], 0, 1)))
        band = int(np.argmax(r))
        peak = E[min(f + 2, n_frames - 1), band]
        end = frames[k + 1] if k + 1 < len(frames) else min(n_frames, f + int(fps * 3))
        after = E[f:end, band]
        below = np.flatnonzero(after < peak - 6)
        rings = (below[0] if len(below) else len(after)) / fps  # until it fades, or the next hit
        decay.append(float(np.clip(rings, 0.06, 3.0)))
        s_ = r / (r.sum() + 1e-9)
        sig.append(s_)
        pitch.append(
            float(np.clip((np.log2(np.sum(s_ * centres)) - np.log2(30)) / (np.log2(11000) - np.log2(30)), 0, 1))
        )
    strength, decay, sig, pitch = map(np.array, (strength, decay, sig, pitch))

    # voices: k-means on the fingerprint (and how long it rings), ordered low → high
    feats = np.hstack([sig, np.log(decay)[:, None] * 0.15])
    lab = _kmeans(feats, VOICES)
    order = np.argsort([pitch[lab == i].mean() if np.any(lab == i) else 9 for i in range(lab.max() + 1)])
    voice = np.argsort(order)[lab]
    impact = np.zeros(len(frames), dtype=bool)
    n_top = max(1, int(len(frames) * IMPACT_SHARE))
    broadness = 1 - np.max(sig, axis=1)  # energy spread over many bands
    impact[np.argsort(strength * (0.5 + broadness))[-n_top:]] = True

    low = E[:, :LOW_BANDS].mean(axis=1)
    low = np.clip((low - np.percentile(low, 10)) / max(np.percentile(low, 99) - np.percentile(low, 10), 1), 0, 1)
    low = np.convolve(low, np.ones(9) / 9, mode="same")  # ~200 ms: a glow, not a flicker
    return Hits(frames / fps, strength, decay, voice, impact, pitch, low.astype(np.float32), fps)


def load_or_detect(path: str | Path, cache_dir: Path = paths.CACHE) -> Hits:
    path = Path(path)
    st = path.stat()
    key = hashlib.sha1(f"{path.resolve()}|{st.st_size}|{st.st_mtime}|{VERSION}".encode()).hexdigest()[:12]
    cached = Path(cache_dir) / f"{path.stem}.{key}.hits.npz"
    if cached.exists():
        z = np.load(cached)
        return Hits(z["t"], z["strength"], z["decay"], z["voice"], z["impact"], z["pitch"], z["low"], float(z["fps"]))
    h = detect(path)
    np.savez_compressed(cached, t=h.t, strength=h.strength, decay=h.decay, voice=h.voice, impact=h.impact,
                        pitch=h.pitch, low=h.low, fps=h.fps)  # fmt: skip
    return h
