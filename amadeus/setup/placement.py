"""Place the fixtures from a photo of the setup.

1. `light_up(rig)`: every fixture lights in its own colour (dimmed; moving heads aim above the
   audience, not into the camera) and stays on until `lights_off()` or a timeout.
2. The phone takes a photo from the audience. The page finds the coloured light spots itself
   (exact positions); a vision model (gpt-6-luna) says per colour where it is mounted (floor, stand,
   truss, upside down), roughly how high, the distance between the outermost fixtures, and anything
   that looks misaligned.
3. `propose(rig, ...)` turns that into rig changes (x, mount, height, stage width) to review and apply.

Coordinates: x across the stage from left to right as the audience sees it, like the rig (geometry.py).
"""

from __future__ import annotations

import json
import math
import threading
import time

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry

# Distinct hues that both colour wheels and RGB LEDs can make; (name, rgb, hue°)
COLOURS = [
    ("red", (1, 0, 0), 0),
    ("blue", (0, 0, 1), 235),
    ("green", (0, 1, 0), 120),
    ("yellow", (1, 0.85, 0), 52),
    ("magenta", (1, 0, 1), 300),
    ("cyan", (0, 0.8, 1), 190),
]
HOLD_S = 120.0
HEAD_DIMMER = 0.35
PAR_DIMMER = 0.6
AIM_UP_DEG = 30.0  # heads point at the audience but this far up: visible lens, no beam into the camera

_stop = threading.Event()
_thread: threading.Thread | None = None


def assignments(rig: dict) -> list[dict]:
    """Fixture → colour, at most len(COLOURS) fixtures per photo (batch 0, 1, …)."""
    out = []
    for i, f in enumerate(rig["fixtures"]):
        name, rgb, hue = COLOURS[i % len(COLOURS)]
        out.append(
            {
                "fixture": f["id"],
                "colour": name,
                "hue": hue,
                "batch": i // len(COLOURS),
                "hex": "#" + "".join(f"{round(v * 255):02x}" for v in rgb),
            }
        )
    return out


def _states(rig: dict, batch: int):
    from amadeus.engine.state import State
    from amadeus.rig.loader import load_rig_dict

    full = load_rig_dict(rig)
    st = geometry.stage(full)
    camera = (st["width_m"] / 2, 3.0)  # somewhere in the audience, centre
    colour = {a["fixture"]: a for a in assignments(rig)}
    by_id = {f["id"]: f for f in full["fixtures"]}
    states = {}
    for e in full["elements"]:
        a = colour[e["fixture"]]
        if a["batch"] != batch:
            states[e["id"]] = State(pan=0.5, tilt=0.5)
            continue
        rgb = next(c[1] for c in COLOURS if c[0] == a["colour"])
        s = State(dimmer=HEAD_DIMMER if e["kind"] == "head" else PAR_DIMMER, r=rgb[0], g=rgb[1], b=rgb[2])
        if e["kind"] == "head":
            fx = by_id[e["fixture"]]
            defn = fxlib.get(fx["fixture"])
            x, y, _ = geometry.position(full, e, fx)
            az = math.degrees(math.atan2(camera[0] - x, camera[1] - y))
            phi, theta = geometry.ik(fx, defn, geometry.direction(az, AIM_UP_DEG), None)
            s.pan, s.tilt = geometry.to_dmx(fx, defn, phi, theta)
        states[e["id"]] = s
    return full, states


def light_up(rig: dict, batch: int = 0, seconds: float = HOLD_S) -> list[dict]:
    """Start sending the colours (replaces a previous light-up); returns the colour per fixture."""
    global _thread
    from amadeus.dmx.artnet import hold
    from amadeus.dmx.outputs import open_output

    lights_off()
    full, states = _states(rig, batch)
    sender = open_output(full, owner=True)
    hold(seconds + 1)  # a running show pauses its DMX meanwhile
    universes = sorted({f["universe"] for f in full["fixtures"]})
    _stop.clear()

    def run():
        end = time.monotonic() + seconds
        while not _stop.is_set() and time.monotonic() < end:
            unis: dict[int, bytearray] = {}
            for f in full["fixtures"]:
                fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, states)
            sender.send(unis)
            time.sleep(0.025)
        sender.blackout(universes)

    _thread = threading.Thread(target=run, daemon=True)
    _thread.start()
    return [a for a in assignments(rig) if a["batch"] == batch]


def lights_off():
    from amadeus.dmx.artnet import release

    _stop.set()
    if _thread is not None:
        _thread.join(timeout=1.0)
    release()


# ------------------------------------------------------------------ vision

VISION_MODEL = "gpt-6-luna"


