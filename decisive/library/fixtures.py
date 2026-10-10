"""Fixture library: channel layouts per model/mode, patching and decoding.

A rig fixture (one physical device) expands into one or more *elements*,
the things the scene engine lights: a moving head is one element, a ComPar
bar in 16ch mode is four (one per RGB head). Patching turns element states
into DMX bytes using the library definition; decoding does the reverse and
is used by the simulated node to show what a real fixture would do.
"""

from __future__ import annotations

import json
import math
from functools import cache

from decisive import paths

LIB_DIR = paths.FIXTURES
PAN_TILT = {"pan", "pan_fine", "tilt", "tilt_fine"}
# definition kind → element kind. A moving bar (DTS Katana, COLORband PiX-M) is a row of cells that share
# one tilt motor: every cell is a "head" element; the engine moves them together.
ELEMENT_KIND = {"moving_head": "head", "moving_bar": "head", "laser": "laser", "blinder": "blinder", "strobe": "strobe"}
MOVING = ("moving_head", "moving_bar")


def is_moving(defn: dict) -> bool:
    return defn.get("kind") in MOVING


@cache
def library() -> dict[str, dict]:
    """All definitions keyed by 'manufacturer/model-file', e.g. 'beamz/fuze75s-spot'."""
    lib = {}
    for path in sorted(LIB_DIR.glob("*/*.json")):
        d = json.loads(path.read_text())
        d["key"] = f"{path.parent.name}/{path.stem}"
        lib[d["key"]] = d
    return lib


def get(key: str) -> dict:
    lib = library()
    if key not in lib:
        raise SystemExit(f"Unknown fixture '{key}'. Known: {', '.join(lib)}")
    return lib[key]


def channels(defn: dict, mode: str) -> list[dict]:
    if mode not in defn["modes"]:
        raise SystemExit(f"{defn['key']} has no mode '{mode}'. Modes: {', '.join(defn['modes'])}")
    return defn["modes"][mode]


def default_mode(defn: dict) -> str:
    """The richest mode: most channels (16-bit movement, per-head colour)."""
    return max(defn["modes"], key=lambda m: len(defn["modes"][m]))


def mode_for_footprint(defn: dict, footprint: int) -> str | None:
    return next((m for m, ch in defn["modes"].items() if len(ch) == footprint), None)


def heads(defn: dict, mode: str) -> list[int]:
    hs = sorted({c["head"] for c in channels(defn, mode) if "head" in c})
    return hs or [0]  # 0 = the whole fixture is one element


def bar_length_m(fx: dict, defn: dict) -> float:
    """Length of a multi-cell fixture (LED bar, moving bar): the rig's `length_m`, else its housing."""
    if fx.get("length_m"):
        return float(fx["length_m"])
    size = defn.get("physical", {}).get("size_mm")
    return size[0] / 1000 if size and size[0] else 1.0


def expand(fx: dict, stage_w: float | None = None) -> list[dict]:
    """Rig fixture → elements. Cells of a bar sit along the bar (`offset_m` from its centre, along its own
    axis, which `rot_deg` turns); `x` is the element's stage position as a fraction of the stage width
    (exact when `stage_w` is given, for ordering otherwise)."""
    defn = get(fx["fixture"])
    kind = ELEMENT_KIND.get(defn["kind"], "par")
    hs = heads(defn, fx["mode"])
    n = len(hs)
    length = bar_length_m(fx, defn)
    rot = math.radians(fx.get("rot_deg", 0.0))
    out = []
    for i, h in enumerate(hs):
        k = n - 1 - i if fx.get("reverse") else i  # "reverse": head 1 is on the audience's right
        off = 0.0 if n == 1 else -length / 2 + length * (k + 0.5) / n
        if n == 1:
            x = fx["x"]
        elif stage_w:
            x = fx["x"] + off * math.cos(rot) / stage_w
        else:  # old sets (no stage width at hand): the historic spacing, for ordering only
            width = fx.get("width", 0.08 * (n - 1))
            x = fx["x"] - width / 2 + width * k / (n - 1)
        e = {
            "id": fx["id"] if h == 0 else f"{fx['id']}.{h}",
            "fixture": fx["id"],
            "head": h,
            "kind": kind,
            "x": round(x, 4),
            "label": f"{defn['manufacturer']} {defn['model']}",
        }
        if n > 1:
            e["offset_m"] = round(off, 4)
        out.append(e)
    return out


# ---------------------------------------------------------------- colour wheels


def _chroma(rgb):
    m = max(rgb)
    return tuple(v / m for v in rgb) if m > 1e-6 else (0.0, 0.0, 0.0)


