"""Exact fixture positions from a 3D scan of the setup (e.g. Niantic Scaniverse, exported as PLY).

Scan the setup while the setup page lights every fixture in its own colour (as for the setup photo):
the lit lenses/LEDs end up as coloured points. Phone scans are in real metres with gravity along one
axis, so from the cloud we get:

- the floor (height 0) and which way is up,
- each fixture: the 3D centre of its colour cluster,
- the stage frame: x along the line of fixtures (left → right as the audience sees it), y towards the
  audience (the side away from the wall behind the fixtures; can be flipped), z up,
- the ceiling height and how deep the room is in front of the fixtures.

Reads binary and ASCII PLY: plain point clouds (x y z red green blue) and Gaussian splats (colour from
f_dc_0..2, opacity filter).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from decisive.library import fixtures as fxlib
from decisive.rig import geometry

PLY_TYPES = {
    "char": "i1",
    "int8": "i1",
    "uchar": "u1",
    "uint8": "u1",
    "short": "i2",
    "int16": "i2",
    "ushort": "u2",
    "uint16": "u2",
    "int": "i4",
    "int32": "i4",
    "uint": "u4",
    "uint32": "u4",
    "float": "f4",
    "float32": "f4",
    "double": "f8",
    "float64": "f8",
}
SH_C0 = 0.28209479177387814
MAX_POINTS = 3_000_000


# ------------------------------------------------------------------ reading


def read_ply(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """→ (xyz float32 N×3, rgb float32 N×3 in 0..1). Only the vertex element is read."""
    with open(path, "rb") as f:
        header = b""
        while not header.endswith(b"end_header\n"):
            line = f.readline()
            if not line:
                raise ValueError("not a PLY file (no end_header)")
            header += line.replace(b"\r\n", b"\n")
        text = header.decode("ascii", "replace")
        if not text.startswith("ply"):
            raise ValueError("not a PLY file")
        fmt = re.search(r"^format (\S+)", text, re.M).group(1)
        elements, cur = [], None
        for line in text.splitlines():
            parts = line.split()
            if parts[:1] == ["element"]:
                cur = {"name": parts[1], "count": int(parts[2]), "props": []}
                elements.append(cur)
            elif parts[:1] == ["property"] and cur is not None:
                if parts[1] == "list":
                    cur["props"].append((parts[4], None))  # lists (faces) are not read
                else:
                    cur["props"].append((parts[2], PLY_TYPES[parts[1]]))
        vertex = next(e for e in elements if e["name"] == "vertex")
        if elements[0] is not vertex:
            raise ValueError("PLY with elements before the vertices is not supported")
        names = [n for n, _ in vertex["props"]]
        if fmt == "ascii":
            data = np.loadtxt(f, max_rows=vertex["count"], usecols=range(len(names)))
            col = {n: data[:, i] for i, n in enumerate(names)}
        else:
            if any(t is None for _, t in vertex["props"]):
                raise ValueError("list properties on vertices are not supported")
            end = "<" if fmt == "binary_little_endian" else ">"
            dtype = np.dtype([(n, end + t) for n, t in vertex["props"]])
            arr = np.fromfile(f, dtype=dtype, count=vertex["count"])
            col = {n: arr[n] for n in names}
    xyz = np.stack([col["x"], col["y"], col["z"]], axis=1).astype(np.float32)
    if "red" in col:
        rgb = np.stack([col["red"], col["green"], col["blue"]], axis=1).astype(np.float32)
        if rgb.max() > 1.0:
            rgb /= 255.0 if rgb.max() <= 255 else 65535.0
    elif "f_dc_0" in col:  # Gaussian splat: base colour from the 0th spherical harmonic
        rgb = np.clip(0.5 + SH_C0 * np.stack([col["f_dc_0"], col["f_dc_1"], col["f_dc_2"]], axis=1), 0, 1)
        rgb = rgb.astype(np.float32)
        if "opacity" in col:  # drop nearly transparent splats (floaters)
            keep = 1 / (1 + np.exp(-col["opacity"])) > 0.3
            xyz, rgb = xyz[keep], rgb[keep]
    else:
        raise ValueError("the PLY has no colours (red/green/blue or f_dc_*): export with colour")
    ok = np.isfinite(xyz).all(axis=1)
    xyz, rgb = xyz[ok], rgb[ok]
    if len(xyz) > MAX_POINTS:
        idx = np.random.default_rng(0).choice(len(xyz), MAX_POINTS, replace=False)
        xyz, rgb = xyz[idx], rgb[idx]
    return xyz, rgb


# ------------------------------------------------------------------ geometry helpers


def find_up(xyz: np.ndarray) -> tuple[np.ndarray, float]:
    """Gravity axis and floor height. Phone scans have gravity along one axis (+y for ARKit; some
    exports convert to +z): the floor is the densest flat slab at one end of that axis."""
    best = None
    for axis in range(3):
        v = xyz[:, axis]
        for sign in (1, -1):
            h = v * sign
            lo = np.percentile(h, 1)
            slab = np.count_nonzero(np.abs(h - lo) < 0.04) / len(h)
            score = slab + (0.02 if axis == 1 and sign == 1 else 0)  # tie-break: ARKit y-up
            if best is None or score > best[0]:
                best = (score, axis, sign, lo)
    _, axis, sign, lo = best
    up = np.zeros(3)
    up[axis] = sign
    # refine the floor height: median of the slab
    h = xyz @ up
    floor = float(np.median(h[np.abs(h - lo) < 0.04]))
    return up, floor


def _hsv(rgb: np.ndarray):
    mx, mn = rgb.max(axis=1), rgb.min(axis=1)
    d = np.maximum(mx - mn, 1e-6)
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) * 60
    s = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return h, s, mx


def _components(pts: np.ndarray, voxel: float = 0.06) -> list[np.ndarray]:
    """Connected groups of points (26-neighbour voxels), as index arrays, largest first."""
    if len(pts) == 0:
        return []
    keys = np.floor(pts / voxel).astype(np.int64)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.ravel()
    lookup = {tuple(k): i for i, k in enumerate(uniq)}
    parent = list(range(len(uniq)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1) if (dx, dy, dz) > (0, 0, 0)]
    for i, k in enumerate(uniq):
        for o in offsets:
            j = lookup.get((k[0] + o[0], k[1] + o[1], k[2] + o[2]))
            if j is not None:
                a, b = root(i), root(j)
                if a != b:
                    parent[a] = b
    roots = np.array([root(i) for i in range(len(uniq))])[inv]
    groups = [np.flatnonzero(roots == r) for r in np.unique(roots)]
    return sorted(groups, key=len, reverse=True)


def big_planes(xyz: np.ndarray, max_planes: int = 5, min_share: float = 0.03) -> list[tuple[np.ndarray, float]]:
    """The room's large flat surfaces (floor, walls, ceiling, a table top) by RANSAC: (normal, offset)."""
    rng = np.random.default_rng(0)
    pts = xyz[rng.choice(len(xyz), min(len(xyz), 60000), replace=False)]
    need = min_share * len(pts)
    planes = []
    for _ in range(max_planes):
        if len(pts) < 500:
            break
        best = (0, None)
        for _ in range(250):
            a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
            n = np.cross(b - a, c - a)
            norm = np.linalg.norm(n)
            if norm < 1e-9:
                continue
            n /= norm
            inl = np.count_nonzero(np.abs((pts - a) @ n) < 0.02)
            if inl > best[0]:
                best = (inl, (n, float(a @ n)))
        if best[1] is None or best[0] < need:
            break
        n, d = best[1]
        on = np.abs(pts @ n - d) < 0.02
        planes.append((n, d))
        pts = pts[~on]
    return planes


