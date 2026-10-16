"""Snare rolls into drops, fills into phrases, and the pause before a drop.

A build-up's snare roll plays its hits close together (sixteenths all the way, or speeding up: quarter notes,
eighths, sixteenths, thirty-seconds); a fill plays a few quick hits into the next phrase. The lights flash on
those hits (engine/rolls.py), so the analysis finds the snare's own hits, at 5 ms, and where they form a roll:
right before a drop or a phrase, filling its beat grid with one drum's sound and clearly faster than the
groove before it (a groove's backbeat, claps, shaker or percussion aren't a roll). A pause before the drop
(the music stops for a moment) is found from the loudness and gets a blackout of exactly its length.
"""

from __future__ import annotations

import numpy as np

ROLL_MAX_BARS = 16  # a roll is looked for this far back from the drop at most
FIRST_MAX_BARS = 8  # its slower start (quarter notes) at most this long before the fast hits
ROLL_GAP_BARS = 2  # the roll ends at most this long before the drop (the rest: a pause or a riser)
ROLL_MIN_BEATS = 4  # its fast part at least this long
FILL_GAP_BARS, FILL_MAX_BARS = 1, 2  # a fill ends at most a bar before its phrase, and lasts at most two
FILL_RATE = 2.5  # …with at least this many hits a beat
SNARE_BAND = (300.0, 5000.0)  # Hz: a snare's body and crack, a tom's attack (the kick, bass and hats mostly outside)
FINE_HOP_S = 0.005  # the roll's own onset envelope: fine enough for thirty-seconds at 180 BPM (42 ms apart)
RISE_S = (0.04, 0.025)  # an onset: the band's loudness over this long after against its quietest this long before
HIT_SHARE = 0.25  # a snare hit: flux at least this share of the build's loud hits…
NOISE_X = 2.5  # …and this many times the onset strength's median around it (a riser's noise: its flicker),
STRONG, STRONG_X = 0.3, 1.8  # or, as strong as this (the track's loud onsets: 1), this many times (thirty-seconds)
MIN_GAP_S = 0.04  # hits at least this far apart (thirty-seconds up to 187 BPM; a flam is one hit)
SLOT_S = 0.03  # a hit on a slot of the beat grid: within this (or 30% of the slot)
TIMBRE_BANDS = ((300, 700), (700, 1500), (1500, 3000), (3000, 6000), (6000, 10000))  # Hz: what a hit sounds like…
SAME, SAME_FILL = 0.93, 0.9  # …a roll's (fill's) hits alike: median likeness to the next (percussion: ~0.85)
FLAM_S, FLAM_SHARE = 0.05, 0.6  # a peak this close to one this much stronger: its flam or echo, not a hit
GAP_BEATS = 0.75  # a fill's hits at most this far apart (its own rhythm)
ALIKE = 0.5  # a roll's slower start: each hit as strong as the next within this factor (a kick and a clap aren't)
MIN_HITS = 5  # a fill: at least this many hits over at least a beat
CORE_HITS, HOLE_BEATS = 2, 2  # its dense part: beats with at least this many hits; a few beats missed
BUZZ_BARS = 2  # a roll at least this long that blurs (its hits too close to tell) goes on to the drop…
BUZZ_DB = 3.0  # …while the music stays this loud
GROOVE_BARS = 4  # the groove before a roll or fill, to tell them apart by
PAUSE_DB = 15.0  # a pause: this much quieter than the build…
PAUSE_MIN_BEATS, PAUSE_MAX_BARS = 0.5, 2  # …for at least half a beat, at most two bars, right before the drop


def _power_db(x: np.ndarray, hop: int) -> np.ndarray:
    """Loudness (dB) every hop, each over two hops: a noise riser's grain evens out."""
    n = len(x) // hop
    power = (x[: n * hop] ** 2).reshape(n, hop).mean(axis=1)
    power = (power + np.r_[power[:1], power[:-1]]) / 2
    return 10 * np.log10(power + 1e-10)


