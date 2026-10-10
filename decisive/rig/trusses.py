"""Fixtures on trusses: where a fixture clamped to a truss ends up.

The same rules as the Mac app's rig editor (RigEditorModel.place), so a fixture placed by either lands in the
same spot. A box truss has four sides a fixture can be clamped to: under it (hanging), on top, on the front
face (towards the audience) or on the back face. A tower (a vertical truss) takes fixtures on its front.

Truss coordinates are metres: `x_m` across the stage, `y_m` towards the audience (0 = the stage's front
edge), `z_m` the height of its centre; `rot_deg` turns it counter-clockwise seen from above.
"""

from __future__ import annotations

import math

HANG_DROP = 0.42  # a fixture under (or on top of) a truss: its centre this far below (above) the truss centre
SIDE_OUT = 0.4  # a fixture on the front/back face: its centre this far out from the truss centre
TOWER_FRONT = 0.32  # a fixture on a tower: this far in front of it
SIDES = ("under", "top", "front", "back")


def point(t: dict, u: float) -> tuple[float, float, float]:
    """The point `u` metres from a truss's centre along it (above its base, for a tower)."""
    if t.get("vertical"):
        return t["x_m"], t["y_m"], t["z_m"] - t["length_m"] / 2 + u
    r = math.radians(t.get("rot_deg", 0.0))
    return t["x_m"] + math.cos(r) * u, t["y_m"] + math.sin(r) * u, t["z_m"]


def place(f: dict, t: dict, u: float, width: float, side: str | None = None) -> dict:
    """Clamp fixture `f` to truss `t` at `u` (on `side` for a box truss) and set its position fields."""
    L = t["length_m"]
    f["truss"] = t["id"]
    if t.get("vertical"):
        u = max(0.2, min(L, u))
        f.update(
            truss_pos_m=round(u, 3),
            x=round(t["x_m"] / width, 4),
            y_m=round(t["y_m"] + TOWER_FRONT, 3),
            z_m=round(t["z_m"] - L / 2 + u, 3),
            mount="stand",
        )
        for k in ("truss_side", "mount_roll_deg"):
            f.pop(k, None)
        return f
    u = max(-L / 2, min(L / 2, u))
    side = side if side in SIDES else ("top" if f.get("mount") == "stand" else "under")
    x, y, z = point(t, u)
    r = math.radians(t.get("rot_deg", 0.0))
    nx, ny = -math.sin(r), math.cos(r)  # the face towards the audience
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
        rot_deg=round(t.get("rot_deg", 0.0), 1),
    )
    roll = {"front": 90, "back": 270}.get(side)
    if roll:
        f["mount_roll_deg"] = roll
    else:
        f.pop("mount_roll_deg", None)
    if not f["rot_deg"]:
        f.pop("rot_deg")
    return f
