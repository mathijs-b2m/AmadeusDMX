"""Auto-mount: hang a set's fixtures on a rig the way a lighting tech would, as a starting point.

The rig is read first: which trusses mirror each other left and right of the stage (two bridges, two towers, two
side trusses: twins), which hang over the stage and which over the crowd. Then every kind of fixture gets its place:

- moving heads under the overhead trusses (on top of a low one), the same share of each truss's length, at a
  comfortable distance by the size of their housing: a model stays together on one truss when it fits there, the
  biggest group at the back, and what a truss has no room for is never squeezed in. Pairs of heads go on the towers
  (on top of a short one, then down its front); a big set keeps a share of its heads for the stage floor, and what
  the trusses have no room for stands there too, in a row at the back of the stage (and one at its front edge);
- tilting bars by the side walls of a narrow room, shining up along them (rig/uplights.py); else with the heads;
- lasers on top of the back truss (high, in the middle), else high on the towers;
- strobes and blinders on the front face of the front truss over the stage: strobes in the middle, blinders
  spread over what is left;
- pars on the light stands that have room, else on the floor at the back (uplighting); bars on the floor along
  the front edge of the stage; smoke machines in the back corners.

Everything is mirrored: twins carry the same fixtures at mirrored places, every row is symmetric and every model
sits in mirrored pairs (an odd one out in the middle). Nothing is put in the DJ's booth or behind the back wall.

A scaffold wall counts as a stack of straight trusses: its ledgers from the top down, a row every ROW_GAP_M or so,
none near the stage floor, and those level with its LED wall only left and right of it.

Fixtures already mounted keep their place and their room on a truss is left free.

A rig without truss objects (an older or generated one, where fixtures hang at fixed positions) first gets its
structure back: hanging fixtures in a row become a truss, fixtures stacked at one spot a tower, and they are put
on them where they are. A rig with no structure at all gets one, like the "stage" template (or "club" on a narrow
stage), before anything is mounted: never a field of stands.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry, templates
from amadeus.rig import trusses as T

# what a fixture takes up along a truss: its housing and the room to the next one, and never less than this
SPACING = {"head": 0.75, "laser": 0.6, "strobe": 0.5, "blinder": 0.6, "bar": 1.1, "par": 0.4}
CLEAR = {"head": 0.45, "laser": 0.3, "strobe": 0.2, "blinder": 0.3, "bar": 0.1, "par": 0.15}
# …and when there is nowhere else to go (a set too big for its rig): closer together
MIN_SPACING = {"head": 0.5, "laser": 0.45, "strobe": 0.4, "blinder": 0.45, "bar": 0.9, "par": 0.3}
MIN_CLEAR = {"head": 0.2, "laser": 0.15, "strobe": 0.1, "blinder": 0.1, "bar": 0.05, "par": 0.05}
SHORT_BAR_M = 2.0  # a light stand's bar no longer than this (a T-bar): its heads go closer together…
SHORT_BAR = (0.5, 0.3)  # …this far apart, their housings this far
STAND_GAP = 0.05  # housings on a light stand's bar are never closer than this
END = 0.35  # the outermost fixture's distance from the truss's end, as a share of the distance between fixtures
LOW_TRUSS_M = 2.2  # a truss lower than this (a riser at the back) carries fixtures on top, not hanging under
LASER_MIN_M = 2.0  # a laser on a tower: at least this high
HEAD_MIN_M = 1.2  # a head on a tower's face: at least this high
TOWER_STEP_M = 0.9  # heads down a tower's face: this far above each other
TOWER_WIDE_M = 0.7  # a housing wider than this (a bar) doesn't go on a tower
HALL_SHARE = 0.5  # a truss over the crowd gets this share of what a truss over the stage gets
FLOOR_FROM = 16  # a set with this many heads or more…
FLOOR_SHARE = 0.25  # …puts this share of them on the stage floor
BEAM_DEG, SPOT_DEG = 5.0, 10.0  # a head with a beam this narrow is a beam, a spot; wider: a wash
FLOOR_PAR_M = 0.25  # a par or bar on the floor: its lens this high (its body is 10 cm round it)
ROW_GAP_M = 1.4  # on a scaffold: rows of fixtures this far above each other (a head and its swing)
OVER_DECK_M = 1.8  # …and the lowest this far over the stage, clear of what stands on it
SCREEN_CLEAR_M = 0.4  # a fixture stays this far off the LED wall's edge
TWIN_OFF_M = 1.0  # twins: mirrored round the stage's middle to within this…
TWIN_DEPTH_M = 1.25  # …this far apart in depth at most…
TWIN_TURN_DEG = 15.0  # …and turned the other way about to within this
BOOTH_HALF_M = 1.3  # the DJ's booth: nothing stands this near the middle of the stage, level with it
WALL_OFF_M = 0.3  # a wall uplighter stands this far from its wall…
WALL_STEP_M = 4.0  # …and this far from the next one along it
ROLES = ("head", "laser", "strobe", "blinder", "bar", "par")


def role(defn: dict) -> str:
    kind = defn.get("kind", "par")
    if kind in ("moving_head", "moving_bar"):
        return "head"
    if kind == "par_bar":
        return "bar"
    return kind if kind in ROLES else "par"


def ledgers(t: dict, merged: dict, big: bool) -> list[dict]:
    """The ledgers of a scaffold to mount on, from the top down. One level with its LED wall has a `gap`: nothing
    within that distance of its middle."""
    deck = float(merged.get("stage", {}).get("deck_m", 0.0) or 0.0)
    n = T.scaffold_lifts(t)
    every = max(1, math.ceil(ROW_GAP_M / (t["z_m"] / n) - 1e-6))
    rows = [T.ledger(t, k) for k in range(n, 0, -every)]
    rows = [r for r in rows if r["z_m"] >= deck + OVER_DECK_M] or rows[:1]
    wall = T.screen_wall(merged.get("trusses", []))
    rect = T.screen_rect(merged, big) if wall and wall["id"] == t["id"] else None
    if rect:
        half, bottom, top = rect
        off = abs(t["x_m"] - float(merged.get("stage", {}).get("width_m", 6.0)) / 2)
        for r in rows:  # what hangs under a ledger just over the wall's top would hang in front of it
            if bottom - SCREEN_CLEAR_M <= r["z_m"] <= top + 0.8:
                r["gap"] = half + off + SCREEN_CLEAR_M
    return rows


def automount(merged: dict, ids: list[str] | None = None) -> dict[str, dict]:
    """Placements (fixture id → position fields) for the fixtures `ids` (all, if None) of a set on a rig.

    A rig without trusses gets its structure first (read from where its fixtures hang, else a standard one):
    `merged["trusses"]` is filled in then, and the fixtures put on it are in the placements too."""
    attached: dict[str, dict] = {}
    if not merged.get("trusses"):
        merged["trusses"], attached = structure(merged)
        stays = [f for f in merged.get("fixtures", []) if ids is not None and f["id"] not in ids]
        placed = [f for f in stays if not f.get("_unplaced")]
        if not merged["trusses"] and not placed:  # an empty room, mounted for the first time: its usual structure
            merged["trusses"] = standard_structure(merged)
    todo = [f for f in merged.get("fixtures", []) if ids is None or f["id"] in ids]
    taken = {f["id"] for f in todo}
    used: dict[tuple[str, str], list[tuple]] = defaultdict(list)  # (truss, side) → (position, housing) in use
    for f in merged.get("fixtures", []):
        if f["id"] not in taken and f.get("truss") and not f.get("_unplaced"):
            bar = f"{f['truss']}/{f['truss_lift']}" if f.get("truss_lift") else f["truss"]
            used[(bar, f.get("truss_side", "front"))].append((f.get("truss_pos_m", 0.0), _housing(f)))
    standing = [
        {"x": float(f.get("x", 0.5)), "y_m": float(f.get("y_m", 0)), "z_m": float(f.get("z_m", 0)), "w": _housing(f)}
        for f in merged.get("fixtures", [])
        if f["id"] not in taken and not f.get("truss") and not f.get("_unplaced")
    ]
    by_role: dict[str, list[dict]] = defaultdict(list)
    smoke, bars = [], []
    for f in todo:
        defn = fxlib.get(f["fixture"])
        if defn.get("kind") == "smoke":
            smoke.append(f)
        elif defn.get("kind") == "moving_bar":
            bars.append(f)
        else:
            by_role[role(defn)].append(f)
    m = _Mounter(merged, used, standing)
    m.smoke(smoke)
    m.lasers(by_role["laser"])
    if bars and m.walls_near():  # tilting bars in a narrow room: up along its side walls
        m.uplighters(bars)
        bars = []
    m.heads(by_role["head"], bars)
    m.front(by_role["strobe"], by_role["blinder"])
    m.pars(by_role["par"])
    m.rows(by_role["bar"], [-0.3], FLOOR_PAR_M, "floor", "bar", 0.8, step=-0.6)
    return {**{k: v for k, v in attached.items() if k not in taken}, **numbered(merged, m.out)}


def natural(name: str) -> list:
    """Sort key for names with numbers in them: top2 before top10."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", name)]