def fine_envelopes(mono: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, float, np.ndarray]:
    """Every FINE_HOP_S (the spectral frames are ~90 ms wide: too coarse for a roll's thirty-seconds or the
    exact start of a pause): the snare band's onset strength (normalised) and the loudness of everything (dB).
    The onset strength is a sustained rise: how much louder the band is just after than at its quietest just
    before (RISE_S). A drum rings on after its attack; a riser's noise flickers up and straight back down.
    Returns (snare flux, loudness, frames per second, the loudness of TIMBRE_BANDS: (bands, frames) dB)."""
    from numpy.lib.stride_tricks import sliding_window_view
    from scipy.signal import butter, sosfilt

    mono = np.asarray(mono, np.float32)
    hop = max(1, int(round(FINE_HOP_S * sr)))
    db = _power_db(sosfilt(butter(4, SNARE_BAND, "band", fs=sr, output="sos"), mono), hop)
    db = np.maximum(db, np.percentile(db, 99) - 40)  # near silence: no rises from the noise floor
    nb, na = (max(1, int(round(s / FINE_HOP_S))) for s in RISE_S)
    pad = np.pad(db, (nb, na), mode="edge")
    before = sliding_window_view(pad[: len(db) + nb - 1], nb).min(axis=1)  # frames i-nb … i-1
    after = sliding_window_view(pad[nb + 1 :], na).mean(axis=1)[: len(db)]  # frames i+1 … i+na
    flux = np.maximum(0.0, after - before)
    nyq = 0.45 * sr
    bands = np.array(
        [
            _power_db(sosfilt(butter(4, (lo, min(hi, nyq)), "band", fs=sr, output="sos"), mono), hop)
            for lo, hi in TIMBRE_BANDS
        ]
    ).astype(np.float32)
    return flux / (np.percentile(flux, 99.5) + 1e-9), _power_db(mono, hop), sr / hop, bands


def timbre(bands: np.ndarray, fps: float, times: np.ndarray) -> np.ndarray:
    """Per hit: what it sounds like, as how much each of TIMBRE_BANDS rises (a unit vector). A roll plays one
    drum over and over; a groove's percussion is several."""
    nb, na = (max(1, int(round(s * fps))) for s in RISE_S)
    out = np.zeros((len(times), len(bands)), np.float32)
    for k, x in enumerate(times):
        i = int(round(x * fps))
        if nb <= i < bands.shape[1] - na - 1:
            out[k] = np.maximum(0.0, bands[:, i + 1 : i + 1 + na].mean(axis=1) - bands[:, i - nb : i].min(axis=1))
    return out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-9)


def snare_hits(flux: np.ndarray, fps: float, lo: float, hi: float, ref: float, period: float) -> np.ndarray:
    """The snare's hits between lo and hi (s): (time, strength against `ref`) per hit. A hit is a peak of the
    snare band's onset strength at least HIT_SHARE of a loud hit and NOISE_X times the onset strength around
    it (a riser's noise flickers all the time, a few flickers stand out but too sparse to make a roll; a
    roll's hits barely fall back between them, so they rise less than a single hit would), or a strong hit
    STRONG_X times (thirty-seconds lift the onset strength around them themselves); a flam's grace note
    or a hit's echo right next to a much stronger hit is that hit, not one of its own."""
    from scipy.signal import find_peaks

    i0, i1 = max(int(lo * fps), 0), min(int(hi * fps), len(flux))
    if i1 - i0 < 3 or ref <= 0:
        return np.zeros((0, 2))
    seg = flux[i0:i1]
    pk, props = find_peaks(seg, height=HIT_SHARE * ref, distance=max(1, int(MIN_GAP_S * fps)))
    v = props["peak_heights"]
    w = int(4 * period * fps)  # the noise: the onset strength's median within a bar
    floor = np.array([np.median(seg[max(k - w, 0) : k + w]) for k in pk])
    keep = (v >= NOISE_X * floor) | ((v >= STRONG) & (v >= STRONG_X * floor))
    hits, level = (i0 + pk[keep]) / fps, v[keep]
    flam = min(FLAM_S, 0.3 * period)
    out = []
    for j, (t, x) in enumerate(zip(hits, level)):
        near = [level[m] for m in (j - 1, j + 1) if 0 <= m < len(hits) and abs(hits[m] - t) < flam]
        if not near or x >= FLAM_SHARE * max(near):
            out.append((float(t), float(x) / ref))
    return np.array(out, float).reshape(-1, 2)


