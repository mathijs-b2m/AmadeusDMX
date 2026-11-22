"""Groups of moving heads: which heads belong together, and where each head is inside its group.

A rig of 60 heads is not one line of 60: there is an overhead truss, a row at the back of the stage,
a row on the front edge, a tower left and right. The director decides how the groups relate (all as
one, each group its own formation, one group featured, ...); the engine uses each head's place in its
group for formations, waves, chases and focus points.

Groups come from the rig ("group" on a fixture), else from the trusses and positions:
- a ring: the heads on one round truss (or a carré), in order round it (`amadeus/engine/rings.py` plays them
  as a circle);
- a lift of a scaffold: 3+ heads on one ledger, left to right (fewer: the rules below, so heads stacked up the sides of
  a scaffold are its columns);
- a column: 3+ fixtures at the same spot across the stage, stacked in height (a truss tower), two of them at least up
  off the floor; a head hung on a lying truss is never part of one, however the floor heads under it stand, and a
  fixture's heads are never split up;
- a row: heads with the same mount at about the same depth and height, chained neighbour to neighbour, and the heads
  on one lying truss always together (two short trusses end to end at one height and depth are one row).
Each group gets a class the director talks about: overhead, ring, back, front, towers (or "all").
"""

from __future__ import annotations

import hashlib

import numpy as np

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry
from amadeus.rig import trusses as T
from amadeus.rig.uplights import is_uplight

CLASSES = {
    "overhead": "the heads hung overhead on the truss: they scan down onto the crowd",
    "ring": "the heads round a circle truss: crowns of beams, cones and twisting tunnels",
    "back": "the row on the stage floor at the back: beams shoot up over the DJ into the room",
    "front": "the low row on the front edge of the stage: beams fan up and over the first rows",
    "towers": "the vertical truss towers left and right: stacked heads, beams from the sides",
    "mid": "heads on stands at mid height",
}


