"""Fixtures on trusses: where a fixture clamped to a truss ends up.

The same rules as the Mac app's rig editor (RigEditorModel.place), so a fixture placed by either lands in the
same spot. A box truss has four sides a fixture can be clamped to: under it (hanging), on top, on the front
face (towards the audience) or on the back face. A tower (a vertical truss) has four faces (front, back, left,
right): a fixture there hangs off the face like on a box truss's side, its base against the truss and its head
out of that face. Only on top of a tower does a fixture stand.

A round truss (`"shape": "circle"`) hangs flat: a full circle, or an arc of `arc_deg` (180: a half circle) of
`diameter_m`. Its `x_m`/`y_m` are the circle's centre, and the middle of an arc faces the audience (turned by
`rot_deg`). Along it is measured round the arc like along a straight truss (`length_m` is the arc's length,
`u` from the arc's middle, to the right seen from the audience); a fixture on it is turned with the arc, so
its front (and the truss's "front" face) faces out of the circle and the "back" face into it.

Truss coordinates are metres: `x_m` across the stage, `y_m` towards the audience (0 = the stage's front
edge), `z_m` the height of its centre; `rot_deg` turns it counter-clockwise seen from above.
"""

from __future__ import annotations

import math

HANG_DROP = 0.42  # a fixture under (or on top of) a truss: its centre this far below (above) the truss centre
SIDE_OUT = 0.4  # a fixture on the front/back face: its centre this far out from the truss centre
TOWER_OUT = 0.32  # a fixture on a tower's face: its centre this far out from the tower's centre
TOWER_TOP = 0.3  # a fixture on top of a tower: its centre this far above the top
SIDES = ("under", "top", "front", "back")
TOWER_SIDES = ("front", "back", "left", "right", "top")
DIAMETERS_M = (2.0, 3.0, 4.0, 5.0, 6.0, 8.0)  # round truss as it is sold (the usual sizes; any other works too)
DEFAULT_DIAMETER_M = 4.0
ARCS_DEG = (360.0, 180.0)  # a full circle or a half circle (any arc works)


def is_ring(t: dict) -> bool:
    """A round truss (a circle or an arc)."""
    return t.get("shape") == "circle" and not t.get("vertical")


def is_full_ring(t: dict) -> bool:
    return is_ring(t) and ring_arc(t) >= 359.5


def ring_arc(t: dict) -> float:
    return float(min(360.0, max(10.0, t.get("arc_deg", 360.0))))


def ring_radius(t: dict) -> float:
    return float(t.get("diameter_m", DEFAULT_DIAMETER_M)) / 2


def ring(tid: str, diameter: float, x: float, y: float, z: float, arc: float = 360.0, rot: float = 0.0) -> dict:
    """A round truss: its `length_m` is the length round the arc (what fixtures are spread over)."""
    t = {"id": tid, "type": "quatro", "shape": "circle", "diameter_m": round(diameter, 2),
         "arc_deg": round(arc, 1), "x_m": round(x, 2), "y_m": round(y, 2), "z_m": round(z, 2)}  # fmt: skip
    if rot:
        t["rot_deg"] = round(rot, 1)
    return normalise(t)


def normalise(t: dict) -> dict:
    """A round truss's `length_m` follows its diameter and arc (they are what is edited)."""
    if is_ring(t):
        t["length_m"] = round(math.radians(ring_arc(t)) * ring_radius(t), 3)
    return t


def ring_angle(t: dict, u: float) -> float:
    """The angle (radians, counter-clockwise from +x seen from above) of the point `u` metres along a round truss
    from the middle of its arc; the middle faces the audience (+y) when it isn't turned."""
    return math.radians(t.get("rot_deg", 0.0) + 90.0) - u / ring_radius(t)


def tower_normal(t: dict, side: str) -> tuple[float, float]:
    """The outward direction of a tower's face (front: towards the audience; left/right: across the stage)."""
    r = math.radians(t.get("rot_deg", 0.0))
    front = (-math.sin(r), math.cos(r))
    return {
        "front": front,
        "back": (-front[0], -front[1]),
        "right": (front[1], -front[0]),  # +x for an unturned tower
        "left": (-front[1], front[0]),
    }[side]