def _trains(t: np.ndarray, gap: float) -> list[np.ndarray]:
    """Runs of hits each at most `gap` after the one before (indices into t)."""
    if not len(t):
        return []
    return np.split(np.arange(len(t)), np.flatnonzero(np.diff(t) > gap) + 1)


def _per_beat(t: np.ndarray, beats: np.ndarray, sel: np.ndarray) -> np.ndarray:
    """For the beats `sel`: how many hits the snare plays per beat, as 1, 2, 4 or 8 (give or take one the detector
    missed; a beat it misses inside the roll keeps the one before: the roll goes on)."""
    out = np.zeros(len(sel), np.int8)
    for k, j in enumerate(sel):
        p = _beat_len(beats, j)
        c = int(((t >= beats[j] - 0.12 * p) & (t < beats[j] + 0.88 * p)).sum())
        out[k] = next(d for d in (8, 4, 2, 1) if c >= 0.75 * d) if c else (out[k - 1] if k else 0)
    return np.maximum(out, 1)


def _beat_len(beats: np.ndarray, j: int) -> float:
    return float(beats[j + 1] - beats[j]) if j + 1 < len(beats) else float(beats[j] - beats[j - 1])


def _slots(t: np.ndarray, b: float, p: float, d: int) -> list[int]:
    """The hits (indices into the sorted t) on the d slots of the beat at b, -1 where a slot has none."""
    tol = min(SLOT_S, 0.3 * p / d)
    out = []
    for k in range(d):
        x = b + k * p / d
        i = int(np.searchsorted(t, x))
        near = [m for m in (i - 1, i) if 0 <= m < len(t) and abs(t[m] - x) <= tol]
        out.append(min(near, key=lambda m: abs(t[m] - x)) if near else -1)
    return out