def head_groups(rig: dict) -> list[dict]:
    """[{name, cls, kind ('row'|'column'|'ring'), ids (ordered: left→right, bottom→top, or round the ring from
    its front middle), centre (x, y, z)}]."""
    heads = []
    for f in rig["fixtures"]:
        if not fxlib.is_moving(fxlib.get(f["fixture"])) or is_uplight(rig, f):  # (wall uplighters: rig/uplights.py)
            continue
        for e in fxlib.expand(f, geometry.stage(rig)["width_m"]):
            if e["kind"] == "head":
                heads.append((e, np.array(geometry.position(rig, e, f)), f))
    if not heads:
        return []
    named: dict[str, list] = {}
    rest = []
    rings = {t["id"]: t for t in rig.get("trusses", []) if T.is_loop(t)}
    walls = {t["id"] for t in rig.get("trusses", []) if T.is_scaffold(t)}
    lifts: dict[tuple, int] = {}
    for h in heads:
        if h[2].get("truss") in walls and not h[2].get("group"):
            key = (h[2]["truss"], h[2].get("truss_lift"))
            lifts[key] = lifts.get(key, 0) + 1
    for h in heads:
        if h[2].get("group"):
            named.setdefault(h[2]["group"], []).append(h)
        elif h[2].get("truss") in rings:
            named.setdefault(f"ring:{h[2]['truss']}", []).append(h)
        elif lifts.get((h[2].get("truss"), h[2].get("truss_lift")), 0) >= 3:
            named.setdefault(f"row:{h[2]['truss']}:{h[2].get('truss_lift')}", []).append(h)
        else:
            rest.append(h)

    # columns: 3+ heads at (almost) the same x and y, spread over height; not the heads on a lying truss (a head on the
    # overhead truss above a head on a totem above one on the floor is no tower: it plays with its truss)
    lying = {t["id"] for t in rig.get("trusses", []) if not t.get("vertical") and t["id"] not in walls}  # (a scaffold
    # is a wall: heads up its sides are its columns)
    stackable = [h for h in rest if h[2].get("truss") not in lying]
    used = set()
    for e, p, _ in stackable:
        if e["id"] in used:
            continue
        col = [
            h for h in stackable if h[0]["id"] not in used and abs(h[1][0] - p[0]) < 0.35 and abs(h[1][1] - p[1]) < 0.6
        ]
        zs = [h[1][2] for h in col]
        units = {h[2]["id"] for h in col}  # fixtures, not cells: a unit of three heads and one above is no tower
        up = {h[2]["id"] for h in col if h[2].get("mount") != "floor"}  # stacked up something, not at its foot: a
        # totem with one head and the floor units round it is no tower (nor is it one on one side of the stage only
        # because the floor heads there stand a little nearer)
        if len(units) >= 3 and len(up) >= 2 and max(zs) - min(zs) > 1.2:
            col = [h for h in stackable if h[2]["id"] in units and h[0]["id"] not in used]  # a fixture's cells together
            name = f"column@{p[0]:.1f}"
            named[name] = col
            used |= {h[0]["id"] for h in col}
    # rows: same mount, about the same depth and height (neighbours chained), the heads on one lying truss together
    for row in _rows([h for h in rest if h[0]["id"] not in used], lying):
        p = np.mean([h[1] for h in row], axis=0)
        key = f"row:{row[0][2].get('mount', 'stand')}:{p[1]:.2f}:{p[2]:.2f}"
        named.setdefault(key, []).extend(row)

    stage_w = geometry.stage(rig)["width_m"]
    xs_all = np.array([h[1] for h in heads])
    out = []
    for name, members in named.items():
        P = np.array([m[1] for m in members])
        spread = P.max(0) - P.min(0)
        kind = "column" if len(members) >= 3 and spread[2] > max(spread[0], 1.0) else "row"
        ring = rings.get(name[5:]) if name.startswith("ring:") else None
        if ring:
            kind = "ring"
            order = np.argsort([m[2].get("truss_pos_m", 0.0) for m in members], kind="stable")
        else:
            order = np.argsort(P[:, 2] if kind == "column" else P[:, 0])
        centre = np.array([ring["x_m"], ring["y_m"], P[:, 2].mean()]) if ring else P.mean(0)
        mounts = {m[2].get("mount", "stand") for m in members}
        if ring:
            cls = "ring"
        elif kind == "column":
            cls = "towers"
        elif "hang" in mounts or centre[2] > 2.5:
            cls = "overhead"
        elif centre[2] < 1.2:
            cls = "back" if centre[1] < np.median(xs_all[:, 1]) - 0.5 else "front"
        else:
            cls = "mid"
        out.append(
            {
                "name": name,
                "cls": cls,
                "kind": kind,
                "ids": [members[i][0]["id"] for i in order],
                "centre": [round(float(v), 2) for v in centre],
                "side": float(centre[0] / stage_w * 2 - 1),
            }
        )
    # stable, readable order: overhead first, then back, front, towers, by position
    rank = {c: i for i, c in enumerate(["overhead", "ring", "back", "mid", "front", "towers"])}
    out.sort(key=lambda g: (rank.get(g["cls"], 9), -g["centre"][1] if g["cls"] == "overhead" else 0, g["centre"][0]))
    for g in out:
        if g["name"].startswith(("row:", "column@", "ring:")):
            g["name"] = _friendly(g, out)
    if len(out) == 1:
        out[0]["cls"] = "all"
    return out


ROW_DEPTH_M, ROW_HEIGHT_M = 0.5, 0.5  # a row of heads stands within this much depth and height


def _rows(heads: list, lying: set[str]) -> list[list]:
    """Heads in rows: the same mount, all within a band of depth and height. The heads on a lying truss that runs
    across the stage go as one, whatever its angle (a truss turned in a V is one row, not cut in two where its depth
    crosses a line), and as wide a band as that truss needs; heads and trusses at the same depth and height join
    them, so two short trusses end to end are one row. A truss running into the room (steeper than about 63°) is
    heads one by one, each in the row across at its depth."""
    units: dict = {}
    for h in heads:
        t = h[2].get("truss")
        units.setdefault(("truss", t) if t in lying else ("head", h[0]["id"]), []).append(h)
    for key, u in list(units.items()):
        x0, x1, y0, y1, _, _ = _span(u)
        if key[0] == "truss" and y1 - y0 > max(2 * (x1 - x0), ROW_DEPTH_M):  # steeper than ~63°
            del units[key]
            units.update({("head", h[0]["id"]): [h] for h in u})

    rows: list[dict] = []  # {mount, members, depth, height}: the band its widest unit needs
    for u in sorted(units.values(), key=lambda u: (-len(u), -_centre(u)[1], -_centre(u)[0])):
        mount = u[0][2].get("mount", "stand")
        _, _, y0, y1, z0, z1 = _span(u)
        depth, height = max(ROW_DEPTH_M, y1 - y0), max(ROW_HEIGHT_M, z1 - z0)
        best = None
        for r in rows:
            if r["mount"] != mount:
                continue
            _, _, ry0, ry1, rz0, rz1 = _span(r["members"] + u)
            if ry1 - ry0 <= max(depth, r["depth"]) + 1e-6 and rz1 - rz0 <= max(height, r["height"]) + 1e-6:
                cy, cz = _centre(r["members"])
                d = float(np.hypot(cy - _centre(u)[0], cz - _centre(u)[1]))
                if best is None or d < best[0]:
                    best = (d, r)
        if best:
            r = best[1]
            r["members"] += u
            r["depth"], r["height"] = max(r["depth"], depth), max(r["height"], height)
        else:
            rows.append({"mount": mount, "members": list(u), "depth": depth, "height": height})
    return [r["members"] for r in rows]


