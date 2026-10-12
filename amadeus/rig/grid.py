"""Test rigs: many fixtures hung on a truss grid, to see how the show scales (e.g. 60 MAC Encores).

The rig sends Art-Net to 127.0.0.1 only (the visualiser), so it never drives the real lights.
"""

from __future__ import annotations

from amadeus.library import catalog
from amadeus.library import fixtures as fxlib


def grid_rig(
    model: str,
    count: int,
    rows: int = 3,
    width: float = 16.0,
    height: float = 7.0,
    depth: float = 6.0,
    mode: str | None = None,
    rise: float = 0.5,
) -> dict:
    """`count` fixtures spread over `rows` trusses, `width` m wide, the front truss at `height` m and
    1 m behind the stage edge, the others up to `depth` m further back and `rise` m higher each."""
    key = catalog.add(model)  # a QLC+/OFL key is converted into fixtures/ first
    defn = fxlib.get(key)
    mode = mode or fxlib.default_mode(defn)
    footprint = len(fxlib.channels(defn, mode))
    rows = max(1, min(rows, count))
    margin = 1.0
    stage_w = width + 2 * margin
    base = key.split("/")[-1].split("-")[0][:5] or "fx"
    per_row = [count // rows + (1 if r < count % rows else 0) for r in range(rows)]
    fixtures, universe, address = [], 1, 1
    for r, n in enumerate(per_row):
        y = -1.0 - (depth * r / (rows - 1) if rows > 1 else 0.0)
        z = height + rise * r
        for i in range(n):
            if address + footprint - 1 > 512:
                universe, address = universe + 1, 1
            # even rows edge to edge, odd rows in between (staggered), so the beams don't line up
            x_m = margin + (width / 2 if n == 1 else width * i / (n - 1) if r % 2 == 0 else width * (i + 0.5) / n)
            fixtures.append(
                {
                    "fixture": key,
                    "mode": mode,
                    "universe": universe,
                    "address": address,
                    "id": f"{base}{len(fixtures) + 1}",
                    "x": round(x_m / stage_w, 4),
                    "y_m": round(y, 2),
                    "z_m": round(z, 2),
                    "mount": "hang" if fxlib.is_moving(defn) else "stand",
                }
            )
            address += footprint
    return {
        "description": f"{count}× {defn['manufacturer']} {defn['model']} on {rows} trusses "
        f"({width:g} m wide, {height:g}–{height + rise * (rows - 1):g} m high); visualiser only",
        "artnet": {"ip": "127.0.0.1", "port": 6454, "fps": 40},
        "safety": {"max_flash_hz": 3, "master": 1.0, "allow_fast_strobe": False},
        "fixtures": fixtures,
        "stage": {
            "width_m": round(stage_w, 2),
            "ceiling_m": round(height + rise * (rows - 1) + 3, 1),
            "room_depth_m": 25,
            "eye_safety": False,
        },
        "director": _current_director(),
    }


def _current_director() -> str:
    import json

    from amadeus.rig import store

    try:
        return store.sets.load().get("director", "rules")
    except (OSError, json.JSONDecodeError):
        return "rules"


# Concert layout: share of the heads per zone (audience scanning: most beams go into the crowd)
CONCERT_ZONES = {"top": 0.40, "back": 0.20, "front": 0.17, "towers": 0.23}


def concert_rig(
    model: str,
    count: int,
    width: float = 16.0,
    height: float = 7.0,
    depth: float = 6.0,
    mode: str | None = None,
    lasers: int = 0,
    zones: dict | None = None,
    blinders: int = 0,
) -> dict:
    """A festival/club stage like the usual DJ show: heads hung on two overhead trusses, a row standing on
    the stage floor at the back (shooting over the DJ into the crowd), a low row on the front edge
    (beams up and over the crowd) and a stack on a truss tower left and right.

    Ids say where a head is (top1, back1, front1, towerL1, towerR1): handy to see and to group later."""
    key = catalog.add(model)
    defn = fxlib.get(key)
    mode = mode or fxlib.default_mode(defn)
    footprint = len(fxlib.channels(defn, mode))
    margin = 1.0
    stage_w = width + 2 * margin
    if zones:  # exact numbers per zone: top, back, front, towers (both towers together)
        n = {z: int(zones.get(z, 0)) for z in CONCERT_ZONES}
        count = sum(n.values())
    else:
        n = {z: int(round(count * share)) for z, share in CONCERT_ZONES.items()}
        n["towers"] -= n["towers"] % 2  # same number left and right
        n["top"] += count - sum(n.values())  # rounding goes to the overhead truss
    top_front = n["top"] if zones and n["top"] <= 12 else (n["top"] + 1) // 2  # up to 12: one truss
    head = fxlib.is_moving(defn)
    fixtures = []

    def add(fid, x_m, y, z, mount):
        fixtures.append(
            {
                "fixture": key,
                "mode": mode,
                "id": fid,
                "x": round(x_m / stage_w, 4),
                "y_m": round(y, 2),
                "z_m": round(z, 2),
                "mount": mount if head else "stand",
            }
        )

    def spread(k, lo, hi, stagger=False):
        if k == 1:
            return [(lo + hi) / 2]
        if stagger:  # in between the other row's positions
            return [lo + (hi - lo) * (i + 0.5) / k for i in range(k)]
        return [lo + (hi - lo) * i / (k - 1) for i in range(k)]

    for i, x in enumerate(spread(top_front, margin + 0.5, margin + width - 0.5)):
        add(f"top{i + 1}", x, -1.5, height, "hang")
    for i, x in enumerate(spread(n["top"] - top_front, margin + 0.5, margin + width - 0.5, stagger=True)):
        add(f"top{top_front + i + 1}", x, -1.5 - depth * 0.5, height + 0.5, "hang")
    for i, x in enumerate(spread(n["back"], margin + 1.5, margin + width - 1.5)):  # on a riser at the back
        add(f"back{i + 1}", x, -1.5 - depth, 0.6, "floor")
    for i, x in enumerate(spread(n["front"], margin + 2.0, margin + width - 2.0)):  # front edge, low
        add(f"front{i + 1}", x, -0.3, 0.35, "floor")
    per_tower = n["towers"] // 2
    for side, x in (("L", 0.3), ("R", stage_w - 0.3)):  # vertical truss towers at the corners
        for i, z in enumerate(spread(per_tower, 1.6, height - 0.8)):
            add(f"tower{side}{i + 1}", x, -1.0, z, "stand")

    universe, address = 1, 1
    for f in fixtures:
        if address + footprint - 1 > 512:
            universe, address = universe + 1, 1
        f["universe"], f["address"] = universe, address
        address += footprint
    rig = {
        "description": f"{count}× {defn['manufacturer']} {defn['model']}, concert stage {width:g} m: "
        f"{n['top']} overhead, {n['back']} at the back, {n['front']} on the front edge, "
        f"{per_tower} per side tower; visualiser only",
        "artnet": {"ip": "127.0.0.1", "port": 6454, "fps": 40},
        "safety": {"max_flash_hz": 3, "master": 1.0, "allow_fast_strobe": False},
        "fixtures": fixtures,
        "stage": {
            "width_m": round(stage_w, 2),
            "ceiling_m": round(height + 3.5, 1),
            "room_depth_m": 25,
            "eye_safety": False,
        },
        "director": _current_director(),
    }
    if lasers:
        add_lasers(rig, lasers)
        rig["description"] += f"; {lasers} lasers"
    if blinders:
        add_blinders(rig, blinders)
        rig["description"] += f"; {blinders} blinders"
    return rig


LASER_MODEL = "laserworld/cs-1000rgb-mk3"


def add_lasers(rig: dict, count: int = 10, model: str = LASER_MODEL) -> list[dict]:
    """Lasers for a concert stage: 40% on the front overhead truss, 40% at the back of the stage, the rest on
    top of the side towers. Patched after the last used channel. Beams always stay above the audience."""
    key = catalog.add(model)
    defn = fxlib.get(key)
    mode = fxlib.default_mode(defn)
    footprint = len(fxlib.channels(defn, mode))
    st = rig.get("stage", {})
    stage_w = st.get("width_m", 18.0)
    heads = [f for f in rig["fixtures"] if f.get("mount") == "hang"]
    top_z = max([f.get("z_m", 7.0) for f in heads] or [7.0])
    back_y = min([f.get("y_m", -7.5) for f in rig["fixtures"]] or [-7.5])
    n_top = round(count * 0.4)
    n_back = round(count * 0.4)
    n_tower = count - n_top - n_back
    spots = []
    for i in range(n_top):
        spots.append(("ltop", (2.5 + (stage_w - 5) * (i + 0.5) / n_top) / stage_w, -1.5, top_z - 0.4, "hang"))
    for i in range(n_back):
        spots.append(("lback", (3.0 + (stage_w - 6) * (i + 0.5) / n_back) / stage_w, back_y, 0.9, "stand"))
    for i in range(n_tower):
        spots.append(
            ("ltower", (0.3 if i % 2 == 0 else stage_w - 0.3) / stage_w, -1.0, top_z - 0.3 + 0.4 * (i // 2), "stand")
        )
    used: dict[int, int] = {}
    for f in rig["fixtures"]:
        end = f["address"] + fxlib.footprint(f)
        used[f["universe"]] = max(used.get(f["universe"], 1), end)
    universe = max(used) if used else 1
    address = used.get(universe, 1)
    new = []
    counts: dict[str, int] = {}
    for prefix, x, y, z, mount in spots:
        if address + footprint - 1 > 512:
            universe, address = universe + 1, 1
        counts[prefix] = counts.get(prefix, 0) + 1
        new.append(
            {
                "fixture": key,
                "mode": mode,
                "universe": universe,
                "address": address,
                "id": f"{prefix}{counts[prefix]}",
                "x": round(x, 4),
                "y_m": round(y, 2),
                "z_m": round(z, 2),
                "mount": mount,
            }
        )
        address += footprint
    rig["fixtures"] += new
    return new


BLINDER_MODEL = "beamz/sb200-stage-blinder"


def add_blinders(rig: dict, count: int = 2, model: str = BLINDER_MODEL) -> list[dict]:
    """Stage blinders on the front edge of the stage, spread out (2: left and right), aimed at the audience."""
    key = catalog.add(model)
    defn = fxlib.get(key)
    mode = fxlib.default_mode(defn)
    footprint = len(fxlib.channels(defn, mode))
    used: dict[int, int] = {}
    for f in rig["fixtures"]:
        used[f["universe"]] = max(used.get(f["universe"], 1), f["address"] + fxlib.footprint(f))
    universe = max(used) if used else 1
    address = used.get(universe, 1)
    new = []
    for i in range(count):
        if address + footprint - 1 > 512:
            universe, address = universe + 1, 1
        x = 0.12 + 0.76 * (i / (count - 1) if count > 1 else 0.5)
        new.append(
            {
                "fixture": key,
                "mode": mode,
                "universe": universe,
                "address": address,
                "id": f"blinder{i + 1}",
                "x": round(x, 4),
                "y_m": -0.2,
                "z_m": 0.9,
                "mount": "stand",
            }
        )
        address += footprint
    rig["fixtures"] += new
    return new
