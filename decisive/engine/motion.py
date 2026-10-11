"""Head motion: where each head points, and a motor simulation of how it really gets there."""

from __future__ import annotations

import bisect
import json
import math
from pathlib import Path

import numpy as np

from decisive import paths
from decisive.director import Decision
from decisive.engine.looks import PREDROP_BEATS, XFADE
from decisive.engine.timing import _ease
from decisive.library import fixtures as fxlib
from decisive.rig import geometry

MOTION_FPS = 50


TRAJ_CACHE = paths.CACHE / "trajectories"


DMX_LEAD_S = 0.12  # pan/tilt targets go out this early, so the head lands on the beat


MIN_BEAT_SWING_DEG = 30  # below this a one-beat move looks like a twitch: use two beats instead


TEMPO = [0.6, 1.0, 1.5, 2.0]  # path speed per intensity level: slow when calm, twice as fast at peaks


MOVE_SCALE = [0.6, 0.8, 1.0, 1.2]  # movement size per intensity level: calm parts move less, drops more


POINT_DISTANCE_M = 3.0  # focus/cross: how far in front of the rig the shared point floats
FOCUS_SPREAD_M = 1.5  # …and how wide the heads spread around it: never every beam into one single spot


def focus_spread(point: np.ndarray, d: np.ndarray, side: float, dz: float) -> np.ndarray:
    """Each head's own spot around a shared point (rows of `point`/`d`): across the beam by where the head
    is in the rig (left to the left), up or down a little by its height, so the beams never meet in one spot."""
    d = np.atleast_2d(d)
    d = d / (np.linalg.norm(d, axis=1, keepdims=True) + 1e-9)
    across = np.cross(d, [0.0, 0.0, 1.0])
    flat = np.linalg.norm(across, axis=1, keepdims=True) < 1e-3  # straight up or down: across is x
    across = np.where(flat, [1.0, 0.0, 0.0], across) / np.maximum(np.linalg.norm(across, axis=1, keepdims=True), 1e-3)
    up = np.cross(across, d)
    r = FOCUS_SPREAD_M / 2
    return point + across * side * r + up * float(np.clip(dz, -1, 1)) * r / 2


WAVE_BEATS = 4.0  # a wave runs over the heads (of the rig or a group) within this many beats


TILT_WAVE_DEG = 30.0  # tilt wave: how far each head tilts up and down (a little less at the fast peak tempo)
TILT_WAVE_SPAN = 1.0  # …and how many waves the row shows at once (1: one full wave from end to end)


AIMS = {  # direction aims: centre azimuth/elevation and swing; point aims: (y centre, y half-range, z) of a surface
    "crowd": {"az": 0, "el": -32, "az_amp": 60, "el_amp": 15, "plane": (2.2, 1.5, 0.0)},
    "stage": {"az": 180, "el": -35, "az_amp": 60, "el_amp": 18, "plane": (-2.2, 1.0, 0.0)},
    "sky": {"az": 0, "el": 60, "az_amp": 50, "el_amp": 20, "plane": (1.0, 2.0, "ceiling")},
}


LOW_HEAD_M = 1.0  # heads below this (on the floor) aim up and over the crowd instead of down onto it


LOW_AIMS = {
    "crowd": {"el": 14, "el_amp": 15, "plane": (3.0, 1.5, 1.9)},  # focus points float above the crowd
    "stage": {"el": 30, "el_amp": 15, "plane": (-2.5, 1.0, 2.5)},  # up the back wall
}


DEFAULT_MOTION = {"pan_speed_dps": 180, "tilt_speed_dps": 150, "accel_dps2": 600}  # conservative if unknown


def _slew(target: np.ndarray, vmax: float, amax: float, dt: float) -> np.ndarray:
    """Follow `target` like a motor: |velocity| <= vmax, |acceleration| <= amax, braking in time."""
    out = np.empty_like(target)
    pos, vel = float(target[0]), 0.0
    for i, goal in enumerate(target):
        err = goal - pos
        v_want = math.copysign(min(vmax, math.sqrt(2 * amax * abs(err))), err)  # slow down before arriving
        vel += max(-amax * dt, min(amax * dt, v_want - vel))
        pos += vel * dt
        out[i] = pos
    return out


