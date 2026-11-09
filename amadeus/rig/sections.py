"""Sections of the rig: one model in one place, its left and right halves mirroring each other.

A rig is an orchestra: the two Fuzes at the ends of the truss are one section, the pars along the walls another, the
minis on the truss a third. The same model somewhere else (the minis on the floor) is a section of its own: fixtures
belong together when they look alike and stand together, or stand mirrored across the middle of the stage. Inside a
section every fixture is paired with its mirror image: a pair always plays the same.

The show hands out its parts (who plays the accents, who holds the glow, who takes which kick, who plays to the
camera) by whole sections, or by pairs when the rig has too few sections for the part, so left and right stay mirrored
and a model plays as one. Waves, chases and the like run through the rig on their own and overrule this.
"""

from __future__ import annotations

import numpy as np

from amadeus.rig import geometry

KINDS = ("head", "par")  # what the show hands parts to (blinders, strobes and lasers play together anyway)
PLACE_GAP_M, PLACE_GAP_WIDTH = 2.5, 0.25  # neighbours this close, seen on one half of the stage, are one place (metres,
PLACE_GAP_Z_M = 0.75  # or this share of the stage if that's more), at about the same height
MIRROR_GAP_M, MIRROR_GAP_WIDTH = 1.0, 0.1  # a fixture's mirror image stands this close to it
CENTRE_M = 0.15  # on the middle of the stage: its own mirror image


def _places(items: list[dict], mid: float, gap: float) -> list[list[dict]]:
    """Items of one model in groups by place: neighbours chained together, folded onto one half of the stage."""
    root = list(range(len(items)))

    def find(i: int) -> int:
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    for i, a in enumerate(items):
        for j, b in enumerate(items[:i]):
            across = abs(a["x"] - mid) - abs(b["x"] - mid)
            near = float(np.hypot(across, a["y"] - b["y"])) <= gap and abs(a["z"] - b["z"]) <= PLACE_GAP_Z_M
            if near or (a["truss"] is not None and a["truss"] == b["truss"]):
                root[find(i)] = find(j)
    places: dict[int, list[dict]] = {}
    for i, item in enumerate(items):
        places.setdefault(find(i), []).append(item)
    return list(places.values())


def _pairs(items: list[dict], mid: float, gap: float) -> list[list[str]]:
    """The section's fixtures with their mirror images, from the outside in; one without a mirror image is alone."""
    left = [i for i in items if i["x"] < mid - CENTRE_M]
    right = [i for i in items if i["x"] > mid + CENTRE_M]
    apart = []
    for a in left:
        for b in right:
            d = float(np.linalg.norm([2 * mid - a["x"] - b["x"], a["y"] - b["y"], a["z"] - b["z"]]))
            if d <= gap:
                apart.append((d, id(a), id(b), a, b))
    taken: set[int] = set()
    pairs = []
    for _, ia, ib, a, b in sorted(apart, key=lambda p: p[0]):
        if ia not in taken and ib not in taken:
            taken |= {ia, ib}
            pairs.append([a, b])
    pairs += [[i] for i in items if id(i) not in taken]
    pairs.sort(key=lambda p: (-max(abs(i["x"] - mid) for i in p), p[0]["y"], p[0]["x"]))
    return [[e for i in p for e in i["ids"]] for p in pairs]


def rig_sections(rig: dict) -> list[dict]:
    """[{name, model, ids, pairs}]: the rig's heads and pars in sections, the highest first; `pairs` are lists of
    element ids (a fixture's cells stay together). A hand-made group on a fixture stays apart from the others."""
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    width = geometry.stage(rig)["width_m"]
    by_light: dict[tuple, list] = {}
    for e in rig["elements"]:
        if e["kind"] in KINDS and not e.get("uplight"):  # (wall uplighters play their own part: rig/uplights.py)
            f = fixtures[e["fixture"]]
            by_light.setdefault((f["id"], e["kind"]), []).append((e["id"], geometry.position(rig, e, f)))
    models: dict[tuple, list[dict]] = {}
    for (fid, kind), cells in by_light.items():
        f = fixtures[fid]
        x, y, z = np.mean([p for _, p in cells], axis=0)
        item = {"ids": [i for i, _ in cells], "x": float(x), "y": float(y), "z": float(z), "truss": f.get("truss")}
        models.setdefault((f["fixture"], kind, f.get("mount", "stand"), f.get("group")), []).append(item)
    mid = width / 2
    gap = max(PLACE_GAP_M, PLACE_GAP_WIDTH * width)
    mirror = max(MIRROR_GAP_M, MIRROR_GAP_WIDTH * width)
    out = []
    for (model, _, _, _), items in models.items():
        for place in _places(items, mid, gap):
            out.append(
                {
                    "name": model.split("/")[-1],
                    "model": model,
                    "ids": [e for i in place for e in i["ids"]],
                    "pairs": _pairs(place, mid, mirror),
                    "z": float(np.mean([i["z"] for i in place])),
                    "y": float(np.mean([i["y"] for i in place])),
                }
            )
    out.sort(key=lambda s: (-round(s["z"], 1), s["y"], s["model"]))
    return out


def parts(sections: list[dict], want: float, only=None) -> list[list[str]]:
    """The rig in units to hand parts to: its sections if there are at least `want` of them, else its pairs. `only`:
    just these lights (a section without any is left out)."""
    keep = set(only) if only is not None else None

    def pick(ids: list[str]) -> list[str]:
        return ids if keep is None else [i for i in ids if i in keep]

    whole = [u for u in (pick(s["ids"]) for s in sections) if u]
    if len(whole) >= want:
        return whole
    return [u for u in (pick(p) for s in sections for p in s["pairs"]) if u]


def share_out(units: list[list[str]], n: int) -> list[list[str]]:
    """Units over `n` equal shares: the biggest first, each to the smallest share so far."""
    shares: list[list[str]] = [[] for _ in range(n)]
    for u in sorted(units, key=len, reverse=True):
        min(shares, key=len).extend(u)
    return shares
