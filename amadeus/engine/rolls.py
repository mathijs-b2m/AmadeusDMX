"""The snare roll into a drop, and a fill into a phrase, played by the lights: short white flashes on the
roll's own hits, getting denser as the roll speeds up, with more lights joining and each flash brighter,
darkness kept between the hits. Then the drop moment (looks._drop_moment): a breath of darkness, or a
blackout as long as the music's own pause, and everything hits on the downbeat.

The analysis finds the roll, its hits and its steps (amadeus/audio/rolls.py: quarters, eighths, sixteenths,
thirty-seconds, or a fill's own rhythm). The flashes land on those hits, never a free-running strobe, and stay
within the set's flash limit:

- `safety.max_flash_hz` (3 Hz): the whole rig flashes together at most this often, so a fast roll is played
  on the hits of the finest beat subdivision that fits (at 128 BPM: the quarter notes) and builds with lights
  and brightness.
- `safety.allow_fast_strobe`: every hit flashes. Each light flashes at most FAST_FLASH_HZ, so on the fastest
  hits the lights take turns: the rig shows the roll's speed without one light chopping faster than that.
- `safety.strobe_free`: no flashing at all. A roll is played as steps: each faster step lifts more lights to a
  steady, brighter white (a fill is left to the look). (The strobe fixtures stay dark and the flashes on the
  big hits are left out.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from amadeus.engine.state import State
from amadeus.engine.timing import _release

STEP = {1: 0, 2: 1, 4: 2, 8: 3}  # hits per beat → the roll's step
LEVEL = (0.55, 0.7, 0.85, 1.0)  # per step: how bright a flash is…
SHARE = (0.25, 0.5, 0.75, 1.0)  # …the share of the lights that flash…
DUTY = (0.2, 0.3, 0.4, 0.5)  # …and how much of the time to a light's next flash it is lit (darkness shrinks)
FLASH_S = (0.025, 0.12)  # a flash lasts at least / at most this long
STEADY = 0.6  # strobe-free: a step's lights hold this share of its level
UNDER = 0.5  # the lights not flashing yet keep their look at this share, so the flashes read
FAST_FLASH_HZ = 10.0  # allow_fast_strobe: the most one light flashes per second
EVERY = (0.125, 0.25, 0.5, 1.0, 2.0, 4.0)  # flash spacings in beats: subdivisions of the beat, or every 2 or 4
ON_SLOT_S = 0.04  # within the flash limit: a hit within this of a slot of the spacing that fits
FILL_DROP_BEATS = 8  # a roll that ends at most this long before a drop the plan plays as one is its roll


def _spacing(div: int, period: float, hz: float) -> float:
    """The finest spacing (in beats) at or above the roll's own (1/div) that keeps to `hz`."""
    return next((e for e in EVERY if e >= 1.0 / div - 1e-9 and e * period >= 1.0 / hz - 1e-9), EVERY[-1])


def _spread(n: int) -> list[int]:
    """0..n-1 in an order that keeps any first k spread out (bit-reversed): lights join across the stage."""
    bits = max(1, (n - 1).bit_length())
    order = sorted(range(1 << bits), key=lambda k: int(f"{k:0{bits}b}"[::-1], 2))
    return [k for k in order if k < n]


@dataclass
class Roll:
    """One roll or fill: its beats, where it plays, and per light the flashes it plays."""

    first: int  # beat indices
    last: int
    start: float
    end: float
    drop: float | None  # the drop it leads into (None: a fill into a phrase)
    flashes: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = field(default_factory=dict)  # (t, level, on)
    joins: dict[str, float] = field(default_factory=dict)  # when each light joins


