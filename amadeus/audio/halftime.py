"""Half time: a track that feels half as fast as its grid is counted.

Future bass, trap and dubstep put the snare on every fourth beat of a 140–160 BPM grid, with the kick on a few of the
beats between: the body hears 70–80 BPM, the snare on its two and four (Flume's remix of Disclosure's "You & Me",
counted 150, is a calm 75). The lights should move to that, not twice as fast.

The mix can't tell: the analysis' own snare onsets also hear the synths and the voice in the snare's band, and
across 391 cached tracks they called Coldplay and Swedish House Mafia half time. The separated drums can
(amadeus/audio/drums.py). Folded over four beats, a half-time snare plays one of the four, while a backbeat plays two
of them, two beats apart. On 425 separated tracks:

- half time: the second-loudest snare beat (two after the loudest) at 0.00 of the loudest, the kick on at most 0.38 of
  the beats, counted 140–176 BPM (Flume, Skrillex, The Cost, Temper City, a Dutch song counted double);
- everything else at 0.11 or more, or a kick on (nearly) every beat (SOFI TUKKER's "Manhattan", a clap only on
  three: 0.00, but its kick on 0.97 of the beats), or counted slower than 130 BPM.

Only with the drums separated, so a track is counted at its full tempo until the separation is in; then the analysis
is made again at half the tempo (analysis.analyze with tempo "half"), and the show plans it again as it already does
for the separated instruments.
"""

from __future__ import annotations

import numpy as np

SNARE_SECOND = 0.08  # the snare two beats after its loudest beat, as a share of that one: under this, one in four
KICK_MAX = 0.5  # the kick on fewer of the beats than this (four on the floor plays every beat: never half time)
MIN_BPM = 130.0  # counted at least this fast (halved: 65 BPM and up)
WINDOW, HOP = 32, 16  # beats folded at a time
LOUD_SNARE = 0.4  # a window counts where its loudest snare beat is at least this strong on average
MIN_WINDOWS = 4


def _per_beat(beats: np.ndarray, t: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Each hit's strength summed onto the beat it lands on (within a fifth of a beat), 0 on the others."""
    n = len(beats)
    v = np.zeros(n)
    if not len(t) or n < 2:
        return v
    period = float(np.median(np.diff(beats)))
    j = np.clip(np.searchsorted(beats, t), 1, n - 1)
    near = np.where(np.abs(beats[j - 1] - t) < np.abs(beats[j] - t), j - 1, j)
    on = np.abs(beats[near] - t) < 0.2 * period
    np.add.at(v, near[on], s[on])
    return v


def measure(beats: np.ndarray, kick_t, kick_s, snare_t, snare_s) -> tuple[float, float] | None:
    """(the snare two beats after its loudest beat, as a share of that one; the share of beats with a kick), the
    median over windows of WINDOW beats where the snare plays, or None (too few of them)."""
    beats = np.asarray(beats, float)
    n = len(beats)
    if n < WINDOW * 2:
        return None
    sv = _per_beat(beats, np.asarray(snare_t, float), np.asarray(snare_s, float))
    kv = _per_beat(beats, np.asarray(kick_t, float), np.asarray(kick_s, float))
    second, kicks = [], []
    for k in range(0, n - WINDOW + 1, HOP):
        folded = np.array([sv[k + j : k + WINDOW : 4].mean() for j in range(4)])
        top = int(np.argmax(folded))
        if folded[top] < LOUD_SNARE:
            continue
        second.append(folded[(top + 2) % 4] / folded[top])
        kicks.append(float(np.mean(kv[k : k + WINDOW] > 0)))
    if len(second) < MIN_WINDOWS:
        return None
    return float(np.median(second)), float(np.median(kicks))


def heard(a) -> bool:
    """Does the track play in half time (by its separated drums)? False when it isn't separated."""
    if a.bpm < MIN_BPM:
        return False
    from amadeus.audio import drums

    kit = drums.kit(a)
    if kit.source != "stem":
        return False
    m = measure(a.beats, kit.kick_t, kit.kick_s, kit.snare_t, kit.snare_s)
    return m is not None and m[0] < SNARE_SECOND and m[1] < KICK_MAX