def _schema(colours: list[str]) -> dict:
    fixture = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "colour",
            "found",
            "x",
            "y",
            "left",
            "right",
            "mount",
            "upside_down",
            "height_m",
            "facing",
            "notes",
        ],
        "properties": {
            "colour": {"type": "string", "enum": colours},
            "found": {"type": "boolean"},
            "x": {"type": "number", "description": "centre of the fixture body, 0 = left edge of the photo, 1 = right"},
            "y": {"type": "number", "description": "0 = top edge of the photo, 1 = bottom"},
            "left": {"type": "number", "description": "left edge of the fixture's housing (not its light), 0..1"},
            "right": {"type": "number", "description": "right edge of the fixture's housing, 0..1"},
            "facing": {
                "type": "string",
                "enum": ["audience", "up", "wall", "left", "right", "down", "unknown"],
                "description": "where its light points",
            },
            "mount": {
                "type": "string",
                "enum": ["floor", "stand", "truss", "hanging", "table", "unknown"],
                "description": "what it stands on or hangs from",
            },
            "upside_down": {"type": "boolean"},
            "height_m": {"type": "number", "description": "height of the fixture above the floor, estimate"},
            "notes": {"type": "string", "description": "misalignment or problems, '' if none"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["fixtures", "outer_distance_m", "camera", "issues"],
        "properties": {
            "fixtures": {"type": "array", "items": fixture},
            "outer_distance_m": {
                "type": "number",
                "description": "distance between the leftmost and rightmost lit fixture, estimate",
            },
            "camera": {"type": "string", "description": "where the photo was taken from, e.g. 'front, centre, 4 m'"},
            "issues": {
                "type": "array",
                "items": {"type": "string"},
                "description": "alignment/placement problems: not level, rotated, asymmetric, blocked …",
            },
        },
    }


def analyse(image_url: str, lit: list[dict], rig: dict) -> dict:
    """Ask the vision model what the photo shows about each lit fixture."""
    from openai import OpenAI

    by_id = {f["id"]: f for f in rig["fixtures"]}
    lines = []
    for a in lit:
        d = fxlib.get(by_id[a["fixture"]]["fixture"])
        size = d.get("physical", {}).get("size_mm")
        size = f", housing {size[0]}×{size[1]} mm (w×h)" if size else ""
        lines.append(f"- {a['colour']}: {d['manufacturer']} {d['model']} ({d['kind'].replace('_', ' ')}{size})")
    prompt = (
        "Photo of a small stage lighting setup, taken from the audience. Each fixture is lit in its own colour "
        "(moving heads aim up over the camera, so look for the coloured lens or glow; LED bars/kits show "
        "several small lights of that colour; fixtures aimed at a wall also light coloured patches on it: "
        "those patches are not the fixture):\n"
        + "\n".join(lines)
        + "\nFor every colour: is that fixture in the photo, where (centre of the fixture body), what it is "
        "mounted on, about how high it is, and the left and right edge of its housing. Estimate distances from "
        "the housing sizes above (or: a door ~2 m, a table ~75 cm). List alignment problems you can see: heads not "
        "level, a fixture rotated away from the audience, uneven spacing, something blocking a fixture."
    )
    r = OpenAI().responses.create(
        model=VISION_MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": image_url, "detail": "high"},
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "setup",
                "strict": True,
                "schema": _schema([a["colour"] for a in lit]),
            }
        },
    )
    return json.loads(r.output_text)


# ------------------------------------------------------------------ proposal

MOUNT_MAP = {"floor": "floor", "table": "floor", "stand": "stand", "truss": "hang", "hanging": "hang"}


