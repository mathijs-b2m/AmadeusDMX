"""Stage geometry: where fixtures are, and pan/tilt ⇄ beam direction.

World frame (metres): x across the stage from left to right as seen by the
audience, y towards the audience (y = 0 is the front edge of the stage),
z up (z = 0 is the floor).

Beam directions are described by azimuth (0° = towards the audience, +90° =
stage right/audience left... i.e. +x) and elevation (0° = horizontal, +90° = up).

Pan/tilt conventions per fixture (calibrate in the rig if your fixture differs):
- pan: DMX centre (`pan_home_deg`, default half the range) points at the audience.
- tilt: DMX centre (`tilt_home_deg`) points straight out of the base: up for a head
  standing on a stand or the floor, down for a head hanging from a truss.
- `pan_invert` / `tilt_invert` flip the direction of rotation.
"""

from __future__ import annotations

import math

import numpy as np

DEFAULT_STAGE = {
    "width_m": 6.0,  # distance between the outermost fixtures, roughly
    "ceiling_m": 4.5,
    "room_depth_m": 6.0,  # from the stage edge to the far wall (beams stop there in the visualiser)
    "eye_safety": False,  # on: keep beams out of the audience's eye height (lasers, very bright beams)
    "audience_min_down_deg": 20.0,  # beams towards the audience must point at least this far down …
    "audience_min_up_deg": 35.0,  # … or this far up (heads below 2.5 m); 10° for higher heads
    "ceiling_guard": True,  # moving-head beams stay off the ceiling (they reach it no nearer than CEILING_RUN_M)
    "back_guard": True,  # … and never swing back past the rig towards the stage and the DJ
}
CEILING_RUN_M = (4.0, 10.0)  # a beam going up reaches the ceiling at least the room's depth away (in this range)
CEILING_CLEAR_M = 0.3  # (measured from this far under the ceiling)
BACK_Y = 0.2  # a beam may point back at most this much (y of the unit direction; 0.2 ≈ 12° past straight down/up)
BACK_DOWN_DEG = -55.0  # … unless it points down steeper than this: onto the floor near the fixture
MOUNTS = {  # default position per mount type: (y, z) in metres
    "stand": (-0.6, 1.8),
    "hang": (-1.0, 3.0),
    "floor": (-0.4, 0.3),
}


def stage(rig: dict) -> dict:
    return {**DEFAULT_STAGE, **rig.get("stage", {})}


def position(rig: dict, element: dict, fx: dict) -> tuple[float, float, float]:
    """Where an element is. A bar's cells sit along the bar: `offset_m` from its centre, turned by the
    fixture's `rot_deg` (0: the bar runs across the stage)."""
    st = stage(rig)
    if element["kind"] == "head":
        y, z = MOUNTS[fx.get("mount", "stand")]
    else:
        y, z = -0.3, 0.4
    y, z = fx.get("y_m", y), fx.get("z_m", z)
    if "offset_m" in element:
        r = math.radians(fx.get("rot_deg", 0.0))
        x = fx["x"] * st["width_m"] + element["offset_m"] * math.cos(r)
        y += element["offset_m"] * math.sin(r)
    else:
        x = element["x"] * st["width_m"]
    return (x, y, z)


STATIC_AIM = {"par": (0.0, 80.0), "blinder": (0.0, 7.0), "strobe": (0.0, 8.0)}  # (azimuth, elevation) by default


def static_dir(fx: dict, kind: str) -> np.ndarray:
    """Where a fixture without motors shines: its `aim` [azimuth°, elevation°] (0° = towards the audience,
    elevation 90° = straight up), turned with the fixture (`rot_deg`)."""
    az, el = fx.get("aim") or STATIC_AIM.get(kind, (0.0, 80.0))
    return direction(az - fx.get("rot_deg", 0.0), el)


