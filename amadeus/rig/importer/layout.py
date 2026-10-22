"""From items with a fixture and a place to a set and a rig: ids, the patch, the stage, trusses and placements.

Hanging fixtures in a row become a truss under them (across the stage, or running up and down it), split where
the row has a gap a truss wouldn't span; a fixed light keeps the way it points. Fixtures without a position are
auto-mounted afterwards, on the trusses found or on a standard structure for the stage.
"""

from __future__ import annotations

import math
import re

from amadeus.library import fixtures as fxlib
from amadeus.rig import trusses as T
from amadeus.rig.automount import role
from amadeus.rig.importer.draft import Draft, Item
from amadeus.rig.importer.resolve import Choice

ROW_NEAR_M = 0.6  # fixtures this close across a row's line are in it
ROW_GAP_M = 3.0  # a gap longer than this between fixtures: two trusses
HIGH_M = 1.8  # hanging higher than this: on a truss
FLOOR_M = 0.6  # lower than this: on the floor
FRONT = re.compile(r"front|foh|f\.o\.h|follow|key ?light|dj", re.I)  # a fixed light there lights the stage


def slug(text: str) -> str:
    words = re.findall(r"[a-z]+", text.lower())
    return next((w for w in words if len(w) > 2 and w not in ("mac", "led", "pro", "the")), words[0] if words else "fx")


def ids(draft: Draft, choices: dict[int, Choice]) -> list[str]:
    """A name per fixture: its model and its number in the documents ("aura201"), else counted ("aura3")."""
    out, taken, counts = [], set(), {}
    for i, it in enumerate(draft.items):
        base = slug(fxlib.get(choices[i].key)["model"])
        label = re.sub(r"[^a-z0-9]+", "", it.label.lower())
        fid = f"{base}{label}" if label else ""
        while not fid or fid in taken:
            counts[base] = counts.get(base, 0) + 1
            fid = f"{base}{counts[base]}"
        taken.add(fid)
        out.append(fid)
    return out


def expand(draft: Draft, choices: dict[int, Choice]) -> None:
    """A row for several fixtures becomes one item each, addressed one after the other."""
    items, new_choices = [], {}
    for i, it in enumerate(draft.items):
        for k in range(it.count):
            one = Item(**{**it.__dict__, "count": 1})
            if k and it.address:
                one.address = it.address + k * choices[i].footprint
                one.label = str(int(it.label) + k) if it.label.isdigit() else f"{it.label}.{k + 1}" if it.label else ""
            new_choices[len(items)] = choices[i]
            items.append(one)
    draft.items[:] = items
    choices.clear()
    choices.update(new_choices)


def rows(points: dict[str, tuple[float, float, float]]) -> list[tuple[list[str], str]]:
    """Groups of hanging fixtures in a line at one height: (ids, "x") across the stage or (ids, "y") up/down it."""
    left = dict(points)
    found = []
    for axis, across in (("x", 1), ("y", 0)):  # across the stage first: the usual truss
        groups: list[list[str]] = []
        for fid in sorted(left, key=lambda f: (left[f][across], left[f][2])):
            p = left[fid]
            for g in groups:
                q = left[g[0]]
                if abs(p[across] - q[across]) <= ROW_NEAR_M and abs(p[2] - q[2]) <= 0.5:
                    g.append(fid)
                    break
            else:
                groups.append([fid])
        along = 0 if axis == "x" else 1
        for g in groups:
            g.sort(key=lambda f: left[f][along])
            run = [g[0]]
            for a, b in zip(g, g[1:]):
                if left[b][along] - left[a][along] > ROW_GAP_M:
                    if len(run) >= 2:
                        found.append((run, axis))
                    run = []
                run.append(b)
            if len(run) >= 2:
                found.append((run, axis))
        for run, _ in found:
            for f in run:
                left.pop(f, None)
    return found


def aim(beam: tuple[float, float, float], rot_deg: float) -> list[float]:
    """[azimuth, elevation] for a fixed light pointing along `beam`, on a fixture turned `rot_deg`."""
    bx, by, bz = beam
    az = math.degrees(math.atan2(bx, by)) + rot_deg
    el = math.degrees(math.asin(max(-1.0, min(1.0, bz))))
    return [round((az + 180) % 360 - 180, 1), round(el, 1)]


