"""Rigs to start from: the usual structures at a venue, sized to the stage.

A rig is only the structure (trusses, towers, the stage, an LED wall); the fixtures come from a set and are
mounted on it afterwards.
"""

from __future__ import annotations

TEMPLATES = {
    "floor": "An empty room: fixtures on the floor and on stands.",
    "stands": "A mobile DJ: two T-bar stands left and right of the booth.",
    "booth": "One truss over the DJ booth.",
    "club": "Two trusses over the booth, front and back.",
    "stage": "A concert stage: two overhead trusses, a low truss at the back and a tower on each side.",
}


def _truss(tid: str, length: float, x: float, y: float, z: float, vertical: bool = False) -> dict:
    t = {"id": tid, "type": "quatro", "length_m": round(length, 2), "x_m": round(x, 2), "y_m": round(y, 2)}
    t["z_m"] = round(length / 2 if vertical else z, 2)
    if vertical:
        t["vertical"] = True
    return t


def _length(span: float) -> float:
    """Box truss comes in whole metres (and halves): the longest that fits the span."""
    return max(1.0, int(span * 2) / 2)


def rig(template: str, width: float = 8.0, height: float = 4.5, depth: float = 15.0, screen: bool = False) -> dict:
    """A new rig: `width` of the stage, trusses at `height` (trim), `depth` of the room in front."""
    if template not in TEMPLATES:
        raise SystemExit(f"No rig template '{template}'. Templates: {', '.join(TEMPLATES)}")
    W = width
    trusses: list[dict] = []
    if template == "stands":
        for k, x in enumerate((W * 0.18, W * 0.82)):
            trusses.append(_truss(f"stand{k + 1}", min(height, 3.0), x, -0.8, 0, vertical=True))
    elif template == "booth":
        trusses.append(_truss("truss1", _length(W * 0.75), W / 2, -1.2, height))
    elif template == "club":
        trusses.append(_truss("front", _length(W * 0.85), W / 2, -1.0, height))
        trusses.append(_truss("back", _length(W * 0.85), W / 2, -3.0, height + 0.3))
    elif template == "stage":
        stage_depth = min(8.0, max(3.0, W * 0.4))
        trusses.append(_truss("front", _length(W - 1), W / 2, -1.5, height))
        trusses.append(_truss("mid", _length(W - 1), W / 2, -1.5 - stage_depth * 0.5, height + 0.5))
        trusses.append(_truss("back", _length(W * 0.8), W / 2, -1.5 - stage_depth, 1.0))
        for side, x in (("L", 0.3), ("R", W - 0.3)):
            trusses.append(_truss(f"tower{side}", max(2.0, height - 0.5), x, -1.0, 0, vertical=True))
    top = max([t["z_m"] + (t["length_m"] / 2 if t.get("vertical") else 0) for t in trusses] or [height])
    out = {
        "description": TEMPLATES[template],
        "stage": {"width_m": round(W, 2), "ceiling_m": round(max(height + 2.5, top + 1.5), 1),
                  "room_depth_m": round(depth, 1), "eye_safety": False},
        "trusses": trusses,
    }  # fmt: skip
    if screen:
        out["screen"] = {"width_m": round(min(10.0, W * 0.55), 1)}
    return out