def point(t: dict, u: float) -> tuple[float, float, float]:
    """The point `u` metres from a truss's centre along it (above its base, for a tower)."""
    if t.get("vertical"):
        return t["x_m"], t["y_m"], t["z_m"] - t["length_m"] / 2 + u
    if is_ring(t):
        a, R = ring_angle(t, u), ring_radius(t)
        return t["x_m"] + R * math.cos(a), t["y_m"] + R * math.sin(a), t["z_m"]
    r = math.radians(t.get("rot_deg", 0.0))
    return t["x_m"] + math.cos(r) * u, t["y_m"] + math.sin(r) * u, t["z_m"]


def place(f: dict, t: dict, u: float, width: float, side: str | None = None) -> dict:
    """Clamp fixture `f` to truss `t` at `u` (on `side` for a box truss) and set its position fields."""
    L = t["length_m"]
    f["truss"] = t["id"]
    if t.get("vertical"):
        side = side if side in TOWER_SIDES else (f.get("truss_side") if f.get("truss_side") in TOWER_SIDES else "front")
        base = t["z_m"] - L / 2
        if side == "top":  # standing on top
            f.update(truss_pos_m=round(L, 3), truss_side="top", x=round(t["x_m"] / width, 4), y_m=round(t["y_m"], 3),
                     z_m=round(base + L + TOWER_TOP, 3), mount="stand")  # fmt: skip
            f.pop("mount_roll_deg", None)
            if not f.get("rot_deg"):
                f.pop("rot_deg", None)
            return f
        u = max(0.2, min(L - 0.2, u))
        nx, ny = tower_normal(t, side)
        # hanging off the face: the hanging fixture rolled 90° about the face's horizontal axis, so its base is
        # against the truss and its head points out (the same roll as on a box truss's front face)
        f.update(
            truss_pos_m=round(u, 3),
            truss_side=side,
            x=round((t["x_m"] + nx * TOWER_OUT) / width, 4),
            y_m=round(t["y_m"] + ny * TOWER_OUT, 3),
            z_m=round(base + u, 3),
            mount="hang",
            mount_roll_deg=90,
            rot_deg=round(math.degrees(math.atan2(-nx, ny)), 1) % 360,
        )
        if not f["rot_deg"]:
            f.pop("rot_deg")
        return f
    if is_ring(t):
        L = normalise(t)["length_m"]
        if is_full_ring(t):  # round the circle: past one end is the other
            u = (u + L / 2) % L - L / 2
    u = max(-L / 2, min(L / 2, u))
    side = side if side in SIDES else ("top" if f.get("mount") == "stand" else "under")
    x, y, z = point(t, u)
    # the truss's direction here (on a ring: the tangent, so "front" faces out of the circle)
    rot = math.degrees(ring_angle(t, u)) - 90.0 if is_ring(t) else t.get("rot_deg", 0.0)
    r = math.radians(rot)
    nx, ny = -math.sin(r), math.cos(r)  # the face towards the audience (on a ring: out of the circle)
    if side == "top":
        z += HANG_DROP
    elif side == "front":
        x, y = x + nx * SIDE_OUT, y + ny * SIDE_OUT
    elif side == "back":
        x, y = x - nx * SIDE_OUT, y - ny * SIDE_OUT
    else:
        z -= HANG_DROP
    f.update(
        truss_pos_m=round(u, 3),
        truss_side=side,
        mount="stand" if side == "top" else "hang",
        x=round(x / width, 4),
        y_m=round(y, 3),
        z_m=round(z, 3),
        rot_deg=round((rot + 180.0) % 360.0 - 180.0 if is_ring(t) else rot, 1),
    )
    roll = {"front": 90, "back": 270}.get(side)
    if roll:
        f["mount_roll_deg"] = roll
    else:
        f.pop("mount_roll_deg", None)
    if not f["rot_deg"]:
        f.pop("rot_deg")
    return f