class RollsMixin:
    """The snare rolls and fills, and the pause before a drop."""

    def _init_rolls(self, rig: dict) -> None:
        a, safety = self.a, rig["safety"]
        roll = getattr(a, "roll", None)
        self.roll_div = np.asarray(roll, np.int8) if roll is not None and len(roll) == len(self.beats) else None
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
        self.rolls: list[Roll] = []
        if self.roll_div is None or not self.roll_div.any():
            return
        hits = getattr(a, "roll_hits", None)
        hits = np.asarray(hits, float).reshape(-1, 2) if hits is not None else self._grid_hits()
        on = np.flatnonzero(self.roll_div > 0)
        for run in np.split(on, np.flatnonzero(np.diff(on) > 1) + 1):
            first, last = int(run[0]), int(run[-1])
            start = float(self.beats[first]) - 0.05
            end = float(self.beats[min(last + 1, len(self.beats) - 1)])
            drop = next((d for d in self.drops if -0.05 <= d - end <= FILL_DROP_BEATS * self._period_at(end)), None)
            if drop is None and self.strobe_free:
                continue  # strobe-free: a fill is left to the look
            r = Roll(first, last, start, end, drop)
            mine = hits[(hits[:, 0] >= start) & (hits[:, 0] < end)]
            if len(mine) and not self.strobe_free:
                self._schedule(r, mine[:, 0])
            self.rolls.append(r)

    def _grid_hits(self) -> np.ndarray:
        """No hits from the analysis (an older one): the roll's steps on the beat grid."""
        out = []
        for j in np.flatnonzero(self.roll_div > 0):
            b, p = float(self.beats[j]), self._period_at(float(self.beats[j]))
            out += [(b + k * p / int(self.roll_div[j]), 1.0) for k in range(int(self.roll_div[j]))]
        return np.array(out, float).reshape(-1, 2)

    def _step_at(self, t: float) -> int:
        """The roll's step at t (a hit a little early is its beat's)."""
        j = self.beat_info(t + 0.03)[0]
        return STEP.get(int(self.roll_div[min(j, len(self.roll_div) - 1)]), 0) if self.roll_div is not None else 0

    def _schedule(self, r: Roll, times: np.ndarray) -> None:
        """Which light flashes on which of the roll's hits, how bright and how long (see the module's description)."""
        n = len(self.roll_order)
        master = float(self.rig["safety"]["master"])
        if self.fast_strobe:
            played = times
        else:  # the rig together within max_flash_hz: the hits on the finest spacing that fits, at least 1/hz apart
            played, prev = [], -1e9
            for x in times:
                j, phase, period = self.beat_info(float(x))
                every = _spacing(max(1, int(self.roll_div[j])), period, self.roll_hz)
                pos = (j + phase) / every
                on_slot = abs(pos - round(pos)) * every * period <= ON_SLOT_S
                if on_slot and x - prev >= 1.0 / self.roll_hz - 1e-6:
                    played.append(float(x))
                    prev = float(x)
            played = np.array(played)
        # each flash lit for DUTY of the time to the roll's next hit (whichever light plays it): dark between hits
        nxt = np.r_[np.diff(played), FLASH_S[1] / DUTY[-1]] if len(played) else np.zeros(0)
        per: dict[str, list[tuple[float, float, float]]] = {eid: [] for eid in self.roll_order}
        limit = 1.0 / (FAST_FLASH_HZ if self.fast_strobe else self.roll_hz) - 1e-6
        for k, x in enumerate(played):
            step = self._step_at(float(x))
            players = self.roll_order[: max(1, math.ceil(SHARE[step] * n))]
            gap = min(float(x - played[k - 1]) if k else 1.0, float(nxt[k]))  # (to the hit before and after)
            turns = max(1, math.ceil((limit + 0.002) / max(gap, 1e-3))) if self.fast_strobe else 1
            on = min(max(DUTY[step] * float(nxt[k]), FLASH_S[0]), FLASH_S[1])
            free = [eid for eid in players if not per[eid] or x - per[eid][-1][0] >= limit]  # (never faster)
            mine = [eid for i, eid in enumerate(players) if i % turns == k % turns and eid in free]
            for eid in mine or free:  # its turn, or any light free to flash
                per[eid].append((float(x), LEVEL[step] * master, on))
                r.joins.setdefault(eid, float(x))
        for eid, fl in per.items():
            if fl:
                r.flashes[eid] = tuple(np.array(c) for c in zip(*fl))

    def _x_of(self, e: dict) -> float:
        """Where a par or head is across the stage (pars by their order, heads by where they hang)."""
        if e["kind"] == "head":
            return float(self.head_pos[self.heads.index(e)][0])
        n = max(len(self.pars) - 1, 1)
        return self.order.get(e["id"], 0) / n * float(self.stage.get("width_m", 8.0))

    def _period_at(self, t: float) -> float:
        return self.beat_info(t)[2]

    def _roll_at(self, t: float) -> Roll | None:
        """The roll or fill t is in."""
        return next((r for r in self.rolls if r.start <= t < r.end), None)

    def roll_flashes(self, t: float) -> dict[str, float] | None:
        """The roll at t, if any: how bright each light that plays it is (0: dark between its hits)."""
        r = self._roll_at(t)
        if r is None:
            return None
        if self.strobe_free:
            step = self._step_at(t)
            n = len(self.roll_order)
            v = STEADY * LEVEL[step] * float(self.rig["safety"]["master"])
            players = self.roll_order[: max(1, math.ceil(SHARE[step] * n))]
            return {eid: v for eid in players if eid not in self.roll_strobes}
        out = {}
        for eid, (ts, levels, ons) in r.flashes.items():
            if t < r.joins[eid] - 0.02:
                continue  # not playing yet: its look, dimmed
            k = int(np.searchsorted(ts, t, side="right")) - 1
            out[eid] = _release(t - ts[k], float(levels[k]), 0.7 * ons[k], 0.3 * ons[k]) if k >= 0 else 0.0
        return out

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