def _on_surface(p: np.ndarray, planes) -> bool:
    """A coloured cluster lying on one of the room's big surfaces is light spilling on a wall/floor."""
    return any(np.mean(np.abs(p @ n - d) < 0.03) > 0.7 for n, d in planes)


def find_fixture(xyz: np.ndarray, rgb: np.ndarray, hue: float, size_m: float | None, planes=()) -> dict | None:
    """The lit fixture of one colour: compact clusters of bright, saturated points of that hue that are
    not light spilling on a wall or the floor. Clusters close together (the LEDs of one bar) are combined."""
    h, s, v = _hsv(rgb)
    dh = np.minimum(np.abs(h - hue), 360 - np.abs(h - hue))
    sel = np.flatnonzero((dh < 25) & (s > 0.45) & (v > 0.45))
    if len(sel) < 8:
        return None
    pts, strength = xyz[sel], (s * v)[sel]
    size = size_m or 0.4
    clusters = []
    for g in _components(pts)[:30]:
        if len(g) < 5:
            continue
        p = pts[g]
        extent = float(np.linalg.norm(np.percentile(p, 95, axis=0) - np.percentile(p, 5, axis=0)))
        spill = _on_surface(p, planes)
        w = strength[g]
        score = len(g) * float(w.mean()) * (1.0 if extent <= max(0.5, size * 1.5) else 0.15) * (0.03 if spill else 1.0)
        clusters.append(
            {"score": score, "centre": (p * w[:, None]).sum(0) / w.sum(), "n": len(g), "extent": extent, "spill": spill}
        )
    if not clusters:
        return None
    clusters.sort(key=lambda c: (c["spill"], -c["score"]))  # any real fixture cluster beats light on a wall
    best = clusters[0]
    group = [
        c
        for c in clusters
        if not c["spill"]
        and c["extent"] <= max(0.5, size * 1.5)
        and np.linalg.norm(c["centre"] - best["centre"]) <= size
    ] or [best]
    if best not in group:
        group = [best]
    n = np.array([c["n"] for c in group], float)
    centre = (np.array([c["centre"] for c in group]) * n[:, None]).sum(0) / n.sum()
    span = float(max((np.linalg.norm(a["centre"] - b["centre"]) for a in group for b in group), default=0.0))
    return {
        "centre": centre.astype(float),
        "extent_m": round(float(max(best["extent"], span)), 3),
        "points": int(n.sum()),
        "clusters": len(group),
        "spill_only": bool(best["spill"]),
    }


