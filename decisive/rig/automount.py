"""Auto-mount: hang a set's fixtures on a rig the way a lighting tech would, as a starting point.

- moving heads under the overhead trusses (front first, spread evenly at a comfortable spacing), then on the
  towers; a big set keeps a share of its heads for the stage floor (a row at the front edge, one at the back),
  and what doesn't fit on the trusses goes there too, never squeezed;
- lasers on top of the back truss (high, in the middle), else on the towers;
- strobes and blinders on the front face of the front truss: strobes in the middle, blinders at the ends;
- bars on the floor along the front edge of the stage, pars on the floor at the back (uplighting).

Fixtures of the same model stay together and every row is symmetric. Fixtures already mounted keep their
place and their room on a truss is left free.

A rig without truss objects (an older or generated one, where fixtures hang at fixed positions) first gets its
structure back: hanging fixtures in a row become a truss, fixtures stacked at one spot a tower, and they are put
on them where they are. A rig with no structure at all gets one, like the "stage" template (or "club" on a narrow
stage), before anything is mounted: never a field of stands.
"""

from __future__ import annotations

import math
from collections import defaultdict

from decisive.library import fixtures as fxlib
from decisive.rig import templates
from decisive.rig import trusses as T

SPACING = {"head": 0.6, "laser": 0.6, "strobe": 0.5, "blinder": 0.6, "bar": 1.1, "par": 0.5}
MIN_SPACING = {"head": 0.45, "laser": 0.45, "strobe": 0.4, "blinder": 0.45, "bar": 0.9, "par": 0.35}
USE = 0.9  # share of a truss's length fixtures are spread over
LOW_TRUSS_M = 2.2  # a truss lower than this (a riser at the back) carries fixtures on top, not hanging under
LASER_MIN_M = 2.0  # a laser on a tower: at least this high
HEAD_MIN_M = 1.2  # a head on a tower: at least this high (more go on stands)
TOWER_SHARE = 0.2  # share of the heads on the towers, when there are trusses too
FLOOR_FROM = 16  # a set with this many heads or more…
FLOOR_SHARE = 0.25  # …puts this share of them on the stage floor
ROLES = ("head", "laser", "strobe", "blinder", "bar", "par")


def role(defn: dict) -> str:
    kind = defn.get("kind", "par")
    if kind in ("moving_head", "moving_bar"):
        return "head"
    if kind == "par_bar":
        return "bar"
    return kind if kind in ROLES else "par"


