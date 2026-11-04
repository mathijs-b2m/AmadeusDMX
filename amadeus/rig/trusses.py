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

A carré (`"shape": "carre"`) is a rectangle of box truss standing on its own four legs (a tower at each corner,
down to the floor), as at a trade-fair stand or round a DJ booth on the dance floor: `width_m` across (before
`rot_deg` turns it), `depth_m` up and down the stage, `x_m`/`y_m` its centre and `z_m` the frame's height. Like a
full round truss it is a closed loop: along it is measured round the frame from the middle of its front side
(towards +x first, `length_m` is the frame's perimeter), its "front" face faces out of the carré and "back" into
it, and its heads play crowns, cones and twisters (`is_loop`). Fixtures clamp to the frame, not to the legs.

A light stand (`"type": "bridge"` or `"tbar"`) is the cheaper kind: a ~40 mm tube instead of a 30 cm box truss,
standing on tripods. A light bridge has a stand under each end of its bar, a T-bar one under its middle; `z_m` is
the bar's height (the stands go down to the floor). Fixtures clamp to the tube like to a box truss's sides, only
closer. It may say what it takes (`max_kg`) and how high it goes (`min_height_m`, `max_height_m`), as the maker
gives them.

A scaffold (`"type": "scaffold"`) is the wall of tube a festival stage is built against: standards every `bay_m`,
ledgers every `lift_m`, braced, two frames `depth_m` apart, standing on the floor. It is a straight truss in every
way that moves it: `length_m` across, `x_m`/`y_m` its centre, `rot_deg`; `z_m` is its top. Fixtures clamp to the
ledgers of its front frame: `truss_pos_m` along it like on any truss, `truss_lift` which ledger (1 is the lowest, the
top one is `lifts`), `truss_side` as on a light stand's tube. Its heads play out to the audience (`light_aim`), and
an LED wall hangs on the front of the widest one that faces the audience (`screen_rect`).

A truss's `aim` says where the heads on it play: `"audience"` (out towards the crowd, never back at the stage), or
`"down"` (onto the crowd under it). Without one it is automatic: a truss hanging over the crowd (its centre at least
OVER_CROWD_M in front of the stage edge) plays down, any other plays wherever the director aims.

Truss coordinates are metres: `x_m` across the stage, `y_m` towards the audience (0 = the stage's front
edge), `z_m` the height of its centre; `rot_deg` turns it counter-clockwise seen from above.
"""

from __future__ import annotations

import math

HANG_DROP = 0.42  # a fixture under (or on top of) a truss: its centre this far below (above) the truss centre
SIDE_OUT = 0.4  # a fixture on the front/back face: its centre this far out from the truss centre
TUBE_DROP = 0.28  # the same on a light stand's tube (40 mm, not 30 cm)
TUBE_OUT = 0.27
TOWER_OUT = 0.32  # a fixture on a tower's face: its centre this far out from the tower's centre
TOWER_TOP = 0.3  # a fixture on top of a tower: its centre this far above the top
SIDES = ("under", "top", "front", "back")
TOWER_SIDES = ("front", "back", "left", "right", "top")
DIAMETERS_M = (2.0, 3.0, 4.0, 5.0, 6.0, 8.0)  # round truss as it is sold (the usual sizes; any other works too)
DEFAULT_DIAMETER_M = 4.0
ARCS_DEG = (360.0, 180.0)  # a full circle or a half circle (any arc works)
STANDS = ("bridge", "tbar")  # light stands: a bridge on two tripods, a T-bar on one
STAND_INSET_M = 0.05  # a light bridge's stands: this far in from the bar's ends
CARRE_SIZES_M = ((3.0, 3.0), (4.0, 3.0), (4.0, 4.0), (6.0, 4.0))  # carrés as they are hired (any size works)
DEFAULT_CARRE_M = (3.0, 3.0)
CARRE_HEIGHT_M = 3.0  # the usual leg: a 3 m tower
CORNER_CLEAR_M = 0.25  # a fixture on a carré stays this far from a corner (the corner block and the leg)
SCAFFOLD_SIZES_M = ((8.0, 5.0), (12.0, 7.0), (16.0, 9.0), (20.0, 11.0))  # width × height to start from (any works)
BAY_M = 2.5  # a scaffold's standards: about this far apart
LIFT_M = 1.0  # its ledgers: about this far above each other
SCAFFOLD_DEPTH_M = 1.0  # its two frames: this far apart
AIMS = ("audience", "down")  # where a truss's heads play (`aim`); none: automatic
OVER_CROWD_M = 1.0  # a truss this far in front of the stage edge hangs over the crowd: automatic is down


def is_ring(t: dict) -> bool:
    """A round truss (a circle or an arc)."""
    return t.get("shape") == "circle" and not t.get("vertical")


def is_full_ring(t: dict) -> bool:
    return is_ring(t) and ring_arc(t) >= 359.5


def is_carre(t: dict) -> bool:
    """A carré: a rectangle of truss on four legs."""
    return t.get("shape") == "carre" and not t.get("vertical")


def is_loop(t: dict) -> bool:
    """A truss whose heads play round it: a round truss (or an arc) or a carré."""
    return is_ring(t) or is_carre(t)


def is_closed(t: dict) -> bool:
    """A loop without ends: a full circle or a carré (round it, past one end is the other)."""
    return is_full_ring(t) or is_carre(t)


def carre_size(t: dict) -> tuple[float, float]:
    """A carré's width (across, before it is turned) and depth (m)."""
    return float(t.get("width_m", DEFAULT_CARRE_M[0])), float(t.get("depth_m", DEFAULT_CARRE_M[1]))


def loop_radius(t: dict) -> float:
    """How big a loop is, as a circle's radius (a carré: half its mean side)."""
    if is_carre(t):
        w, d = carre_size(t)
        return (w + d) / 4
    return ring_radius(t)


def carre_corners(t: dict) -> list[tuple[float, float]]:
    """A carré's corners (x, y), where its legs stand: front +x, back +x, back -x, front -x (round it, the way
    along it goes)."""
    w, d = carre_size(t)
    r = math.radians(t.get("rot_deg", 0.0))
    c, s = math.cos(r), math.sin(r)
    return [(t["x_m"] + c * lx - s * ly, t["y_m"] + s * lx + c * ly)
            for lx, ly in ((w / 2, d / 2), (w / 2, -d / 2), (-w / 2, -d / 2), (-w / 2, d / 2))]  # fmt: skip


def _carre_local(t: dict, u: float) -> tuple[float, float, float]:
    """(x, y, the frame's direction in degrees) `u` metres round an unturned carré from its front middle."""
    w, d = carre_size(t)
    s = (u + w / 2) % (2 * (w + d))  # from the front -x corner
    if s < w:
        return -w / 2 + s, d / 2, 0.0  # the front, towards +x
    if s < w + d:
        return w / 2, d / 2 - (s - w), -90.0  # the +x side, upstage
    if s < 2 * w + d:
        return w / 2 - (s - w - d), -d / 2, 180.0  # the back, towards -x
    return -w / 2, -d / 2 + (s - 2 * w - d), 90.0  # the -x side, downstage


def carre_clear(t: dict, u: float) -> float:
    """`u` moved off a carré's corner (CORNER_CLEAR_M), staying on the side it was on."""
    w, d = carre_size(t)
    L = 2 * (w + d)
    s = (u + w / 2) % L
    for c in (0.0, w, w + d, 2 * w + d, L):
        if abs(s - c) < CORNER_CLEAR_M:
            s = c + CORNER_CLEAR_M if s >= c else c - CORNER_CLEAR_M
            break
    return (s - w / 2 + L / 2) % L - L / 2


def carre_spread(t: dict, k: int) -> list[float]:
    """`k` places round a carré, mirrored: front and back alike, the two sides alike (shared by their lengths),
    each side's evenly along it; an odd one out goes to the front."""
    w, d = carre_size(t)
    pairs, odd = divmod(k, 2)
    fb = round(pairs * w / (w + d)) if pairs else 0
    counts = (fb + odd, pairs - fb, fb, pairs - fb)  # front, +x side, back, -x side
    out, start = [], -w / 2
    for n, side in zip(counts, (w, d, w, d)):
        out += [start + side * (i + 0.5) / n for i in range(n)]
        start += side
    L = 2 * (w + d)
    return [round((u + L / 2) % L - L / 2, 3) for u in out]


def carre(
    tid: str, width: float, depth: float, x: float, y: float, z: float = CARRE_HEIGHT_M, rot: float = 0.0
) -> dict:
    """A carré: a `width` × `depth` frame at `z` on four legs."""
    t = {"id": tid, "type": "quatro", "shape": "carre", "width_m": round(width, 2), "depth_m": round(depth, 2),
         "x_m": round(x, 2), "y_m": round(y, 2), "z_m": round(z, 2)}  # fmt: skip
    if rot:
        t["rot_deg"] = round(rot, 1)
    return normalise(t)


def is_stand(t: dict) -> bool:
    """A light stand: a bridge or a T-bar (a tube on tripods), not a box truss."""
    return t.get("type") in STANDS and not t.get("vertical") and not is_loop(t)


def stand_feet(t: dict) -> list[tuple[float, float]]:
    """Where a light stand's tripods stand (x, y): under both ends of a bridge, under the middle of a T-bar."""
    if not is_stand(t):
        return []
    if t["type"] == "tbar":
        return [(t["x_m"], t["y_m"])]
    u = max(0.0, t["length_m"] / 2 - STAND_INSET_M)
    return [point(t, -u)[:2], point(t, u)[:2]]


def stand(
    tid: str,
    kind: str,
    length: float,
    x: float,
    y: float,
    z: float,
    max_kg: float | None = None,
    max_height: float | None = None,
) -> dict:
    """A light stand: a bridge (`kind` "bridge") or a T-bar ("tbar"), its bar `length` long at `z` high."""
    t = {"id": tid, "type": kind, "length_m": round(length, 2), "x_m": round(x, 2), "y_m": round(y, 2),
         "z_m": round(min(z, max_height or z), 2)}  # fmt: skip
    if max_kg:
        t["max_kg"] = max_kg
    if max_height:
        t["max_height_m"] = max_height
    return t


def is_scaffold(t: dict) -> bool:
    """A scaffold wall: tube, bays across and lifts up, standing on the floor."""
    return t.get("type") == "scaffold" and not t.get("vertical") and not is_loop(t)


def is_tube(t: dict) -> bool:
    """A bar fixtures clamp close to: a light stand's tube, or a ledger of a scaffold."""
    return is_stand(t) or t.get("type") == "ledger"


def scaffold_depth(t: dict) -> float:
    return float(t.get("depth_m", SCAFFOLD_DEPTH_M))


def scaffold_bays(t: dict) -> int:
    """How many bays across (the standards share its length evenly)."""
    return max(1, round(t["length_m"] / float(t.get("bay_m", BAY_M))))


def scaffold_lifts(t: dict) -> int:
    """How many lifts up: its ledgers share its height evenly, the top one at `z_m`."""
    return max(1, round(t["z_m"] / float(t.get("lift_m", LIFT_M))))


def lift_height(t: dict, lift: int) -> float:
    return t["z_m"] * lift / scaffold_lifts(t)


def nearest_lift(t: dict, z: float) -> int:
    """The ledger nearest height `z`."""
    n = scaffold_lifts(t)
    return min(n, max(1, round(z / t["z_m"] * n)))


def ledger(t: dict, lift: int) -> dict:
    """Ledger `lift` of a scaffold's front frame, as a straight bar of its own (a fixture placed on it lands on the
    scaffold, at that lift)."""
    lift = min(scaffold_lifts(t), max(1, lift))
    r, out = math.radians(t.get("rot_deg", 0.0)), scaffold_depth(t) / 2
    return {"id": f"{t['id']}/{lift}", "type": "ledger", "scaffold": t["id"], "lift": lift, "length_m": t["length_m"],
            "x_m": t["x_m"] - math.sin(r) * out, "y_m": t["y_m"] + math.cos(r) * out,
            "z_m": round(lift_height(t, lift), 3), "rot_deg": t.get("rot_deg", 0.0)}  # fmt: skip


def scaffold(
    tid: str,
    width: float,
    height: float,
    x: float,
    y: float,
    depth: float = SCAFFOLD_DEPTH_M,
    bay: float = BAY_M,
    lift: float = LIFT_M,
    rot: float = 0.0,
) -> dict:
    """A scaffold wall `width` across and `height` high, its centre at `x`, `y`."""
    t = {"id": tid, "type": "scaffold", "length_m": round(width, 2), "x_m": round(x, 2), "y_m": round(y, 2),
         "z_m": round(height, 2), "depth_m": round(depth, 2), "bay_m": round(bay, 2), "lift_m": round(lift, 2)}  # fmt: skip
    if rot:
        t["rot_deg"] = round(rot, 1)
    return t


def screen_wall(trusses: list[dict]) -> dict | None:
    """The scaffold an LED wall hangs on: the widest one that faces the audience."""
    walls = [t for t in trusses if is_scaffold(t) and abs(t.get("rot_deg", 0.0)) < 1.0]
    return max(walls, key=lambda t: t["length_m"], default=None)


def screen_rect(rig: dict, big: bool = True) -> tuple[float, float, float] | None:
    """The LED wall on the rig's scaffold, as the apps draw it, centred on the stage: (half its width, its bottom,
    its top) in metres, or None when it has no scaffold to hang on. `big`: a big rig's wall (Scenery)."""
    if not rig.get("screen") or not screen_wall(rig.get("trusses", [])):
        return None
    st = rig.get("stage", {})
    sw = min(10.0, float(st.get("width_m", 6.0)) * 0.55) if big else 2.6
    bottom = (1.4 if big else 1.15) + float(st.get("deck_m", 0.0) or 0.0)
    return sw / 2, bottom, bottom + sw * 9 / 16


def ring_arc(t: dict) -> float:
    return float(min(360.0, max(10.0, t.get("arc_deg", 360.0))))


def ring_radius(t: dict) -> float:
    return float(t.get("diameter_m", DEFAULT_DIAMETER_M)) / 2


def light_aim(t: dict) -> str | None:
    """Where the heads on this truss play: "audience", "down", or None (the director's aim as it is)."""
    if t.get("aim") in AIMS:
        return t["aim"]
    if is_scaffold(t):  # a wall: nothing to play behind it
        return "audience"
    if not t.get("vertical") and float(t.get("y_m", 0.0)) >= OVER_CROWD_M:
        return "down"
    return None


def ring(tid: str, diameter: float, x: float, y: float, z: float, arc: float = 360.0, rot: float = 0.0) -> dict:
    """A round truss: its `length_m` is the length round the arc (what fixtures are spread over)."""
    t = {"id": tid, "type": "quatro", "shape": "circle", "diameter_m": round(diameter, 2),
         "arc_deg": round(arc, 1), "x_m": round(x, 2), "y_m": round(y, 2), "z_m": round(z, 2)}  # fmt: skip
    if rot:
        t["rot_deg"] = round(rot, 1)
    return normalise(t)


def normalise(t: dict) -> dict:
    """A round truss's `length_m` follows its diameter and arc, a carré's its sides (they are what is edited)."""
    if is_ring(t):
        t["length_m"] = round(math.radians(ring_arc(t)) * ring_radius(t), 3)
    if is_carre(t):
        t["length_m"] = round(2 * sum(carre_size(t)), 3)
    if is_stand(t):  # a stand goes as high (and as low) as it does
        z = max(t["z_m"], t.get("min_height_m") or 0.0)
        t["z_m"] = min(z, t.get("max_height_m") or z)
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
    if is_carre(t):
        lx, ly, _ = _carre_local(t, u)
        r = math.radians(t.get("rot_deg", 0.0))
        return t["x_m"] + math.cos(r) * lx - math.sin(r) * ly, t["y_m"] + math.sin(r) * lx + math.cos(r) * ly, t["z_m"]
    r = math.radians(t.get("rot_deg", 0.0))
    return t["x_m"] + math.cos(r) * u, t["y_m"] + math.sin(r) * u, t["z_m"]


def direction(t: dict, u: float) -> float:
    """The way a horizontal truss runs at `u` (degrees, counter-clockwise from +x seen from above): its face
    towards the audience (on a loop: out of it) is to the left of it."""
    if is_ring(t):
        return math.degrees(ring_angle(t, u)) - 90.0
    if is_carre(t):
        return t.get("rot_deg", 0.0) + _carre_local(t, u)[2]
    return t.get("rot_deg", 0.0)


def outline(t: dict) -> list[tuple[float, float]]:
    """A horizontal truss seen from above as a line (x, y): its ends, round an arc, or round a carré's corners."""
    L = normalise(t)["length_m"]
    if is_carre(t):
        c = carre_corners(t)
        return [point(t, 0.0)[:2], *c, point(t, 0.0)[:2]]
    n = 48 if is_ring(t) else 1
    return [point(t, -L / 2 + L * k / n)[:2] for k in range(n + 1)]


def place(f: dict, t: dict, u: float, width: float, side: str | None = None) -> dict:
    """Clamp fixture `f` to truss `t` at `u` (on `side` for a box truss) and set its position fields."""
    if is_scaffold(t):  # onto the ledger it is on (new here: the top one)
        return place(f, ledger(t, f.get("truss_lift") or scaffold_lifts(t)), u, width, side)
    L = t["length_m"]
    f["truss"] = t.get("scaffold", t["id"])
    f.pop("truss_lift", None)
    if t.get("scaffold"):
        f["truss_lift"] = t["lift"]
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
    if is_loop(t):
        L = normalise(t)["length_m"]
        if is_closed(t):  # round the loop: past one end is the other
            u = (u + L / 2) % L - L / 2
        if is_carre(t):
            u = carre_clear(t, u)
    u = max(-L / 2, min(L / 2, u))
    side = side if side in SIDES else ("top" if f.get("mount") == "stand" else "under")
    x, y, z = point(t, u)
    # the truss's direction here (on a loop: round it, so "front" faces out of it)
    rot = direction(t, u)
    r = math.radians(rot)
    nx, ny = -math.sin(r), math.cos(r)  # the face towards the audience (on a ring: out of the circle)
    drop, out = (TUBE_DROP, TUBE_OUT) if is_tube(t) else (HANG_DROP, SIDE_OUT)
    if side == "top":
        z += drop
    elif side == "front":
        x, y = x + nx * out, y + ny * out
    elif side == "back":
        x, y = x - nx * out, y - ny * out
    else:
        z -= drop
    f.update(
        truss_pos_m=round(u, 3),
        truss_side=side,
        mount="stand" if side == "top" else "hang",
        x=round(x / width, 4),
        y_m=round(y, 3),
        z_m=round(z, 3),
        rot_deg=round((rot + 180.0) % 360.0 - 180.0 if is_loop(t) else rot, 1),
    )
    roll = {"front": 90, "back": 270}.get(side)
    if roll:
        f["mount_roll_deg"] = roll
    else:
        f.pop("mount_roll_deg", None)
    if not f["rot_deg"]:
        f.pop("rot_deg")
    return f
