"""Round truss: the heads on a circle (or an arc) play it as a circle.

A row of heads reads left to right; heads round a circle read round it. On a ring the formations take the
circle's shape (any director's plan, nothing extra to choose):

- fan → a **crown**: every beam out of the circle, the way its head faces, the whole crown twisting one way and
  back with the movement (over the crowd: a chandelier of beams; up: a sunburst). The crown is squeezed into
  the front of the room so the back of the ring doesn't shine at the DJ (`back_guard`);
- focus → a **cone**: every beam towards one point on the ring's axis, moving with the movement (a tunnel of
  light, not one spot: the beams keep a small circle apart);
- cross → a **twister**: every beam across the circle to a point turned a little further round, so together
  they make a twisted hourglass, its waist twisting with the movement;
- wave → the movement **runs round the ring** (one lap in WAVE_BEATS, a full circle loops), in the crown;
- the tilt wave rolls round the ring too; sync and mirror stay as they are (a ring can do parallel beams).

Pars on a full ring chase round it (looks.py) instead of to and fro.
"""

from __future__ import annotations

import math

import numpy as np

from amadeus.rig import trusses as T

RING_FORMATIONS = ("fan", "focus", "cross", "wave")
CROWN_FRONT_DEG = 100.0  # the crown squeezed into the front of the room: azimuths within ±this (back_guard on)
CROWN_TWIST = 0.6  # how far the crown twists with the movement (share of the aim's swing)
CONE_SPREAD = 0.35  # the cone's beams keep this share of the ring's radius apart at its point
TWIST_DEG, TWIST_SWING_DEG = 45.0, 30.0  # the twister: how far round its beams reach past straight across, ± swing
RING_WAVE_BEATS = 4.0  # the wave runs once round the ring in this many beats


class RingsMixin:
    """Heads (and pars) on round trusses."""

    def _init_rings(self, rig: dict, fixtures: dict):
        """Per head: its ring, or None (`centre`, `radius`, `angle` (radians round the centre, from +x),
        `frac` (0..1 round the ring from the front middle), `full`)."""
        rings = {t["id"]: T.normalise(dict(t)) for t in rig.get("trusses", []) if T.is_ring(t)}
        self.rings: list[dict | None] = []
        for j, e in enumerate(self.heads):
            t = rings.get(fixtures[e["fixture"]].get("truss"))
            if t is None:
                self.rings.append(None)
                continue
            p = self.head_pos[j]
            a = math.atan2(p[1] - t["y_m"], p[0] - t["x_m"])
            if T.is_full_ring(t):  # round from the front middle, to the right seen from the audience
                frac = ((math.radians(t.get("rot_deg", 0.0) + 90.0) - a) / (2 * math.pi)) % 1.0
            else:  # along the arc, end to end
                u = float(fixtures[e["fixture"]].get("truss_pos_m", 0.0))
                frac = min(max(u / max(t["length_m"], 1e-6) + 0.5, 0.0), 1.0)
            self.rings.append(
                {
                    "truss": t["id"],
                    "centre": np.array([t["x_m"], t["y_m"], p[2]]),
                    "radius": T.ring_radius(t),
                    "angle": a,
                    "frac": frac,
                    "full": T.is_full_ring(t),
                }
            )
        self._order_pars_on_rings(rings, fixtures)

    def _order_pars_on_rings(self, rings: dict, fixtures: dict):
        """Pars on a ring take their order round it (chases run round the circle); `par_loop`: every par is on one
        full ring, so a chase loops round instead of going to and fro."""
        on = {e["id"]: rings.get(fixtures[e["fixture"]].get("truss")) for e in self.pars}
        if not any(on.values()):
            self.par_loop = False
            return
        W = float(self.stage["width_m"])

        def key(e):
            t = on[e["id"]]
            if t is None:
                return (e["x"], 0.0)
            return (t["x_m"] / W, float(fixtures[e["fixture"]].get("truss_pos_m", 0.0)))

        self.pars = sorted(self.pars, key=key)
        self.order = {f["id"]: i for i, f in enumerate(self.pars)}
        ids = {t["id"] if t else None for t in on.values()}
        self.par_loop = len(ids) == 1 and None not in ids and T.is_full_ring(next(iter(on.values())))

    def _ring_wave_pos(self, ring: dict, pos: np.ndarray) -> np.ndarray:
        return pos - ring["frac"] * RING_WAVE_BEATS

    def _crown_az(self, ring: dict) -> float:
        """The azimuth (0° = towards the audience, +90° = +x) a head on the ring faces out of it, squeezed into the
        front of the room unless beams may point back."""
        az = 90.0 - math.degrees(ring["angle"])
        az = (az + 180.0) % 360.0 - 180.0
        if self.stage.get("back_guard", True):
            az *= CROWN_FRONT_DEG / 180.0
        return az

    def _ring_dir_v(self, f: str, ring: dict, aim: dict, u: np.ndarray, v: np.ndarray, head_pos) -> np.ndarray:
        """World directions for a head on a ring in formation `f` (u, v: the movement, in units of the aim's
        swing)."""
        if f in ("fan", "wave"):  # the crown
            az = self._crown_az(ring) + u * aim["az_amp"] * CROWN_TWIST
            el = aim["el"] + v * aim["el_amp"]
            return self._direction_v(az, el)
        R = ring["radius"]
        reach = max(3.0, 2.0 * R)  # far enough that the shape reads (and the beams point forwards, not back)
        aim_d = self._direction_v(aim["az"] + u * aim["az_amp"], aim["el"] + v * aim["el_amp"])  # (T, 3)
        point = ring["centre"] + aim_d * reach
        a = ring["angle"]
        if f == "focus":  # the cone: a small circle round the point, each beam at its own place on it
            r, turn = R * CONE_SPREAD, np.full(len(u), a)
        else:  # the twister: across the circle and a little further round, the waist twisting with the movement
            r = R
            turn = a + math.pi + np.radians(TWIST_DEG + TWIST_SWING_DEG * np.clip(u, -1, 1))
        # a level circle round the point: each beam to its own place on it, in the order of the heads round the ring
        point = point + r * np.stack([np.cos(turn), np.sin(turn), np.zeros(len(u))], axis=1)
        vec = point - head_pos
        return vec / (np.linalg.norm(vec, axis=1, keepdims=True) + 1e-9)