# ------------------------------------------------------------------ analysis


def analyse(path: Path, rig: dict, lit: list[dict], flip: bool = False, moves: dict | None = None) -> dict:
    """Find the lit fixtures in the scan and express everything in stage coordinates (metres).

    `lit`: the colour per fixture that was on during the scan (placement.assignments).
    `flip`: the audience is on the other side of the fixture line. `moves`: fixture → [x_m, y_m] set
    by hand in the top-down view (stage coordinates)."""
    xyz, rgb = read_ply(path)
    up, floor = find_up(xyz)
    planes = big_planes(xyz)
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    found = {}
    for a in lit:
        size = fxlib.get(fixtures[a["fixture"]]["fixture"]).get("physical", {}).get("size_mm")
        r = find_fixture(xyz, rgb, a["hue"], size[0] / 1000 if size else None, planes)
        if r:
            found[a["fixture"]] = r

    # Horizontal frame: e1, e2 span the floor plane.
    tmp = np.array([1.0, 0, 0]) if abs(up[0]) < 0.9 else np.array([0, 0, 1.0])
    e1 = np.cross(up, tmp)
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(up, e1)
    flat = lambda p: np.array([p @ e1, p @ e2])
    centres = {k: flat(v["centre"]) for k, v in found.items()}

    # Stage x axis: along the line of fixtures (principal direction), or along the nearest wall.
    if len(centres) >= 2:
        P = np.array(list(centres.values()))
        _, _, vt = np.linalg.svd(P - P.mean(0))
        ax = vt[0]
    else:
        ax = np.array([1.0, 0.0])
    normal = np.array([-ax[1], ax[0]])
    origin = np.array(list(centres.values())).mean(0) if centres else flat(xyz.mean(0))

    # Audience side: the side of the fixture line with more open space (the wall is behind them).
    pts2 = np.stack([xyz @ e1, xyz @ e2], axis=1)
    height = xyz @ up - floor
    body = (height > 0.3) & (height < 2.0)  # walls/furniture, not floor or ceiling
    d = (pts2[body] - origin) @ normal
    along = np.abs((pts2[body] - origin) @ ax)
    span = float(np.ptp([c @ ax for c in centres.values()])) if len(centres) >= 2 else 1.0
    near = along < span / 2 + 1.0
    front = np.count_nonzero((d > 0.15) & (d < 1.2) & near)
    back = np.count_nonzero((d < -0.15) & (d > -1.2) & near)
    side = 1.0 if front < back else -1.0  # +normal is the audience side when there is less in front
    if flip:
        side = -side
    yaxis = normal * side
    # x: left → right as the audience sees it. (e1, e2, up) is right-handed; someone looking along -y
    # with up overhead has their right hand at (-y) × up = (-y2, y1) in this plane.
    xaxis = np.array([-yaxis[1], yaxis[0]])

    def to_stage(p3):
        p = flat(p3) - origin
        return float(p @ xaxis), float(p @ yaxis), float(p3 @ up - floor)

    out_fx = []
    for a in lit:
        f = found.get(a["fixture"])
        if f is None and not (moves or {}).get(a["fixture"]):
            out_fx.append({"fixture": a["fixture"], "colour": a["colour"], "hex": a["hex"], "found": False})
            continue
        x, y, z = to_stage(f["centre"]) if f else (0.0, 0.0, 0.3)
        if moves and a["fixture"] in moves:
            x, y = moves[a["fixture"]]
        out_fx.append(
            {
                "fixture": a["fixture"],
                "colour": a["colour"],
                "hex": a["hex"],
                "found": bool(f),
                "moved": bool(moves and a["fixture"] in moves),
                "x_m": round(x, 3),
                "y_m": round(y, 3),
                "z_m": round(z, 3),
                "points": f["points"] if f else 0,
                "extent_m": f["extent_m"] if f else None,
                "spill_only": bool(f and f["spill_only"]),
            }
        )

    # Room: ceiling (high percentile of heights) and depth in front of the fixtures.
    stage_xy = (pts2 - origin) @ np.stack([xaxis, yaxis], axis=1)
    ceiling = float(np.percentile(height, 99.5))
    depth = float(np.percentile(stage_xy[:, 1], 99)) if len(stage_xy) else None
    # Preview: a thinned top-down + height sample for the page.
    rng = np.random.default_rng(1)
    idx = rng.choice(len(xyz), min(len(xyz), 40000), replace=False)
    preview = np.concatenate([stage_xy[idx], height[idx, None], rgb[idx]], axis=1)
    return {
        "points": int(len(xyz)),
        "up_axis": "xyz"[int(np.argmax(np.abs(up)))] + ("+" if up.max() > 0 else "-"),
        "fixtures": out_fx,
        "ceiling_m": round(ceiling, 2),
        "room_depth_m": round(depth, 2) if depth else None,
        "flip": flip,
        "audience_guess": "less in front" if not flip else "flipped by hand",
        "preview": np.round(preview, 3).tolist(),
    }


