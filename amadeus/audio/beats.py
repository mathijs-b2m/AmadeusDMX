"""The beat grid: local tempo, beat tracking (dynamic programming), refining it to what is heard, downbeats
and the set's BPM."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import median_filter

from amadeus.audio.features import normalize


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


KICK_DOUBLE = 0.93  # the low end rises this much as clearly on the lines between: the kick runs twice as fast
KICK_DOUBLE_MAX = 200.0  # (measured: hardcore 0.96–0.98; Maluma, Chemise and other real 90–100 BPM tracks ≤ 0.89)


def kick_double(env: np.ndarray, fps: float, bpm: float, score: float, share: float = KICK_DOUBLE) -> bool:
    """Is the music twice as fast as `bpm`? A kick on every beat also scores on every other beat, so the comb
    can't tell 168 BPM hardcore from 84 BPM. Twice as many lines tell: every one of them lands on a kick only
    when the kick really runs at that tempo. Beyond KICK_DOUBLE_MAX it is a band's double-time (Metallica)."""
    return 2 * bpm <= KICK_DOUBLE_MAX and comb_score(env, fps, 2 * bpm) >= share * score


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
    # a grid continued back to before the track starts, or on past its last frame
    return grid[(grid >= 0.0) & (grid <= (len(low_rise) - 1) / fps)]


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
        # (the top lies between the neighbours; an almost flat onset can put the parabola's anywhere)
        t[k] = (j + (float(np.clip(0.5 * (y0 - y2) / den, -1.0, 1.0)) if den < 0 else 0.0)) / fps
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


STRUCTURE_SHARE = 0.45  # the low end's changes pick the bar phase when this share of them falls on one phase
STRUCTURE_SILENT_DB = 30  # the low end this far under its usual level: the track hasn't started yet
FIRST_SOUND_VOTE = 2.0  # a first sound the biggest changes overrule counts this many usual changes
RUN_LOW_MARGIN = 2  # a stretch on its own bar phase needs this many more low-end changes on it than on the next one's
SLAM_RISE = 0.3  # the low end (0..1 over the track) jumping this much from one beat to the next: it comes in here
CHORD_SPAN = 4  # beats of harmony either side of a beat, to tell how much the chord changes there


def _low_changes(lb: np.ndarray) -> np.ndarray:
    """Per beat how much the low end (per beat, dB) changes there: one beat per change, the big changes only."""
    n = len(lb)
    nov = np.zeros(n)
    for i in range(4, n - 4):
        nov[i] = abs(lb[i : i + 4].mean() - lb[i - 4 : i].mean())
    peak = np.array([nov[i] > 0 and nov[i] >= nov[max(0, i - 2) : i + 3].max() for i in range(n)])
    nov = np.where(peak, nov, 0.0)  # one beat per change: where it changes most
    if (nov > 0).any():
        nov = np.where(nov >= np.percentile(nov[nov > 0], 75), nov, 0.0)  # the big changes only
    return nov


def _first_sound_overruled(lb: np.ndarray, nov: np.ndarray) -> np.ndarray:
    """The changes, with the first sound after a silent start in its place. Measured from digital silence it weighs
    more than every drop in reach, and music often comes in on a pickup. When the track's two biggest changes after
    it agree on a beat of the bar that isn't the first sound's, those are the bar lines: it counts as a change like
    the others. Otherwise a track that starts on its one keeps that (a silence inside a track always counts)."""
    first = int(np.argmax(lb > np.median(lb) - STRUCTURE_SILENT_DB))
    if first < 4:
        return nov
    heard = lb.copy()
    heard[:first] = lb[first]
    rest = _low_changes(heard)
    top = np.argsort(rest)[::-1][:2]
    if (rest[top] > 0).all() and top[0] % 4 == top[1] % 4 != first % 4:
        rest[first] = FIRST_SOUND_VOTE * np.median(rest[rest > 0])
        return rest
    return nov


def _per_beat(x: np.ndarray, beat_frames: np.ndarray) -> np.ndarray:
    """The mean of a per-frame feature over each beat."""
    edges = np.r_[beat_frames, min(len(x), beat_frames[-1] + int(np.median(np.diff(beat_frames))))]
    return np.array([x[a:b].mean(axis=0) if b > a else x[min(a, len(x) - 1)] for a, b in zip(edges, edges[1:])])


def _chord_changes(chroma: np.ndarray) -> np.ndarray:
    """Per beat how much the harmony (chroma per beat) changes there: the bar after against the bar before, as far
    as that is more than the track's usual difference between two bars."""
    c = np.sqrt(np.maximum(chroma, 0.0))
    c = c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-9)
    change = np.zeros(len(c))
    for i in range(CHORD_SPAN, len(c) - CHORD_SPAN):
        a, b = c[i - CHORD_SPAN : i].mean(axis=0), c[i : i + CHORD_SPAN].mean(axis=0)
        change[i] = 1 - a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9)
    return np.maximum(change - np.median(change), 0.0)


