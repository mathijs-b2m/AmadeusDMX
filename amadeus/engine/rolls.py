"""The snare roll into a drop, played by the lights: short white flashes on the roll's own hits, getting denser
as the roll speeds up, with more lights joining and each flash brighter, darkness kept between the hits. Then
the drop moment (looks._drop_moment): a breath of darkness, or a blackout as long as the music's own pause,
and everything hits on the downbeat.

The analysis finds the roll and its steps (amadeus/audio/rolls.py: quarters, eighths, sixteenths,
thirty-seconds). The flashes follow those steps, never a free-running strobe, and stay within the set's
flash limit:

- `safety.max_flash_hz` (3 Hz): the whole rig flashes together at most this often, so a fast roll is played on
  the finest beat subdivision that fits (at 128 BPM: quarter notes) and builds with lights and brightness.
- `safety.allow_fast_strobe`: over the roll's last FAST_MAX_S each light may flash up to FAST_FLASH_HZ, and the
  lights take turns on the faster subdivisions, so the rig shows the roll's speed without one light chopping
  faster than that.
- `safety.strobe_free`: no flashing at all. The roll is played as steps: each faster step lifts more lights to
  a steady, brighter white. (The strobe fixtures stay dark and the flashes on the big hits are left out.)
"""

from __future__ import annotations

import math

import numpy as np

from amadeus.engine.state import State
from amadeus.engine.timing import _release

STEP = {1: 0, 2: 1, 4: 2, 8: 3}  # hits per beat → the roll's step
LEVEL = (0.55, 0.7, 0.85, 1.0)  # per step: how bright a flash is…
SHARE = (0.25, 0.5, 0.75, 1.0)  # …the share of the lights that flash…
DUTY = (0.2, 0.3, 0.4, 0.5)  # …and how much of the time between a light's flashes it is lit (darkness shrinks)
FLASH_S = (0.025, 0.12)  # a flash lasts at least / at most this long
STEADY = 0.6  # strobe-free: a step's lights hold this share of its level
UNDER = 0.5  # the lights not flashing yet keep their look at this share, so the flashes read
FAST_FLASH_HZ = 10.0  # allow_fast_strobe: the most one light flashes per second…
FAST_MAX_S = 6.0  # …over the roll's last seconds only
EVERY = (0.125, 0.25, 0.5, 1.0, 2.0, 4.0)  # flash spacings in beats: subdivisions of the beat, or every 2 or 4


def _spacing(div: int, period: float, hz: float) -> float:
    """The finest spacing (in beats) at or above the roll's own (1/div) that keeps to `hz`."""
    return next((e for e in EVERY if e >= 1.0 / div - 1e-9 and e * period >= 1.0 / hz - 1e-9), EVERY[-1])


def _spread(n: int) -> list[int]:
    """0..n-1 in an order that keeps any first k spread out (bit-reversed): lights join across the stage."""
    bits = max(1, (n - 1).bit_length())
    order = sorted(range(1 << bits), key=lambda k: int(f"{k:0{bits}b}"[::-1], 2))
    return [k for k in order if k < n]


