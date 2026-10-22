"""Drawings under the rig: the plans an import placed fixtures from, kept with the rig so the editor can show them
on the stage floor, and so they can be lined up again by hand (two clicks) when the AI's scale was off.

A rig's `"underlays"`: one per plan, `{"id", "title", "source", "file", "w", "h", "set", "a", "b", "a_m", "b_m",
"fixtures"}`: the page (a one-page PDF in `config/underlays/`, `w`×`h` points), two points on it (`a`, `b`,
fractions of the page from its top left) and where they are on the rig (`a_m`, `b_m`: metres from stage left
and towards the audience), and every fixture the plan placed with its spot on the page. Those two pairs fix the
whole page: its scale, how it is turned and where (a plan is mirrored too: the page's y runs down, the rig's y
runs to the audience). Lining up again moves that plan's fixtures, and the trusses that carry only them.
"""

from __future__ import annotations

import cmath
import hashlib
import math

from amadeus import paths
from amadeus.rig import trusses as T

FOLDER = paths.CONFIG / "underlays"


def page_name(data: bytes) -> str:
    """A page's file name: by its content, so the same page twice is one file."""
    return hashlib.sha1(data).hexdigest()[:20] + ".pdf"


def save_page(data: bytes) -> str:
    """Keep a page; returns its file name."""
    name = page_name(data)
    FOLDER.mkdir(parents=True, exist_ok=True)
    if not (FOLDER / name).exists():
        (FOLDER / name).write_bytes(data)
    return name


def page_bytes(name: str) -> bytes:
    p = FOLDER / name
    if p.parent != FOLDER or not p.exists():  # a name only, never a path out of the folder
        raise FileNotFoundError(name)
    return p.read_bytes()


def _transform(u: dict) -> tuple[complex, complex]:
    """rig = k · conj(page) + t, with the page in points (x right, y down) and the rig in metres."""
    ap, bp = complex(u["a"][0] * u["w"], u["a"][1] * u["h"]), complex(u["b"][0] * u["w"], u["b"][1] * u["h"])
    am, bm = complex(*u["a_m"]), complex(*u["b_m"])
    k = (bm - am) / ((bp - ap).conjugate() or 1e-9)
    return k, am - k * ap.conjugate()


def to_rig(u: dict, fx: float, fy: float) -> tuple[float, float]:
    """A spot on the page (fractions) → (metres from stage left, metres towards the audience)."""
    k, t = _transform(u)
    z = k * complex(fx * u["w"], fy * u["h"]).conjugate() + t
    return z.real, z.imag


def crop(u: dict) -> list[float]:
    """The part of the page that is this plan ([x0, y0, x1, y1], page fractions): a page can hold several."""
    return u.get("crop") or [0.0, 0.0, 1.0, 1.0]


def corners(u: dict) -> list[tuple[float, float]]:
    """The plan's corners on the rig (top left, top right, bottom right, bottom left of its `crop`): where to draw
    it, with the page's texture from `crop`."""
    x0, y0, x1, y1 = crop(u)
    return [to_rig(u, x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]


def align(rig_doc: dict, uid: str, a: list[float], b: list[float], width_m: float) -> dict:
    """Line a drawing up again: `a` and `b` (page fractions) are the stage's front edge, stage left then stage
    right, `width_m` apart, around the middle of the stage. Its fixtures (and the trusses carrying only them)
    move to where the drawing now puts them. Returns the underlay."""
    u = next(x for x in rig_doc.get("underlays", []) if x["id"] == uid)
    W = float(rig_doc.get("stage", {}).get("width_m", 8.0))
    k_old, _ = _transform(u)
    u.update(a=list(a), b=list(b), a_m=[W / 2 - width_m / 2, 0.0], b_m=[W / 2 + width_m / 2, 0.0])
    k_new, _ = _transform(u)
    places = rig_doc.get("placements", {}).get(u.get("set", ""), {})
    spots = {fid: to_rig(u, *p) for fid, p in u["fixtures"].items() if fid in places}
    by_truss: dict[str, list[str]] = {}
    for fid in spots:
        if places[fid].get("truss"):
            by_truss.setdefault(places[fid]["truss"], []).append(fid)
    trusses = {t["id"]: t for t in rig_doc.get("trusses", [])}
    for tid, fids in by_truss.items():
        t = trusses.get(tid)
        others = [f for f, p in places.items() if p.get("truss") == tid and f not in spots]
        if t is None or t.get("vertical") or t.get("shape") == "circle" or len(others) > len(fids):
            continue  # mostly fixtures from elsewhere: it stays, the drawing's are put on it where it is
        turn = math.degrees(cmath.phase(k_new / k_old)) if k_old else 0.0
        rot = t.get("rot_deg", 0.0) - turn  # mirrored: a turn of the page is the other way round on the rig
        if len(fids) >= 2:
            far = max(((spots[f], spots[g]) for f in fids for g in fids), key=lambda p: math.dist(*p))
            (x0, y0), (x1, y1) = far
            rot = math.degrees(math.atan2(y1 - y0, x1 - x0))
        rot = (rot + 90) % 180 - 90  # a truss either way round is the same truss
        r = math.radians(rot)
        dx, dy = math.cos(r), math.sin(r)
        cx = sum(spots[f][0] for f in fids) / len(fids)
        cy = sum(spots[f][1] for f in fids) / len(fids)
        along = [(spots[f][0] - cx) * dx + (spots[f][1] - cy) * dy for f in fids]
        mid = (max(along) + min(along)) / 2
        t["x_m"], t["y_m"] = round(cx + mid * dx, 3), round(cy + mid * dy, 3)
        reach = max([abs(a - mid) for a in along] + [abs(places[f].get("truss_pos_m", 0.0)) for f in others])
        t["length_m"] = max(1.0, math.ceil((2 * reach + 1.0) * 2) / 2)
        if abs(rot) > 0.5:
            t["rot_deg"] = round(rot, 1)
        else:
            t.pop("rot_deg", None)
        moved = list(zip(fids, [a - mid for a in along])) + [(f, places[f].get("truss_pos_m", 0.0)) for f in others]
        for f, u_along in moved:  # the drawing's where it puts them, the others where they were along it
            spot = places[f]
            aim = spot.get("aim")
            T.place(spot, t, round(u_along, 3), W, spot.get("truss_side", "under"))
            if aim:
                spot["aim"] = aim
    for fid, (x, y) in spots.items():
        if not places[fid].get("truss") or places[fid]["truss"] not in trusses:
            places[fid]["x"], places[fid]["y_m"] = round(x / W, 4), round(y, 3)
    return u
