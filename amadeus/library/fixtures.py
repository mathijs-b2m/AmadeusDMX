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
import re
import time
from functools import cache
from pathlib import Path

from amadeus import paths
from amadeus.dmx import limiter

LIB_DIR = paths.FIXTURES
# Your fixtures, when they live apart from the shipped library (the Mac app): they win over LIB_DIR, and additions
# and calibrations are saved there. None in a checkout: one folder for both.
USER_DIR = paths.USER_FIXTURES if paths.USER_FIXTURES != paths.FIXTURES else None
PAN_TILT = {"pan", "pan_fine", "tilt", "tilt_fine"}
# definition kind → element kind. A moving bar (DTS Katana, COLORband PiX-M) is a row of cells that share
# one tilt motor: every cell is a "head" element; the engine moves them together. A bar with a tilt channel per
# cell (COLORado PXL Curve) has a motor per cell: its cells move on their own (cell_motors).
ELEMENT_KIND = {
    "moving_head": "head",
    "moving_bar": "head",
    "laser": "laser",
    "blinder": "blinder",
    "strobe": "strobe",
    "smoke": "smoke",  # a smoke machine or hazer: engine/fog.py decides when and how much
}
MOVING = ("moving_head", "moving_bar")
# Colour emitters the show does not mix into its colours (held at 0, lit by the light test). On a bar they still
# belong to their cell: a UV bar's sections are its heads. A fixture with UV and nothing else (a blacklight) is
# played all the same: always UV, at the level the show gives it (uv_only).
DARK_EMITTERS = ("uv", "amber", "lime", "indigo")
UV_RGB = (0.35, 0.0, 1.0)  # how UV looks (setup/colors.py "uv")

# Lasers from the QLC+ / Open Fixture Library come without the hand-made mapping the show needs to drive them
# safely: they are "inert", every channel held at its off value (the visualisers draw them dark). So is a smoke
# machine whose output channel the converter couldn't find.
OFF_WORDS = re.compile(r"\b(off|blackout|no output|closed?|stop|disabled?|no function|nothing)\b", re.I)
AUTO_WORDS = re.compile(r"\b(auto(matic)?|sound|music|programs?|show|demo|random)\b", re.I)
MODE_CHANNEL = re.compile(r"^(?!.*speed).*\b(modes?|control|operation|function)\b", re.I)  # what switches it on


def inert(defn: dict) -> str:
    """Why the show never drives this fixture ('' if it does): it holds every channel at its default."""
    if defn.get("inert"):
        return defn["inert"]
    if defn.get("kind") == "smoke" and not any(c["attr"] == "fog" for m in defn.get("modes", {}).values() for c in m):
        return "a smoke machine whose output channel isn't known: the show never fires it"
    if defn.get("kind") == "laser" and "laser" not in defn:
        return "a laser whose channels aren't mapped by hand yet: it stays dark"
    return ""


def off_value(channel: str, caps: list[tuple[int, str]]) -> tuple[int, bool]:
    """The DMX value that keeps a channel of a laser or smoke machine off: the first range called off,
    blackout, no function…, else 0. False when 0 starts the fixture by itself (a mode channel whose 0 is
    sound or auto) and nothing on the channel says off: DMX can't keep it dark."""
    for lo, name in sorted(caps):
        if OFF_WORDS.search(name) and not re.search(r"\bon\b", name, re.I):
            return lo, True
    first = min(caps)[1] if caps else ""
    return 0, not (AUTO_WORDS.search(first) and MODE_CHANNEL.search(channel))


FOG_OUTPUT = re.compile(r"^(fog|smoke|haze|pump)\b|output|volume|density", re.I)
FOG_NOT = re.compile(r"duration|interval|time|program|colou?r|random|auto|speed|fan|strob|dimmer|macro", re.I)


def smoke_channel(name: str, caps: list[tuple[int, str]], have_output: bool) -> dict | None:
    """A smoke machine's channel the show drives: its output ("fog", from the first value that makes smoke)
    or its fan; None for the rest (timers, colours, programs: held off)."""
    if not have_output and FOG_OUTPUT.search(name) and not FOG_NOT.search(name):
        off = [hi for lo, hi, n in caps if OFF_WORDS.search(n) and not re.search(r"\bon\b", n, re.I) and lo == 0]
        return {"attr": "fog", "on_from": min(max(off, default=0) + 1, 255)}
    if re.search(r"\bfan\b", name, re.I):
        return {"attr": "fog_fan", "default": off_value(name, [(lo, n) for lo, _, n in caps])[0]}
    return None


