"""Snare rolls into drops, and the pause before a drop.

A build-up's snare roll speeds up in steps: quarter notes, eighths, sixteenths, sometimes thirty-seconds. The
lights follow those steps (engine/rolls.py), so the analysis finds, per beat, which subdivision the snare plays,
only in the build right before a drop and only where it really accelerates. A pause before the drop (the music
stops for a moment) is found from the loudness and gets a blackout of exactly its length.
"""

from __future__ import annotations

import numpy as np

ROLL_MIN_BARS = 2  # a roll lasts at least this long…
ROLL_MAX_BARS = 16  # …and is looked for this far back from the drop at most
FIRST_MAX_BARS = 8  # its first, slowest step at most this long (the rest: a groove's backbeat)
ROLL_GAP_BARS = 2  # the roll ends at most this long before the drop (the rest: a pause or a riser)
SNARE_BAND = (1200.0, 5000.0)  # Hz: the snare's crack (the kick's click and the hats mostly outside)
FINE_HOP_S = 0.005  # the roll's own onset envelope: fine enough for thirty-seconds at 180 BPM (42 ms apart)
HIT_SHARE = 0.25  # a snare hit: flux at least this share of the build's loud hits…
CONTRAST = 3.0  # …and this many times the flux around it (a riser's noise rises too, but evenly)
ALIKE = 0.5  # a subdivision's hits at least this share of the beat's own (weaker ones: a groove's hats)
PAUSE_DB = 15.0  # a pause: this much quieter than the build…
PAUSE_MIN_BEATS, PAUSE_MAX_BARS = 0.5, 2  # …for at least half a beat, at most two bars, right before the drop


def _power_db(x: np.ndarray, hop: int) -> np.ndarray:
    """Loudness (dB) every hop, each over two hops: a noise riser's grain evens out."""
    n = len(x) // hop
    power = (x[: n * hop] ** 2).reshape(n, hop).mean(axis=1)
    power = (power + np.r_[power[:1], power[:-1]]) / 2
    return 10 * np.log10(power + 1e-10)


