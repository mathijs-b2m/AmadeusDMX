"""The beat grid: local tempo, beat tracking (dynamic programming), downbeats and the set's BPM."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

from decisive.audio.features import normalize


def beat_kicks(flux_kick: np.ndarray, beat_frames: np.ndarray, fps: float):
    """Kicks = beats with a strong low-end transient right on them.

    Peak-picking the low band also fires on offbeat bass notes; checking each
    beat instead gives a clean "is the kick running" signal and pump triggers
    that are locked to the grid.
    """
    env = normalize(flux_kick)
    lo, hi = -1, 3  # frames around the beat to look for the transient
    pulse, where = [], []
    for b in beat_frames:
        seg = env[max(b + lo, 0) : b + hi]
        j = int(np.argmax(seg)) if len(seg) else 0
        pulse.append(seg[j] if len(seg) else 0)
        where.append(max(b + lo, 0) + j)
    pulse = np.array(pulse)
    ref = np.percentile(pulse, 90) + 1e-9
    hit = pulse > 0.45 * ref
    return np.array(where)[hit] / fps, np.clip(pulse[hit] / ref, 0, 1).astype(np.float32)


def local_tempo(onset_env: np.ndarray, fps: float) -> np.ndarray:
    """BPM per frame from windowed autocorrelation with a prior around 125 BPM."""
    win, hop = int(fps * 12), int(fps * 3)
    min_lag, max_lag = int(fps * 60 / 185), int(fps * 60 / 85)
    lags = np.arange(min_lag, max_lag + 1)
    prior = np.exp(-0.5 * (np.log2((60 * fps / lags) / 125) / 0.5) ** 2)
    centers, bpms = [], []
    for s in range(0, max(1, len(onset_env) - win), hop):
        seg = onset_env[s : s + win] - onset_env[s : s + win].mean()
        ac = np.correlate(seg, seg, mode="full")[len(seg) - 1 :]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        score = ac[lags] * prior
        double = np.clip(2 * lags, 0, len(ac) - 1)  # reward lags whose double is also periodic
        score += 0.5 * ac[double] * prior
        i = int(np.argmax(score))
        lag = float(lags[i])
        if 0 < i < len(lags) - 1:  # parabolic refinement for sub-frame precision
            a, b, c = score[i - 1], score[i], score[i + 1]
            denom = a - 2 * b + c
            if denom != 0:
                lag += 0.5 * (a - c) / denom
        centers.append(s + win // 2)
        bpms.append(60 * fps / lag)
    if not bpms:
        return np.full(len(onset_env), 125.0)
    bpms = median_filter(np.array(bpms), size=9, mode="nearest")  # DJ tempo moves slowly
    return np.interp(np.arange(len(onset_env)), centers, bpms)


def track_beats(onset_env: np.ndarray, bpm: np.ndarray, fps: float, tightness: float = 400):
    """Dynamic-programming beat tracker (Ellis 2007) with a time-varying period."""
    n = len(onset_env)
    period = 60 * fps / bpm
    score = onset_env.astype(np.float64).copy()
    back = np.full(n, -1, dtype=np.int64)
    for t in range(n):
        p = period[t]
        lo, hi = int(t - 2 * p), int(t - p / 2)
        if hi <= 0:
            continue
        prev = np.arange(max(lo, 0), hi)
        cand = score[prev] - tightness * np.log((t - prev) / p) ** 2
        j = int(np.argmax(cand))
        score[t] = onset_env[t] + cand[j]
        back[t] = prev[j]
    tail = int(period[-1])
    t = n - tail + int(np.argmax(score[n - tail :]))
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    return np.array(beats[::-1], dtype=int)


def downbeats(beat_frames: np.ndarray, accent_env: np.ndarray) -> np.ndarray:
    """Pick the bar phase (0..3) per 64-beat window; assumes 4/4 like nearly all DJ music."""
    strength = accent_env[beat_frames]
    phases = []
    for s in range(0, len(beat_frames), 64):
        seg = strength[s : s + 64]
        scores = [seg[((np.arange(len(seg)) + s) % 4) == p].mean() if len(seg) > 4 else 0 for p in range(4)]
        phases.append(int(np.argmax(scores)))
    if len(phases) >= 3:  # a phase flip needs agreement from neighbours
        phases = list(median_filter(np.array(phases), size=3, mode="nearest"))
    idx = [i for i in range(len(beat_frames)) if i % 4 == phases[min(i // 64, len(phases) - 1)]]
    return np.array(idx, dtype=int)


def set_bpm(beat_times: np.ndarray) -> float:
    """Mean of the central beat intervals: the median of integer-frame intervals is quantised (~2 BPM steps)."""
    iv = np.diff(beat_times)
    if len(iv) < 2:
        return 0.0
    lo, hi = np.percentile(iv, [20, 80])
    return float(60 / iv[(iv >= lo) & (iv <= hi)].mean())