def mark_smoke(defn: dict, haze: bool):
    """A converted smoke machine with an output channel: what kind, how much (estimated from its power)."""
    for k in ("pan_deg", "tilt_deg", "lumens", "_lumens_note"):
        defn["physical"].pop(k, None)
    defn["physical"]["fog"] = {
        "type": "haze" if haze else "fog",
        "estimated": True,
        "_note": "Output estimated from the power; set m3_min (m³ per minute), max_burst_s and rest_s from "
        "the manual for better timing (engine/fog.py).",
    }


def mark_inert(defn: dict, unsafe: list[str]):
    """A converted laser or smoke machine: inert, and a warning when DMX can't keep it off."""
    defn["inert"] = inert(defn)
    for k in ("pan_deg", "tilt_deg", "lumens", "_lumens_note"):
        defn["physical"].pop(k, None)
    if unsafe:
        defn["warning"] = (
            f"DMX can't keep it off ({', '.join(sorted(set(unsafe)))} at 0 is a sound or auto mode): "
            "power it from a switch you control"
        )


def uv_only(defn: dict) -> bool:
    """A blacklight: UV emitters and no other colour."""
    attrs = {c["attr"] for m in defn.get("modes", {}).values() for c in m}
    return "uv" in attrs and not attrs & {"red", "green", "blue", "white", "cyan", "color_wheel"}


def is_moving(defn: dict) -> bool:
    return defn.get("kind") in MOVING


@cache
def library() -> dict[str, dict]:
    """All definitions keyed by 'manufacturer/model-file', e.g. 'beamz/fuze75s-spot'."""
    lib = {}
    for folder in [LIB_DIR] + ([USER_DIR] if USER_DIR else []):  # yours last: it replaces the shipped one
        for path in sorted(folder.glob("*/*.json")):
            d = json.loads(path.read_text(encoding="utf-8"))
            d["key"] = f"{path.parent.name}/{path.stem}"
            lib[d["key"]] = d
    return lib


def path_of(key: str) -> Path:
    """The file a definition comes from: yours if you have one, else the shipped one."""
    mine = (USER_DIR or LIB_DIR) / f"{key}.json"
    return mine if mine.exists() else LIB_DIR / f"{key}.json"


def save(key: str, data: dict) -> Path:
    """Writes a definition to your fixtures (the shipped library stays as it came)."""
    path = (USER_DIR or LIB_DIR) / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    library.cache_clear()
    return path


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


def cell_motors(defn: dict, mode: str) -> bool:
    """A bar whose cells tilt on their own (a tilt channel per cell, COLORado PXL Curve), not on one shared motor."""
    return any(c["attr"] == "tilt" and "head" in c for c in channels(defn, mode))


# Fixtures that can hurt eyes: risk group 2 and 3 (IEC 62471, `physical.risk_group` from the manual or label).
# This is alpha software: those stay dark with real lights. Without a rating we estimate it from the light
# packed into each beam: a Sharpy or a Pointe counts, a Fuze, a Katana or a wash doesn't.
POWERFUL_LUMENS = 5000  # per beam
POWERFUL_LM_PER_DEG2 = 200  # lumens per square degree of beam


def high_risk(defn: dict) -> bool:
    """Risk group 2 or 3, or (unrated) a narrow beam with real power."""
    phys = defn.get("physical", {})
    if phys.get("risk_group") is not None:
        return int(phys["risk_group"]) >= 2
    lumens, beam = phys.get("lumens"), phys.get("beam_deg")
    if not lumens or not beam or defn.get("kind") not in MOVING:
        return False
    per_beam = lumens / len(heads(defn, default_mode(defn)))
    return per_beam >= POWERFUL_LUMENS and per_beam / float(beam) ** 2 >= POWERFUL_LM_PER_DEG2


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
    kind = "inert" if inert(defn) else ELEMENT_KIND.get(defn["kind"], "par")
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
    if white > 0.5 or max(rgb) - min(rgb) < 0.2 or len(slots) < 2:  # unsaturated (or only open) → open/white
        return slots[0]
    want = _chroma(rgb)
    return min(slots[1:], key=lambda s: sum((a - b) ** 2 for a, b in zip(_chroma(s["rgb"]), want)))