def fine_envelopes(mono: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Every FINE_HOP_S (the spectral frames are ~90 ms wide: too coarse for a roll's thirty-seconds or the
    exact start of a pause): the snare band's onset strength (the rise of its loudness, normalised) and the
    loudness of everything (dB). Returns (snare flux, loudness, frames per second)."""
    from scipy.signal import butter, sosfilt

    mono = np.asarray(mono, np.float32)
    hop = max(1, int(round(FINE_HOP_S * sr)))
    db = _power_db(sosfilt(butter(4, SNARE_BAND, "band", fs=sr, output="sos"), mono), hop)
    db = np.maximum(db, np.percentile(db, 99) - 40)  # near silence: no rises from the noise floor
    rise = np.maximum(0.0, db[2:] - db[:-2])  # over two hops: an attack rises within ~10 ms
    flux = np.concatenate([[0.0, 0.0], rise])
    return flux / (np.percentile(flux, 99.5) + 1e-9), _power_db(mono, hop), sr / hop


def _lag(flux: np.ndarray, fps: float, beats: np.ndarray) -> float:
    """How late the snare's attacks peak in `flux` against the beat grid (the envelope's own delay, and the
    grid being dated as heard): the shift, within ±60 ms, that puts the most flux on the beats."""
    idx = np.round(beats * fps).astype(int)
    idx = idx[(idx > 0) & (idx < len(flux))]
    lags = np.arange(-int(0.06 * fps), int(0.06 * fps) + 1)
    score = [flux[np.clip(idx + k, 0, len(flux) - 1)].sum() for k in lags]
    return float(lags[int(np.argmax(score))]) / fps


def beat_divisions(flux: np.ndarray, fps: float, beats: np.ndarray, ref: float) -> np.ndarray:
    """Per beat: how many snare hits on the grid, 0, 1, 2, 4 or 8 (the beat itself, then the finest
    subdivision whose every slot has a hit). `flux`: snare_flux, dated like `beats`; `ref`: how strong a loud
    hit is in this stretch. A hit stands out from the flux around it (most of the beat: its 75th percentile)."""
    n = len(flux)
    w = max(1, int(round(0.012 * fps)))  # a hit within ±12 ms of its slot

    def at(t: float) -> float:
        i = int(round(t * fps))
        return float(flux[max(i - w, 0) : min(i + w + 1, n)].max()) if 0 <= i < n else 0.0

    out = np.zeros(len(beats), np.int8)
    for j in range(len(beats) - 1):
        b, p = float(beats[j]), float(beats[j + 1] - beats[j])
        seg = flux[max(int(b * fps), 0) : min(int((b + p) * fps), n)]
        floor = float(np.percentile(seg, 75)) if len(seg) else 0.0
        level = max(HIT_SHARE * ref, CONTRAST * floor)
        div, first = 0, at(b)
        for d in (1, 2, 4, 8):  # a roll's hits are alike: the ones between the beats near the one on it
            if all(at(b + k * p / d) >= max(level, ALIKE * first) for k in range(d)):
                div = d
            else:
                break
        out[j] = div
    return out


def _bar_levels(div: np.ndarray, bar_beats: list[np.ndarray]) -> list[int]:
    """Per bar: does the snare play (nearly) every beat? Then the subdivision most of its beats play, else 0."""
    out = []
    for idx in bar_beats:
        d = np.sort(div[idx])[::-1]
        every = len(d) and (d > 0).sum() >= 0.75 * len(d)  # one missed beat is fine; a backbeat isn't a roll
        out.append(int(d[len(d) // 2]) if every else 0)  # the lower median: a groove's pattern isn't a step
    return out


def snare_rolls(
    flux: np.ndarray,
    loud_db: np.ndarray,
    fps: float,
    beats: np.ndarray,
    bars: np.ndarray,
    drops: list[tuple[float, float, float]],
) -> tuple[np.ndarray, np.ndarray]:
    """The accelerating snare rolls into the drops, and the pauses before them.

    `flux`, `loud_db`: fine_envelopes; `drops`: (where to look from at the earliest: the drop before; where
    its build-up phrase starts; the drop) per drop.
    Returns (roll: per beat the subdivision the roll plays there, 0 outside a roll; pauses: (start, drop) per
    drop with a pause). A roll: at least ROLL_MIN_BARS bars with a snare on every beat, ending at most
    ROLL_GAP_BARS before the drop (or its pause), that gets faster: its last step at least eighths and faster
    than its first. The steps only go up: a roll doesn't slow down, a missed hit is the detector's."""
    roll = np.zeros(len(beats), np.int8)
    pauses = []
    if len(bars) < 3 or len(beats) < 8:
        return roll, np.zeros((0, 2))
    for since, build, drop in drops:
        period = float(np.median(np.diff(beats[(beats > drop - 8) & (beats < drop)]))) if drop > 8 else 0.5
        p = pause_before(loud_db, fps, drop, period)
        if p is not None:
            pauses.append((p, drop))
        k = int(np.argmin(np.abs(bars - drop)))
        if abs(bars[k] - drop) > 0.6 * float(np.median(np.diff(bars))):
            continue
        b0 = max(0, k - ROLL_MAX_BARS, int(np.searchsorted(bars, since - 0.05)))
        if p is not None:
            drop = p  # the roll stops where the pause starts
        lo, hi = int(bars[b0] * fps), int(drop * fps)
        if hi - lo < fps:
            continue
        ref = float(np.percentile(flux[max(lo, hi - int(8 * 4 * period * fps)) : hi], 99))  # the build's hits
        sel = np.flatnonzero((beats >= bars[b0] - 0.02) & (beats < drop - 0.02))
        div = np.zeros(len(beats), np.int8)
        if len(sel):
            near = beats[sel[0] : sel[-1] + 2]
            div[sel] = beat_divisions(flux, fps, near + _lag(flux, fps, near), ref)[: len(sel)]
        bar_beats = [np.flatnonzero((beats >= bars[b] - 0.02) & (beats < bars[b + 1] - 0.02)) for b in range(b0, k)]
        levels = _bar_levels(div, bar_beats)
        # back from the drop: skip the gap (a pause, a riser), then the bars the snare plays every beat, as long
        # as they get slower going back (faster bars before it: the groove's hats, not the roll); its first
        # step at most FIRST_MAX_BARS long, and not from before the build-up when that starts during it (the
        # groove's kick or clap on every beat before it)
        e = len(levels)
        while e > 0 and levels[e - 1] == 0 and len(levels) - e < ROLL_GAP_BARS:
            e -= 1
        s = e
        while s > 0 and 0 < levels[s - 1] <= levels[s if s < e else e - 1]:
            s -= 1
        while s < e and levels[s + FIRST_MAX_BARS : s + FIRST_MAX_BARS + 1] == [levels[s]]:
            s += 1
        f = s
        while f < e and levels[f] == levels[s]:
            f += 1
        kb = int(np.searchsorted(bars, build - 0.05)) - b0
        if s < kb < f:
            s = kb
        if e - s < ROLL_MIN_BARS:
            continue
        # the steps, per half bar (a roll often speeds up halfway through a bar): what both its beats play
        idx = np.concatenate([bar_beats[b] for b in range(s, e)])
        halves = np.array_split(idx, max(1, len(idx) // 2))
        steps = np.concatenate([np.full(len(h), div[h].min()) for h in halves])
        steps = np.maximum.accumulate(np.maximum(steps, 1))
        while len(steps) and (steps[: min(4, len(steps))] != steps[0]).any():  # its first step lasts a bar at least
            keep = steps != steps[0]
            idx, steps = idx[keep], steps[keep]
        if not len(steps) or steps[-1] < 2 or steps[-1] <= steps[0]:
            continue
        played = (beats[idx] < drop - 0.02) & (np.arange(len(idx)) <= np.flatnonzero(div[idx])[-1])  # to its last hit
        roll[idx[played]] = steps[played]
    return roll, np.array(pauses, float).reshape(-1, 2)


def pause_before(loud_db: np.ndarray, fps: float, drop: float, period: float) -> float | None:
    """Where the music stops right before a drop, if it does: a stretch at least PAUSE_DB below the build's
    loudness, from at least half a beat to two bars, ending at the drop (give or take 30 ms)."""
    d = int(round(drop * fps))
    look = int(PAUSE_MAX_BARS * 4 * period * fps)
    bar = int(4 * period * fps)
    if d - look - bar < 0 or d > len(loud_db):
        return None
    build = float(np.percentile(loud_db[d - look - bar : d - look], 75))
    quiet = loud_db < build - PAUSE_DB
    i = d - int(0.03 * fps)  # the drop's attack (and its dating as heard) may start a little early
    if not quiet[i - int(0.03 * fps) : i].all():
        return None
    while i > d - look and quiet[i - 1]:
        i -= 1
    start = i / fps
    return start if drop - start >= PAUSE_MIN_BEATS * period else None
