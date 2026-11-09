"""Wall uplighters: a tilting bar (a moving bar: tilt only) standing on the floor next to a wall of the room.

Its job is depth: it shines straight up along the wall, onto the ceiling, and it moves only at the night's surprise
(engine/uplights.py). So it is no moving head to the show: it plays in no group of heads and no section, and the
heads' motion never drives it. A tilting bar anywhere else (on a truss, on the stage) is an ordinary head."""

from __future__ import annotations

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry

WALL_NEAR_M = 1.0  # a floor bar this close to a side wall, or to the far wall of the room, is a wall uplighter


def wall_distance(rig: dict, fx: dict) -> float:
    """How far a fixture stands from the nearest wall of the room: a side wall, or the far wall behind the
    audience (the stage's back is the stage, not a wall to light)."""
    st = geometry.stage(rig)
    w = float(st["width_m"])
    side = geometry.room_side(st)
    x = float(fx.get("x", 0.5)) * w
    y = float(fx.get("y_m", geometry.MOUNTS["floor"][0]))
    far = float(st.get("room_depth_m") or 6.0)
    return min(x + side, w + side - x, far - y)


def is_uplight(rig: dict, fx: dict) -> bool:
    """A tilting bar on the floor next to a wall."""
    if fx.get("mount") != "floor" or fxlib.get(fx["fixture"]).get("kind") != "moving_bar":
        return False
    return wall_distance(rig, fx) <= WALL_NEAR_M


def uplight_fixtures(rig: dict) -> set[str]:
    return {f["id"] for f in rig.get("fixtures", []) if is_uplight(rig, f)}