def has_wheel(defn: dict) -> bool:
    return "color_wheel" in defn


# ---------------------------------------------------------------- LED rings

# An LED ring or strip round a head's lens, on one channel of colour macros (named in the mapper). It wears the
# beam's colour while the head plays and goes off when it rests, but it plays the phrase, not the notes: it stays
# lit a while after the beam went dark and takes a new colour only once that colour has lasted (no blips).
RING_REST_S = 3.0  # dark this long: the head rests, the ring goes off
RING_SETTLE_S = 1.0  # a colour lasts this long before the ring takes it (a white flash doesn't change it)
_rings: dict[str, dict] = {}  # fixture id → {"lit": when its beam last shone, "slot", "want", "since"}


def _ring_off(slot: dict) -> bool:
    return max(slot["rgb"]) <= 0.0 or bool(OFF_WORDS.search(slot["name"]))


def ring_colour(slots: list[dict], rgb, white: float = 0.0) -> dict | None:
    """The ring's colour nearest the beam's (an unsaturated beam: its white, if it has one); None: none fits."""
    lit = [s for s in slots if not _ring_off(s)]
    if white > 0.5 or max(rgb) - min(rgb) < 0.2:
        return min(lit, key=lambda s: max(s["rgb"]) - min(s["rgb"]), default=None) if lit else None
    want = _chroma(rgb)
    coloured = [s for s in lit if max(s["rgb"]) - min(s["rgb"]) >= 0.2]
    return min(coloured, key=lambda s: sum((a - b) ** 2 for a, b in zip(_chroma(s["rgb"]), want)), default=None)


def ring_value(defn: dict, fx_id: str, s, now: float | None = None) -> int:
    """The ring colour channel's value for a head in state `s` (the middle of its slot)."""
    slots = defn.get("ring_color", {}).get("slots", [])
    if not slots:
        return 0
    now = time.monotonic() if now is None else now
    r = _rings.setdefault(fx_id, {"lit": -1e9, "slot": None, "want": None, "since": now})
    if s.dimmer > 0.02 and max(s.r, s.g, s.b, s.white) > 0.02:
        r["lit"] = now
        want = ring_colour(slots, (s.r, s.g, s.b), s.white)
        if want is not None and want != r["want"]:
            r["want"], r["since"] = want, now
        if r["want"] is not None and (r["slot"] is None or now - r["since"] >= RING_SETTLE_S):
            r["slot"] = r["want"]
    if r["slot"] is None or now - r["lit"] > RING_REST_S:
        r["slot"] = None
        off = next((x for x in slots if _ring_off(x)), None)
        return (off["from"] + off["to"]) // 2 if off else 0
    return (r["slot"]["from"] + r["slot"]["to"]) // 2


# ---------------------------------------------------------------- patching


# a beam effect a fixture (or its mode) can't play, played as the nearest one it can: a rotating gobo as a still one
FX_FALLBACK = {"gobo_rotate": "gobo", "gobo_shake": "gobo", "gobo_spin": "gobo", "prism_spin": "prism"}


def beam_effect(defn: dict, chans: list[dict], fx: str) -> str:
    """The beam effect the fixture really plays for `fx`: the one asked for when this mode has its channels, else
    the nearest it has, else an open beam."""
    table = defn.get("beam_fx", {})
    attrs = {c["attr"] for c in chans}
    while fx:
        entry = table.get(fx)
        if isinstance(entry, dict) and set(entry) <= attrs:
            return fx
        fx = FX_FALLBACK.get(fx, "")
    return "open"


def zoom_of(s) -> float:
    """How wide the zoom opens for a state: 0 tightest .. 1 widest (a frost wash always wide)."""
    return 1.0 if getattr(s, "fx", "open") == "frost" else min(max(getattr(s, "zoom", 0.0), 0.0), 1.0)


def patched(fx: dict) -> bool:
    """Has a start address. A fixture added without one plays in the visualiser only until it gets one."""
    return isinstance(fx.get("address"), int) and not isinstance(fx.get("address"), bool)