def direction(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    a, e = math.radians(azimuth_deg), math.radians(elevation_deg)
    return np.array([math.cos(e) * math.sin(a), math.cos(e) * math.cos(a), math.sin(e)])


def mount_roll(fx: dict) -> np.ndarray | None:
    """A fixture clamped on the side of a box truss: rolled about the truss axis (`mount_roll_deg`; 90 = on the
    front face, base against the truss and the head towards the audience; 270 = the back face). It is the
    hanging fixture (0°), turned: returns that rotation (local → world), or None."""
    roll = fx.get("mount_roll_deg", 0.0)
    if not roll or fx.get("mount", "stand") != "hang":
        return None
    t, r = math.radians(roll), math.radians(fx.get("rot_deg", 0.0))
    a = np.array([math.cos(r), math.sin(r), 0.0])  # the truss axis
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * K + (1 - math.cos(t)) * K @ K  # Rodrigues


def mount_up(fx: dict) -> np.ndarray:
    """Direction from the fixture's base to its head (for drawing): down when hanging, up on a stand,
    out of the truss face when rolled onto its side."""
    up = np.array([0.0, 0.0, _up(fx)])
    R = mount_roll(fx)
    return R @ up if R is not None else up


def _up(fx: dict) -> float:
    return -1.0 if fx.get("mount", "stand") == "hang" else 1.0


def _ranges(fx: dict, defn: dict):
    P, T = defn["physical"].get("pan_deg", 0) or 0, defn["physical"]["tilt_deg"]  # P = 0: no pan motor (moving bar)
    return P, T, fx.get("pan_home_deg", P / 2), fx.get("tilt_home_deg", T / 2)


def fk(fx: dict, defn: dict, pan_norm: float, tilt_norm: float) -> np.ndarray:
    """DMX pan/tilt (0..1) → unit beam direction in the world."""
    P, T, ph, th = _ranges(fx, defn)
    # rot_deg: the fixture turned on its truss (counter-clockwise seen from above); its "front" turns with it
    phi = math.radians((pan_norm * P - ph) * (-1 if fx.get("pan_invert") else 1) - fx.get("rot_deg", 0.0))
    theta = math.radians((tilt_norm * T - th) * (-1 if fx.get("tilt_invert") else 1))
    s = math.sin(theta)
    d = np.array([s * math.sin(phi), s * math.cos(phi), _up(fx) * math.cos(theta)])
    R = mount_roll(fx)
    return R @ d if R is not None else d


def ik(
    fx: dict, defn: dict, d: np.ndarray, prev: tuple[float, float] | None, w_pan: float = 1.0, w_tilt: float = 1.0
) -> tuple[float, float]:
    """Unit direction → (phi, theta) in degrees relative to home, the solution closest to `prev`.

    Every direction has two pan/tilt solutions (pan + 180°, tilt mirrored) and, with
    more than 360° of pan, extra ±360° copies. Choosing the nearest one in *time*
    (weights = 1/speed) avoids pointless half-turns.
    """
    P, T, ph, th = _ranges(fx, defn)
    R = mount_roll(fx)
    if R is not None:  # solve in the fixture's own frame (as if it hung under the truss)
        d = R.T @ np.asarray(d, dtype=float)
    if not P:  # a moving bar: tilt only, forwards or backwards in the plane of its front
        lo_t, hi_t = (-(T - th), th) if fx.get("tilt_invert") else (-th, T - th)
        r = math.radians(fx.get("rot_deg", 0.0))
        front = float(d[0]) * math.sin(-r) + float(d[1]) * math.cos(-r)
        theta = math.degrees(math.atan2(front, float(d[2]) * _up(fx)))
        return 0.0, min(max(theta, lo_t), hi_t)
    c = max(-1.0, min(1.0, float(d[2]) * _up(fx)))
    theta = math.degrees(math.acos(c))
    if math.hypot(d[0], d[1]) < 1e-6:
        phi = prev[0] if prev else 0.0
    else:
        phi = math.degrees(math.atan2(d[0], d[1])) + fx.get("rot_deg", 0.0)
    # reachable phi/theta (relative to home, before inversion): DMX 0..range maps to these
    lo_p, hi_p = (-(P - ph), ph) if fx.get("pan_invert") else (-ph, P - ph)
    lo_t, hi_t = (-(T - th), th) if fx.get("tilt_invert") else (-th, T - th)
    cands = []
    for p0, t0 in ((phi, theta), (phi + 180.0, -theta)):
        for k in (-2, -1, 0, 1, 2):
            p = p0 + 360.0 * k
            if lo_p - 1e-6 <= p <= hi_p + 1e-6 and lo_t - 1e-6 <= t0 <= hi_t + 1e-6:
                cands.append((p, t0))
    if not cands:  # unreachable: clamp the plain solution into range
        cands = [(min(max(phi, lo_p), hi_p), min(max(theta, lo_t), hi_t))]
    if prev is None:
        return min(cands, key=lambda pt: abs(pt[0]) + abs(pt[1]))
    return min(cands, key=lambda pt: abs(pt[0] - prev[0]) * w_pan + abs(pt[1] - prev[1]) * w_tilt)


def to_dmx(fx: dict, defn: dict, phi: float, theta: float) -> tuple[float, float]:
    P, T, ph, th = _ranges(fx, defn)
    phi *= -1 if fx.get("pan_invert") else 1
    theta *= -1 if fx.get("tilt_invert") else 1
    return ((phi + ph) / P if P else phi * 0 + 0.5), (theta + th) / T


def in_eye_band(d: np.ndarray, head_z: float, st: dict) -> bool:
    """True if the beam travels towards the audience at roughly eye height (and eye safety is on)."""
    if not st["eye_safety"] or d[1] <= 0.15:
        return False
    elev = math.degrees(math.asin(max(-1.0, min(1.0, float(d[2])))))
    hi = 10.0 if head_z >= 2.5 else st["audience_min_up_deg"]
    return -st["audience_min_down_deg"] < elev < hi


def eye_safe(d: np.ndarray, head_z: float, st: dict) -> np.ndarray:
    """Keep beams that travel towards the audience out of the eye-height band (if eye safety is on)."""
    if not st["eye_safety"] or d[1] <= 0.15:  # off, or pointing sideways/back
        return d
    elev = math.degrees(math.asin(max(-1.0, min(1.0, float(d[2])))))
    lo = -st["audience_min_down_deg"]
    hi = 10.0 if head_z >= 2.5 else st["audience_min_up_deg"]
    if lo - 3 < elev < hi + 3:  # 3° margin: motors don't track perfectly
        elev = lo - 3 if elev - lo < hi - elev else hi + 3
        az = math.degrees(math.atan2(d[0], d[1]))
        return direction(az, elev)
    return d


def room_safe_v(d: np.ndarray, head_pos, st: dict) -> np.ndarray:
    """Default limits for moving-head beams (rows of unit directions), for every rig unless switched off:
    off the ceiling (`ceiling_guard`: up only so far that the beam reaches the ceiling at least the room's depth
    away) and not backwards (`back_guard`: never back past the rig towards the stage and the DJ, unless steeply
    down onto the floor near the fixture)."""
    d = np.asarray(d, dtype=float)
    el = np.degrees(np.arcsin(np.clip(d[:, 2], -1, 1)))
    az = np.degrees(np.arctan2(d[:, 0], d[:, 1]))
    changed = np.zeros(len(d), dtype=bool)
    if st.get("ceiling_guard", True):
        lo, hi = CEILING_RUN_M
        run = min(hi, max(lo, float(st.get("room_depth_m", 6.0))))
        room = float(st.get("ceiling_m", 4.5)) - CEILING_CLEAR_M - float(head_pos[2])
        top = math.degrees(math.atan2(room, run)) if room > 0 else 0.0
        over = el > top
        el = np.where(over, top, el)
        changed |= over
    if st.get("back_guard", True):
        h = np.cos(np.radians(el))
        limit = np.degrees(np.arccos(np.clip(-BACK_Y / np.maximum(h, 1e-6), -1, 1)))  # the widest |azimuth| allowed
        back = (np.abs(az) > limit) & (el > BACK_DOWN_DEG)
        az = np.where(back, np.sign(az + 1e-9) * limit, az)
        changed |= back
    if not changed.any():
        return d
    a, e = np.radians(az), np.radians(el)
    fixed = np.stack([np.cos(e) * np.sin(a), np.cos(e) * np.cos(a), np.sin(e)], axis=-1)
    return np.where(changed[:, None], fixed, d)


def beam_end(pos, d, st: dict, max_len: float = 12.0):
    """Where the beam lands: floor, ceiling, or max_len away. Returns (point, length, surface)."""
    p = np.asarray(pos, dtype=float)
    if d[2] < -1e-3:
        t, surf = -p[2] / d[2], "floor"
    elif d[2] > 1e-3:
        t, surf = (st["ceiling_m"] - p[2]) / d[2], "ceiling"
    else:
        t, surf = max_len, "air"
    if t > max_len:
        t, surf = max_len, "air"
    return p + d * t, t, surf
