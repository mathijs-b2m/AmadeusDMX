"""Colour wheels turn in the dark: a beam at full brightness never shows the wheel moving.

What the big consoles call move in black (grandMA), mark (Eos, MagicQ) or move in dark (Titan), for a show nobody
programmed. A wheel has no fade, so a head's colour is one change at one moment, and the engine looks ahead to find
where that change can hide. Per change, in this order:

1. The head is dark long enough just before the new colour: the wheel turns in that gap, nobody sees it.
2. A dark gap long enough within a bar before it: the wheel turns there, the new colour comes a little early.
3. A dark gap within a bar after it: the old colour stays until then.
4. No gap: the old note lets go early, the wheel turns in the dark that leaves, and the new colour hits on time. At
   most once in two bars, so a look that changes colour every bar doesn't chop: the colours in between are skipped.

Colours too short for a wheel (a fill's hit, a glint) are skipped too. How long a turn takes depends on the distance
round the wheel and the fixture (`color_wheel.slot_s`, from a GDTF's RealFade; else a typical wheel). Only heads
whose wheel makes the colour: CMY heads mix, and lasers switch their macros at once.

Everything is worked out on a coarse grid some seconds ahead of the show, a few frames per render, so a jump in time
never stalls the light loop: after one the wheel starts from where the show is and the look-ahead fills up again.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from amadeus.library import fixtures as fxlib

TRACE_FPS = 20  # the look-ahead's grid; shorter gaps are no use to a wheel
DARK = 0.03  # at or below this level a turning wheel can't be seen
SLOT_S = 0.08  # a typical wheel: about this long per slot (no maker publishes this)
SLOT_S_RANGE = (0.02, 0.3)  # what a fixture may say, so a bad file can't stop the wheel or wait for ever
SETTLE_S = 0.15  # starting up and settling on the slot
MIN_HOLD_S = 0.5  # a colour that doesn't last this long isn't worth a turn of the wheel
RELEASE_S = 0.12  # the old note's gentle release, before the dark of a made gap
DIP_EVERY_BARS = 2  # a head makes a gap at most this often
MAX_BAR_S = 2.5  # how far a colour may move, at most (very slow tracks have long bars)
FILL_PER_RENDER = 12  # look-ahead frames per render, at most: catches up after a jump without a stall
JUMP_S = 1.0  # time moving further than this at once (or back at all): a seek, a loop, another deck
BACK_S = 0.25  # (a little backwards is a phase lock nudging the clock)


def slot_seconds(defn: dict) -> float:
    """How long this wheel takes per slot."""
    v = defn["color_wheel"].get("slot_s")
    return min(max(float(v), SLOT_S_RANGE[0]), SLOT_S_RANGE[1]) if v else SLOT_S


def travel_s(n: int, slot_s: float, a: int, b: int) -> float:
    """From slot a to slot b on a wheel of n slots, the shortest way round."""
    return SETTLE_S + min((a - b) % n, (b - a) % n) * slot_s


def wheel_fixtures(rig: dict) -> dict[str, dict]:
    """The elements whose colour comes from a wheel, with their definitions."""
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    out = {}
    for e in rig["elements"]:
        fx = fixtures[e["fixture"]]
        defn = fxlib.get(fx["fixture"])
        if e["kind"] == "laser" or not fxlib.has_wheel(defn) or len(defn["color_wheel"]["slots"]) < 2:
            continue
        attrs = {c["attr"] for c in fxlib.channels(defn, fx["mode"])}
        if "color_wheel" in attrs and "cyan" not in attrs:
            out[e["id"]] = defn
    return out


class _Wheel:
    """One head's wheel: what the show wants per look-ahead frame, and where the wheel really is told to go."""

    def __init__(self, defn: dict, frames: int):
        self.defn = defn
        self.slots = defn["color_wheel"]["slots"]
        self.slot_s = slot_seconds(defn)
        self.want = np.zeros(frames, np.int16)
        self.lit = np.zeros(frames, bool)
        self.slot = np.zeros(frames, np.int16)  # the slot sent, per frame
        self.dips: list[tuple[float, float, float]] = []  # gaps made: (release starts, dark from, new colour hits)
        self.restart(0, 0)

    def restart(self, frame: int, slot: int):
        self.slot[:] = slot
        self.cur = self.heard = slot  # where the wheel goes; the colour of the last lit frame seen
        self.scan = frame + 1
        self.last_dip = -math.inf
        self.dips.clear()

    def index(self, rgb) -> int:
        return self.slots.index(fxlib.nearest_slot(self.defn, rgb))

    def _move(self, frame: int, slot: int):
        self.slot[frame:] = slot
        self.cur = slot

    def _dark_before(self, c: int, floor: int) -> int:
        """The dark frames right before frame c, not before `floor`."""
        k = c
        while k > floor and not self.lit[k - 1]:
            k -= 1
        return c - k

    def _short(self, c: int, frames: int) -> bool:
        """The colour at frame c is gone again too soon (dark frames don't count: a note may end and come back)."""
        end = min(c + frames, len(self.want))
        return bool((self.lit[c:end] & (self.want[c:end] != self.want[c])).any())

    def _gap_before(self, c: int, need: int, floor: int) -> int | None:
        """The start of the last dark gap of at least `need` frames in floor..c."""
        k = c
        while k > floor:
            if self.lit[k - 1]:
                k -= 1
                continue
            run = self._dark_before(k, floor)
            if run >= need:
                return k - run
            k -= run
        return None

    def _gap_after(self, c: int, need: int, ceil: int) -> bool:
        run = 0
        for lit in self.lit[c:ceil]:
            run = 0 if lit else run + 1
            if run >= need:
                return True
        return False

    def decide(self, limit: int, floor: int, bar: int, hit_time, on_bar, gaps: bool) -> None:
        """Place the changes up to frame `limit`; frames before `floor` have been played."""
        hold = int(MIN_HOLD_S * TRACE_FPS)
        n = len(self.slots)
        for c in range(self.scan, limit + 1):
            if not self.lit[c]:
                continue
            b = int(self.want[c])
            fresh = b != self.heard
            self.heard = b
            if b == self.cur:
                continue
            need = math.ceil(travel_s(n, self.slot_s, self.cur, b) * TRACE_FPS)
            dark = self._dark_before(c, floor)
            if dark >= need:  # 1: in the gap before it, on time
                self._move(c - dark, b)
                continue
            hit = hit_time(c)
            due = hit - self.last_dip >= DIP_EVERY_BARS * bar / TRACE_FPS
            if not fresh and not (due and on_bar(c)):  # (held back earlier: wait for a bar's start, or a gap)
                continue
            if self._short(c, hold):
                continue
            gap = self._gap_before(c, need, max(floor, c - bar))
            if gap is not None:  # 2: a little early
                self._move(gap, b)
            elif self._gap_after(c, need, c + bar):  # 3: a little late (1 takes it at the gap's end)
                continue
            elif due and gaps:  # 4: make the gap
                start = max(hit - (need + 1) / TRACE_FPS, floor / TRACE_FPS)  # (a frame's margin: see below)
                if start < hit:
                    self.dips.append((max(start - RELEASE_S, floor / TRACE_FPS), start, hit))
                    self.last_dip = hit
                self._move(max(math.ceil(start * TRACE_FPS), floor), b)  # on the grid, once it's dark
        self.scan = max(self.scan, limit + 1)

    def gain(self, t: float) -> float:
        """The made gaps: 1 is the look as it is, 0 dark."""
        for start, dark, end in reversed(self.dips):
            if end <= t:
                break
            if start <= t:
                return 0.0 if t >= dark else 1.0 - (t - start) / max(dark - start, 1e-6)
        return 1.0