def _slam_beats(lb: np.ndarray, low: np.ndarray) -> np.ndarray:
    """The beats where the low end comes in at once: a jump from the beat before, the biggest within two beats."""
    lo, hi = np.percentile(low, [5, 95])
    level = np.clip((lb - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    rise = np.r_[0.0, np.diff(level)]
    return np.array([r >= SLAM_RISE and r >= rise[max(0, i - 2) : i + 3].max() for i, r in enumerate(rise)])


def _settled(phases: list[int], n: int, changes: np.ndarray, chords: np.ndarray, slams: np.ndarray) -> list[list[int]]:
    """The stretches of one bar phase, (first beat, end, phase), without the ones the music in them doesn't back.

    The vote looks well past its window, so a change far away can turn a stretch that has nothing of its own, and the
    bars then jump there and back for nothing. A stretch joins the phase next to it unless its own music says otherwise:
    RUN_LOW_MARGIN more low-end changes on its phase, or more of the chord changes and about as many low-end changes
    (a margin of one low-end change is chance; a clear one nearly always has the chords with it). A slam off the
    neighbour's bar lines keeps it apart too: bars never move away from where the low end comes in, even when that is on
    a third phase. A flip that stands stays where the vote put it: moving it to where the music turns fits the bars
    better, but costs drops."""
    runs = [[s * 64, min(n, (s + 1) * 64), int(p)] for s, p in enumerate(phases)]

    def joined(rs: list[list[int]]) -> list[list[int]]:
        out: list[list[int]] = []
        for r in rs:
            if out and out[-1][2] == r[2]:
                out[-1][1] = r[1]
            else:
                out.append(list(r))
        return out

    def chord_share(a: int, b: int, p: int) -> float:
        total = chords[a:b].sum()
        return float(chords[a:b][(np.arange(a, b) - p) % 4 == 0].sum() / total) if total > 0 else 0.0

    def unbacked(a: int, b: int, p: int, q: int) -> tuple[int, float] | None:
        """How little a stretch on phase p holds against phase q next to it; None when it stands."""
        beat = np.arange(a, b)
        if slams[a:b][(beat - q) % 4 != 0].any():
            return None
        margin = int((changes[a:b][(beat - p) % 4 == 0] > 0).sum() - (changes[a:b][(beat - q) % 4 == 0] > 0).sum())
        chord = chord_share(a, b, p) - chord_share(a, b, q)
        return None if margin >= RUN_LOW_MARGIN or (margin >= -1 and chord > 0) else (margin, chord)

    runs = joined(runs)
    while len(runs) > 1:
        weak = [
            (unbacked(a, b, p, q), k, q)
            for k, (a, b, p) in enumerate(runs)
            for q in sorted({r[2] for r in runs[max(0, k - 1) : k] + runs[k + 1 : k + 2]})
        ]
        weak = [w for w in weak if w[0] is not None]
        if not weak:
            break
        _, k, q = min(weak, key=lambda w: w[0])
        runs[k][2] = q
        runs = joined(runs)
    return runs


def downbeats(
    beat_frames: np.ndarray, accent_env: np.ndarray, low: np.ndarray | None = None, chroma: np.ndarray | None = None
) -> np.ndarray:
    """Pick the bar phase (0..3) per 64-beat window; assumes 4/4 like nearly all DJ music.

    First by the music's structure: drops, breaks, the kick or bass coming in or out all start on the one, so
    the beats where the low end changes most (its level over the next bar against the bar before) mark the bar
    lines. With a steady four-on-the-floor kick the beats' own accents are nearly equal and pick a phase
    almost by chance; they decide only where the structure says nothing clear (fewer than STRUCTURE_SHARE of
    the change on one phase, looking a few windows around). With the track's chroma, a flip of the phase then has to
    be backed by the music where it happens (`_settled`)."""
    strength = accent_env[beat_frames]
    n = len(beat_frames)
    nov = np.zeros(n)
    if low is not None and n > 8:
        lb = _per_beat(low, beat_frames)
        nov = _first_sound_overruled(lb, _low_changes(lb))
    phases = []
    for s in range(0, n, 64):
        seg = strength[s : s + 64]
        lo, hi = max(0, s - 128), min(n, s + 192)
        idx = np.arange(lo, hi)
        struct = np.array([nov[idx[idx % 4 == p]].sum() for p in range(4)])
        if struct.sum() > 0 and struct.max() / struct.sum() >= STRUCTURE_SHARE:
            phases.append(int(np.argmax(struct)))
            continue
        scores = [seg[((np.arange(len(seg)) + s) % 4) == p].mean() if len(seg) > 4 else 0 for p in range(4)]
        phases.append(int(np.argmax(scores)))
    if len(phases) >= 3:  # a phase flip needs agreement from neighbours
        phases = list(median_filter(np.array(phases), size=3, mode="nearest"))
    if low is not None and chroma is not None and n > 8 and len(set(phases)) > 1:
        chords = _chord_changes(_per_beat(chroma, beat_frames))
        runs = _settled(phases, n, nov, chords, _slam_beats(lb, low))
        return np.array([i for a, b, p in runs for i in range(a, b) if i % 4 == p], dtype=int)
    idx = [i for i in range(n) if i % 4 == phases[min(i // 64, len(phases) - 1)]]
    return np.array(idx, dtype=int)


def set_bpm(beat_times: np.ndarray) -> float:
    """Mean of the central beat intervals: the median of integer-frame intervals is quantised (~2 BPM steps)."""
    iv = np.diff(beat_times)
    if len(iv) < 2:
        return 0.0
    lo, hi = np.percentile(iv, [20, 80])
    return float(60 / iv[(iv >= lo) & (iv <= hi)].mean())
