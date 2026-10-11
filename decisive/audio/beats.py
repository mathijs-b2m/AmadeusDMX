"""The beat grid: local tempo, beat tracking (dynamic programming), refining it to what is heard, downbeats
and the set's BPM."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

from decisive.audio.features import normalize


def beat_kicks(flux_kick: np.ndarray, beat_frames: np.ndarray, fps: float, beat_times: np.ndarray | None = None):
    """Kicks = beats with a strong low-end transient right on them.

    Peak-picking the low band also fires on offbeat bass notes; checking each
    beat instead gives a clean "is the kick running" signal and pump triggers
    that are locked to the grid. With `beat_times` (the refined grid), a kick is dated at its beat.
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
    times = np.asarray(beat_times) if beat_times is not None else np.array(where) / fps
    return times[hit], np.clip(pulse[hit] / ref, 0, 1).astype(np.float32)


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


def comb(env: np.ndarray, fps: float, period: float, spread: float = 0.02, steps: int = 400):
    """The tempo and phase at which `env` rises most on an evenly spaced grid over the whole track.

    Every line of the grid is a sample of `env`; at the right tempo all of them land on hits, a hair off and
    they drift away over hundreds of beats. → (period, phase, score, median score over the tempos tried).
    """
    n = len(env)
    best = (period, 0.0, -1.0)
    scores = []
    for p in period * np.linspace(1 - spread, 1 + spread, steps):
        lines = np.arange(0.0, n / fps - p, p)
        phases = np.arange(0.0, p, 1.0 / fps)
        idx = np.round((lines[None, :] + phases[:, None]) * fps).astype(int)
        idx = np.minimum(idx, n - 1)
        sc = env[idx].mean(axis=1)
        j = int(np.argmax(sc))
        scores.append(sc[j])
        if sc[j] > best[2]:
            best = (float(p), float(phases[j]), float(sc[j]))
    return (*best, float(np.median(scores)))


def strongest_tempo(env: np.ndarray, fps: float, lo: float = 80.0, hi: float = 180.0) -> tuple[float, float]:
    """The tempo (BPM) at which `env` rises most on evenly spaced lines over the whole track, between `lo` and
    `hi`, and that score. A coarse pass, then `comb` around the best."""
    best_bpm, best = lo, -1.0
    for bpm in np.arange(lo, hi, 0.5):
        _, _, sc, _ = comb(env, fps, 60.0 / bpm, spread=0.0, steps=1)
        if sc > best:
            best_bpm, best = bpm, sc
    period, _, sc, _ = comb(env, fps, 60.0 / best_bpm, spread=0.005, steps=40)
    return 60.0 / period, sc


def comb_score(env: np.ndarray, fps: float, bpm: float) -> float:
    return comb(env, fps, 60.0 / bpm, spread=0.003, steps=13)[2]


def constant_grid(beat_times: np.ndarray, low_rise: np.ndarray, fps: float, agree: float = 0.7):
    """One straight grid for a track made at one tempo (most club music), or None.

    The tracker follows the music beat by beat; its tempo wobbles a little in breaks, and where the off-beats
    are as loud as the beats (hats, a rolling bass) it can drift half a beat off for a while. A track made at
    one tempo has one grid: the tempo and phase at which the low end (sub included) rises most on evenly
    spaced lines over the whole track, so on the kicks (`comb`). It is used when the tracker's own beats agree
    with it (`agree` of them on it, or half a beat off), then fitted to them exactly; else None (a mix, live
    drums, a tempo change).
    """
    if len(beat_times) < 64:
        return None
    env = normalize(low_rise)
    period, phase, score, typical = comb(env, fps, float(np.median(np.diff(beat_times))))
    if score < 1.3 * typical:  # no tempo stands out
        return None
    off = ((beat_times - phase) / period) % 1.0
    near = np.minimum(np.abs((off + 0.5) % 1.0 - 0.5), np.abs(off - 0.5))  # on the grid, or half a beat off
    if np.mean(near < 0.15) < agree:
        return None
    n = np.round((beat_times - phase) / period)
    on = np.abs(beat_times - (phase + n * period)) < 0.15 * period
    if on.sum() >= 16:  # the comb is as fine as a frame: the beats on it place it exactly
        period, phase = np.polyfit(n[on], beat_times[on], 1)
    first = int(np.ceil((beat_times[0] - phase) / period - 0.5))
    last = int(np.floor((beat_times[-1] - phase) / period + 0.5))
    grid = phase + period * np.arange(first, last + 1)
    return grid[grid >= 0.0]  # a grid continued back to before the track starts