def _span(members: list) -> tuple[float, ...]:
    P = np.array([m[1] for m in members])
    lo, hi = P.min(0), P.max(0)
    return lo[0], hi[0], lo[1], hi[1], lo[2], hi[2]


def _centre(members: list) -> tuple[float, float]:
    P = np.array([m[1] for m in members])
    return float(P[:, 1].mean()), float(P[:, 2].mean())


def _friendly(g: dict, groups: list[dict]) -> str:
    same = [x for x in groups if x["cls"] == g["cls"]]
    if len(same) == 1:
        return g["cls"]
    if g["cls"] == "towers":
        return "tower left" if g["side"] < 0 else "tower right"
    i = same.index(g)
    if g["cls"] == "overhead" and len(same) == 2:
        return ["overhead front", "overhead back"][i]
    return f"{g['cls']} {i + 1}"


def has_smoke(rig: dict) -> bool:
    """Is there a smoke machine or hazer the show can fire (engine/fog.py)?"""
    return any(e["kind"] == "smoke" for e in rig.get("elements", []))


def laser_list(rig: dict) -> list[dict]:
    """The rig's lasers and roughly where they are (for the director's prompt)."""
    out = []
    w = geometry.stage(rig)["width_m"]
    for f in rig["fixtures"]:
        if fxlib.get(f["fixture"])["kind"] != "laser" or fxlib.inert(fxlib.get(f["fixture"])):
            continue
        for e in fxlib.expand(f):
            x, y, z = geometry.position(rig, e, f)
            where = (
                "on the overhead truss"
                if z > 3 and f.get("mount") == "hang"
                else "on the towers"
                if z > 3 and (x < 0.15 * w or x > 0.85 * w)
                else "at the back of the stage"
                if y < -3
                else "on the stage"
            )
            out.append({"id": e["id"], "where": where})
    return out


def classes(groups: list[dict]) -> list[str]:
    seen = []
    for g in groups:
        if g["cls"] not in seen:
            seen.append(g["cls"])
    return seen


def signature(groups: list[dict]) -> str | None:
    """Short id of the group layout for plan caches; None for a rig that is one group (plans as before), "ring"
    for a lone ring (the prompt tells of it)."""
    if len(groups) == 1 and groups[0]["kind"] == "ring":
        return "ring"
    if len(groups) <= 1:
        return None
    text = ";".join(f"{g['cls']}:{len(g['ids'])}" for g in groups)
    return "g" + hashlib.sha1(text.encode()).hexdigest()[:6]


def describe(groups: list[dict]) -> str:
    """The rig in words, for the director's prompt."""
    lines = []
    for g in groups:
        c = g["centre"]
        where = f"{c[2]:.1f} m high, {abs(c[1]):.1f} m {'behind' if c[1] < 0 else 'in front of'} the stage edge"
        shapes = {"column": "stacked bottom to top", "ring": "round a circle truss"}
        shape = shapes.get(g["kind"], "in a row left to right")
        lines.append(f"- {g['name']} [{g['cls']}]: {len(g['ids'])} heads {shape}, {where}")
    if any(g["kind"] == "ring" for g in groups):
        lines.append(RING_NOTE)
    return "\n".join(lines)


RING_NOTE = (
    "  On a circle truss the formations take its shape: fan = a crown of beams out of the circle, twisting with the "
    "movement; focus = a cone of beams to one point under or in front of it; cross = a twisted hourglass; wave = "
    "the movement runs round the ring. Sync and mirror stay plain. Rings shine with circle, sweep and tilt_wave."
)