def automount(merged: dict, ids: list[str] | None = None) -> dict[str, dict]:
    """Placements (fixture id → position fields) for the fixtures `ids` (all, if None) of a set on a rig.

    A rig without trusses gets its structure first (read from where its fixtures hang, else a standard one):
    `merged["trusses"]` is filled in then, and the fixtures put on it are in the placements too."""
    W = merged.get("stage", {}).get("width_m", 6.0)
    attached: dict[str, dict] = {}
    if not merged.get("trusses"):
        merged["trusses"], attached = structure(merged)
        stays = [f for f in merged.get("fixtures", []) if ids is not None and f["id"] not in ids]
        placed = [f for f in stays if not f.get("_unplaced")]
        if not merged["trusses"] and not placed:  # an empty room, mounted for the first time: its usual structure
            merged["trusses"] = standard_structure(merged)
    trusses = merged.get("trusses", [])
    horiz = sorted((t for t in trusses if not t.get("vertical")), key=lambda t: -t["y_m"])  # front first
    towers = sorted((t for t in trusses if t.get("vertical")), key=lambda t: t["x_m"])
    todo = [f for f in merged.get("fixtures", []) if ids is None or f["id"] in ids]
    taken = {f["id"] for f in todo}
    used: dict[tuple[str, str], list[float]] = defaultdict(list)  # (truss, side) → positions already in use
    for f in merged.get("fixtures", []):
        if f["id"] not in taken and f.get("truss") and not f.get("_unplaced"):
            used[(f["truss"], f.get("truss_side", "front"))].append(f.get("truss_pos_m", 0.0))

    by_role: dict[str, list[dict]] = defaultdict(list)
    for f in sorted(todo, key=lambda f: f["fixture"]):  # the same models together
        by_role[role(fxlib.get(f["fixture"]))].append(f)
    standing = [
        {"x": float(f.get("x", 0.5)), "y_m": float(f.get("y_m", 0)), "z_m": float(f.get("z_m", 0))}
        for f in merged.get("fixtures", [])
        if f["id"] not in taken and not f.get("truss") and not f.get("_unplaced")
    ]
    m = _Mounter(W, used, standing)

    lasers = by_role["laser"]  # first: they need the high spots
    if lasers:
        high = [t for t in horiz if t["z_m"] >= LOW_TRUSS_M]
        back = [(high[-1] if high else horiz[-1], "top")] if horiz else []
        rest = m.trusses(lasers, back, "laser", share=0.6)
        rest = m.towers(rest, towers, lowest=LASER_MIN_M)
        m.row(rest, y=-1.5, z=2.2, mount="stand", span=0.5)
    heads = by_role["head"]
    back_y = min([t["y_m"] for t in horiz] or [-1.5]) - 0.6
    if heads:
        on_floor = []
        if len(heads) >= FLOOR_FROM:  # a big set: some heads on the stage floor, as a lighting tech would
            k = int(len(heads) * FLOOR_SHARE) // 2 * 2
            heads, on_floor = heads[: len(heads) - k], heads[len(heads) - k :]
        on_towers = []
        if towers and horiz and len(heads) >= 8:  # a share for the towers, the same on every tower
            k = round(len(heads) * TOWER_SHARE / len(towers)) * len(towers)
            heads, on_towers = heads[: len(heads) - k], heads[len(heads) - k :]
        rest = m.trusses(heads, [(t, "under" if t["z_m"] >= LOW_TRUSS_M else "top") for t in horiz], "head")
        rest = m.towers(on_towers + rest, towers, lowest=HEAD_MIN_M)
        on_floor += rest  # what doesn't fit comfortably on the trusses: the floor, not squeezed in
        if len(on_floor) <= 3:
            m.row(on_floor, y=-1.2, z=1.8, mount="stand", span=0.8)  # a few: tripods behind the booth
        else:  # a row along the front edge of the stage and one at the back, mirrored
            m.row(on_floor[0::2], y=-0.5, z=0.3, mount="floor", span=0.85)
            m.row(on_floor[1::2], y=back_y, z=0.3, mount="floor", span=0.7)
    front = [(horiz[0], "front")] if horiz else []
    m.row(m.trusses(by_role["strobe"], front, "strobe", share=0.4), y=-0.3, z=0.25, mount="floor", span=0.3)
    m.row(m.ends(by_role["blinder"], front[0][0] if front else None), y=-0.2, z=0.9, mount="stand", span=0.76)
    m.row(by_role["bar"], y=-0.3, z=0.15, mount="floor", span=0.8)
    m.row(by_role["par"], y=back_y - 0.5, z=0.15, mount="floor", span=0.8)
    return {**{k: v for k, v in attached.items() if k not in taken}, **m.out}


TOWER_NEAR_M = 0.3  # fixtures this close across the floor, at different heights: on one tower
ROW_NEAR_M = 0.3  # hanging fixtures this close in depth…
ROW_HEIGHT_M = 0.4  # …and in height: under one truss