def name_order(fixtures: list[dict]):
    """Sort key for fixture names: a family of names (top1, top2…) in the order the set lists it first, and within
    a family by number (so top2 comes before top10, and the set's "top" heads before its "back" ones)."""
    rank: dict[str, int] = {}
    for f in fixtures:
        rank.setdefault(re.sub(r"\d+$", "", f["id"]), len(rank))
    return lambda fid: (rank.get(re.sub(r"\d+$", "", fid), len(rank)), natural(fid))


def numbered(merged: dict, places: dict[str, dict]) -> dict[str, dict]:
    """The same spots, the fixtures of each model on them in name order along the rig: the hang sheet's order
    (each truss from its stage-left end, front truss first, then the towers and the floor). top1 hangs at the
    first place, top2 at the next, so the names (and the addresses patched in name order) count along the truss
    like the places do. Which spots a model has (its symmetry) doesn't change, only which of them gets which name."""
    from amadeus.rig import hangsheet, store

    if len(places) < 2:
        return places
    rig = {**merged, "fixtures": []}
    for f in merged.get("fixtures", []):
        if f["id"] in places:
            f = {k: v for k, v in f.items() if k not in store.PLACEMENT_KEYS and k != store.UNPLACED}
            f.update(places[f["id"]])
        rig["fixtures"].append(f)
    lay = hangsheet.layout(rig)
    order = {r["id"]: i for i, r in enumerate([r for st in lay["structures"] for r in st["fixtures"]] + lay["floor"])}
    model = {f["id"]: f["fixture"] for f in merged.get("fixtures", [])}
    groups: dict[str, list[str]] = defaultdict(list)
    for fid in places:
        groups[model.get(fid, "")].append(fid)
    out, key = dict(places), name_order(merged.get("fixtures", []))
    for ids in groups.values():
        spots = sorted(ids, key=lambda i: order.get(i, len(order)))
        for name, spot in zip(sorted(ids, key=key), spots):
            out[name] = places[spot]
    return out


def in_order(merged: dict, ids: list[str] | None = None) -> dict[str, dict]:
    """The mounted fixtures (of `ids`, else all) put in name order on the spots they already take (`numbered`):
    the placements that change. Nothing moves to a new spot."""
    from amadeus.rig import store

    places = {
        f["id"]: {k: f[k] for k in store.PLACEMENT_KEYS if k in f}
        for f in merged.get("fixtures", [])
        if (ids is None or f["id"] in ids) and not f.get(store.UNPLACED)
    }
    return {fid: p for fid, p in numbered(merged, places).items() if p != places[fid]}


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


