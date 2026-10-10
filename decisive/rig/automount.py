"""Auto-mount: hang a set's fixtures on a rig the way a lighting tech would, as a starting point.

- moving heads under the overhead trusses (front first, spread evenly), then on the towers, then on stands;
- lasers on top of the back truss (high, in the middle), else on the towers;
- strobes and blinders on the front face of the front truss: strobes in the middle, blinders at the ends;
- bars on the floor along the front edge of the stage, pars on the floor at the back (uplighting).

Fixtures of the same model stay together and every row is symmetric. Fixtures already mounted keep their
place and their room on a truss is left free.
"""

from __future__ import annotations

from collections import defaultdict

from decisive.library import fixtures as fxlib
from decisive.rig import trusses as T

SPACING = {"head": 0.6, "laser": 0.6, "strobe": 0.5, "blinder": 0.6, "bar": 1.1, "par": 0.5}
MIN_SPACING = {"head": 0.45, "laser": 0.45, "strobe": 0.4, "blinder": 0.45, "bar": 0.9, "par": 0.35}
USE = 0.9  # share of a truss's length fixtures are spread over
LOW_TRUSS_M = 2.2  # a truss lower than this (a riser at the back) carries fixtures on top, not hanging under
LASER_MIN_M = 2.0  # a laser on a tower: at least this high
HEAD_MIN_M = 1.2  # a head on a tower: at least this high (more go on stands)
TOWER_SHARE = 0.2  # share of the heads on the towers, when there are trusses too
ROLES = ("head", "laser", "strobe", "blinder", "bar", "par")


def role(defn: dict) -> str:
    kind = defn.get("kind", "par")
    if kind in ("moving_head", "moving_bar"):
        return "head"
    if kind == "par_bar":
        return "bar"
    return kind if kind in ROLES else "par"


def automount(merged: dict, ids: list[str] | None = None) -> dict[str, dict]:
    """Placements (fixture id → position fields) for the fixtures `ids` (all, if None) of a set on a rig."""
    W = merged.get("stage", {}).get("width_m", 6.0)
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
    m = _Mounter(W, used)

    lasers = by_role["laser"]  # first: they need the high spots
    if lasers:
        high = [t for t in horiz if t["z_m"] >= LOW_TRUSS_M]
        back = [(high[-1] if high else horiz[-1], "top")] if horiz else []
        rest = m.trusses(lasers, back, "laser", share=0.6)
        rest = m.towers(rest, towers, lowest=LASER_MIN_M)
        m.row(rest, y=-1.5, z=2.2, mount="stand", span=0.5)
    heads = by_role["head"]
    if heads:
        on_towers = []
        if towers and horiz and len(heads) >= 8:  # a share for the towers, the same on every tower
            k = round(len(heads) * TOWER_SHARE / len(towers)) * len(towers)
            heads, on_towers = heads[: len(heads) - k], heads[len(heads) - k :]
        rest = m.trusses(heads, [(t, "under" if t["z_m"] >= LOW_TRUSS_M else "top") for t in horiz], "head")
        rest = m.towers(on_towers + rest, towers, lowest=HEAD_MIN_M)
        m.row(rest, y=-1.2, z=1.8, mount="stand", span=0.8)  # tripods behind the booth
    front = [(horiz[0], "front")] if horiz else []
    m.row(m.trusses(by_role["strobe"], front, "strobe", share=0.4), y=-0.3, z=0.25, mount="floor", span=0.3)
    m.row(m.ends(by_role["blinder"], front[0][0] if front else None), y=-0.2, z=0.9, mount="stand", span=0.76)
    m.row(by_role["bar"], y=-0.3, z=0.15, mount="floor", span=0.8)
    back_y = min([t["y_m"] for t in horiz] or [-1.5]) - 0.6
    m.row(by_role["par"], y=back_y, z=0.15, mount="floor", span=0.8)
    return m.out


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
    def __init__(self, width: float, used: dict):
        self.W, self.used, self.out = width, used, {}

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
            k = min(n, int(span / MIN_SPACING[kind]) + 1)
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
        """A symmetric row across the stage (the middle `span` of its width)."""
        n = len(fixtures)
        for i, f in enumerate(fixtures):
            x = 0.5 if n == 1 else 0.5 - span / 2 + span * i / (n - 1)
            self.out[f["id"]] = {"x": round(x, 4), "y_m": round(y, 2), "z_m": round(z, 2), "mount": mount}
