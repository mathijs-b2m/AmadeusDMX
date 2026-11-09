"""Wall uplighters (rig/uplights.py): tilting bars on the floor by the walls, for depth in the room and on camera.

- **aim**: straight up, along the wall onto the ceiling, all night. They are no moving heads: the heads' motion
  never drives them.
- **light**: a run along the walls on the beat grid, one step a beat from the stage to the back of the room (bars
  at the same depth, a mirrored pair across the room, are one step). Each step is a note: on at the beat, held,
  let go gently while the next one comes, so the run flows instead of blinking. The level is the phrase's (the
  look's intensity), not the loudness from moment to moment, and well under the heads' (a layer behind the show,
  never the brightest thing in the room: they leave the heads their headroom). Where the beat doesn't drive the
  music (a breakdown, an intro, the kick gone), the run steps once a bar, softer.
- **cells**: a bar of cells plays as one light in calm phrases. In phrases that drive, at times its cells play a
  pattern along the bar: a waterfall from the stage end to the back (continuing the run: the next step's bars take
  it over), or out from the middle. Each cell is its own short note started on the grid, so only part of the bar is
  lit at a time: it moves, and stays dimmer.
- **move**: only at the night's surprise (`surprise`: a phrase the show arc grants once or twice a night, the
  moment the LED wall counts into; show/arc.py). On its downbeat the steps lean in towards the room, one a beat,
  lit full; four bars later they stand back up, one a beat. Never more: a move seen every drop is no surprise.
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from amadeus.director.style import BEAT_SECTIONS
from amadeus.engine.motion import DEFAULT_MOTION, DMX_LEAD_S
from amadeus.engine.state import State
from amadeus.engine.timing import _ease, _release
from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry

STEP_GAP_M = 0.75  # bars this close in depth are one step of the run (a mirrored pair across the room)
HOLD_STEPS, RELEASE_STEPS = 0.5, 1.5  # a step's note: held this many steps, let go over this many
RUN_LEVEL = 0.55  # a step at its peak: well under the heads, so they keep their headroom
QUIET_LEVEL = 0.35  # a run once a bar (no beat to lock on) is softer
CELL_HOLD, CELL_RELEASE = 0.1, 0.4  # a cell's note in a pattern, in steps: short, so the pattern travels
CELL_SPREAD = 0.8  # the pattern runs over the bar in this much of a step (the last cell lights here)
LEAN_DEG = 35.0  # the surprise: leaning in this far from straight up …
EYE_MARGIN_DEG = 3.0  # … never under the eye rule for low heads (audience_min_up_deg) plus this
SURPRISE_HOLD_BEATS = 16  # leaning for four bars, then back up


class UplightsMixin:
    """Wall uplighters: light and aim, worked out once per track."""

    def _init_uplights(self, rig: dict, fixtures: dict):
        self.surprise: int | None = None  # the phrase they lean in at (set by the show arc, or the player)
        els = [e for e in rig["elements"] if e.get("uplight")]
        self.uplight_ids = [e["id"] for e in els]
        self.up_steps: list[list[str]] = []
        self.up_aim: dict[str, tuple[float, float, float, float]] = {}  # element → (pan, up, lean, travel s)
        self.up_rank: dict[str, float] = {}  # a cell's place along its bar: 0 the stage end .. 1 the back end
        if not els:
            return
        st = self.stage
        units: dict[str, list[dict]] = {}
        for e in els:
            units.setdefault(e["fixture"], []).append(e)
        placed = []
        for fid, cells in units.items():
            fx = fixtures[fid]
            defn = fxlib.get(fx["fixture"])
            at = [geometry.position(rig, e, fx) for e in cells]
            pos = np.mean(at, axis=0)
            order = sorted(range(len(cells)), key=lambda i: (round(float(at[i][1]), 3), float(at[i][0])))
            for r, i in enumerate(order):
                self.up_rank[cells[i]["id"]] = r / max(len(cells) - 1, 1)
            placed.append((float(pos[1]), [e["id"] for e in cells]))
            pan, up = geometry.to_dmx(fx, defn, *geometry.ik(fx, defn, np.array([0.0, 0.0, 1.0]), None))
            lean_deg = LEAN_DEG
            if st.get("eye_safety"):
                lean_deg = min(lean_deg, 90.0 - st["audience_min_up_deg"] - EYE_MARGIN_DEG)
            r = math.radians(fx.get("rot_deg", 0.0))
            front = np.array([-math.sin(r), math.cos(r)])  # the way the bar tilts (its front, seen from above)
            middle = np.array([st["width_m"] / 2, float(st.get("room_depth_m") or 6.0) / 2]) - pos[:2]
            if front @ middle < 0:
                front = -front
            a = math.radians(lean_deg)
            d = np.array([front[0] * math.sin(a), front[1] * math.sin(a), math.cos(a)])
            _, lean = geometry.to_dmx(fx, defn, *geometry.ik(fx, defn, d, None))
            speed = float(defn.get("motion", DEFAULT_MOTION)["tilt_speed_dps"])
            for e in cells:
                self.up_aim[e["id"]] = (pan, up, lean, max(0.15, lean_deg / max(speed, 1.0)))
        placed.sort(key=lambda p: p[0])  # from the stage to the back of the room
        for y, ids in placed:
            if self.up_steps and y - self._up_step_y < STEP_GAP_M:
                self.up_steps[-1] += ids
            else:
                self.up_steps.append(list(ids))
                self._up_step_y = y

    def _uplight_quiet(self, d, t: float) -> bool:
        """No beat to lock on: a calm section, or the kick gone for a while inside one."""
        if d.section not in BEAT_SECTIONS:
            return True
        return any(s <= t < e for s, e, _ in self.kick_breaks)

    def _uplight_pattern(self, d) -> str:
        """How a bar's cells play this phrase: "whole" (one light), "fall" (a waterfall from the stage end to the
        back) or "out" (from the middle out). Calm phrases play whole; phrases that drive, at times a pattern."""
        if d.section not in BEAT_SECTIONS:
            return "whole"
        if d.intensity >= 2:
            return ("fall", "out")[d.phrase % 2]
        return ("whole", "fall")[d.phrase % 2]

    def _uplight_run(self, d, t: float, s: int, lag: float, pattern: str) -> float:
        """A cell's level (0..1) in the run along the walls, a step a beat (a bar when quiet): the cell of step
        `s` whose note starts `lag` (a fraction of a step) after the step's beat."""
        n = len(self.up_steps)
        quiet = self._uplight_quiet(d, t)
        grid = self.downbeat_times if quiet else self.beats
        k = bisect.bisect_right(grid, t) - 1
        if k < 0 or not n:
            return 0.0
        k0 = min(bisect.bisect_left(grid, d.start - 0.02), k)  # the phrase's first step: the run starts at the stage
        top = QUIET_LEVEL if quiet else RUN_LEVEL
        hold, release = (HOLD_STEPS, RELEASE_STEPS) if pattern == "whole" else (CELL_HOLD, CELL_RELEASE)
        v = 0.0
        for j in range(max(k0, k - math.ceil(hold + release + 1)), k + 1):
            if (j - k0) % n != s:
                continue
            length = float(grid[j + 1] - grid[j]) if j + 1 < len(grid) else self.beat_info(t)[2] * (4 if quiet else 1)
            dt = t - float(grid[j]) - lag * length
            if dt >= 0:
                v = max(v, _release(dt, top, hold * length, release * length))
        return v

    def _uplight_lean(self, t: float) -> list[float]:
        """How far each step leans in (0 up .. 1 leaning): only in the surprise phrase."""
        n = len(self.up_steps)
        if self.surprise is None or not 0 <= self.surprise < len(self.plan) or not n:
            return [0.0] * n
        b = self.beats
        k = bisect.bisect_left(b, self.plan[self.surprise].start - 0.02)
        out = []
        for s in range(n):
            if k + s + SURPRISE_HOLD_BEATS >= len(b):
                out.append(0.0)
                continue
            t_in, t_out = float(b[k + s]), float(b[k + s + SURPRISE_HOLD_BEATS])
            travel = next(iter(self.up_aim.values()))[3]
            out.append(_ease(min(max((t - t_in) / travel, 0.0), 1.0)) - _ease(min(max((t - t_out) / travel, 0.0), 1.0)))
        return out

    def _uplight_states(self, d, t: float, out: dict[str, State]) -> None:
        """The uplighters' states in a look (before its intensity: the phrase sets their level)."""
        if not self.uplight_ids:
            return
        col = self._colours(d)[0]
        pattern = self._uplight_pattern(d)
        lean_now, lean_dmx = self._uplight_lean(t), self._uplight_lean(t + DMX_LEAD_S)
        for s, ids in enumerate(self.up_steps):
            for eid in ids:
                rank = self.up_rank.get(eid, 0.0)
                lag = {"whole": 0.0, "fall": rank, "out": abs(rank - 0.5) * 2}[pattern] * CELL_SPREAD
                level = max(self._uplight_run(d, t, s, lag, pattern), lean_now[s])  # leaning in: lit full
                pan, up, lean, _ = self.up_aim[eid]
                out[eid] = State(
                    dimmer=level,
                    r=col[0],
                    g=col[1],
                    b=col[2],
                    pan=pan,
                    tilt=up + (lean - up) * lean_now[s],
                    dmx_pan=pan,
                    dmx_tilt=up + (lean - up) * lean_dmx[s],
                )