class RollsMixin:
    """The snare roll and the pause before a drop."""

    def _init_rolls(self, rig: dict) -> None:
        a, safety = self.a, rig["safety"]
        roll = getattr(a, "roll", None)
        self.roll_div = np.asarray(roll, np.int8) if roll is not None and len(roll) == len(self.beats) else None
        # only rolls that end at a drop the plan plays as one: (first beat index, last beat index, drop)
        self.rolls: list[tuple[int, int, float]] = []
        if self.roll_div is not None and self.roll_div.any() and self.drops:
            on = np.flatnonzero(self.roll_div > 0)
            for run in np.split(on, np.flatnonzero(np.diff(on) > 1) + 1):
                end = float(self.beats[min(run[-1] + 1, len(self.beats) - 1)])
                drop = next((d for d in self.drops if -0.05 <= d - end <= 8 * self._period_at(end)), None)
                if drop is not None:
                    self.rolls.append((int(run[0]), int(run[-1]), drop))
        pauses = getattr(a, "pauses", None)
        self.pause_before = {}  # drop → when its pause starts
        for start, drop in pauses if pauses is not None else ():
            near = [d for d in self.drops if abs(d - drop) < 0.1]
            if near:
                self.pause_before[near[0]] = float(start)
        self.strobe_free = bool(safety.get("strobe_free", False))
        self.fast_strobe = bool(safety.get("allow_fast_strobe", False)) and not self.strobe_free
        self.roll_hz = float(safety.get("max_flash_hz", 3.0))
        # who flashes first: the strobes (made for it), then the rest spread over the stage, left to right
        strobes = [e["id"] for e in rig["elements"] if e["kind"] == "strobe"]
        lights = [e["id"] for e in sorted(self.pars + self.heads, key=self._x_of)]
        self.roll_order = strobes + [lights[k] for k in _spread(len(lights))] if lights else strobes
        self.roll_strobes, self.roll_lights = set(strobes), set(self.roll_order)

    def _x_of(self, e: dict) -> float:
        """Where a par or head is across the stage (pars by their order, heads by where they hang)."""
        if e["kind"] == "head":
            return float(self.head_pos[self.heads.index(e)][0])
        n = max(len(self.pars) - 1, 1)
        return self.order.get(e["id"], 0) / n * float(self.stage.get("width_m", 8.0))

    def _period_at(self, t: float) -> float:
        return self.beat_info(t)[2]

    def _roll_at(self, t: float) -> tuple[int, float, float, float] | None:
        """The roll t is in: (hits per beat, where in the beat grid (beat index + phase), beat length, seconds left)."""
        if not self.rolls:
            return None
        j, phase, period = self.beat_info(t)
        for first, last, _ in self.rolls:
            if first <= j <= last:
                end = float(self.beats[min(last + 1, len(self.beats) - 1)])
                return int(self.roll_div[j]), j + phase, period, end - t
        return None

    def roll_flashes(self, t: float) -> dict[str, float] | None:
        """The roll at t, if any: how bright each light that plays it is (0: dark between its hits)."""
        now = self._roll_at(t)
        if now is None:
            return None
        div, pos, period, left = now
        step = STEP.get(div, 0)
        n = len(self.roll_order)
        players = self.roll_order[: max(1, math.ceil(SHARE[step] * n))]
        master = float(self.rig["safety"]["master"])
        level = LEVEL[step] * master
        if self.strobe_free:
            v = STEADY * level
            flashes = {eid: v for eid in players if eid not in self.roll_strobes}
        else:
            fast = self.fast_strobe and left <= FAST_MAX_S
            own = _spacing(div, period, FAST_FLASH_HZ if fast else self.roll_hz)  # how often one light flashes
            every = 1.0 / div if fast else own  # fast: the lights take turns on every hit of the roll
            turns = max(1, round(own / every))
            slot = int(math.floor(pos / every + 1e-6))
            since = (pos - slot * every) * period
            on = min(max(DUTY[step] * every * period, FLASH_S[0]), FLASH_S[1])
            v = _release(since, level, 0.7 * on, 0.3 * on)
            flashes = {eid: (v if slot % turns == k % turns else 0.0) for k, eid in enumerate(players)}
        return flashes

    def _roll(self, t: float, states: dict[str, State], skip: set[str] = frozenset()) -> None:
        """Play the roll over the look (see the module's description): its lights white, the strobes not playing
        yet dark, the others' look dimmed. `skip`: lights left as they are (the heads while they move in black
        to the drop's picture)."""
        flashes = self.roll_flashes(t)
        if flashes is None:
            return
        for eid, s in states.items():
            if eid in skip:
                continue
            if eid in flashes:
                s.dimmer, s.white = flashes[eid], flashes[eid]
                s.r, s.g, s.b = 1.0, 1.0, 1.0
            elif eid in self.roll_strobes:
                s.dimmer, s.white = 0.0, 0.0
            elif eid in self.roll_lights:
                s.dimmer, s.white = s.dimmer * UNDER, s.white * UNDER

    def _pause_dark(self, drop: float, t: float, period: float) -> bool:
        """Dark before this drop: the last half beat, or the music's own pause before it, whichever is longer."""
        start = min(self.pause_before.get(drop, drop), drop - 0.5 * period)
        return start < t < drop