def propose(rig: dict, scan: dict) -> list[dict]:
    """Rig changes from the scan: exact positions (x from the fixture line, centred on the stage),
    distance to the stage edge, height, mount, stage width, ceiling and room depth."""
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    st = geometry.stage(rig)
    placed = [f for f in scan["fixtures"] if f.get("x_m") is not None]
    if not placed:
        return []
    xs = [f["x_m"] for f in placed]
    width = st["width_m"]
    span = max(xs) - min(xs)
    if span + 0.2 > width:  # keep 0.1 m to spare on both sides
        width = round(span + 0.2, 2)
    centre_offset = width / 2 - (max(xs) + min(xs)) / 2

    def old_position(fx):
        kind = "head" if fxlib.get(fx["fixture"])["kind"] == "moving_head" else "par"
        return geometry.position(rig, {"x": fx["x"], "kind": kind}, fx)

    # The scan has y = 0 on the fixture line; keep the rig's distance from that line to the stage edge.
    base_y = float(np.mean([old_position(fixtures[f["fixture"]])[1] for f in placed]))
    changes = []
    for f in placed:
        fx = fixtures[f["fixture"]]
        kind = fxlib.get(fx["fixture"])["kind"]
        c = {"fixture": f["fixture"], "colour": f["colour"], "hex": f["hex"]}
        x = round((f["x_m"] + centre_offset) / width, 3)
        if abs(x - fx["x"]) >= 0.005:
            c["x"] = [fx["x"], x]
        old_pos = old_position(fx)
        y = round(base_y + f["y_m"], 2)
        if abs(y - old_pos[1]) >= 0.05:
            c["y_m"] = [round(old_pos[1], 2), y]
        if abs(f["z_m"] - old_pos[2]) >= 0.05:
            c["z_m"] = [round(old_pos[2], 2), round(f["z_m"], 2)]
        if kind == "moving_head":
            mount = "hang" if f["z_m"] > 2.0 else "floor" if f["z_m"] < 0.8 else "stand"
            if mount != fx.get("mount", "stand"):
                c["mount"] = [fx.get("mount", "stand"), mount]
        if len(c) > 3:
            changes.append(c)
    if round(width, 2) != round(st["width_m"], 2):
        changes.append({"stage": "width_m", "width_m": [st["width_m"], width]})
    if scan.get("ceiling_m") and abs(scan["ceiling_m"] - st["ceiling_m"]) >= 0.1:
        changes.append({"stage": "ceiling_m", "ceiling_m": [st["ceiling_m"], scan["ceiling_m"]]})
    if scan.get("room_depth_m") and abs(scan["room_depth_m"] - st["room_depth_m"]) >= 0.2:
        changes.append({"stage": "room_depth_m", "room_depth_m": [st["room_depth_m"], scan["room_depth_m"]]})
    return changes