def patch(buf: bytearray, fx: dict, states: dict, limit: float | None = None) -> None:
    """Write one rig fixture's channels into a 512-byte universe buffer (nothing without a start address).

    `states` maps element id → engine State (dimmer, r, g, b, white, pan, tilt, all 0..1). `limit`: the
    brightness limiter's ceiling (dmx/limiter.py; None: its saved level), applied here, last, to the light only.
    """
    if not patched(fx):
        return
    ceiling = limiter.level() if limit is None else min(max(limit, 0.0), 1.0)
    defn = get(fx["fixture"])
    chans = channels(defn, fx["mode"])
    if inert(defn):  # never driven: every channel at its off value
        for off, c in enumerate(chans):
            if 0 <= fx["address"] - 1 + off < 512:
                buf[fx["address"] - 1 + off] = int(c.get("default", 0))
        return
    els = {e["head"]: states[e["id"]] for e in expand(fx)}
    first = next(iter(els.values()))
    per_head_colour = len(els) > 1
    has_dimmer = any(c["attr"] == "dimmer" for c in chans)
    head_dimmers = any(c["attr"] == "dimmer" and "head" in c for c in chans)  # a dimmer per cell (Sunstrip)
    blacklight = uv_only(defn)
    rgb_level = (per_head_colour and not head_dimmers) or not has_dimmer  # the RGB carries the level, not a dimmer

    def ceiled(s) -> float:
        """How much the limiter turns this element's emitters down (1: not at all), the same for all of them so
        the colour keeps its hue. Only where they carry the level; a dimmer channel is limited on its own."""
        if ceiling >= 1.0 or not rgb_level:
            return 1.0
        peak = min((max(s.r, s.g, s.b, 0.0) + max(s.white, 0.0)) * s.dimmer, 1.0)
        return ceiling / peak if peak > ceiling else 1.0

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
    shown = beam_effect(defn, chans, getattr(first, "fx", "open"))
    for attr, val in defn.get("beam_fx", {}).get(shown, {}).items():
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
        scale = s.dimmer if rgb_level else 1.0
        level = min(max(max(s.dimmer, s.white), 0), 1, ceiling)  # a dimmer channel's level, under the limiter
        if a in overrides:
            v = overrides[a]
        elif a == "fog":  # smoke output: the element's level (engine/fog.py), above the value where smoke starts
            on = c.get("on_from", 1)
            v = 0 if s.dimmer <= 0 else on + round(min(s.dimmer, 1.0) * (255 - on))
        elif a == "fog_fan":  # a hazer's fan: spreads what it makes; resting when it makes nothing
            v = round((0.4 + 0.6 * min(s.dimmer, 1.0)) * 255) if s.dimmer > 0 else c.get("default", 0)
        elif a == "uv" and blacklight:  # its only colour: the level, as a dimmer-only lamp shows it
            lvl = max(s.dimmer, s.white) if rgb_level else 1.0
            v = round(min(max(lvl, 0), 1, ceiling) * 255)
        elif "default" in c:
            v = c["default"]
        elif a == "pan":
            v = p16 >> 8
        elif a == "pan_fine":
            v = p16 & 255
        elif a in ("tilt", "tilt_fine") and "head" in c:  # this cell's own motor
            tc = s.tilt if getattr(s, "dmx_tilt", None) is None else s.dmx_tilt
            tc16 = int(min(max(tc, tilt_l[0], 0), tilt_l[1], 1) * 65535)
            v = tc16 >> 8 if a == "tilt" else tc16 & 255
        elif a == "tilt":
            v = t16 >> 8
        elif a == "tilt_fine":
            v = t16 & 255
        elif a == "dimmer" and "head" in c:  # this cell's own dimmer
            v = round(level * 255)
        elif a == "dimmer":
            v = 255 if per_head_colour else round(level * 255)
        elif a == "dimmer_fine":  # low byte of a 16-bit dimmer
            v = 255 if per_head_colour else round(level * 65535) & 255
        elif a in ("cyan", "magenta", "yellow"):  # subtractive: filter out what the colour lacks
            mx = max(s.r, s.g, s.b) + s.white
            base = {"cyan": s.r, "magenta": s.g, "yellow": s.b}[a] + s.white
            v = 0 if mx < 1e-6 else round(min(max(1 - base / mx, 0), 1) * 255)
        elif a in ("red", "green", "blue"):
            base = {"red": s.r, "green": s.g, "blue": s.b}[a]
            v = round(min(max((base + s.white) * scale, 0), 1) * ceiled(s) * 255)
        elif a == "white":
            v = round(min(max(s.white * scale, 0), 1) * ceiled(s) * 255)
        elif a == "color_wheel" and getattr(first, "lcolor", "") in defn.get("laser", {}).get("color_modes", {}):
            v = defn["laser"]["color_modes"][first.lcolor]  # laser multicolour modes
        elif a == "color_wheel":
            v = (slot["from"] + slot["to"]) // 2
        elif a == "ring_color":
            v = ring_value(defn, fx.get("id", ""), first)
        elif a == "zoom" and "tight" in c:  # the show's zoom between the lens's tightest and widest
            v = round(c["tight"] + (c["wide"] - c["tight"]) * zoom_of(s))
        elif a.startswith("laser_") and "laser" in defn:
            v = _laser_value(a, defn["laser"], s)
        else:
            v = 0
        buf[addr] = min(max(int(v), 0), 255)  # a bad value in a definition must never stop the show