def _grid(t: np.ndarray, b: float, p: float) -> int:
    """The finest subdivision of the beat at b (1, 2, 4 or 8 hits) whose slots the hits fill, all but one of
    four or eight (the detector misses one now and then); 0: not even the beat. A roll fills its grid, a
    groove's percussion is syncopated."""
    best = 0
    for d in (1, 2, 4, 8):
        filled = sum(m >= 0 for m in _slots(t, b, p, d))
        if filled >= (d if d <= 2 else d - d // 4):
            best = d
    return best


def _lag(t: np.ndarray, beats: np.ndarray, period: float) -> float:
    """How late the hits sit against the beat grid (its dating, the onset measure's own delay): their median
    offset from the nearest sixteenth, within ±40 ms."""
    if not len(t):
        return 0.0
    q = period / 4
    j = np.clip(np.searchsorted(beats, t) - 1, 0, len(beats) - 1)
    off = (t - beats[j]) % q
    off = np.where(off > q / 2, off - q, off)
    return float(np.clip(np.median(off), -0.04, 0.04))


def _core(t: np.ndarray, last: int, period: float, lo: float) -> np.ndarray:
    """The dense stretch of hits that ends at or before hit `last` (indices into t): beat by beat back from it,
    the beats with at least CORE_HITS hits, give or take HOLE_BEATS beats the detector misses; a groove's
    backbeat before it, and a stray hit after it, fall away."""
    end = t[last]
    edge, first, final, weak = end + 1e-9, None, None, 0
    while edge - period >= lo - 1e-9 and weak <= HOLE_BEATS:
        if ((t >= edge - period) & (t < edge)).sum() >= CORE_HITS:
            weak, first = 0, edge - period
            final = edge if final is None else final
        elif final is not None:
            weak += 1
        elif end - edge > period * HOLE_BEATS:
            break  # no dense beat right before `last`
        edge -= period
    if first is None:
        return np.zeros(0, int)
    sel = np.flatnonzero((t >= max(first - period, lo) - 1e-9) & (t < final))  # (and a part beat at its start)
    while len(sel) > 1 and t[sel[1]] - t[sel[0]] > GAP_BEATS * period:
        sel = sel[1:]
    while len(sel) > 1 and t[sel[-1]] - t[sel[-2]] > GAP_BEATS * period:  # a stray hit after the dense part
        sel = sel[:-1]
    return sel


def _drop_roll(
    t: np.ndarray,
    power: np.ndarray,
    beats: np.ndarray,
    period: float,
    lo: float,
    end: float,
    since: float,
    build: float,
    prof: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, list[int]] | None:
    """The roll into a drop: back from the drop (or its pause), past at most ROLL_GAP_BARS (a riser), the
    beats whose grid the snare fills, eighths or faster, give or take HOLE_BEATS, within the build-up phrase
    (a groove's eighths before it fill a grid too); before them a slower start of quarter notes, each hit
    alike the next one, at most FIRST_MAX_BARS. Its fast hits sound alike (SAME; `prof`: timbre per hit), and
    the groove before it plays at most half the roll's speed (a groove's own sixteenths aren't a roll; with no
    groove before it there's nothing to tell it by).
    Returns (the roll's beats, its step per beat (only going up), the hits it plays), or None."""
    shift = _lag(t, beats, period)
    sel = np.flatnonzero((beats >= lo - 0.02) & (beats + 0.5 * period < end))
    if len(sel) < 4:
        return None
    div = np.array([_grid(t, float(beats[j]) + shift, _beat_len(beats, j)) for j in sel])
    k = len(sel) - 1
    while k >= 0 and div[k] < 2 and len(sel) - 1 - k < 4 * ROLL_GAP_BARS:
        k -= 1
    if k < 0 or div[k] < 2:
        return None
    e, s, weak = k, k, 0
    while k > 0 and weak <= HOLE_BEATS and beats[sel[k - 1]] >= build - 0.05:
        k -= 1
        weak = 0 if div[k] >= 2 else weak + 1
        if div[k] >= 2:
            s = k
    if int((div[s : e + 1] >= 2).sum()) < ROLL_MIN_BEATS:
        return None
    first_bar = int(round(FIRST_MAX_BARS * 4))

    def hit_at(k: int) -> int:  # the hit on beat k's downbeat, -1: none
        return _slots(t, float(beats[sel[k]]) + shift, _beat_len(beats, sel[k]), 1)[0]

    fast = s
    while s > 0 and div[s - 1] == 1 and fast - s < first_bar:
        a, b = hit_at(s - 1), hit_at(s)
        if a < 0 or b < 0 or not ALIKE <= power[a] / power[b] <= 1 / ALIKE:
            break
        s -= 1
    top = float(np.percentile(div[s : e + 1], 75))
    before = np.flatnonzero((beats >= max(beats[sel[s]] - GROOVE_BARS * 4 * period, since)) & (beats < beats[sel[s]]))
    if len(before) < 4:
        return None
    groove = np.array([_grid(t, float(beats[j]) + shift, _beat_len(beats, j)) for j in before])
    if np.median(groove) > top / 2:
        return None
    steps = np.maximum.accumulate(np.maximum(div[s : e + 1], 1)).astype(np.int8)
    played, quick = [], []
    for j, d in zip(sel[s : e + 1], steps):
        on = [m for m in _slots(t, float(beats[j]) + shift, _beat_len(beats, j), int(d)) if m >= 0]
        played += on
        quick += on if d >= 2 else []
    quick = sorted(set(quick))
    alike = (prof[quick[1:]] * prof[quick[:-1]]).sum(axis=1) if prof is not None and len(quick) > 2 else [1.0]
    if np.median(alike) < SAME:
        return None
    return sel[s : e + 1], steps, sorted(set(played))


def _fill(
    t: np.ndarray, beats: np.ndarray, period: float, lo: float, end: float, since: float, prof: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray, list[int]] | None:
    """A fill into a phrase (or a drop): a run of hits close together, its own rhythm, ending at most
    FILL_GAP_BARS before it, at most FILL_MAX_BARS long, at least FILL_RATE hits a beat and MIN_HITS over a
    beat, sounding alike (SAME_FILL: one drum, a tom's pitch may move), and at least twice as dense as the
    snare before it. Returns (its beats, hits per beat, its hits)."""
    bar = 4 * period
    cand = [r for r in _trains(t, GAP_BEATS * period) if end - FILL_GAP_BARS * bar <= t[r[-1]] < end]
    if not cand:
        return None
    r = _core(t, int(cand[-1][-1]), period, max(lo, end - FILL_MAX_BARS * bar - period))
    if len(r) < MIN_HITS:
        return None
    start, last = float(t[r[0]]), float(t[r[-1]])
    rate = (len(r) - 1) / max((last - start) / period, 1e-9)  # hits per beat
    if last - start < 0.9 * period or rate < FILL_RATE or start < end - FILL_MAX_BARS * bar - period:
        return None
    if prof is not None and np.median((prof[r[1:]] * prof[r[:-1]]).sum(axis=1)) < SAME_FILL:
        return None
    w0 = max(start - GROOVE_BARS * bar, since)
    if start - w0 < bar or ((t >= w0) & (t < start - 0.25 * period)).sum() / ((start - w0) / period) > rate / 2:
        return None
    sel = np.flatnonzero((beats >= start - 0.12 * period) & (beats <= last))
    if not len(sel):
        return None
    return sel, _per_beat(t[r], beats, sel), list(r)


def snare_rolls(
    flux: np.ndarray,
    loud_db: np.ndarray,
    fps: float,
    beats: np.ndarray,
    bars: np.ndarray,
    drops: list[tuple[float, float, float]],
    fills: list[tuple[float, float]] = (),
    bands: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The snare rolls into the drops, the fills into other phrases, and the pauses before the drops.

    `flux`, `loud_db`, `bands`: fine_envelopes (without `bands`, a roll's hits needn't sound alike); `drops`:
    (where to look from at the earliest: the drop before; where its build-up phrase starts; the drop) per
    drop; `fills`: (where to look from at the earliest, the phrase) per other phrase. A drop gets a roll
    (_drop_roll) or else a fill (_fill), a phrase a fill.
    Returns (roll: per beat the hits per beat the roll plays there (1, 2, 4, 8), 0 outside a roll; pauses:
    (start, drop) per drop with a pause; hits: (time, strength) per hit of every roll and fill)."""
    roll = np.zeros(len(beats), np.int8)
    pauses, hits = [], []
    if len(bars) < 3 or len(beats) < 8:
        return roll, np.zeros((0, 2)), np.zeros((0, 2))
    todo = [(since, build, drop, True) for since, build, drop in drops]
    todo += [(since, phrase, phrase, False) for since, phrase in fills]
    for since, build, at, is_drop in sorted(todo, key=lambda x: x[2]):
        near = beats[(beats > at - 8) & (beats < at)]
        period = float(np.median(np.diff(near))) if len(near) > 2 else 0.5
        bar = 4 * period
        end = at
        if is_drop:
            p = pause_before(loud_db, fps, at, period)
            if p is not None:
                pauses.append((p, at))
                end = p  # the roll stops where the pause starts
        lo = max(since, end - ROLL_MAX_BARS * bar, 0.0)
        if end - lo < 2 * period:
            continue
        ref = float(np.percentile(flux[max(int(lo * fps), int((end - 8 * bar) * fps), 0) : int(end * fps)], 99))
        h = snare_hits(flux, fps, lo - GROOVE_BARS * bar, end, ref, period)
        t = h[:, 0]
        prof = timbre(bands, fps, t) if bands is not None else None
        found = _drop_roll(t, h[:, 1], beats, period, lo, end, since, build, prof) if is_drop else None
        found = found or _fill(t, beats, period, lo, end, since, prof)
        if found is None:
            continue
        sel, steps, idx = found
        times, power = list(t[idx]), list(h[idx, 1])
        if not times:
            continue
        start, last = times[0], times[-1]
        # a long roll that blurs into a buzz (or under a riser) goes on to the drop at its last speed, as long
        # as the music doesn't get quieter
        gap = period / int(steps[-1])
        i0, i1, i2 = int((last - bar) * fps), int(last * fps), int(end * fps)
        long = is_drop and last - start >= BUZZ_BARS * bar
        if long and end - last > 1.5 * gap and np.median(loud_db[i1:i2]) >= np.median(loud_db[i0:i1]) - BUZZ_DB:
            more = np.arange(last + gap, end - 0.5 * gap, gap)
            times += list(more)
            power += [float(np.median(power[-8:]))] * len(more)
            rest = np.flatnonzero((beats > beats[sel[-1]] + 0.01) & (beats < end - 0.02))
            sel, steps = np.r_[sel, rest], np.r_[steps, np.full(len(rest), steps[-1], np.int8)]
        roll[sel] = steps
        hits += [(float(x), float(v)) for x, v in zip(times, power) if x >= lo]
    return roll, np.array(pauses, float).reshape(-1, 2), np.array(sorted(hits), float).reshape(-1, 2)


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