def build(draft: Draft, choices: dict[int, Choice], name: str) -> tuple[dict, dict]:
    """The set and the rig (its placements for set `name`); fixtures without a place are left for auto-mount."""
    expand(draft, choices)
    names = ids(draft, choices)
    fixtures = []
    for i, it in enumerate(draft.items):
        f = {"id": names[i], "fixture": choices[i].key, "mode": choices[i].mode}
        if it.address:
            f.update(universe=it.universe or 1, address=it.address)
        fixtures.append(f)
    placed = {names[i]: it for i, it in enumerate(draft.items) if it.pos}
    on_stage = [it.pos[0] for it in placed.values() if it.pos[1] <= 1.0] or [it.pos[0] for it in placed.values()]
    if draft.stage.get("width_m"):  # the documents give it: positions are from its centre line
        W, mid = float(draft.stage["width_m"]), 0.0
    else:
        W = max(6.0, math.ceil((max(on_stage) - min(on_stage) + 2.0) * 2) / 2) if on_stage else 8.0
        mid = (max(on_stage) + min(on_stage)) / 2 if on_stage else 0.0
    trusses, places = [], {}

    def xyz(it: Item) -> tuple[float, float, float]:
        return it.pos[0] - mid + W / 2, it.pos[1], it.pos[2]

    high = {fid: xyz(it) for fid, it in placed.items() if it.pos[2] >= HIGH_M}
    trusses, places = on_drawn_trusses(draft, high, W, mid)
    high = {fid: p for fid, p in high.items() if fid not in places and placed[fid].hanging is not False}
    for run, axis in rows(high):
        ps = [high[f] for f in run]
        z = sorted(p[2] for p in ps)[len(ps) // 2] + T.HANG_DROP
        along = 0 if axis == "x" else 1
        lo, hi = min(p[along] for p in ps), max(p[along] for p in ps)
        cx, cy = sum(p[0] for p in ps) / len(ps), sum(p[1] for p in ps) / len(ps)
        if axis == "x":
            cx = (lo + hi) / 2
        else:
            cy = (lo + hi) / 2
        t = {
            "id": _truss_id(draft, trusses, cx - W / 2 + mid, cy, z),
            "type": "quatro",
            "length_m": math.ceil((hi - lo + 1.0) * 2) / 2,
            "x_m": round(cx, 2),
            "y_m": round(cy, 2),
            "z_m": round(z, 2),
        }
        if axis == "y":
            t["rot_deg"] = 90
        trusses.append(t)
        for f in run:
            p = high[f]
            u = p[0] - cx if axis == "x" else p[1] - cy
            places[f] = T.place({}, t, round(u, 3), W, "under")
    for fid, it in placed.items():
        if fid in places:
            continue
        x, y, z = xyz(it)
        mount = "floor" if z < FLOOR_M else ("hang" if it.hanging is not False else "stand")
        places[fid] = {"x": round(x / W, 4), "y_m": round(y, 3), "z_m": round(max(z, 0.0), 3), "mount": mount}
    for i, it in enumerate(draft.items):
        fid = names[i]
        if fid not in places or role(fxlib.get(choices[i].key)) == "head":
            continue
        if it.beam:
            places[fid]["aim"] = aim(it.beam, places[fid].get("rot_deg", 0.0))
        elif places[fid].get("mount") == "hang":  # the documents don't say: down, front light onto the stage
            front = FRONT.search(it.where) and places[fid]["y_m"] > 0
            places[fid]["aim"] = aim(
                (0.0, -0.8, -0.6) if front else (0.0, 0.26, -0.97), places[fid].get("rot_deg", 0.0)
            )
    ys = [p["y_m"] for p in places.values()]
    zs = [p["z_m"] for p in places.values()]
    stage = {
        "width_m": W,
        "ceiling_m": float(draft.stage.get("ceiling_m") or round(max(zs + [4.0]) + 1.0, 1)),
        "eye_safety": True,
        "room_depth_m": round(max(15.0, max(ys + [0.0]) + 4.0), 1),
    }
    set_doc = {
        "description": f"Imported: {len(fixtures)} fixtures",
        "artnet": {"ip": "127.0.0.1", "port": 6454, "fps": 40},
        "safety": {"max_flash_hz": 3, "master": 1.0, "allow_fast_strobe": False},
        "director": "openai",
        "fixtures": fixtures,
    }
    rig_doc = {"description": "Imported", "stage": stage, "trusses": trusses, "zones": [], "placements": {name: places}}
    return set_doc, rig_doc


TRUSS_NEAR_M = 0.8  # a fixture this close to a drawn truss's line (seen from above) is on it
TRUSS_BELOW_M = 1.2  # …and at most this far below it, or on top of it


def on_drawn_trusses(draft: Draft, points: dict[str, tuple[float, float, float]], W: float, mid: float):
    """Put fixtures on the trusses the documents draw (an MVR's Truss objects): each on the nearest truss line,
    the truss as long as its fixtures need, each fixture under it, on top or on a side face as it was drawn."""
    lines = []
    for t in draft.trusses:
        dx, dy = t["dir"]
        n = math.hypot(dx, dy) or 1.0
        lines.append((t, t["s"] - mid + W / 2, t["y"], dx / n, dy / n))
    on: dict[int, list[tuple[str, float, float, float]]] = {}
    for fid, (x, y, z) in points.items():
        best = None
        for k, (t, ox, oy, dx, dy) in enumerate(lines):
            along = (x - ox) * dx + (y - oy) * dy
            across = -(x - ox) * dy + (y - oy) * dx  # + is the side towards the audience for a truss across
            if abs(across) <= TRUSS_NEAR_M and -0.6 <= t["z"] - z <= TRUSS_BELOW_M:
                score = (round(abs(across) / 0.3), abs(along))
                if best is None or score < best[0]:
                    best = (score, k, along, across, z)
        if best:
            on.setdefault(best[1], []).append((fid, best[2], best[3], best[4]))
    trusses, places = [], {}
    for k, fs in on.items():
        t0, ox, oy, dx, dy = lines[k]
        lo, hi = min(f[1] for f in fs), max(f[1] for f in fs)
        c = (lo + hi) / 2
        under = sorted(f[3] for f in fs if abs(f[2]) <= 0.25 and f[3] < t0["z"])
        z = under[len(under) // 2] + T.HANG_DROP if under else t0["z"]
        rot = math.degrees(math.atan2(dy, dx))
        if rot > 90 or rot <= -90:  # the same truss, counted from its other end
            rot, dx, dy = rot - 180 if rot > 90 else rot + 180, -dx, -dy
            fs = [(f, -a, -b, zz) for f, a, b, zz in fs]
            c = -c
        t = {
            "id": re.sub(r"[^A-Za-z0-9]+", "", t0["name"]) or "truss",
            "type": "quatro",
            "length_m": math.ceil((hi - lo + 1.0) * 2) / 2,
            "x_m": round(ox + c * dx, 2),
            "y_m": round(oy + c * dy, 2),
            "z_m": round(z, 2),
        }
        while t["id"] in {x["id"] for x in trusses}:
            t["id"] += "b"
        if abs(rot) > 0.5:
            t["rot_deg"] = round(rot, 1)
        trusses.append(t)
        for fid, along, across, zz in fs:
            side = "top" if zz > z + 0.1 else ("front" if across > 0.25 else "back" if across < -0.25 else "under")
            places[fid] = T.place({}, t, round(along - c, 3), W, side)
    return trusses, places


def _truss_id(draft: Draft, trusses: list[dict], s: float, y: float, z: float) -> str:
    """The document's name for the truss at this spot (an MVR truss within a metre), else truss1, truss2…"""
    taken = {t["id"] for t in trusses}
    for t in draft.trusses:
        if abs(t["s"] - s) < 1.5 and abs(t["y"] - y) < 1.0 and abs(t["z"] - z) < 1.0:
            base = re.sub(r"[^A-Za-z0-9]+", "", t["name"]) or "truss"
            if base not in taken:
                return base
    n = len(trusses) + 1
    while f"truss{n}" in taken:
        n += 1
    return f"truss{n}"