def test_light(buf: bytearray, fx: dict, level: float = 0.6, aim: tuple[float, float] | None = None) -> None:
    """Light one fixture for the light test (is it patched and connected?): every cell white at `level`, its
    emitters the show keeps dark (UV, amber…) lit too, heads centred (or at `aim`: pan and tilt, 0..1). Not for
    lasers and smoke machines."""
    defn = get(fx["fixture"])
    if inert(defn) or defn["kind"] == "smoke":
        raise ValueError(test_refusal(defn))
    if not patched(fx):
        return
    from amadeus.engine.state import State

    pan, tilt = aim or (0.5, 0.5)
    patch(buf, fx, {e["id"]: State(dimmer=level, r=1, g=1, b=1, pan=pan, tilt=tilt) for e in expand(fx)})
    chans = channels(defn, fx["mode"])
    has_dimmer = any(c["attr"] == "dimmer" for c in chans)
    cells_mixed = len(heads(defn, fx["mode"])) > 1 and not any(c["attr"] == "dimmer" and "head" in c for c in chans)
    # as patch scales the RGB (the dimmer sets the level), under the brightness limiter where the emitter carries it
    scale = min(level, limiter.level()) if cells_mixed or not has_dimmer else 1.0
    for off, c in enumerate(chans):
        if c["attr"] in DARK_EMITTERS and 0 <= fx["address"] - 1 + off < 512:
            buf[fx["address"] - 1 + off] = round(scale * 255)


LIGHT_ATTRS = ("dimmer", "red", "green", "blue", "white", "uv", "amber", "lime", "indigo")


def test_raw(buf: bytearray, fx: dict, raw: list[int], light: set[int] = frozenset()) -> None:
    """The DMX mapper's values, as they are, on one fixture's channels; the ones that carry light (the definition's
    and `light`, the channels the mapper gives a light role) kept under the brightness limiter."""
    if not patched(fx):
        return
    chans = channels(get(fx["fixture"]), fx["mode"])
    ceiling = round(limiter.level() * 255)
    for off, v in enumerate(raw[: len(chans)]):
        if 0 <= fx["address"] - 1 + off < 512:
            lit = off in light or chans[off]["attr"] in LIGHT_ATTRS
            buf[fx["address"] - 1 + off] = min(v, ceiling) if lit else v


def test_refusal(defn: dict) -> str:
    """Why the light test leaves this fixture alone ('' if it lights it)."""
    if inert(defn):
        return f"Not tested: {inert(defn)}."
    if defn.get("kind") == "smoke":
        return "Not tested: a smoke machine fires only in the show or the hardware test (amadeus test)."
    return ""


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
    """Out-of-range addresses: what a set can't be saved with. Overlaps are allowed while you patch (overlaps)."""
    problems = []
    for fx in rig["fixtures"]:
        if not patched(fx):
            continue
        n = footprint(fx)
        if fx["address"] < 1 or fx["address"] + n - 1 > 512:
            problems.append(f"{fx['id']}: channels {fx['address']}–{fx['address'] + n - 1} don't fit in a universe")
    return problems


def overlaps(rig: dict) -> list[str]:
    """Fixtures whose channels overlap: a warning, not a reason to refuse a save (moving fixtures around passes
    through overlaps). Fixtures without a start address overlap nothing."""
    problems, used = [], {}
    for fx in rig["fixtures"]:
        if not patched(fx):
            continue
        for ch in range(fx["address"], fx["address"] + footprint(fx)):
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
