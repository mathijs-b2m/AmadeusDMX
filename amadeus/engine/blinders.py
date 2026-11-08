"""Blinders: the punch for the heaviest moments of a song only, in every program.

A blinder lit often stops meaning anything, and it blinds the audience. So:

- **where**: only in the song's heaviest phrases. A phrase's weight is its loudness and its low end (as
  percentiles); it counts as heavy when it is heavy in itself (HEAVY_MIN), within HEAVY_MARGIN of the heaviest
  phrase around it (the whole song; in a long live set NEIGHBOUR_S either way, about the track it is in), and
  one of the HEAVY_PHRASES heaviest there. Usually the last drop or the last chorus.
- **what**: a heavy phrase's downbeat slams them in and lets them go over a bar (a build into a heavy drop
  swells them over its last two beats first); inside it they punch on a few of its biggest hits (the track's
  top accents, at most PUNCHES_PER_PHRASE, PUNCH_GAP_BARS apart), each a note: on at once, held, let go gently.
- everywhere else: dark. They never play the booms with the floor lights.
"""

from __future__ import annotations

import bisect

import numpy as np

from amadeus.engine.state import State
from amadeus.engine.timing import _release

HEAVY_MIN = 40.0  # a phrase's weight (0.55·loudness + 0.45·low end, percentiles) from which it can be heavy
HEAVY_MARGIN = 5.0  # …and within this many points of the heaviest phrase around it
HEAVY_PHRASES = 2  # …and of those around it at most this many, the heaviest
WHOLE_TRACK_S = 600.0  # a track up to this long: "around it" is the whole track
NEIGHBOUR_S = 180.0  # a longer one (a live set): this far either way, about the track it is in
TOP_ACCENTS = 0.9  # a punch: an accent at least as strong as this share of the track's accents
PUNCHES_PER_PHRASE = 2  # besides the slam on its downbeat
PUNCH_GAP_BARS = 2  # punches at least this far apart (and from the slam)
PUNCH_HOLD_S, PUNCH_RELEASE_S = 0.25, 0.7
SWELL_BEATS = 2
SWELL_LEVEL = 0.8
WARM = (1.0, 0.72, 0.42)  # tungsten


def phrase_weight(p) -> float:
    return 0.55 * p.loudness_pct + 0.45 * p.low_pct


def heavy_phrases(phrases) -> set[int]:
    """The indices of the heaviest phrases: heavy in themselves, (nearly) the heaviest around them, and of
    those around a moment at most HEAVY_PHRASES, the heaviest (the later one when equal: songs end big)."""
    if not phrases:
        return set()
    w = np.array([phrase_weight(p) for p in phrases])
    mid = np.array([(p.start + p.end) / 2 for p in phrases])
    whole = mid[-1] - mid[0] <= WHOLE_TRACK_S  # one song: it is its own neighbourhood
    out: set[int] = set()
    for i in range(len(phrases)):
        near = np.ones(len(w), bool) if whole else np.abs(mid - mid[i]) <= NEIGHBOUR_S
        if w[i] < HEAVY_MIN or w[i] < w[near].max() - HEAVY_MARGIN:
            continue
        rivals = [j for j in np.flatnonzero(near) if w[j] >= HEAVY_MIN and w[j] >= w[near].max() - HEAVY_MARGIN]
        if i in sorted(rivals, key=lambda j: (-w[j], -j))[:HEAVY_PHRASES]:
            out.add(i)
    return out


def pick_punches(times, strengths, start: float, end: float, floor: float, bar: float, avoid=()) -> list[float]:
    """The phrase's biggest hits (at least `floor`), strongest first, kept PUNCH_GAP_BARS apart (and from
    `avoid`), at most PUNCHES_PER_PHRASE, in time order."""
    sel = (times >= start) & (times < end) & (strengths >= floor)
    cand = sorted(zip(times[sel], strengths[sel]), key=lambda x: -x[1])
    gap = PUNCH_GAP_BARS * bar - 0.02
    kept: list[float] = []
    for t, _ in cand:
        if all(abs(t - k) >= gap for k in (*kept, *avoid)):
            kept.append(float(t))
            if len(kept) >= PUNCHES_PER_PHRASE:
                break
    return sorted(kept)


class BlindersMixin:
    """When the blinders light: worked out once per track, played the same in every program."""

    def _init_blinders(self, rig: dict):
        self.blinder_ids = [e["id"] for e in rig["elements"] if e["kind"] == "blinder"]
        self.blinder_heavy: set[int] = set()
        self.blinder_punches = np.zeros(0)
        if not self.blinder_ids:
            return
        phrases = self.a.phrases
        self.blinder_heavy = {i for i in heavy_phrases(phrases) if i < len(self.plan)}
        acc_t, acc_s = np.asarray(self.acc_t, float), np.asarray(self.acc_s, float)
        floor = float(np.quantile(acc_s, TOP_ACCENTS)) if len(acc_s) else 1.0
        bar = 4 * 60.0 / max(float(self.a.bpm or 120), 1.0)
        punches: list[float] = []
        for i in sorted(self.blinder_heavy):
            d = self.plan[i]
            punches += pick_punches(acc_t, acc_s, d.start + 0.02, d.end, floor, bar, (d.start,))
        self.blinder_punches = np.array(sorted(punches))

    def blinder_level(self, t: float) -> float:
        """How bright the blinders are at t (0..1)."""
        if not self.blinder_heavy:
            return 0.0
        i, d = self.decision_at(t)
        _, _, period = self.beat_info(t)
        level = 0.0
        size = 1.0 if self.drop_strength is None else self.drop_strength  # the show arc's "drops" knob
        if i in self.blinder_heavy and t - d.start < 4 * period:
            level = (1.0 - (t - d.start) / (4 * period)) * size  # the slam: full → dark over the first bar
        k = bisect.bisect_right(self.blinder_punches, t)
        if k:
            level = max(level, _release(t - float(self.blinder_punches[k - 1]), 1.0, PUNCH_HOLD_S, PUNCH_RELEASE_S))
        nxt = i + 1
        if nxt in self.blinder_heavy and nxt in self.drop_idx and nxt < len(self.plan):
            left = self.plan[nxt].start - t
            if left < SWELL_BEATS * period:
                level = max(level, (1.0 - left / (SWELL_BEATS * period)) ** 2 * SWELL_LEVEL * size)
        return level

    def _blinders(self, t: float, states: dict[str, State]) -> None:
        if not self.blinder_ids:
            return
        dim = self.blinder_level(t)
        for eid in self.blinder_ids:
            states[eid] = State(dimmer=dim, r=WARM[0], g=WARM[1], b=WARM[2])