def mirrored(fixtures: list[dict], spots: list[float], loop: float | None = None) -> list[tuple[dict, float]]:
    """Fixtures onto spots so that every model is mirrored around the middle: the biggest group takes the
    outermost pairs, the next group the pairs inside those, an odd one out goes to the middle. Round a closed
    loop `loop` m long (a full ring, a carré), the spot half way round is its own mirror too."""
    spots = sorted(spots)
    back = [u for u in spots if loop and abs(u + loop / 2) < 1e-3]
    spots = [u for u in spots if u not in back]
    pairs = [(spots[i], spots[-1 - i]) for i in range(len(spots) // 2)]
    middle = ([spots[len(spots) // 2]] if len(spots) % 2 else []) + back
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


def _housing(f: dict) -> float:
    """A fixture's housing width (m): what it takes up along a bar."""
    size = fxlib.get(f["fixture"]).get("physical", {}).get("size_mm") or []
    return size[0] / 1000 if len(size) == 3 and size[0] > 0 else 0.3


def _models(fixtures: list[dict], beams: bool = False) -> list[list[dict]]:
    """Fixtures by model, the biggest group first (then the strongest lamp, then by name). `beams`: the models
    with the narrowest beam first (beams, then spots, then washes)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in fixtures:
        groups[f["fixture"]].append(f)

    def key(model: str):
        physical = fxlib.get(model).get("physical", {})
        beam = physical.get("beam_deg") or 15.0
        band = (0 if beam <= BEAM_DEG else 1 if beam <= SPOT_DEG else 2) if beams else 0
        return (band, -len(groups[model]), -(physical.get("watts") or 0), model)

    return [groups[k] for k in sorted(groups, key=key)]


def _mirrored(groups: list[list[dict]]) -> list[dict]:
    """A row from left to right in which every model is mirrored round the middle: its fixtures in pairs, the
    models taking turns from the outside in, an odd one out in the middle."""
    groups = [list(g) for g in sorted(groups, key=lambda g: -len(g)) if g]
    left = [len(g) // 2 for g in groups]
    total = list(left)
    a, b = [], []
    while any(left):
        j = max(range(len(groups)), key=lambda j: (left[j] / total[j] if total[j] else 0.0, -j))
        a.append(groups[j].pop())
        b.append(groups[j].pop())
        left[j] -= 1
    return a + [f for g in groups for f in g] + b[::-1]


def _stretches(lo: float, hi: float, blocks: list[tuple], end: tuple[float, float]) -> list[tuple]:
    """The free stretches of a bar from `lo` to `hi` between what is on it already: (from, to, and how far the
    first and the last fixture on it stay from its ends, in distances between fixtures). A block is (from, to,
    that distance): a fixture (a whole distance away from it) or a stretch to keep clear (half a distance)."""
    out, at, margin = [], lo, end[0]
    for a, b, m in sorted(blocks):
        if b < lo or a > hi:
            continue
        if a - at > 1e-6:
            out.append((at, min(a, hi), margin, m))
        at, margin = max(at, b), m
    if hi - at > 1e-6:
        out.append((at, hi, margin, end[1]))
    return out


def _block(u: float, housing: float, new: float | None) -> tuple:
    """A fixture on a bar as a block for new ones `new` wide: wider than they are, it keeps them further off."""
    extra = max(0.0, (housing - new) / 2) if new is not None else 0.0
    return (u - extra, u + extra, 1.0)


def _room(stretch: tuple, pitch: float) -> int:
    """How many fixtures `pitch` apart a free stretch takes."""
    a, b, ma, mb = stretch
    return max(0, int((b - a) / pitch + 1 - ma - mb + 1e-6))


def spread(
    k: int, lo: float, hi: float, pitch: float, blocks: list | None = None, end: tuple[float, float] = (END, END)
) -> list[float]:
    """Up to `k` places on a bar from `lo` to `hi`, at least `pitch` apart, clear of what is on it: evenly over
    its free stretches (so the fixtures end up as far apart as they can be), and mirrored round its middle
    wherever what is on it is."""
    st = _stretches(lo, hi, blocks or [], end)
    cap = [_room(s, pitch) for s in st]
    mid = (lo + hi) / 2

    def after(j: int, c: int) -> float:  # the distance between fixtures on a stretch that carries c
        return round((st[j][1] - st[j][0]) / (c - 1 + st[j][2] + st[j][3]), 4)

    # stretches that mirror each other fill up together; the one over the middle takes the odd ones
    twin: dict[int, int] = {}
    for i in range(len(st)):
        for j in range(i + 1, len(st)):
            a, b = st[i], st[j]
            alike = abs(a[0] + b[1] - 2 * mid) < 1e-3 and abs(a[1] + b[0] - 2 * mid) < 1e-3 and a[2:] == b[:1:-1]
            if i not in twin and j not in twin and alike:
                twin[i], twin[j] = j, i
    centre = next((j for j in range(len(st)) if j not in twin and abs(st[j][0] + st[j][1] - 2 * mid) < 1e-3), None)
    pairs = [j for j in twin if j < twin[j]]
    k = min(k, sum(cap))
    if k <= 0:
        return []
    best = None
    if pairs and len(twin) + (centre is not None) == len(st):
        for c in range(min(k, cap[centre]) + 1 if centre is not None else 1):
            if (k - c) % 2 or (k - c) // 2 > sum(cap[j] for j in pairs):
                continue
            n = [0] * len(st)
            if centre is not None:
                n[centre] = c
            for _ in range((k - c) // 2):
                j = max((j for j in pairs if n[j] < cap[j]), key=lambda j: (after(j, n[j] + 1), -st[j][0]))
                n[j] += 1
                n[twin[j]] += 1
            tightest = min(after(j, n[j]) for j in range(len(st)) if n[j])
            if best is None or tightest > best[0]:
                best = (tightest, n)
    if best is None:  # nothing to mirror: the stretch where one more leaves the most room, the outer ones first
        n = [0] * len(st)
        for _ in range(k):
            j = max(
                (j for j in range(len(st)) if n[j] < cap[j]),
                key=lambda j: (after(j, n[j] + 1), round(abs((st[j][0] + st[j][1]) / 2 - mid), 4), -st[j][0]),
            )
            n[j] += 1
        best = (0.0, n)
    out = []
    for (a, b, ma, mb), c in zip(st, best[1]):
        if c:
            p = (b - a) / (c - 1 + ma + mb)
            out += [a + p * (ma + i) for i in range(c)]
    return [round(u, 3) for u in sorted(out)]


def justify(
    widths: list[float], lo: float, hi: float, least: float, end: tuple[float, float] = (END, END)
) -> list[float] | None:
    """Fixtures of these housing widths in a row from `lo` to `hi`, the same gap between every two housings
    (`least` or more: else None)."""
    k = len(widths)
    if not k:
        return []
    between = sum((widths[i] + widths[i + 1]) / 2 for i in range(k - 1))
    gap = (hi - lo - between - end[0] * widths[0] - end[1] * widths[-1]) / (k - 1 + end[0] + end[1])
    if gap < least - 1e-6:
        return None
    out = [lo + end[0] * (widths[0] + gap)]
    for i in range(1, k):
        out.append(out[-1] + (widths[i - 1] + widths[i]) / 2 + gap)
    return [round(u, 3) for u in out]


def _alike(a: dict, b: dict) -> bool:
    """Two trusses of one kind, as long and as high as each other."""
    if bool(a.get("vertical")) != bool(b.get("vertical")) or a.get("type") != b.get("type"):
        return False
    return (abs(a["length_m"] - b["length_m"]) <= max(0.3, 0.1 * a["length_m"])
            and abs(a["z_m"] - b["z_m"]) <= 0.5)  # fmt: skip


def twins(trusses: list[dict], width: float) -> list[tuple]:
    """The trusses in their order, the ones that mirror each other left and right of the stage's middle as a pair
    (the stage-left one first): alike, at the same depth, turned the other way about."""
    found = []
    for i, a in enumerate(trusses):
        for j in range(i + 1, len(trusses)):
            b = trusses[j]
            if not _alike(a, b) or abs(a["x_m"] - b["x_m"]) < 0.5:
                continue
            off, deep = abs(a["x_m"] + b["x_m"] - width), abs(a["y_m"] - b["y_m"])
            turn = 0.0
            if not a.get("vertical"):
                turn = (a.get("rot_deg", 0.0) + b.get("rot_deg", 0.0)) % 180.0
                turn = min(turn, 180.0 - turn)
            if off <= TWIN_OFF_M and deep <= TWIN_DEPTH_M and turn <= TWIN_TURN_DEG:
                found.append((off + deep + turn / 30.0, i, j))
    pair: dict[int, int] = {}
    for _, i, j in sorted(found):
        if i not in pair and j not in pair:
            pair[i], pair[j] = j, i
    out = []
    for i, t in enumerate(trusses):
        if i not in pair:
            out.append((t,))
        elif pair[i] > i:
            a, b = t, trusses[pair[i]]
            out.append((a, b) if a["x_m"] <= b["x_m"] else (b, a))
    return out


def _twin_sign(a: dict, b: dict) -> int:
    """Where on twin `b` the mirror image of a place on `a` is: at the same distance from its middle (1) or at
    minus that (-1)."""
    c = (a["x_m"] + b["x_m"]) / 2
    x, y, _ = T.point(a, 1.0)
    far = [math.hypot(2 * c - x - T.point(b, s)[0], y - T.point(b, s)[1]) for s in (-1.0, 1.0)]
    return -1 if far[0] <= far[1] else 1


class _Bar:
    """A row to hang fixtures in: one side of a straight truss (a light stand's bar, a ledger, an arc), or of two
    twins, which carry the same at mirrored places. `share`: only the middle of it."""

    def __init__(self, m: _Mounter, trusses: tuple, side: str, share: float = 1.0, weight: float = 1.0):
        self.m, self.share, self.weight = m, share, weight
        self.sign = _twin_sign(*trusses) if len(trusses) == 2 else -1
        other = {"front": "back", "back": "front"}.get(side, side) if self.sign == 1 else side
        self.parts = [(trusses[0], side)] + ([(trusses[1], other)] if len(trusses) == 2 else [])
        e = END if share > 0.99 else 0.5
        self.ends = {t["id"]: (e, e) for t in trusses}
        a, b = trusses[0], trusses[-1]
        turn = abs((a.get("rot_deg", 0.0) - b.get("rot_deg", 0.0) + 90.0) % 180.0 - 90.0)
        if len(trusses) == 2 and share > 0.99 and turn < 5.0:  # twins in line, end to end: one row over the joint
            for s in (-1.0, 1.0):
                pa = T.point(a, s * a["length_m"] / 2)
                pb = T.point(b, s * self.sign * b["length_m"] / 2)
                if math.dist(pa[:2], pb[:2]) <= 0.5:
                    self.ends[a["id"]] = (0.5, e) if s < 0 else (e, 0.5)
                    self.ends[b["id"]] = (0.5, e) if s * self.sign < 0 else (e, 0.5)
        self.even = len(trusses) == 2 or any(t.get("gap") for t in trusses)
        self.short = T.is_stand(trusses[0]) and trusses[0]["length_m"] <= SHORT_BAR_M
        self.shared = False  # other kinds of fixtures hang here already
        self.y = sum(t["y_m"] for t in trusses) / len(trusses)
        self.z = trusses[0]["z_m"]

    def _free(self, t: dict, side: str, new: float | None = None) -> tuple[float, float, list]:
        """The stretch of a truss to hang on, and what is on it (for fixtures `new` wide)."""
        half = t["length_m"] / 2 * self.share
        blocks = [_block(u, w, new) for u, w in self.m.used.get((t["id"], side), [])]
        if t.get("gap"):
            blocks.append((-t["gap"], t["gap"], 0.5))
        return -half, half, blocks

    def busy(self) -> bool:
        return any(self.m.used.get((t["id"], side)) for t, side in self.parts)

    def size(self) -> float:
        return sum(b - a for t, side in self.parts
                   for a, b, _, _ in _stretches(*self._free(t, side), self.ends[t["id"]]))  # fmt: skip

    def fits(self, fixtures: list[dict]) -> bool:
        n = len(fixtures)
        if not n:
            return True
        if self.even and n % 2:
            return False
        needs = [self.m.need(self, f) for f in fixtures]
        k, total = n / len(self.parts), sum(needs) / len(self.parts)
        for t, side in self.parts:
            lo, hi, blocks = self._free(t, side, min(_housing(f) for f in fixtures))
            end = self.ends[t["id"]]
            if blocks:
                if k > sum(_room(s, max(needs)) for s in _stretches(lo, hi, blocks, end)):
                    return False
            elif total > hi - lo + (1 - sum(end)) * min(needs) + 1e-6:
                return False
        return True

    def _spots(self, t: dict, side: str, row: list[dict]) -> list[float] | None:
        widths = [_housing(f) for f in row]
        lo, hi, blocks = self._free(t, side, min(widths))
        needs = [self.m.need(self, f) for f in row]
        if not blocks:
            return justify(widths, lo, hi, min(n - w for n, w in zip(needs, widths)), self.ends[t["id"]])
        us = spread(len(row), lo, hi, max(needs), blocks, self.ends[t["id"]])
        return us if len(us) == len(row) else None

    def _plan(self, groups: list[list[dict]]) -> list[tuple] | None:
        if len(self.parts) == 1:
            row = _mirrored(groups)
            us = self._spots(*self.parts[0], row)
            return None if us is None else [(f, *self.parts[0], u) for f, u in zip(row, us)]
        # twins: each bar is symmetric in itself where a model has four or more (the outer places first), and the
        # other bar is its mirror image
        fixtures = [f for g in sorted(groups, key=lambda g: -len(g)) for f in g]
        mine, theirs = fixtures[0::2], fixtures[1::2]
        k = len(mine)
        order = [i // 2 if i % 2 == 0 else k - 1 - i // 2 for i in range(k)]
        rows: list[list] = [[None] * k, [None] * k]
        for j, i in enumerate(order):
            rows[0][i] = mine[j]
            rows[1][k - 1 - i if self.sign == -1 else i] = theirs[j]
        out = []
        for (t, side), row in zip(self.parts, rows):
            us = self._spots(t, side, row)
            if us is None:
                return None
            out += [(f, t, side, u) for f, u in zip(row, us)]
        return out

    def place(self, groups: list[list[dict]]) -> list[dict]:
        """Hang these on it; returns the ones it had no room for after all."""
        groups, rest = [list(g) for g in groups if g], []
        while groups:
            plan = self._plan(groups)
            if plan is not None:
                for f, t, side, u in plan:
                    self.m.put(f, t, u, side)
                break
            g = groups[-1]
            n = 2 if len(g) >= 2 and (self.even or len(g) % 2 == 0) else 1
            rest += g[-n:]
            del g[-n:]
            if not g:
                groups.pop()
        return rest


class _Loop:
    """A closed truss (a full ring, a carré): evenly all the way round, no ends to keep clear."""

    even, short = False, False

    def __init__(self, m: _Mounter, t: dict, side: str, weight: float = 1.0):
        self.m, self.t, self.side, self.weight = m, t, side, weight
        self.L = T.normalise(t)["length_m"]
        self.y, self.z = t["y_m"], t["z_m"]

    def size(self) -> float:
        return self.L

    def _spots(self, n: int, pitch: float) -> list[float]:
        t, L = self.t, self.L
        busy = [u for u, _ in self.m.used.get((t["id"], self.side), [])]
        k = min(n, int(L / pitch + 1e-6))
        if k <= 0:
            return []
        if not busy and T.is_carre(t):  # mirrored, along the sides, clear of the corners
            return T.carre_spread(t, k)
        if not busy:  # one in the middle of the front (u = 0), the rest evenly round
            return [(L * i / k + L / 2) % L - L / 2 for i in range(k)]
        slots = int(L / pitch + 1e-6)

        def gap(a, b):
            d = abs(a - b) % L
            return min(d, L - d)

        us = [-L / 2 + L / slots * i for i in range(slots)]
        if T.is_carre(t):  # not on a corner
            us = [s for s in us if abs(T.carre_clear(t, s) - s) < 1e-6]
        us = [s for s in us if all(gap(s, b) >= pitch * 0.75 for b in busy)]
        if len(us) <= n:
            return us
        return [us[round(i * len(us) / n)] for i in range(n)]

    def fits(self, fixtures: list[dict]) -> bool:
        if not fixtures:
            return True
        needs = [self.m.need(self, f) for f in fixtures]
        if sum(needs) > self.L + 1e-6:
            return False
        return len(self._spots(len(fixtures), max(needs))) == len(fixtures)

    def place(self, groups: list[list[dict]]) -> list[dict]:
        fixtures = [f for g in groups for f in g]
        if not fixtures:
            return []
        us = self._spots(len(fixtures), sum(self.m.need(self, f) for f in fixtures) / len(fixtures))
        for f, u in mirrored(fixtures[: len(us)], us, self.L):
            self.m.put(f, self.t, u, self.side)
        return fixtures[len(us) :]


class _Towers:
    """A tower, or two twins: one fixture on top (a short tower carries only that), more down its front face."""

    short, y = False, 0.0

    def __init__(self, m: _Mounter, towers: tuple, lowest: float, weight: float = 1.0):
        self.m, self.towers, self.lowest, self.weight = m, towers, lowest, weight
        self.even = len(towers) == 2
        self.z = towers[0]["z_m"]

    def _spots(self, t: dict) -> list[tuple[str, float]]:
        base, L = t["z_m"] - t["length_m"] / 2, t["length_m"]
        out = []
        top = base + L + T.TOWER_TOP
        if top >= self.lowest and top + 0.4 <= self.m.ceiling and not self.m.used.get((t["id"], "top")):
            out.append(("top", L))
        u = L - 0.6
        while base + u >= max(self.lowest, HEAD_MIN_M) - 1e-6:
            if all(abs(u - b) >= 0.6 for b, _ in self.m.used.get((t["id"], "front"), [])):
                out.append(("front", round(u, 3)))
            u -= TOWER_STEP_M
        return out

    def _each(self) -> int:
        return min(len(self._spots(t)) for t in self.towers)

    def size(self) -> float:
        return self._each() * len(self.towers) * SPACING["head"]

    def fits(self, fixtures: list[dict]) -> bool:
        if any(_housing(f) > TOWER_WIDE_M for f in fixtures) or (self.even and len(fixtures) % 2):
            return False
        return len(fixtures) <= self._each() * len(self.towers)

    def place(self, groups: list[list[dict]]) -> list[dict]:
        fixtures = [f for g in groups for f in g]
        spots = [self._spots(t) for t in self.towers]
        n = min(len(fixtures), self._each() * len(self.towers))
        for i, f in enumerate(fixtures[:n]):  # twins: a pair at the same height
            t = self.towers[i % len(self.towers)]
            side, u = spots[i % len(self.towers)][i // len(self.towers)]
            self.m.put(f, t, u, side)
        return fixtures[n:]


class _Mounter:
    def __init__(self, merged: dict, used: dict, standing: list[dict] | None = None):
        st = geometry.stage(merged)
        self.merged, self.st = merged, st
        self.W, self.used, self.out = float(st["width_m"]), used, {}
        self.deck = float(st.get("deck_m", 0.0) or 0.0)  # the stage's height: the rows on it stand that much higher
        self.ceiling = math.inf if st.get("outdoor") else float(st.get("ceiling_m") or math.inf)
        self.standing = standing or []  # fixtures already on the floor or on stands (that stay where they are)
        self.role, self.tight = "head", False
        self.wide: dict[str, float] = {}  # the housings of what was put on the floor
        trusses = merged.get("trusses", [])
        heads = sum(role(fxlib.get(f["fixture"])) == "head" for f in merged.get("fixtures", []))
        big = self.W >= 6 or heads >= 8
        flat = [t for t in trusses if not t.get("vertical")]
        self.walls = [t for t in flat if T.is_scaffold(t)]
        plain = [t for t in flat if not T.is_scaffold(t) and not T.is_closed(t)]
        self.groups: list[tuple] = twins(plain, self.W)  # straight trusses, twins together
        self.groups += [(r,) for t in self.walls for r in ledgers(t, merged, big)]
        self.loops = [t for t in flat if T.is_closed(t)]
        self.towers = twins([t for t in trusses if t.get("vertical")], self.W)
        self.any = bool(trusses)
        # the back of the stage: the wall behind it (a scaffold, the room's), else behind the rig
        rear = min([geometry._truss_rear(t) for t in trusses if t["y_m"] < T.OVER_CROWD_M] or [-1.5])
        if self.walls:
            front = max(t["y_m"] + T.scaffold_depth(t) / 2 for t in self.walls)
            self.back_y, self.par_y = front + 0.9, front + 0.4
        elif st.get("room_back_m") is not None:
            wall = -float(st["room_back_m"])
            self.back_y, self.par_y = max(rear - 0.6, wall + 0.5), max(rear - 1.1, wall + 0.25)
        else:
            self.back_y, self.par_y = rear - 0.6, rear - 1.1
        dj = geometry.dj_head(merged, [], heads)
        self.booth = (float(dj[1]) - 0.6, float(dj[1]) + 0.9 + 0.3)  # in depth, with room to walk round it

    # ------------------------------------------------------------ where things can go

    def need(self, line, f: dict) -> float:
        """What a fixture takes up along a bar (m): its housing and the room to the next one."""
        w = _housing(f)
        if self.tight:
            return max(MIN_SPACING[self.role], w + MIN_CLEAR[self.role])
        if self.role == "head" and line is not None and line.short:
            return max(SHORT_BAR[0], w + SHORT_BAR[1])
        if self.role == "par" and line is not None and not line.shared:  # a stand of pars: side by side
            return max(MIN_SPACING["par"], w + STAND_GAP)
        return max(SPACING[self.role], w + CLEAR[self.role])

    def put(self, f: dict, t: dict, u: float, side: str):
        spot = {"mount": "stand" if side == "top" else "hang"}
        T.place(spot, t, u, self.W, side)
        self.used[(t["id"], side)].append((u, _housing(f)))
        self.out[f["id"]] = {k: v for k, v in spot.items() if k != "id"}

    def _hall(self, y: float) -> bool:
        return y >= T.OVER_CROWD_M

    def _under(self, t: dict) -> str:
        return "under" if t["z_m"] >= LOW_TRUSS_M else "top"

    def overhead(self) -> list:
        """Every truss as a row for heads: the ones over the stage from the back to the front, then the ones over
        the crowd (they get less)."""
        rows: list = [_Bar(self, g, self._under(g[0])) for g in self.groups]
        rows += [_Loop(self, t, self._under(t)) for t in self.loops]
        for r in rows:
            if self._hall(r.y):
                r.weight = HALL_SHARE
        return sorted(rows, key=lambda r: (self._hall(r.y), r.y))

    def stage_rows(self, straight: bool = False) -> list[tuple]:
        """The trusses over the stage (all, when none is), twins together."""
        groups = list(self.groups) + ([] if straight else [(t,) for t in self.loops])
        over = [g for g in groups if sum(t["y_m"] for t in g) / len(g) < T.OVER_CROWD_M + 0.5]
        return over or groups

    # ------------------------------------------------------------ sharing fixtures over rows

    def share(
        self, groups: list[list[dict]], lines: list, back: bool = False, also: list | None = None, fill: bool = True
    ) -> list[list[dict]]:
        """Hang groups of fixtures (a model each) in these rows, every row filled as far as the others (by its
        length), and returns what is left. A model stays together in one row when it fits there; only a group too
        big for its row is shared out, in pairs, and never one fixture on its own. `fill`: what is left after that
        goes where there is room still, the emptiest row first. `back`: the rows take whole groups from the back
        of the list (the smallest), none in part. `also`: rows that are filled later, and get their share then."""
        queue = [list(g) for g in groups if g]
        on: list[list[list[dict]]] = [[] for _ in lines]

        def flat(i: int) -> list[dict]:
            return [f for o in on[i] for f in o]

        def odd_ok(i: int) -> bool:
            return not lines[i].even and not any(len(o) % 2 for o in on[i])

        for i, line in enumerate(lines):
            if not queue:
                break
            sizes = [ln.size() * ln.weight for ln in lines[i:] + list(also or [])]
            if sizes[0] <= 0:
                continue
            target = sum(self.need(line, f) for g in queue for f in g) * sizes[0] / sum(sizes)
            got = 0.0
            while queue:
                pick = None
                for g in reversed(queue) if back else queue[:1]:  # a whole group: most of it within the row's share
                    d, n = self.need(line, g[0]), len(g)
                    if got >= target - d / 2 or (n % 2 and not odd_ok(i)):
                        continue
                    within = got + n * d / 2 <= target if on[i] else n * d <= target + max(d, target / 4) + 1e-6
                    if within and line.fits(flat(i) + g):
                        pick = g
                        break
                if pick is not None:
                    on[i].append(list(pick))
                    got += sum(self.need(line, f) for f in pick)
                    queue.remove(pick)
                    continue
                if on[i] or back:  # only the first group in a row is shared out
                    break
                g = queue[0]
                d, n = self.need(line, g[0]), len(g)
                take = min(n, int((target - got) / d + 0.5))
                if n - take == 1:  # never one left over on its own
                    take = n if not line.even and line.fits(g) else take - 1
                if take % 2 and take < n:  # in pairs
                    take -= 1
                while take > 0 and not line.fits(g[:take]):
                    take -= 2 if take % 2 == 0 else 1
                if take > 0:
                    on[i].append(g[:take])
                    del g[:take]
                    if not g:
                        queue.pop(0)
                break
        while fill and queue:  # where there is room still: whole groups first, then pairs of them
            g = queue[0]
            n = len(g)
            home = None
            for take in [n] + list(range(n - 1 - (n - 1) % 2, 0, -2)):
                rows = [i for i, ln in enumerate(lines) if (take % 2 == 0 or odd_ok(i)) and ln.fits(flat(i) + g[:take])]
                if rows:  # the row that is the least full
                    home = min(rows, key=lambda i: sum(self.need(lines[i], f) for f in flat(i)) / lines[i].size())
                    break
            if home is None:
                break
            same = next((o for o in on[home] if o[0]["fixture"] == g[0]["fixture"]), None)
            if same is not None:
                same += g[:take]
            else:
                on[home].append(g[:take])
            del g[:take]
            if not g:
                queue.pop(0)
        for i, line in enumerate(lines):
            rest = line.place(on[i])
            if rest:
                queue.append(rest)
        return queue

    # ------------------------------------------------------------ the kinds of fixtures

    def lasers(self, fixtures: list[dict]):
        """On top of the back truss over the stage (the top ledger of a scaffold), in the middle; else high on the
        towers; else on stands at the back."""
        if not fixtures:
            return
        self.role = "laser"
        rows = self.stage_rows()
        high = sorted((g for g in rows if g[0]["z_m"] >= LOW_TRUSS_M), key=lambda g: g[0]["y_m"])
        top = next((g for g in high if g[0].get("scaffold")), None) or (high[0] if high else None)
        top = top or (min(rows, key=lambda g: g[0]["y_m"]) if rows else None)
        lines: list = []
        if top:
            share = 1.0 if top[0].get("gap") else 0.6  # (beside an LED wall: the whole of what is left)
            lines.append(_Loop(self, top[0], "top") if T.is_closed(top[0]) else _Bar(self, top, "top", share=share))
        lines += [_Towers(self, g, LASER_MIN_M) for g in self.towers]
        rest = self._all(_models(fixtures), lines)
        self.rows(rest, [-1.5], 2.2, "stand", "laser", 0.5)

    def _all(self, groups: list[list[dict]], lines: list) -> list[dict]:
        """As many as fit in the first row, the rest in the next: mirrored, a row of twins an even number."""
        left = [f for g in groups for f in g]
        for line in lines:
            n = len(left)
            while n > 0 and not line.fits(left[:n]):
                n -= 1
            if n:
                left = line.place(_by_model(left[:n])) + left[n:]
        return left

    def heads(self, heads: list[dict], bars: list[dict]):
        """Moving heads (and tilting bars, last): over the trusses and towers, the rest on the stage floor."""
        if not heads and not bars:
            return
        self.role = "head"
        groups = _models(heads, beams=True) + _models(bars)
        n = len(heads) + len(bars)
        floor: list[dict] = []
        if n >= FLOOR_FROM and heads:  # a big set: beams on the stage floor too (the narrowest model's, or a part)
            hold = int(n * FLOOR_SHARE) // 2 * 2
            k = len(groups[0]) if len(groups[0]) <= hold + 2 else hold
            floor, groups[0] = groups[0][:k], groups[0][k:]
            groups = [g for g in groups if g]
        before = (dict(self.out), {k: list(v) for k, v in self.used.items()})
        rest = floor + self._hang(groups)
        ys = [self.back_y] + ([-0.5] if self.back_y <= -1.2 else [])
        ys += [self.back_y + 0.8 * k for k in range(1, int((-1.3 - self.back_y) / 0.8) + 1)]  # more rows between
        if rest and len(rest) > sum(self._rows_room(rest, ys, 0.3, 0.85)):  # too many for the floor: closer up there
            loose = (self.out, self.used)
            self.out, self.used, self.tight = before[0], defaultdict(list, before[1]), True
            closer = floor + self._hang(groups)
            self.tight = False
            if len(closer) < len(rest):
                rest = closer
            else:
                self.out, self.used = loose
        if not rest:
            return
        if not self.any and len(rest) <= 4:
            self.rows(rest, [-1.2], 1.8, "stand", "head", 0.8)  # an empty room: tripods
            return
        self.rows(rest, ys, 0.3, "floor", "head", 0.85, step=-0.8 if len(ys) == 1 else 0.0)

    def _hang(self, groups: list[list[dict]]) -> list[dict]:
        """The heads on the structure: the small groups (pairs) on the towers, the big ones under the trusses.
        Returns the ones that are left."""
        over = self.overhead()
        towers = [_Towers(self, g, HEAD_MIN_M) for g in self.towers]
        if over:
            groups = self.share(groups, towers, back=True, also=over, fill=False)
        groups = self.share(groups, over + towers)
        return [f for g in groups for f in g]

    def front(self, strobes: list[dict], blinders: list[dict]):
        """On the front face of the front truss over the stage: strobes in the middle, blinders spread over the
        rest of it. What it has no room for: strobes on the floor at the front, blinders on stands."""
        rows = self.stage_rows(straight=True) or self.stage_rows()
        rows = sorted(rows, key=lambda g: -sum(t["y_m"] for t in g) / len(g))

        def line(g, share):
            return _Loop(self, g[0], "front") if T.is_closed(g[0]) else _Bar(self, g, "front", share=share)

        self.role = "strobe"
        rest = self._all(_models(strobes), [line(g, 0.5 if len(g) == 1 else 1.0) for g in rows[:1]])
        self.rows(rest, [-0.3], 0.25, "floor", "strobe", 0.3)
        self.role = "blinder"
        rest = self._all(_models(blinders), [line(g, 1.0) for g in rows[:1]])
        self.rows(rest, [-0.2], 0.9, "stand", "blinder", 0.76)

    def pars(self, fixtures: list[dict]):
        """On the light stands that have room (between their heads); else on the floor at the back, uplighting."""
        self.role = "par"
        stands = [_Bar(self, g, self._under(g[0])) for g in self.groups if T.is_stand(g[0])]
        for line in stands:
            line.shared = line.busy()
        rest = [f for g in self.share(_models(fixtures), stands) for f in g]
        self.rows(rest, [self.par_y], FLOOR_PAR_M, "floor", "par", 0.8, step=0.5)

    def walls_near(self) -> bool:
        return geometry.room_side(self.st) <= 1.0

    def uplighters(self, bars: list[dict]):
        """Tilting bars on the floor along the side walls of the room, in front of the stage: the same number
        left and right, an odd one out against the far wall."""
        side = geometry.room_side(self.st)
        depth = float(self.st.get("room_depth_m") or 6.0)
        n = len(bars) // 2
        z = round(FLOOR_PAR_M, 2)
        far = max(1.0, min(depth - 0.5, 0.5 + WALL_STEP_M * n))
        for k in range(n):
            y = round(0.5 + (far - 0.5) * (k + 0.5) / n, 2)
            left, right = -side + WALL_OFF_M, self.W + side - WALL_OFF_M
            for f, x, rot in ((bars[2 * k], left, 270), (bars[2 * k + 1], right, 90)):
                self.out[f["id"]] = {"x": round(x / self.W, 4), "y_m": y, "z_m": z, "mount": "floor", "rot_deg": rot}
        if len(bars) % 2:
            self.out[bars[-1]["id"]] = {"x": 0.5, "y_m": round(depth - WALL_OFF_M, 2), "z_m": z, "mount": "floor"}

    def smoke(self, fixtures: list[dict]):
        """Smoke machines: on the floor at the sides of the stage, near the back, out of the way of the rows."""
        z = round(FLOOR_PAR_M + self.deck, 2)
        for k, f in enumerate(fixtures):
            x = min(0.3, self.W * 0.05)
            x = x if k % 2 == 0 else self.W - x
            y = round(min(-0.75, self.back_y + 0.45 + 0.9 * (k // 2)), 2)
            self.out[f["id"]] = {"x": round(x / self.W, 4), "y_m": y, "z_m": z, "mount": "floor"}

    # ------------------------------------------------------------ rows on the floor

    def rows(
        self, fixtures: list[dict], ys: list[float], z: float, mount: str, kind: str, span: float, step: float = 0.0
    ):
        """Symmetric rows across the stage (the middle `span` of its width), at these depths (and on from the last,
        `step` further each time): as many rows as it takes, every model mirrored round the middle, clear of the
        DJ's booth and of what stands there already."""
        if not fixtures:
            return
        self.role = kind
        lo, hi = self.W * (1 - span) / 2, self.W * (1 + span) / 2
        order = [f for g in _models(fixtures) for f in g]
        ys = list(ys) + ([ys[-1] + step * k for k in range(1, 12)] if step else [])
        room = self._rows_room(order, ys, z, span)
        n = next((i + 1 for i in range(len(ys)) if sum(room[: i + 1]) >= len(order)), len(ys))
        room = [max(r, 1) for r in room[:n]]
        sizes = [len(order) * r // sum(room) for r in room]  # each row as full as the others
        for i in sorted(range(n), key=lambda i: -(len(order) * room[i] % sum(room)))[: len(order) - sum(sizes)]:
            sizes[i] += 1
        ends, at = [], 0
        for g in _models(fixtures):
            at += len(g)
            ends.append(at)
        for i in range(n - 1):
            cut = sum(sizes[: i + 1])
            near = min(ends, key=lambda e: abs(e - cut))  # a model stays in one row, when that is about as full
            move = near - cut
            if move and abs(move) <= 2 and sizes[i] + move <= room[i] and sizes[i + 1] - move >= 1:
                sizes[i], sizes[i + 1] = sizes[i] + move, sizes[i + 1] - move
            elif sizes[i] % 2:  # pairs stay in one row
                move = 1 if sizes[i] < room[i] else -1
                sizes[i], sizes[i + 1] = sizes[i] + move, sizes[i + 1] - move
        for y, size in zip(ys, sizes):
            self._row(order[:size], y, z + self.deck, mount, lo, hi)
            order = order[size:]

    def _blocks(self, y: float, z: float, lo: float, new: float | None = None) -> list[tuple]:
        """What a row on the floor stays clear of (for fixtures `new` wide): what stands there, the DJ's booth."""
        there = self.standing + [{**p, "w": self.wide.get(i, 0.3)} for i, p in self.out.items() if not p.get("truss")]
        blocks = [_block(p["x"] * self.W, p.get("w", 0.3), new) for p in there
                  if abs(p["y_m"] - y) <= 0.4 and abs(p["z_m"] - z) <= 0.6]  # fmt: skip
        mid = self.W / 2
        if self.booth[0] <= y <= self.booth[1] and lo < mid - BOOTH_HALF_M - 0.3:
            blocks.append((mid - BOOTH_HALF_M, mid + BOOTH_HALF_M, 0.5))
        return blocks

    def _rows_room(self, fixtures: list[dict], ys: list[float], z: float, span: float) -> list[int]:
        """How many of these each row on the floor takes, at their ease."""
        lo, hi = self.W * (1 - span) / 2, self.W * (1 + span) / 2
        pitch = max(self.need(None, f) for f in fixtures)
        new = min(_housing(f) for f in fixtures)
        rows = [_stretches(lo, hi, self._blocks(y, z + self.deck, lo, new), (END, END)) for y in ys]
        return [sum(_room(s, pitch) for s in row) for row in rows]

    def _row(self, fixtures: list[dict], y: float, z: float, mount: str, lo: float, hi: float):
        if not fixtures:
            return
        row = _mirrored(_by_model(fixtures))
        k = len(row)
        widths = [_housing(f) for f in row]
        blocks = self._blocks(y, z, lo, min(widths))
        needs = [self.need(None, f) for f in row]
        self.wide.update({f["id"]: w for f, w in zip(row, widths)})
        xs = None
        if not blocks:
            xs = justify(widths, lo, hi, min(n - w for n, w in zip(needs, widths))) or justify(widths, lo, hi, 0.02)
        else:
            pitch = max(needs)
            while pitch >= 0.25:  # closer together, as long as they stay clear of what is there
                xs = spread(k, lo, hi, pitch, blocks)
                if len(xs) == k:
                    break
                xs, pitch = None, pitch * 0.8
        if xs is None:  # no room at all: evenly, whatever stands there
            xs = [lo + (hi - lo) * (i + 0.5) / k for i in range(k)]
        for f, x in zip(row, xs):
            self.out[f["id"]] = {"x": round(x / self.W, 4), "y_m": round(y, 2), "z_m": round(z, 2), "mount": mount}


def _by_model(fixtures: list[dict]) -> list[list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for f in fixtures:
        groups[f["fixture"]].append(f)
    return list(groups.values())