class WheelsMixin:
    def _init_wheels(self, rig: dict):
        frames = int(self.a.duration * TRACE_FPS) + 2
        self.wheel_heads = {eid: _Wheel(defn, frames) for eid, defn in wheel_fixtures(rig).items()}
        beat = float(np.median(np.diff(self.beats))) if len(self.beats) > 1 else 0.5
        self.wheel_bar = max(int(min(4 * beat, MAX_BAR_S) * TRACE_FPS), 1)
        self.wheel_look = self.wheel_bar + int((MIN_HOLD_S + 1.0) * TRACE_FPS)  # to decide a change: what comes after
        slowest = max((w.slot_s * len(w.slots) / 2 for w in self.wheel_heads.values()), default=0.0)
        turn = int((slowest + SETTLE_S + RELEASE_S) * TRACE_FPS) + 2  # the longest gap to make
        self.wheel_ahead = self.wheel_look + max(self.wheel_bar, turn) + 1  # and a gap before it must still be ahead
        self.wheel_bars = {int(math.ceil(float(x) * TRACE_FPS)) for x in self.downbeat_times}
        self.wheel_frames = frames
        self.wheel_seen = -1  # the look-ahead reaches this frame
        self.wheel_t: float | None = None
        self.wheel_gaps = True  # may the show make a gap for a wheel? (a stand-in groove stays lit: no)

    def _wheel_colours(self, mixed: dict, colours: dict) -> dict:
        """A crossfade fades a wheel head's beam, not its colour: a wheel has no colours in between."""
        for eid in self.wheel_heads:
            mixed[eid].r, mixed[eid].g, mixed[eid].b = colours[eid].r, colours[eid].g, colours[eid].b
        return mixed

    def _wheel_note(self, frame: int, states: dict):
        self.wheel_seen = frame
        for eid, w in self.wheel_heads.items():
            s = states[eid]
            w.want[frame] = w.index((s.r, s.g, s.b))
            w.lit[frame] = (s.strobe or max(s.dimmer, s.white)) > DARK

    def _wheel_hit(self, frame: int) -> float:
        """When the note at this look-ahead frame starts: on the beat it's next to."""
        t = frame / TRACE_FPS
        k = bisect.bisect_left(self.beats, t)
        near = [float(self.beats[j]) for j in (k - 1, k) if 0 <= j < len(self.beats)]
        best = min(near, key=lambda x: abs(x - t), default=t)
        return best if abs(best - t) <= 1.5 / TRACE_FPS else t

    def _wheels_play(self, t: float, states: dict):
        """The last word on the wheel heads: the slot the plan says for now, dark in a gap it made."""
        if not self.wheel_heads:
            return
        frame = min(max(int(t * TRACE_FPS), 0), self.wheel_frames - 1)
        if self.wheel_t is None or t < self.wheel_t - BACK_S or t > self.wheel_t + JUMP_S:
            self._wheel_note(frame, states)
            for w in self.wheel_heads.values():
                w.restart(frame, int(w.want[frame]))
        self.wheel_t = t
        goal = min(frame + self.wheel_ahead, self.wheel_frames - 1)
        for k in range(self.wheel_seen + 1, min(goal, self.wheel_seen + FILL_PER_RENDER) + 1):
            self._wheel_note(k, self._look(k / TRACE_FPS, peek=True)[1])
        done = self.wheel_seen >= self.wheel_frames - 1
        limit = self.wheel_seen if done else self.wheel_seen - self.wheel_look
        for eid, w in self.wheel_heads.items():
            w.decide(limit, frame + 1, self.wheel_bar, self._wheel_hit, self.wheel_bars.__contains__, self.wheel_gaps)
            s = states[eid]
            s.r, s.g, s.b = w.slots[int(w.slot[frame])]["rgb"]
            gain = w.gain(t)
            s.dimmer, s.strobe = s.dimmer * gain, s.strobe * gain