def structure(merged: dict) -> tuple[list[dict], dict[str, dict]]:
    """The trusses and towers a rig's fixtures hang on, read from where they are (a rig without truss objects),
    and those fixtures' placements on them (where they already are)."""
    W = merged.get("stage", {}).get("width_m", 6.0)
    pool = [f for f in merged.get("fixtures", []) if f.get("mount") in ("hang", "stand") and f.get("z_m", 0) > 1.2]
    xs = {f["id"]: float(f.get("x", 0.5)) * W for f in pool}
    trusses: list[dict] = []
    out: dict[str, dict] = {}

    def put(f, t, u, side):
        spot = {"mount": f.get("mount", "hang")}
        T.place(spot, t, u, W, side)
        out[f["id"]] = spot

    # towers: fixtures stacked at one spot
    left = list(pool)
    stacks: list[list[dict]] = []
    for f in sorted(left, key=lambda f: (xs[f["id"]], f.get("y_m", 0))):
        for s in stacks:
            g = s[0]
            if (
                abs(xs[f["id"]] - xs[g["id"]]) <= TOWER_NEAR_M
                and abs(f.get("y_m", 0) - g.get("y_m", 0)) <= TOWER_NEAR_M
            ):
                s.append(f)
                break
        else:
            stacks.append([f])
    towers = [s for s in stacks if len(s) >= 2 and max(f["z_m"] for f in s) - min(f["z_m"] for f in s) >= 0.5]
    for s in towers:
        x = sum(xs[f["id"]] for f in s) / len(s)
        y = sum(f.get("y_m", 0) for f in s) / len(s) - T.TOWER_OUT  # they were in front of it
        length = math.ceil((max(f["z_m"] for f in s) + 0.3) * 2) / 2
        tid = _new_id(trusses, "towerL" if x < W / 2 else "towerR")
        t = {"id": tid, "type": "quatro", "length_m": length, "x_m": round(x, 2), "y_m": round(y, 2),
             "z_m": round(length / 2, 2), "vertical": True}  # fmt: skip
        trusses.append(t)
        for f in s:
            put(f, t, f["z_m"], "front")
            left.remove(f)
    # trusses: hanging fixtures in a row
    rows: list[list[dict]] = []
    for f in sorted((f for f in left if f.get("mount") == "hang"), key=lambda f: (f.get("y_m", 0), f["z_m"])):
        for r in rows:
            g = r[0]
            if abs(f.get("y_m", 0) - g.get("y_m", 0)) <= ROW_NEAR_M and abs(f["z_m"] - g["z_m"]) <= ROW_HEIGHT_M:
                r.append(f)
                break
        else:
            rows.append([f])
    for r in sorted((r for r in rows if len(r) >= 2), key=lambda r: -r[0].get("y_m", 0)):  # front first
        lo, hi = min(xs[f["id"]] for f in r), max(xs[f["id"]] for f in r)
        zs = sorted(f["z_m"] for f in r)
        t = {"id": _new_id(trusses, "truss"), "type": "quatro", "length_m": math.ceil((hi - lo + 1.0) * 2) / 2,
             "x_m": round((lo + hi) / 2, 2), "y_m": round(sum(f.get("y_m", 0) for f in r) / len(r), 2),
             "z_m": round(zs[len(zs) // 2] + T.HANG_DROP, 2)}  # fmt: skip
        trusses.append(t)
        for f in r:
            put(f, t, xs[f["id"]] - t["x_m"], "under")
    return trusses, out


ROOM_FOR_TRUSS = (4.0, 3.5)  # a room at least this wide and high (m) gets trusses; a smaller one: stands


def standard_structure(merged: dict) -> list[dict]:
    """A rig with no structure at all: the usual one for its stage (the "stage" template, "club" when narrow),
    under its ceiling. A small room (a living room, a booth) gets none: its fixtures go on stands."""
    st = merged.get("stage", {})
    W, ceiling = float(st.get("width_m", 6.0)), float(st.get("ceiling_m", 6.5))
    if ROOM_FOR_TRUSS[0] > W or ceiling < ROOM_FOR_TRUSS[1]:
        return []
    height = max(2.5, min(7.0, ceiling - 1.0))
    trusses = templates.rig("stage" if W >= 8 else "club", width=W, height=height)["trusses"]
    for t in trusses:  # never through the ceiling
        top = t["z_m"] + (t["length_m"] / 2 if t.get("vertical") else 0) + 0.15
        if top > ceiling - 0.2:
            if t.get("vertical"):
                t["length_m"] = max(1.0, int((ceiling - 0.5) * 2) / 2)
                t["z_m"] = t["length_m"] / 2
            else:
                t["z_m"] = round(ceiling - 0.4, 2)
    return trusses


def _new_id(trusses: list[dict], base: str) -> str:
    n, ids = 1, {t["id"] for t in trusses}
    while f"{base}{n}" in ids:
        n += 1
    return f"{base}{n}"


def mirrored(fixtures: list[dict], spots: list[float]) -> list[tuple[dict, float]]:
    """Fixtures onto spots so that every model is mirrored around the middle: the biggest group takes the
    outermost pairs, the next group the pairs inside those, an odd one out goes to the middle."""
    spots = sorted(spots)
    pairs = [(spots[i], spots[-1 - i]) for i in range(len(spots) // 2)]
    middle = [spots[len(spots) // 2]] if len(spots) % 2 else []
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in fixtures:
        groups[f["fixture"]].append(f)
    out, singles = [], []
    for model in sorted(groups, key=lambda m: -len(groups[m])):
        g = groups[model]
        while len(g) >= 2 and pairs:
            a, b = pairs.pop(0)
            out += [(g.pop(0), a), (g.pop(0), b)]
        singles += g
    rest = middle + [u for pair in pairs for u in pair]
    rest.sort(key=abs)  # odd ones out: as near the middle as there is room
    out += list(zip(singles, rest))
    return out


class _Mounter:
    def __init__(self, width: float, used: dict, standing: list[dict] | None = None):
        self.W, self.used, self.out = width, used, {}
        self.standing = standing or []  # fixtures already on the floor or on stands (that stay where they are)

    def _put(self, f: dict, t: dict, u: float, side: str):
        spot = {"mount": "stand" if side == "top" else "hang"}
        T.place(spot, t, u, self.W, side)
        self.used[(t["id"], side)].append(u)
        self.out[f["id"]] = {k: v for k, v in spot.items() if k != "id"}

    def _free(self, t: dict, side: str, n: int, kind: str, share: float) -> list[float]:
        """Up to `n` positions on a truss side, spread evenly and symmetric, clear of what hangs there."""
        span = t["length_m"] * share
        busy = self.used.get((t["id"], side), [])
        if not busy:
            k = min(n, int(span / SPACING[kind]) + 1)  # a comfortable spacing: a big set goes to the floor too
            if k <= 0:
                return []
            return [-span / 2 + span * (i + 0.5) / k for i in range(k)] if k > 1 else [0.0]
        step = SPACING[kind]
        slots = [-span / 2 + step * i for i in range(int(span / step) + 1)]
        slots = [s for s in slots if all(abs(s - b) >= MIN_SPACING[kind] for b in busy)]
        if len(slots) <= n:
            return slots
        return [slots[round(i * (len(slots) - 1) / (n - 1))] for i in range(n)] if n > 1 else [slots[len(slots) // 2]]

    def trusses(self, fixtures: list[dict], sides: list[tuple[dict, str]], kind: str, share: float = USE) -> list[dict]:
        """Spread over truss sides in proportion to their length (front first); returns what didn't fit."""
        if not fixtures or not sides:
            return list(fixtures)
        total = sum(t["length_m"] for t, _ in sides)
        left = list(fixtures)
        for i, (t, side) in enumerate(sides):
            want = len(left) if i == len(sides) - 1 else round(len(fixtures) * t["length_m"] / total)
            spots = self._free(t, side, min(want, len(left)), kind, share)
            for f, u in mirrored(left[: len(spots)], spots):
                self._put(f, t, u, side)
            left = left[len(spots) :]
        for t, side in sides:  # overflow: squeeze more onto trusses that still have room
            if not left:
                break
            spots = self._free(t, side, len(left), kind, share)
            for f, u in mirrored(left[: len(spots)], spots):
                self._put(f, t, u, side)
            left = left[len(spots) :]
        return left

    def towers(self, fixtures: list[dict], towers: list[dict], lowest: float = 0.3) -> list[dict]:
        """Shared left/right over the towers, stacked from the top down (no lower than `lowest` m)."""
        left = list(fixtures)
        if not towers:
            return left
        while left:
            placed = False
            for t in towers:
                if not left:
                    break
                n = len(self.used.get((t["id"], "front"), []))
                u = t["length_m"] - 0.3 - n * 0.6
                if t["z_m"] - t["length_m"] / 2 + u < lowest:
                    continue
                self._put(left.pop(0), t, u, "front")
                placed = True
            if not placed:
                break
        return left

    def ends(self, fixtures: list[dict], t: dict | None) -> list[dict]:
        """Blinders: the outer ends of the front truss's front face, in pairs; returns what didn't fit."""
        if not t or not fixtures:
            return list(fixtures)
        half = t["length_m"] / 2 - 0.3
        spots = []
        for i in range(len(fixtures)):
            u = half - (i // 2) * 0.6
            spots.append(-u if i % 2 == 0 else u)
        fits = [
            u for u in spots if abs(u) >= 0.3 and all(abs(u - b) >= 0.45 for b in self.used.get((t["id"], "front"), []))
        ]
        for f, u in zip(fixtures, fits):
            self._put(f, t, u, "front")
        return fixtures[len(fits) :]

    def row(self, fixtures: list[dict], y: float, z: float, mount: str, span: float):
        """A symmetric row across the stage (the middle `span` of its width), clear of fixtures already standing
        there (on that row: the same depth and height)."""
        n = len(fixtures)
        if not n:
            return
        near = [p["x"] for p in self.standing if abs(p["y_m"] - y) <= 0.4 and abs(p["z_m"] - z) <= 0.6]
        near += [p["x"] for p in self.out.values() if not p.get("truss") and abs(p["y_m"] - y) <= 0.4
                 and abs(p["z_m"] - z) <= 0.6]  # fmt: skip
        gap = min(0.5 / max(self.W, 0.5), 0.15)  # half a metre apart (as a share of the width)
        k = n + len(near)
        while True:  # an even row with room for them and the ones already there, then the free spots
            spots = [0.5] if k == 1 else [0.5 - span / 2 + span * i / (k - 1) for i in range(k)]
            free = [s for s in spots if all(abs(s - x) >= gap for x in near)]
            if len(free) >= n or k > 4 * (n + len(near)):
                break
            k += 1
        free = sorted(free, key=lambda s: abs(s - 0.5))[:n] if len(free) > n else free
        free.sort()
        for f, x in zip(fixtures, free + [0.5] * (n - len(free))):
            self.out[f["id"]] = {"x": round(x, 4), "y_m": round(y, 2), "z_m": round(z, 2), "mount": mount}