def refine_beats(beat_frames: np.ndarray, onset_env: np.ndarray, fps: float, span: int = 8) -> np.ndarray:
    """Beat frames → beat times in seconds, finer than a frame (~21 ms) and steadier than the tracker.

    Each beat moves to the top of its onset (a parabola through the strongest frame near it and its two
    neighbours); then each beat takes its place on a straight line through its neighbours (±`span` beats).
    The tracker keeps beats near a tempo estimated over seconds; a tempo a fraction of a percent off makes them
    drift against the music and jump back. The line follows the music's own tempo, and its gradual changes.
    """
    n = len(onset_env)
    t = np.empty(len(beat_frames))
    for k, b in enumerate(beat_frames):
        lo, hi = max(b - 2, 1), min(b + 3, n - 1)
        j = lo + int(np.argmax(onset_env[lo:hi]))
        y0, y1, y2 = onset_env[j - 1], onset_env[j], onset_env[min(j + 1, n - 1)]
        den = y0 - 2 * y1 + y2
        t[k] = (j + (0.5 * (y0 - y2) / den if den < 0 else 0.0)) / fps
    if len(t) < 2 * span + 1:
        return t
    out = t.copy()
    idx = np.arange(len(t))
    for k in range(len(t)):
        lo = min(max(0, k - span), len(t) - 2 * span - 1)  # at the ends: a full window, slid inwards
        hi = lo + 2 * span + 1
        slope, icept = np.polyfit(idx[lo:hi], t[lo:hi], 1)
        fit = slope * k + icept
        if abs(fit - t[k]) < 0.25 * slope:  # not across a jump in the grid (a tempo change, a missed beat)
            out[k] = fit
    return out


def attack_offset(audio: np.ndarray, sr: int, beat_times: np.ndarray, max_s: float = 0.04) -> float:
    """How far after the beats the music's attack is, on average (seconds; 0 when it isn't clear).

    The loudness around every beat, averaged: one clean hit, wherever the beats really are. Its attack (where
    it is 30% up: a sound is noticed early in its rise) at sample precision, relative to the beat. Onsets are
    noticed before the sound is loud; this moves the grid to what is heard.
    """
    from scipy.signal import butter, sosfiltfilt

    env = sosfiltfilt(butter(2, 300, "low", fs=sr, output="sos"), audio.astype(np.float64) ** 2)
    w0, w1 = int(0.10 * sr), int(0.20 * sr)
    segs = [env[int(b * sr) - w0 : int(b * sr) + w1] for b in beat_times if w0 < b * sr < len(env) - w1]
    if len(segs) < 16:
        return 0.0
    avg = np.mean(segs, axis=0)
    # the hit right at the beat, not a later one in the same beat (a clap, a bass note): its peak within
    # -50..+60 ms, and the quietest point before it
    near = slice(w0 - int(0.05 * sr), w0 + int(0.06 * sr))
    peak = near.start + int(np.argmax(avg[near]))
    lo = near.start - int(0.05 * sr) + int(np.argmin(avg[near.start - int(0.05 * sr) : peak + 1]))
    if avg[peak] < 1.5 * np.median(avg):  # no clear hit on the beat: leave it
        return 0.0
    cross = lo + int(np.argmax(avg[lo : peak + 1] >= avg[lo] + 0.3 * (avg[peak] - avg[lo])))  # heard early in a rise
    off = (cross - w0) / sr
    return off if abs(off) <= max_s else 0.0


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