class MotionMixin:
    """Head targets per phrase and the motor simulation behind them (cached on disk)."""

    def _reach(self, j: int) -> dict[str, tuple[float, float]]:
        """How big a beat-locked swing head j can land at this song's tempo, per aim, as (u, v) multipliers.

        A move gets one beat if the head can make a clear swing (>= MIN_BEAT_SWING_DEG) in that time,
        otherwise two beats: twice the time is four times the distance for a motor that accelerates.
        Distance with a triangular speed profile: accel * t^2 / 4, capped by top speed and 90°.
        """
        fx, defn = self.head_fx[j]
        motion = defn.get("motion", DEFAULT_MOTION)
        period = float(np.median(np.diff(self.beats))) if len(self.beats) > 2 else 0.45

        def travel(dist, vmax, acc):  # time for a rest-to-rest move (accelerate, cruise, brake)
            if dist <= vmax * vmax / acc:
                return 2 * math.sqrt(dist / acc)
            return dist / vmax + vmax / acc

        def reach(vmax, acc, beats):
            t = 0.9 * period * beats  # leave a little rest at each landing
            return min(acc * t * t / 4, vmax * t * 0.75, 90.0)

        axes, frac = {}, {}
        for axis in ("pan", "tilt"):
            vmax = motion[f"{axis}_speed_dps"]
            acc = motion.get(f"{axis}_accel_dps2", motion["accel_dps2"])
            beats = 1 if reach(vmax, acc, 1) >= MIN_BEAT_SWING_DEG else 2
            dist = reach(vmax, acc, beats)
            axes[axis] = (dist, beats)
            frac[axis] = min(0.98, travel(dist, vmax, acc) / (beats * period))  # share of the move spent travelling
        self.move_beats[j] = (axes["pan"][1], axes["tilt"][1])
        self.move_travel[j] = (frac["pan"], frac["tilt"])
        out = {}
        for name, aim in AIMS.items():
            if self.head_pos[j][2] < LOW_HEAD_M:
                aim = {**aim, **LOW_AIMS.get(name, {})}
            out[name] = (axes["pan"][0] / aim["az_amp"], axes["tilt"][0] / aim["el_amp"])
        return out

    def _follow_lead(self, t: float, j: int) -> tuple[float, float]:
        """Up/down with the melody's pitch; a sideways step with each new note (eased, motor-friendly)."""
        v = float(self.lead_pitch[self._frame(t)]) * 2 - 1
        i = bisect.bisect_right(self.lead_t, t)

        def spot(k):  # a well-spread sideways position per note (golden ratio), different per head
            return ((k * 0.618 + j * 0.37) % 1.0) * 2 - 1

        if i == 0:
            return 0.0, v
        a = _ease(min((t - self.lead_t[i - 1]) / 0.35, 1.0))
        return 0.7 * (spot(i - 1) + (spot(i) - spot(i - 1)) * a), v

    def _shape(self, m: str, pos: float, seed: int, tempo: float = 1.0) -> tuple[float, float]:
        """Path in a unit square (u = sideways, v = up/down or near/far), as a function of beats.

        Positions depend on the musical position (beat number + fraction), never on
        t / beat-length: the beat length wobbles, and dividing time by it makes patterns jump.
        """
        if m == "sweep":
            return math.sin(2 * math.pi * pos * tempo / 16), 0.0
        if m == "nod":
            return 0.0, math.sin(2 * math.pi * pos * tempo / 8)
        if m == "circle":
            w = 2 * math.pi * pos * tempo / 8
            return math.sin(w), math.cos(w)
        if m == "figure8":
            w = 2 * math.pi * pos * tempo / 8
            return math.sin(w), math.sin(2 * w)
        # per-beat moves: amplitudes in units of the aim's swing (u: az_amp, v: el_amp), set by _reach
        ru, rv = self._reach_uv
        nb_pan, nb_tilt = self._move_beats
        tr_pan, tr_tilt = self._move_travel

        def step(n, travel):  # hold at the landing, then jump the target so the head arrives on the next landing
            q = pos / n
            return int(q // 1), 1.0 if (q % 1) >= 1.0 - travel else 0.0

        if m == "step_on_beat":  # four spots, one per move (diagonal steps: split the reach)
            k, ld = step(max(nb_pan, nb_tilt), max(tr_pan, tr_tilt) * 0.6)  # diagonal steps are shorter
            spots = [(-1, -0.6), (1, 0.4), (-0.4, 1), (0.6, -0.8)]
            (u0, v0), (u1, v1) = spots[k % 4], spots[(k + 1) % 4]
            return 0.35 * ru * (u0 + (u1 - u0) * ld), 0.35 * rv * (v0 + (v1 - v0) * ld)
        if m == "bounce":  # up and down, landing on the beat
            k, ld = step(nb_tilt, tr_tilt)
            v0, v1 = (1, -1) if k % 2 == 0 else (-1, 1)
            return 0.0, 0.5 * rv * (v0 + (v1 - v0) * ld)  # up at even landings, down at odd ones
        if m == "swing":  # left and right, landing on the beat
            k, ld = step(nb_pan, tr_pan)
            u0, u1 = (1, -1) if k % 2 == 0 else (-1, 1)
            return 0.5 * ru * (u0 + (u1 - u0) * ld), 0.0
        if m == "ballyhoo":  # new pseudo-random spot every two beats

            def rnd(k):
                return (math.sin(k * 12.9898 + seed * 78.233) * 43758.5453) % 1.0 * 2 - 1

            seg, a = int(pos // 2), _ease((pos % 2) / 2)
            amp = 0.6  # jumps a real motor can make within two beats
            return (
                amp * (rnd(seg) + (rnd(seg + 1) - rnd(seg)) * a),
                amp * (rnd(seg + 1000) + (rnd(seg + 1001) - rnd(seg + 1000)) * a),
            )
        return 0.0, 0.0  # still

    def _head_dir(self, d: Decision, t: float, j: int) -> np.ndarray:
        """World direction head j should point in: shape × formation × aim."""
        beat, phase, _ = self.beat_info(t)
        pos = beat + phase
        n = len(self.heads)
        side = (j / max(n - 1, 1)) * 2 - 1 if n > 1 else 0.0  # -1 left .. +1 right
        f = d.formation
        if f == "wave":
            pos -= j  # one beat later per head
        seed = j if f in ("wave",) else 0  # ballyhoo: same random path unless the heads are offset anyway
        tempo = TEMPO[max(0, min(3, d.intensity))]
        self._reach_uv = self.reach_uv[j].get(d.aim, (1.0, 1.0))
        self._move_beats = self.move_beats.get(j, (1, 1))
        self._move_travel = self.move_travel.get(j, (0.9, 0.9))
        if d.movement == "follow_lead":
            u, v = self._follow_lead(t, j)
        else:
            u, v = self._shape(d.movement, pos, seed, tempo)
        if d.movement in ("sweep", "nod", "circle", "figure8") and tempo > 1:
            u, v = u / math.sqrt(tempo), v / math.sqrt(tempo)  # faster loops, a bit smaller: speed stays reachable
        if d.movement not in ("bounce", "swing", "step_on_beat", "follow_lead"):  # these keep their full size
            scale = MOVE_SCALE[max(0, min(3, d.intensity))]
            u, v = u * scale, v * scale
        head_pos = self.head_pos[j]
        aim = AIMS.get(d.aim, AIMS["crowd"])
        if head_pos[2] < LOW_HEAD_M:
            aim = {**aim, **LOW_AIMS.get(d.aim, {})}
        W = self.stage["width_m"]

        az = aim["az"] + u * aim["az_amp"]
        el = aim["el"] + v * aim["el_amp"]
        if f in ("focus", "cross"):
            # A shared point that moves with the same angles as the other formations, at a fixed distance in
            # front of the middle of the rig; every head aims at it (cross: at a point shifted to the other side).
            centre = np.mean(self.head_pos, axis=0)
            aim_d = geometry.direction(az, el)
            point = focus_spread(centre + aim_d * POINT_DISTANCE_M, aim_d, side, head_pos[2] - centre[2])[0]
            if f == "cross":
                point = point + np.array([-side * max(0.2 * W, 0.8), 0.0, 0.0])
            vec = point - head_pos
            out = vec / (np.linalg.norm(vec) + 1e-9)
        else:
            if f == "mirror" and side > 0:
                az = 2 * aim["az"] - az
            elif f == "fan":
                az += side * 30
            out = geometry.direction(az, el)

        if d.dynamics == "rise":  # swing up towards the drop
            progress = min(max((t - d.start) / max(d.end - d.start, 1e-6), 0), 1)
            up = geometry.direction(0, 75)
            out = out * (1 - 0.8 * progress) + up * 0.8 * progress
            out /= np.linalg.norm(out) + 1e-9
        if self.zones.heads:  # artistic zones: off the walls/set, inside the keep-in area
            out = self.zones.filter(head_pos, out[None])[0]
        out = geometry.room_safe_v(out[None], head_pos, self.stage)[0]
        return geometry.eye_safe(out, head_pos[2], self.stage)

    def _drop_ahead(self, i: int, t: float) -> int | None:
        """Index of the drop phrase if one starts within the next beat (for moving in black)."""
        if i + 1 in self.drop_idx:
            _, _, period = self.beat_info(t)
            if 0 < self.plan[i + 1].start - t <= period * PREDROP_BEATS:
                return i + 1
        return None

    def _share_motors(self):
        """The cells of a moving bar share its one tilt motor: they all follow the first cell."""
        by_fixture: dict[str, list[str]] = {}
        for e in self.heads:
            by_fixture.setdefault(e["fixture"], []).append(e["id"])
        for ids in by_fixture.values():
            for eid in ids[1:]:
                if ids[0] in self.traj:
                    self.traj[eid] = self.traj[ids[0]]
                    self.goals[eid] = self.goals[ids[0]]

    def _cached_trajectories(self) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        """Motor simulation, cached on disk: it takes seconds per head for a whole track (a 60-head rig:
        ~15 s). The key covers the track, the plan, the rig and this code, so a cache is never stale."""
        import hashlib

        if not self.heads:
            return {}
        h = hashlib.sha1()
        for src in sorted(Path(__file__).parent.glob("*.py")) + [Path(geometry.__file__)]:
            h.update(src.read_bytes())
        h.update(
            json.dumps(
                [
                    str(self.a.path),
                    round(float(self.a.duration), 3),
                    [d.__dict__ for d in self.plan],
                    self.rig["fixtures"],
                    self.stage,
                    self.rig.get("zones", []),
                    self.program,  # a program's head pictures depend on its hits
                    [len(self.cine_hits), float(self.cine_hits.t.sum()), self.CINE_VERSION] if self.program else None,
                    [(p.pickup_kind, round(p.pickup_start, 3)) for p in self.a.phrases if p.pickup_beats],
                ],
                sort_keys=True,
                default=str,
            ).encode()
        )
        for e in self.heads:  # the fixture definitions (motion, ranges) matter too
            fx = next(f for f in self.rig["fixtures"] if f["id"] == e["fixture"])
            h.update(json.dumps(fxlib.get(fx["fixture"]), sort_keys=True).encode())
        path = TRAJ_CACHE / f"{Path(str(self.a.path)).stem[:40]}.{h.hexdigest()[:16]}.traj.npz"
        if path.exists():
            try:
                z = np.load(path)
                ids = [e["id"] for e in self.heads]
                self.goals = {eid: (z[f"gp:{eid}"], z[f"gt:{eid}"]) for eid in ids}
                return {eid: (z[f"p:{eid}"], z[f"t:{eid}"]) for eid in ids}
            except (OSError, KeyError, ValueError):
                pass
        traj = self._trajectories_fast()
        try:
            TRAJ_CACHE.mkdir(parents=True, exist_ok=True)
            arrays = {}
            for eid, (p, t) in traj.items():
                arrays[f"p:{eid}"], arrays[f"t:{eid}"] = p.astype(np.float32), t.astype(np.float32)
                arrays[f"gp:{eid}"], arrays[f"gt:{eid}"] = (g.astype(np.float32) for g in self.goals[eid])
            np.savez_compressed(path, **arrays)
            for old in sorted(TRAJ_CACHE.glob("*.traj.npz"), key=lambda p: p.stat().st_mtime)[:-40]:
                old.unlink()  # keep the 40 most recent
        except OSError:
            pass
        return traj

    def _shape_v(self, m: str, pos: np.ndarray, seed: int, tempo: float, j: int):
        z = np.zeros_like(pos)
        if m == "sweep":
            return np.sin(2 * math.pi * pos * tempo / 16), z
        if m == "nod":
            return z, np.sin(2 * math.pi * pos * tempo / 8)
        if m == "circle":
            w = 2 * math.pi * pos * tempo / 8
            return np.sin(w), np.cos(w)
        if m == "figure8":
            w = 2 * math.pi * pos * tempo / 8
            return np.sin(w), np.sin(2 * w)
        ru, rv = self._reach_uv
        nb_pan, nb_tilt = self.move_beats.get(j, (1, 1))
        tr_pan, tr_tilt = self.move_travel.get(j, (0.9, 0.9))

        def step(n, travel):
            q = pos / n
            return np.floor(q).astype(np.int64), np.where(np.mod(q, 1.0) >= 1.0 - travel, 1.0, 0.0)

        if m == "step_on_beat":
            k, ld = step(max(nb_pan, nb_tilt), max(tr_pan, tr_tilt) * 0.6)
            spots = np.array([(-1, -0.6), (1, 0.4), (-0.4, 1), (0.6, -0.8)])
            s0, s1 = spots[np.mod(k, 4)], spots[np.mod(k + 1, 4)]
            return (
                0.35 * ru * (s0[:, 0] + (s1[:, 0] - s0[:, 0]) * ld),
                0.35 * rv * (s0[:, 1] + (s1[:, 1] - s0[:, 1]) * ld),
            )
        if m == "bounce":
            k, ld = step(nb_tilt, tr_tilt)
            v0 = np.where(np.mod(k, 2) == 0, 1.0, -1.0)
            return z, 0.5 * rv * (v0 + (-v0 - v0) * ld)
        if m == "swing":
            k, ld = step(nb_pan, tr_pan)
            u0 = np.where(np.mod(k, 2) == 0, 1.0, -1.0)
            return 0.5 * ru * (u0 + (-u0 - u0) * ld), z
        if m == "ballyhoo":

            def rnd(k):
                return np.mod(np.sin(k * 12.9898 + seed * 78.233) * 43758.5453, 1.0) * 2 - 1

            seg = np.floor(pos / 2)
            x = np.clip(np.mod(pos, 2) / 2, 0.0, 1.0)
            a = 0.5 - 0.5 * np.cos(math.pi * x)
            amp = 0.6
            return (
                amp * (rnd(seg) + (rnd(seg + 1) - rnd(seg)) * a),
                amp * (rnd(seg + 1000) + (rnd(seg + 1001) - rnd(seg + 1000)) * a),
            )
        return z, z

    @staticmethod
    def _direction_v(az, el):
        a, e = np.radians(az), np.radians(el)
        return np.stack([np.cos(e) * np.sin(a), np.cos(e) * np.cos(a), np.sin(e)], axis=-1)

    def _eye_safe_v(self, out: np.ndarray, head_z: float) -> np.ndarray:
        st = self.stage
        if not st["eye_safety"]:
            return out
        elev = np.degrees(np.arcsin(np.clip(out[:, 2], -1, 1)))
        lo = -st["audience_min_down_deg"]
        hi = 10.0 if head_z >= 2.5 else st["audience_min_up_deg"]
        bad = (out[:, 1] > 0.15) & (elev > lo - 3) & (elev < hi + 3)
        if not bad.any():
            return out
        new_el = np.where(elev - lo < hi - elev, lo - 3, hi + 3)
        az = np.degrees(np.arctan2(out[:, 0], out[:, 1]))
        fixed = self._direction_v(az, new_el)
        return np.where(bad[:, None], fixed, out)

    def _head_dir_v(self, d: Decision, ts: np.ndarray, j: int) -> np.ndarray:
        """_head_dir for many times at once (one decision, one head)."""
        if d.movement == "follow_lead" and not self.multi:  # retired option: the scalar path
            return np.array([self._head_dir(d, float(t), j) for t in ts]).reshape(-1, 3)
        beat, phase, _ = self._beat_info_v(ts)
        pos = beat + phase
        role = self._role(d, j)
        side, idx, count = role["side"], role["idx"], role["count"]
        f, movement = role["formation"], role["movement"]
        beats = pos + role["phase"]  # (the tilt wave makes its own offsets: by place in the row)
        if f == "wave":  # one beat per head, but a wave spans at most WAVE_BEATS (60 heads: not 60 beats)
            pos = pos - idx * min(1.0, WAVE_BEATS / max(count - 1, 1))
        pos = pos + role["phase"]
        seed = role["seed"] if role["seed"] is not None else (idx if f in ("wave",) else 0)
        tempo = TEMPO[max(0, min(3, d.intensity))]
        self._reach_uv = self.reach_uv[j].get(d.aim, (1.0, 1.0))
        u, v = self._shape_v(movement, pos, seed, tempo, j)
        if movement in ("sweep", "nod", "circle", "figure8") and tempo > 1:
            u, v = u / math.sqrt(tempo), v / math.sqrt(tempo)
        if movement not in ("bounce", "swing", "step_on_beat", "follow_lead"):
            scale = MOVE_SCALE[max(0, min(3, d.intensity))]
            u, v = u * scale, v * scale
        head_pos = self.head_pos[j]
        aim = AIMS.get(d.aim, AIMS["crowd"])
        if head_pos[2] < LOW_HEAD_M:
            aim = {**aim, **LOW_AIMS.get(d.aim, {})}
        W = role["width"]
        az = aim["az"] + u * aim["az_amp"]
        el = aim["el"] + v * aim["el_amp"]
        if movement == "tilt_wave":
            # A row of heads tilting up and down in a wave that rolls over the row: each head a step behind its
            # neighbour by where it hangs (left to right; mirrored: from the centre out). One wave per bar, every
            # two beats at the peaks. The beams fan out a little so the row reads as a row.
            period = 2.0 if d.intensity >= 3 else 4.0
            amp = TILT_WAVE_DEG * (0.8 if period < 4 else 1.0)
            across = abs(side) if f == "mirror" else (side + 1) / 2
            wave = np.sin(2 * math.pi * (beats / period - across * TILT_WAVE_SPAN))
            centre = aim["el"] - 8 if aim["el"] < 0 else aim["el"]  # over the crowd: room for the top of the wave
            az = np.full_like(ts, aim["az"] + side * (30 if f == "fan" else 15), dtype=float)
            el = centre + amp * wave + role["vside"] * 6
            out = self._direction_v(az, el)
        elif f in ("focus", "cross"):  # a shared point: of the whole rig, or of this head's group
            centre = np.mean(self.head_pos, axis=0) if role["centre"] is None else role["centre"]
            aim_d = self._direction_v(az, el)
            point = focus_spread(centre + aim_d * POINT_DISTANCE_M, aim_d, side, head_pos[2] - centre[2])
            if f == "cross":
                point = point + np.array([-side * max(0.2 * W, 0.8), 0.0, 0.0])
            vec = point - head_pos
            out = vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-9)
        else:
            if f == "mirror" and side > 0:
                az = 2 * aim["az"] - az
            elif f == "fan":
                az = az + side * 30
                el = el + role["vside"] * 12  # a tower fans out in height
            elif f == "wave" and role["vside"]:
                el = el + role["vside"] * 6
            out = self._direction_v(az, el)
        if d.dynamics == "rise":
            progress = np.clip((ts - d.start) / max(d.end - d.start, 1e-6), 0, 1)[:, None]
            up = geometry.direction(0, 75)
            out = out * (1 - 0.8 * progress) + up * 0.8 * progress
            out = out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-9)
        if self.zones.heads:
            out = self.zones.filter(head_pos, out)
        out = geometry.room_safe_v(out, head_pos, self.stage)  # off the ceiling, not back at the DJ
        return self._eye_safe_v(out, head_pos[2])

    def _head_dirs_v(self, ts: np.ndarray, j: int) -> np.ndarray:
        """A head's target directions over time: per phrase, with the crossfade and the move-in-black before drops."""
        if self.program == "cinematic":
            return self._cinematic_head_dirs(ts, j)
        out = np.empty((len(ts), 3))
        idx = np.maximum(0, np.searchsorted(self.starts, ts, side="right") - 1)
        _, _, period = self._beat_info_v(ts)
        for i in np.unique(idx):
            sel = np.flatnonzero(idx == i)
            t_i = ts[sel]
            d = self.plan[i]
            res = self._head_dir_v(d, t_i, j)
            lead = self._pickup_of(i + 1)
            if lead is not None and lead.pickup_kind == "early":  # the next section leads in: move into it now
                into = t_i >= lead.pickup_start
                if into.any():
                    k = (t_i[into] - lead.pickup_start) / max(self.plan[i + 1].start - lead.pickup_start, 1e-6)
                    k = (0.5 - 0.5 * np.cos(math.pi * np.clip(k, 0.0, 1.0)))[:, None]
                    nxt = self._head_dir_v(self.plan[i + 1], t_i[into], j)
                    blend = res[into] * (1 - k) + nxt * k
                    res[into] = blend / (np.linalg.norm(blend, axis=1, keepdims=True) + 1e-9)
            if i > 0 and i not in self.drop_idx and not self._led_in(i):  # (led in: already there)
                xf = (t_i - d.start) < XFADE
                if xf.any():
                    k = np.clip((t_i[xf] - d.start) / XFADE, 0.0, 1.0)
                    k = (0.5 - 0.5 * np.cos(math.pi * k))[:, None]
                    prev = self._head_dir_v(self.plan[i - 1], t_i[xf], j)
                    blend = prev * (1 - k) + res[xf] * k
                    res[xf] = blend / (np.linalg.norm(blend, axis=1, keepdims=True) + 1e-9)
            if i + 1 in self.drop_idx:
                gap = self.plan[i + 1].start - t_i
                ahead = (gap > 0) & (gap <= period[sel] * PREDROP_BEATS)
                if ahead.any():
                    res[ahead] = self._head_dir_v(self.plan[i + 1], t_i[ahead], j)
            out[sel] = res
        return out

    def _trajectories_fast(self) -> dict[str, tuple[np.ndarray, np.ndarray]]:
        dt = 1 / MOTION_FPS
        ts = np.arange(0, self.a.duration + 1, dt)
        n = len(self.heads)
        if n == 0:
            return {}
        dirs = np.stack([self._head_dirs_v(ts, j) for j in range(n)], axis=1)  # (T, N, 3)
        for j, (fx, _) in enumerate(self.head_fx):  # side-mounted (rolled) fixtures: solve in their own frame
            R = geometry.mount_roll(fx)
            if R is not None:
                dirs[:, j, :] = dirs[:, j, :] @ R  # row vectors: d_local = Rᵀ d
        P, T_, PH, TH, UP, VP, VT, AP, AT, INVP, INVT, ROT = (np.empty(n) for _ in range(12))
        for j, (fx, defn) in enumerate(self.head_fx):
            P[j], T_[j], PH[j], TH[j] = geometry._ranges(fx, defn)
            UP[j] = geometry._up(fx)
            motion = defn.get("motion", DEFAULT_MOTION)
            VP[j], VT[j] = motion["pan_speed_dps"], motion["tilt_speed_dps"]
            AP[j] = motion.get("pan_accel_dps2", motion["accel_dps2"])
            AT[j] = motion.get("tilt_accel_dps2", motion["accel_dps2"])
            INVP[j], INVT[j] = bool(fx.get("pan_invert")), bool(fx.get("tilt_invert"))
            ROT[j] = fx.get("rot_deg", 0.0)
        lo_p = np.where(INVP > 0, -(P - PH), -PH)
        hi_p = np.where(INVP > 0, PH, P - PH)
        lo_t = np.where(INVT > 0, -(T_ - TH), -TH)
        hi_t = np.where(INVT > 0, TH, T_ - TH)
        ks = np.array([-2, -1, 0, 1, 2], float) * 360.0
        wp, wt = 1 / VP, 1 / VT
        # IK pieces that don't depend on the motor position, for all frames at once
        theta = np.degrees(np.arccos(np.clip(dirs[:, :, 2] * UP, -1.0, 1.0)))  # (T, N)
        flat = np.hypot(dirs[:, :, 0], dirs[:, :, 1]) < 1e-6
        phi_raw = np.degrees(np.arctan2(dirs[:, :, 0], dirs[:, :, 1])) + ROT[None, :]  # the fixture's own front
        # moving bars (no pan motor): tilt only, forwards or backwards in the plane of the bar's front
        bar = P == 0
        if bar.any():
            r = np.radians(ROT)
            front = dirs[:, :, 0] * np.sin(-r)[None, :] + dirs[:, :, 1] * np.cos(-r)[None, :]
            bar_theta = np.degrees(np.arctan2(front, dirs[:, :, 2] * UP[None, :]))
        pos = vel = None
        phi_out, theta_out = np.empty((len(ts), n)), np.empty((len(ts), n))
        # keep-out zones are a physical stop for the motors: a head never turns into one, it slides along it
        avoid = bool(self.zones.avoid)
        if avoid:
            HP = np.array(self.head_pos, dtype=float)
            ROLL = [geometry.mount_roll(fx) for fx, _ in self.head_fx]
            # a moving bar's cells share its motor: the first cell's move is checked for every cell of the bar
            cells: dict[str, list[int]] = {}
            for j, e in enumerate(self.heads):
                cells.setdefault(e["fixture"], []).append(j)
            ROWS = np.array(
                [
                    k
                    for j, e in enumerate(self.heads)
                    for k in (cells[e["fixture"]] if cells[e["fixture"]][0] == j else [j])
                ]
            )  # positions to test, per row
            OWNER = np.array(
                [
                    j
                    for j, e in enumerate(self.heads)
                    for _ in (cells[e["fixture"]] if cells[e["fixture"]][0] == j else [j])
                ]
            )  # whose motor each row is

            slot = np.full(n, -1)
            every = np.arange(n)

            def blocked(p, sel):
                """Would heads `sel` at motor positions p (rows match sel) point into a zone (any cell of a bar)?"""
                slot[:] = -1
                slot[sel] = np.arange(len(sel))
                k = slot[OWNER]
                mask = k >= 0
                own, kk = OWNER[mask], k[mask]
                hit = self.zones.blocked(HP[ROWS[mask]], pointing(p[kk], own))
                out = np.zeros(len(sel), dtype=bool)
                np.logical_or.at(out, kk, hit)
                return out

            RM = np.stack([R if R is not None else np.eye(3) for R in ROLL])  # (n, 3, 3)
            ROLLED = np.array([R is not None for R in ROLL])

            def pointing(p, sel):
                """World beam directions for motor positions p (rows: phi, theta in degrees) of heads `sel`."""
                az = np.radians(p[:, 0] - ROT[sel])
                th = np.radians(p[:, 1])
                d = np.stack([np.sin(th) * np.sin(az), np.sin(th) * np.cos(az), UP[sel] * np.cos(th)], axis=1)
                r = ROLLED[sel]
                if r.any():
                    d[r] = np.einsum("nij,nj->ni", RM[sel][r], d[r])
                return d

        goal_phi, goal_theta = np.empty((len(ts), n)), np.empty((len(ts), n))
        for s_ in range(len(ts)):
            th = theta[s_]
            ph = np.where(flat[s_], pos[:, 0] if pos is not None else 0.0, phi_raw[s_])
            # candidates in the reference order: (phi, theta) then (phi + 180, -theta), each with k = -2..2
            cp = np.concatenate([ph[:, None] + ks, ph[:, None] + 180.0 + ks], axis=1)  # (N, 10)
            ct = np.concatenate([np.repeat(th[:, None], 5, 1), np.repeat(-th[:, None], 5, 1)], axis=1)
            ok = (
                (cp >= lo_p[:, None] - 1e-6)
                & (cp <= hi_p[:, None] + 1e-6)
                & (ct >= lo_t[:, None] - 1e-6)
                & (ct <= hi_t[:, None] + 1e-6)
            )
            if pos is None:
                cost = np.abs(cp) + np.abs(ct)
            else:
                cost = np.abs(cp - pos[:, 0:1]) * wp[:, None] + np.abs(ct - pos[:, 1:2]) * wt[:, None]
            cost = np.where(ok, cost, np.inf)
            best = np.argmin(cost, axis=1)
            rows = np.arange(n)
            gp, gt = cp[rows, best], ct[rows, best]
            none = ~ok.any(axis=1)
            if none.any():  # unreachable: clamp the plain solution into range
                gp = np.where(none, np.clip(ph, lo_p, hi_p), gp)
                gt = np.where(none, np.clip(th, lo_t, hi_t), gt)
            if bar.any():
                gp = np.where(bar, 0.0, gp)
                gt = np.where(bar, np.clip(bar_theta[s_], lo_t, hi_t), gt)
            goal = np.stack([gp, gt], axis=1)
            goal_phi[s_], goal_theta[s_] = gp, gt
            if pos is None:
                pos, vel = goal.copy(), np.zeros((n, 2))
            vmax = np.stack([VP, VT], axis=1)
            acc = np.stack([AP, AT], axis=1)
            err = goal - pos
            v_want = np.copysign(np.minimum(vmax, np.sqrt(2 * acc * np.abs(err))), err)
            vel = vel + np.clip(v_want - vel, -acc * dt, acc * dt)
            step = vel * dt
            new = pos + step
            if avoid:
                # only moves INTO a zone are stopped: a head that is in one (a moving bar's target can't always
                # dodge, it only tilts) may always move, so it gets out instead of getting stuck
                stuck = np.flatnonzero(blocked(new, every))
                if len(stuck):  # (already inside, only for the few that would be stopped)
                    stuck = stuck[~blocked(pos[stuck], stuck)]
                for axis in (0, 1):  # slide: keep only the pan move, or only the tilt move
                    if not len(stuck):
                        break
                    only = pos[stuck].copy()
                    only[:, axis] += step[stuck, axis]
                    ok = ~blocked(only, stuck)
                    new[stuck[ok]] = only[ok]
                    vel[stuck[ok], 1 - axis] = 0.0
                    stuck = stuck[~ok]
                if len(stuck):  # neither: wait at the edge
                    new[stuck] = pos[stuck]
                    vel[stuck] = 0.0
            pos = new
            phi_out[s_], theta_out[s_] = pos[:, 0], pos[:, 1]
        out = {}
        for j, e in enumerate(self.heads):
            fx, defn = self.head_fx[j]
            pan, tilt = geometry.to_dmx(fx, defn, phi_out[:, j], theta_out[:, j])
            out[e["id"]] = (np.clip(pan, 0, 1), np.clip(tilt, 0, 1))
            if avoid:  # the real fixture is told the path that goes around the zones, not the raw targets
                gpan, gtilt = geometry.to_dmx(fx, defn, phi_out[:, j], theta_out[:, j])
            else:
                gpan, gtilt = geometry.to_dmx(fx, defn, goal_phi[:, j], goal_theta[:, j])
            self.goals[e["id"]] = (np.clip(gpan, 0, 1), np.clip(gtilt, 0, 1))
        return out