def nearest_slot(defn: dict, rgb, white: float = 0.0) -> dict:
    """Pick the colour-wheel slot closest to the wanted colour (white flash → open)."""
    slots = defn["color_wheel"]["slots"]
    if white > 0.5 or max(rgb) - min(rgb) < 0.2:  # unsaturated → open/white
        return slots[0]
    want = _chroma(rgb)
    return min(slots[1:], key=lambda s: sum((a - b) ** 2 for a, b in zip(_chroma(s["rgb"]), want)))


def has_wheel(defn: dict) -> bool:
    return "color_wheel" in defn


# ---------------------------------------------------------------- patching


def patch(buf: bytearray, fx: dict, states: dict) -> None:
    """Write one rig fixture's channels into a 512-byte universe buffer.

    `states` maps element id → engine State (dimmer, r, g, b, white, pan, tilt, all 0..1).
    """
    defn = get(fx["fixture"])
    chans = channels(defn, fx["mode"])
    els = {e["head"]: states[e["id"]] for e in expand(fx)}
    first = next(iter(els.values()))
    per_head_colour = len(els) > 1
    has_dimmer = any(c["attr"] == "dimmer" for c in chans)
    head_dimmers = any(c["attr"] == "dimmer" and "head" in c for c in chans)  # a dimmer per cell (Sunstrip)

    pan_l, tilt_l = fx.get("pan_limits", [0, 1]), fx.get("tilt_limits", [0, 1])  # optional hard limits
    want_pan = first.pan if getattr(first, "dmx_pan", None) is None else first.dmx_pan
    want_tilt = first.tilt if getattr(first, "dmx_tilt", None) is None else first.dmx_tilt
    pan = min(max(want_pan, pan_l[0]), pan_l[1])
    tilt = min(max(want_tilt, tilt_l[0]), tilt_l[1])
    p16, t16 = int(min(max(pan, 0), 1) * 65535), int(min(max(tilt, 0), 1) * 65535)
    has_cmy = any(c["attr"] == "cyan" for c in chans)
    # CMY fixtures mix the colour; their wheel (if any) stays open
    slot = (
        (defn["color_wheel"]["slots"][0] if has_cmy else nearest_slot(defn, (first.r, first.g, first.b), first.white))
        if has_wheel(defn)
        else None
    )
    overrides = {}
    for attr, val in defn.get("beam_fx", {}).get(getattr(first, "fx", "open"), {}).items():
        if isinstance(val, list):  # one value per gobo
            overrides[attr] = val[getattr(first, "gobo", 0) % len(val)]
        elif isinstance(val, dict):  # rotation: [slow, fast] range, optionally the other direction
            lo, hi = val["reverse"] if getattr(first, "fx_reverse", False) and "reverse" in val else val["range"]
            overrides[attr] = round(lo + (hi - lo) * min(max(getattr(first, "fx_speed", 0.5), 0.0), 1.0))
        else:
            overrides[attr] = val

    for off, c in enumerate(chans):
        addr = fx["address"] - 1 + off
        if not 0 <= addr < 512:
            continue
        a = c["attr"]
        s = els.get(c.get("head", 0), first)
        # Per-head colour without per-head dimmers: master dimmer full, intensity goes into RGB.
        scale = s.dimmer if ((per_head_colour and not head_dimmers) or not has_dimmer) else 1.0
        if a in overrides:
            v = overrides[a]
        elif "default" in c:
            v = c["default"]
        elif a == "pan":
            v = p16 >> 8
        elif a == "pan_fine":
            v = p16 & 255
        elif a == "tilt":
            v = t16 >> 8
        elif a == "tilt_fine":
            v = t16 & 255
        elif a == "dimmer" and "head" in c:  # this cell's own dimmer
            v = round(min(max(max(s.dimmer, s.white), 0), 1) * 255)
        elif a == "dimmer":
            v = 255 if per_head_colour else round(min(max(max(s.dimmer, s.white), 0), 1) * 255)
        elif a == "dimmer_fine":  # low byte of a 16-bit dimmer
            v = 255 if per_head_colour else round(min(max(max(s.dimmer, s.white), 0), 1) * 65535) & 255
        elif a in ("cyan", "magenta", "yellow"):  # subtractive: filter out what the colour lacks
            mx = max(s.r, s.g, s.b) + s.white
            base = {"cyan": s.r, "magenta": s.g, "yellow": s.b}[a] + s.white
            v = 0 if mx < 1e-6 else round(min(max(1 - base / mx, 0), 1) * 255)
        elif a in ("red", "green", "blue"):
            base = {"red": s.r, "green": s.g, "blue": s.b}[a]
            v = round(min(max((base + s.white) * scale, 0), 1) * 255)
        elif a == "white":
            v = round(min(max(s.white * scale, 0), 1) * 255)
        elif a == "color_wheel" and getattr(first, "lcolor", "") in defn.get("laser", {}).get("color_modes", {}):
            v = defn["laser"]["color_modes"][first.lcolor]  # laser multicolour modes
        elif a == "color_wheel":
            v = (slot["from"] + slot["to"]) // 2
        elif a == "zoom" and "tight" in c:  # crisp, tight beams for scanning; wide only for a frost wash
            v = c["wide"] if getattr(first, "fx", "open") == "frost" else c["tight"]
        elif a.startswith("laser_") and "laser" in defn:
            v = _laser_value(a, defn["laser"], s)
        else:
            v = 0
        buf[addr] = int(v)


