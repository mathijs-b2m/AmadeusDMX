"""Groups of moving heads: which heads belong together, and where each head is inside its group.

A rig of 60 heads is not one line of 60: there is an overhead truss, a row at the back of the stage,
a row on the front edge, a tower left and right. The director decides how the groups relate (all as
one, each group its own formation, one group featured, ...); the engine uses each head's place in its
group for formations, waves, chases and focus points.

Groups come from the rig ("group" on a fixture), else from the positions:
- a column: 3+ heads at the same spot across the stage, stacked in height (a truss tower);
- a row: heads with the same mount at about the same depth and height.
Each group gets a class the director talks about: overhead, back, front, towers (or "all").
"""

from __future__ import annotations

import hashlib

import numpy as np

from decisive.library import fixtures as fxlib
from decisive.rig import geometry

CLASSES = {
    "overhead": "the heads hung overhead on the truss: they scan down onto the crowd",
    "back": "the row on the stage floor at the back: beams shoot up over the DJ into the room",
    "front": "the low row on the front edge of the stage: beams fan up and over the first rows",
    "towers": "the vertical truss towers left and right: stacked heads, beams from the sides",
    "mid": "heads on stands at mid height",
}


def head_groups(rig: dict) -> list[dict]:
    """[{name, cls, kind ('row'|'column'), ids (ordered: left→right, or bottom→top), centre (x, y, z)}]."""
    heads = []
    for f in rig["fixtures"]:
        if not fxlib.is_moving(fxlib.get(f["fixture"])):
            continue
        for e in fxlib.expand(f, geometry.stage(rig)["width_m"]):
            if e["kind"] == "head":
                heads.append((e, np.array(geometry.position(rig, e, f)), f))
    if not heads:
        return []
    named: dict[str, list] = {}
    rest = []
    for h in heads:
        (named.setdefault(h[2]["group"], []) if h[2].get("group") else rest).append(h)

    # columns: 3+ heads at (almost) the same x and y, spread over height
    used = set()
    for e, p, _ in rest:
        if e["id"] in used:
            continue
        col = [h for h in rest if h[0]["id"] not in used and abs(h[1][0] - p[0]) < 0.35 and abs(h[1][1] - p[1]) < 0.6]
        zs = [h[1][2] for h in col]
        if len(col) >= 3 and max(zs) - min(zs) > 1.2:
            name = f"column@{p[0]:.1f}"
            named[name] = col
            used |= {h[0]["id"] for h in col}
    # rows: same mount, about the same depth and height
    for e, p, f in rest:
        if e["id"] in used:
            continue
        key = f"row:{f.get('mount', 'stand')}:{round(p[1] * 2) / 2:g}:{round(p[2] * 2) / 2:g}"
        named.setdefault(key, []).append((e, p, f))

    stage_w = geometry.stage(rig)["width_m"]
    xs_all = np.array([h[1] for h in heads])
    out = []
    for name, members in named.items():
        P = np.array([m[1] for m in members])
        spread = P.max(0) - P.min(0)
        kind = "column" if len(members) >= 3 and spread[2] > max(spread[0], 1.0) else "row"
        order = np.argsort(P[:, 2] if kind == "column" else P[:, 0])
        centre = P.mean(0)
        mounts = {m[2].get("mount", "stand") for m in members}
        if kind == "column":
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
    rank = {c: i for i, c in enumerate(["overhead", "back", "mid", "front", "towers"])}
    out.sort(key=lambda g: (rank.get(g["cls"], 9), -g["centre"][1] if g["cls"] == "overhead" else 0, g["centre"][0]))
    for g in out:
        if g["name"].startswith(("row:", "column@")):
            g["name"] = _friendly(g, out)
    if len(out) == 1:
        out[0]["cls"] = "all"
    return out


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


def laser_list(rig: dict) -> list[dict]:
    """The rig's lasers and roughly where they are (for the director's prompt)."""
    out = []
    w = geometry.stage(rig)["width_m"]
    for f in rig["fixtures"]:
        if fxlib.get(f["fixture"])["kind"] != "laser":
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
    """Short id of the group layout for plan caches; None for a rig that is one group (plans as before)."""
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
        shape = "stacked bottom to top" if g["kind"] == "column" else "in a row left to right"
        lines.append(f"- {g['name']} [{g['cls']}]: {len(g['ids'])} heads {shape}, {where}")
    return "\n".join(lines)
