"""Reggaeton's rhythm, from the analysis: how clearly the snare plays the dembow (for the genre call), and the
two voices the lights play, boom-tac:

- the **tac**: the snare on the 16ths its pattern keeps coming back to (the dembow's 3+3+2);
- the **boom**: the kick on every beat it plays, and its runs of 1/8 notes ("boom boom boom boom", mostly
  leading into a new part);
- the **breathers**: the beats where the kick and the bass are gone for a moment (the lights pause, then hit
  together when the beat is back).

The boom and the breathers are read from the low end itself (its rise and level on each beat and each 8th
between them), not from the kick onsets, which only look on the beat.
"""

from __future__ import annotations

import numpy as np

from amadeus.audio.model import Analysis


def _snare_slots(a: Analysis, first: int):
    """The snare hits in two-beat cells (counted from beat `first`): their times, strengths, 16th slot (0..7),
    and each slot's share of the snare."""
    t, s = a.onsets.get("snare", (np.zeros(0), np.zeros(0)))
    cells = a.beats[first::2]
    if len(cells) < 9 or len(t) < 16:
        return np.zeros(0), np.zeros(0), np.zeros(0, int), np.zeros(8)
    i = np.searchsorted(cells, t, side="right") - 1
    ok = (i >= 0) & (i < len(cells) - 1)
    i, t, s = i[ok], t[ok], s[ok]
    slot = np.round((t - cells[i]) / (cells[i + 1] - cells[i]) * 8).astype(int) % 8
    return t, s, slot, np.bincount(slot, weights=s, minlength=8) / max(float(s.sum()), 1e-9)


def _dembow_of(h: np.ndarray) -> float:
    return float(min(h[3], h[6]) - h[2] - (h[1] + h[5] + h[7]) / 2)


def dembow(a: Analysis) -> float:
    """How clearly the snare plays the dembow: per two beats, eight 16ths, the snare's share on the two dembow
    16ths (the 4th, just before the second beat, and the 7th, its "and"; the weaker of the two counts) minus its
    share on the 8th between them (a backbeat pattern) and half its share on the other off-16ths (busy
    playing that hits every slot). -1..1; > DEMBOW: reggaeton. Both alignments of the two-beat cell are tried."""
    return max(0.0, *(_dembow_of(_snare_slots(a, first)[3]) for first in (0, 1)))


TAC_SHARE = 0.12  # a 16th of the two-beat cell where the snare plays at least this share of its hits: the pattern
TAC_GAP_BEATS = 0.5  # tac hits at least this far apart (the dembow's are 0.75 and 1.25 beats apart)


def tac(a: Analysis) -> tuple[np.ndarray, np.ndarray]:
    """The "tac" of boom-tac: the snare hits on the 16ths its pattern keeps coming back to (the dembow's two,
    or a backbeat), without the ghost notes and fills in between. The kick is the boom."""
    t, s, slot, h = max((_snare_slots(a, first) for first in (0, 1)), key=lambda x: _dembow_of(x[3]))
    pattern = set(np.flatnonzero(h >= TAC_SHARE).tolist())
    if pattern - {0, 4}:  # off-beat 16ths in the pattern (the dembow): the beats themselves are the boom's
        pattern -= {0, 4}
    beat = float(np.median(np.diff(a.beats))) if len(a.beats) > 1 else 0.5
    kept: list[int] = []
    for k in np.flatnonzero(np.isin(slot, list(pattern))):  # at least half a beat apart: a fill is no tac
        if not kept or t[k] - t[kept[-1]] >= TAC_GAP_BEATS * beat:
            kept.append(k)
    return t[kept], s[kept]


BOOM_RISE = 0.6  # a beat or 8th whose low end rises this much (of a typical kick's rise) has a kick on it
BOOM_LEVEL_DB = 12  # … and stays within this much of a typical kick's level (a quiet bass note isn't one)
RUN_8THS = 2  # 1/8 kicks count in runs of at least this many off-beat 8ths in a row (an off-beat bass note
# on its own is the dembow's bass line, not a run)
BREATHER_DB = 15  # the low end this much below a typical kick's level on a beat: the beat is gone
BREATHER_BEATS = (2, 8)  # a breather lasts this many beats (longer: a breakdown, the sections handle it)
BREATHER_AFTER = 4  # … and comes after this many beats with the low end on (a sparse kick pattern isn't one)


def _low_end(a: Analysis):
    """The low end's rise into time t, and its level just after it (dB), as functions of t."""
    low = np.maximum(a.bands_db["sub"], a.bands_db["bass"])
    n = len(low)

    def rise(t: float) -> float:
        f = int(round(t * a.fps))
        return float(low[f - 1 : f + 3].max() - low[f - 4 : f].min()) if 4 <= f < n - 3 else 0.0

    def level(t: float) -> float:
        f = int(round(t * a.fps))
        return float(low[f : f + 6].max()) if 0 <= f < n - 6 else -120.0

    return rise, level


def _typical_kick(a: Analysis, rise, level) -> tuple[float, float]:
    kt = a.onsets.get("kick", (np.zeros(0), np.zeros(0)))[0]
    on = kt if len(kt) >= 8 else a.beats
    return float(np.median([rise(x) for x in on])) + 1e-6, float(np.median([level(x) for x in on]))


def boom(a: Analysis) -> tuple[np.ndarray, np.ndarray]:
    """The boom: the kick on every beat it plays (heard by the kick detector or in the low end), plus its 1/8
    runs. (times, strengths 0..1)"""
    b = a.beats
    if len(b) < 8:
        return np.zeros(0), np.zeros(0, np.float32)
    rise, level = _low_end(a)
    ref_rise, ref_level = _typical_kick(a, rise, level)

    def kick(t: float) -> float:
        r = rise(t)
        return r / ref_rise if r >= BOOM_RISE * ref_rise and level(t) >= ref_level - BOOM_LEVEL_DB else 0.0

    kt, ks = a.onsets.get("kick", (np.zeros(0), np.zeros(0)))
    heard = {int(np.argmin(np.abs(b - x))): float(s) for x, s in zip(kt, ks)}  # the kick detector's beats count too
    on = np.array([max(kick(x), heard.get(k, 0.0)) for k, x in enumerate(b)])
    mids = (b[:-1] + b[1:]) / 2
    off = np.array([kick(x) for x in mids])
    in_run = np.zeros(len(off), bool)
    k = 0
    while k < len(off):
        e = k
        while e < len(off) and off[e] > 0:
            e += 1
        if e - k >= RUN_8THS:
            in_run[k:e] = True
        k = max(e, k + 1)
    t = np.concatenate([b[on > 0], mids[in_run]])
    s = np.concatenate([on[on > 0], off[in_run]])
    order = np.argsort(t)
    return t[order], np.clip(s[order], 0.0, 1.0).astype(np.float32)


def breathers(a: Analysis) -> list[tuple[float, float]]:
    """Where the beat is gone for a moment: (start, end) per breather, from its first silent beat to the beat
    the low end comes back on."""
    b = a.beats
    if len(b) < 8:
        return []
    rise, level = _low_end(a)
    _, ref_level = _typical_kick(a, rise, level)
    gone = np.array([level(x) < ref_level - BREATHER_DB for x in b])
    out, k = [], BREATHER_AFTER
    while k < len(b):
        if gone[k] and not gone[k - BREATHER_AFTER : k].any():
            e = k
            while e < len(b) and gone[e]:
                e += 1
            if BREATHER_BEATS[0] <= e - k <= BREATHER_BEATS[1] and e < len(b):
                out.append((float(b[k]), float(b[e])))
            k = e
        k += 1
    return out