def _laser_value(a: str, laser: dict, s) -> int:
    """DMX for a laser channel from the element state: fx = shape, pan/tilt = offset, size, spin."""
    if a == "laser_mode":  # fail-safe: an "off" look is off whatever the dimmer says (e.g. mid-crossfade)
        return laser["on"] if s.dimmer > 0.05 and getattr(s, "fx", "") not in ("off", "open") else laser["off"]
    if a == "laser_pattern":
        pats = laser["patterns"]
        return pats.get(getattr(s, "fx", "beams"), next(iter(pats.values())))
    if a == "laser_x":
        return round(min(max(s.pan, 0.0), 1.0) * 127)
    if a == "laser_y":
        return round(min(max(s.tilt, 0.0), 1.0) * 127)
    if a in ("laser_size_x", "laser_size_y"):  # big to small
        return round((1.0 - min(max(getattr(s, "size", 0.5), 0.0), 1.0)) * 255)
    if a == "laser_rot_z":
        spin = getattr(s, "spin", 0.0)
        if abs(spin) < 0.02:
            return laser.get("sheet_rot_z", 64) if getattr(s, "fx", "") == "sheet" else 64
        return 192 + round(min(spin, 1.0) * 63) if spin > 0 else 128 + round(min(-spin, 1.0) * 63)
    return 0


def footprint(fx: dict) -> int:
    return len(channels(get(fx["fixture"]), fx["mode"]))


def validate(rig: dict) -> list[str]:
    """Overlapping or out-of-range addresses."""
    problems, used = [], {}
    for fx in rig["fixtures"]:
        n = footprint(fx)
        if fx["address"] < 1 or fx["address"] + n - 1 > 512:
            problems.append(f"{fx['id']}: channels {fx['address']}–{fx['address'] + n - 1} don't fit in a universe")
        for ch in range(fx["address"], fx["address"] + n):
            other = used.get((fx["universe"], ch))
            if other:
                problems.append(f"{fx['id']} overlaps {other} at universe {fx['universe']} channel {ch}")
                break
            used[(fx["universe"], ch)] = fx["id"]
    return problems


# ---------------------------------------------------------------- decoding (simulator)


def decode(defn: dict, mode: str, data: bytes) -> str:
    """Human-readable summary of what a fixture does with these DMX bytes."""
    chans = channels(defn, mode)
    vals = {}
    for c, v in zip(chans, data):
        vals[(c["attr"], c.get("head", 0))] = v
    parts = []
    if ("pan", 0) in vals:
        p = (vals[("pan", 0)] << 8 | vals.get(("pan_fine", 0), 0)) / 65535
        t = (vals[("tilt", 0)] << 8 | vals.get(("tilt_fine", 0), 0)) / 65535
        parts.append(f"pan {p * defn['physical']['pan_deg']:5.1f}° tilt {t * defn['physical']['tilt_deg']:5.1f}°")
    if ("color_wheel", 0) in vals:
        v = vals[("color_wheel", 0)]
        slot = next((s["name"] for s in defn["color_wheel"]["slots"] if s["from"] <= v <= s["to"]), f"raw {v}")
        parts.append(f"wheel {slot:<9}")
    if ("dimmer", 0) in vals:
        parts.append(f"dim {vals[('dimmer', 0)] * 100 // 255:3d}%")
    fx = {a: vals[(a, 0)] for a in ("gobo", "prism", "frost") if (a, 0) in vals}
    if fx:
        parts.append(" ".join(f"{a} {v:3d}" for a, v in fx.items()))
    if ("shutter", 0) in vals:
        parts.append("open" if 32 <= vals[("shutter", 0)] <= 63 else f"shutter {vals[('shutter', 0)]}")
    for h in sorted({h for (_, h) in vals if h}):
        r, g, b = (vals.get((a, h), 0) for a in ("red", "green", "blue"))
        parts.append(f"#{r:02x}{g:02x}{b:02x}")
    return "  ".join(parts)