def _measured_span(found: list[dict], fixtures: dict) -> float | None:
    """Distance between the outermost fixtures in metres, scaled by the known housing widths.

    Each fixture with a known size and a housing extent from the vision model gives metres per photo
    width; the median of those times the photo distance between the outermost fixtures. Fixtures at
    about the same distance from the camera (one row) only."""
    scales = []
    for f in found:
        v, size = f["vision"] or {}, fxlib.get(fixtures[f["fixture"]]["fixture"]).get("physical", {}).get("size_mm")
        w = (v.get("right") or 0) - (v.get("left") or 0)
        if size and 0.01 < w < 0.9:
            scales.append(size[0] / 1000 / w)
    if not scales:
        return None
    scales.sort()
    xs = [f["img_x"] for f in found]
    return round((max(xs) - min(xs)) * scales[len(scales) // 2], 2)


def propose(rig: dict, lit: list[dict], blobs: dict, seen: dict) -> dict:
    """Rig changes from the light spots found on the phone (`blobs`: colour → {x, y, w, h, n}) and the
    vision answer. Positions come from the light spots when found, else from the vision model."""
    by_colour = {f["colour"]: f for f in seen.get("fixtures", []) if f.get("found")}
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    stage = geometry.stage(rig)
    found = []
    wall = []
    for a in lit:
        b, v = blobs.get(a["colour"]), by_colour.get(a["colour"])
        if not b and not v:
            continue
        # A big spread-out glow is light on a wall or ceiling, not the fixture: use the vision position.
        if (
            b
            and v
            and (b["w"] > 0.12 or b["h"] > 0.12 or v.get("facing") in ("wall", "up") and abs(b["x"] - v["x"]) > 0.03)
        ):
            wall.append(a["fixture"])
            b = None
        src = "light" if b else "vision"
        found.append(
            {
                "fixture": a["fixture"],
                "colour": a["colour"],
                "hex": a["hex"],
                "source": src,
                "img_x": round((b or v)["x"], 4),
                "img_y": round((b or v)["y"], 4),
                "box": [b["x"] - b["w"] / 2, b["y"] - b["h"] / 2, b["w"], b["h"]] if b else None,
                "vision": v,
            }
        )
    missing = [a["fixture"] for a in lit if a["fixture"] not in {f["fixture"] for f in found}]

    # Across the stage: keep the rig's centre, take the spacing from the photo and the vision model's
    # estimate of the distance between the outermost fixtures (perspective is ignored: one row).
    changes, notes = [], []
    width = stage["width_m"]
    if len(found) >= 2:
        xs = [f["img_x"] for f in found]
        lo, hi = min(xs), max(xs)
        old_m = [fixtures[f["fixture"]]["x"] * width for f in found]
        centre = (min(old_m) + max(old_m)) / 2
        span = _measured_span(found, fixtures) or seen.get("outer_distance_m") or (max(old_m) - min(old_m)) or 1.0
        new_m = {f["fixture"]: centre + ((f["img_x"] - lo) / max(hi - lo, 1e-6) - 0.5) * span for f in found}
        left = min(new_m.values())
        if left < 0 or max(new_m.values()) > width:  # the stage is wider than the rig says: grow it
            shift = -min(left, 0) + (0.1 if left < 0.1 else 0)
            new_m = {k: v + shift for k, v in new_m.items()}
            width = max(width + shift, max(new_m.values()) + 0.1)
            # fixtures not in this photo keep their place in metres
            for f in rig["fixtures"]:
                new_m.setdefault(f["id"], f["x"] * stage["width_m"] + shift)
        order_old = [f["fixture"] for f in sorted(found, key=lambda f: fixtures[f["fixture"]]["x"])]
        order_new = [f["fixture"] for f in sorted(found, key=lambda f: f["img_x"])]
        if order_old != order_new:
            notes.append(
                f"Left to right in the photo: {', '.join(order_new)} (the rig had "
                f"{', '.join(order_old)}). If the colours are on the wrong fixtures, the addresses or "
                f"DMX modes don't match the rig: check them with Identify."
            )
    else:
        new_m = {f["fixture"]: fixtures[f["fixture"]]["x"] * width for f in found}

    others = [
        {"fixture": k, "colour": None, "hex": None, "vision": None}
        for k in new_m
        if k not in {f["fixture"] for f in found}
    ]
    for f in found + others:
        fx = fixtures[f["fixture"]]
        v = f["vision"] or {}
        change = {"fixture": f["fixture"], "colour": f["colour"], "hex": f["hex"]}
        x = round(new_m[f["fixture"]] / width, 3)
        if abs(x - fx["x"]) >= 0.02:
            change["x"] = [fx["x"], x]
        kind = fxlib.get(fx["fixture"])["kind"]
        mount = MOUNT_MAP.get(v.get("mount", "unknown"))
        if v.get("upside_down"):
            mount = "hang"
        if kind == "moving_head" and mount and mount != fx.get("mount", "stand"):
            change["mount"] = [fx.get("mount", "stand"), mount]
        h = v.get("height_m")
        if h and 0 <= h <= 12:
            old_z = fx.get("z_m", geometry.MOUNTS[fx.get("mount", "stand")][1] if kind == "moving_head" else 0.4)
            if abs(h - old_z) >= 0.25:
                change["z_m"] = [round(old_z, 2), round(h, 2)]
        if v.get("notes"):
            change["note"] = v["notes"]
        if f in others and "x" in change:
            change["note"] = "Not in this photo: stays where it is, the stage just got wider."
        if len(change) > 3:
            changes.append(change)
    if round(width, 2) != round(stage["width_m"], 2):
        changes.append({"stage": "width_m", "width_m": [stage["width_m"], round(width, 2)]})
    if wall:
        notes.append(
            f"{', '.join(wall)}: the coloured light is on the wall/ceiling, not on the fixture; "
            f"position taken from the photo analysis instead."
        )
    measured = _measured_span(found, fixtures) if len(found) >= 2 else None
    return {
        "found": found,
        "missing": missing,
        "changes": changes,
        "notes": notes + seen.get("issues", []),
        "camera": seen.get("camera", ""),
        "outer_distance_m": measured or seen.get("outer_distance_m"),
        "distance_source": "measured from the fixture sizes" if measured else "estimated",
    }


def apply(rig: dict, changes: list[dict]) -> dict:
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    for c in changes:
        if "stage" in c:
            rig.setdefault("stage", {})[c["stage"]] = c[c["stage"]][1]
            continue
        f = fixtures[c["fixture"]]
        for key in ("x", "mount", "y_m", "z_m"):
            if key in c:
                f[key] = c[key][1]
    return rig
