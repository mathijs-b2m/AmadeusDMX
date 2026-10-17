"""QLC+ fixture library (https://github.com/mcallegari/qlcplus, Apache-2.0): search and convert.

QLC+ ships ~1,800 fixture definitions (.qxf XML) — more than the Open Fixture Library for many DJ
brands (e.g. beamZ, Ayra, Showtec). The fixture folder is fetched once with a sparse git checkout
(~18 MB, a few seconds) into .cache/qlcplus, only to rebuild fixtures/catalog/ (tools/build_catalog.py) or
for a fixture newer than it. Conversion follows the same safety rules as
the OFL converter: driven channels get an attribute, everything else a quiet default (shutter open,
programs and macros off).
"""

from __future__ import annotations

import functools
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from functools import cache
from pathlib import Path

from amadeus import paths
from amadeus.library import fixtures as fxlib

QLC_DIR = paths.CACHE / "qlc"
REPO_DIR = paths.CACHE / "qlcplus"
FIXTURES_DIR = REPO_DIR / "resources" / "fixtures"
REPO_URL = "https://github.com/mcallegari/qlcplus.git"
RAW_URL = "https://raw.githubusercontent.com/mcallegari/qlcplus/master/resources/fixtures/{path}"
NS = {"q": "http://www.qlcplus.org/FixtureDefinition"}
CONVERTER_VERSION = 7

PRESET_ATTR = {
    "IntensityMasterDimmer": "dimmer",
    "IntensityDimmer": "dimmer",
    "IntensityRed": "red",
    "IntensityGreen": "green",
    "IntensityBlue": "blue",
    "IntensityWhite": "white",
    "PositionPan": "pan",
    "PositionPanFine": "pan_fine",
    "PositionTilt": "tilt",
    "PositionTiltFine": "tilt_fine",
    "IntensityDimmerFine": "dimmer_fine",
    "IntensityMasterDimmerFine": "dimmer_fine",
    "IntensityCyan": "cyan",
    "IntensityMagenta": "magenta",
    "IntensityYellow": "yellow",
}
# Colour emitters the show does not drive (yet): kept dark.
QUIET_INTENSITY = {
    "IntensityAmber",
    "IntensityUV",
    "IntensityLime",
    "IntensityIndigo",
    "IntensityRedFine",
    "IntensityGreenFine",
    "IntensityBlueFine",
    "IntensityWhiteFine",
    "IntensityAmberFine",
    "IntensityUVFine",
    "IntensityCyanFine",
    "IntensityMagentaFine",
    "IntensityYellowFine",
}
QUIET_PRESETS = ("ShutterOpen",)


TYPES = {  # QLC+ <Type> → our fixture types (also used to narrow photo recognition)
    "Moving Head": "moving head",
    "Scanner": "scanner",
    "Color Changer": "par",
    "Dimmer": "par",
    "LED Bar (Beams)": "led bar",
    "LED Bar (Pixels)": "led bar",
    "Strobe": "strobe",
    "Laser": "laser",
    "Flower": "effect",
    "Effect": "effect",
    "Smoke": "smoke",
    "Hazer": "smoke",
    "Fan": "other",
    "Other": "other",
}
LOOKS = ("beam", "spot", "wash", "hybrid", "profile")


def _tag(xml: str, tag: str) -> str:
    """The text of the first <tag>…</tag> in a QLC+ definition ('' if absent)."""
    m = re.search(f"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m[1].strip() if m else ""


def ensure_downloaded() -> Path:
    if not FIXTURES_DIR.exists():
        import subprocess

        REPO_DIR.parent.mkdir(parents=True, exist_ok=True)
        print("Fetching the QLC+ fixture library (once, ~18 MB)…", flush=True)
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--filter=blob:none", "--sparse", REPO_URL, str(REPO_DIR)],
            check=True,
        )
        subprocess.run(["git", "-C", str(REPO_DIR), "sparse-checkout", "set", "resources/fixtures"], check=True)
    return FIXTURES_DIR


def _look(model: str, xml: str) -> str:
    """beam / spot / wash / hybrid for moving heads, from the name or else the channels."""
    words = model.lower()
    for look in LOOKS:
        if look in words:
            return "hybrid" if look == "profile" else look
    if '<Group Byte="0">Gobo</Group>' in xml:
        return "spot"
    return "wash" if "Zoom" in xml or "Intensity" in xml else ""


@cache
def index() -> list[dict]:
    """All QLC+ fixtures with brand, model and type (read from the files), cached on disk."""
    path = QLC_DIR / "index.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == CONVERTER_VERSION:
            return data["fixtures"]
    base = ensure_downloaded()
    items = []
    for f in sorted(base.glob("*/*.qxf")):
        xml = f.read_text(errors="replace", encoding="utf-8")
        get = functools.partial(_tag, xml)
        ftype = TYPES.get(get("Type"), "other")
        item = {
            "key": f"qlc:{f.parent.name}/{f.name}",
            "manufacturer": get("Manufacturer") or f.parent.name,
            "model": get("Model") or f.stem,
            "type": ftype,
        }
        if ftype == "moving head":
            item["look"] = _look(item["model"], xml)
        items.append(item)
    QLC_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CONVERTER_VERSION, "fixtures": items}), encoding="utf-8")
    return items


def _load(rel: str) -> ET.Element:
    local = FIXTURES_DIR / rel
    if not local.exists():
        try:
            ensure_downloaded()
        except Exception:  # noqa: BLE001 - no git: fetch just this file
            local = QLC_DIR / "files" / rel
            if not local.exists():
                local.parent.mkdir(parents=True, exist_ok=True)
                local.write_bytes(
                    urllib.request.urlopen(RAW_URL.format(path=urllib.request.quote(rel)), timeout=30).read()
                )
    return ET.parse(local).getroot()


def _text(el, tag):
    x = el.find(f"q:{tag}", NS)
    return x.text.strip() if x is not None and x.text else ""


def _hex_rgb(h: str) -> list[float]:
    h = h.lstrip("#")
    return [round(int(h[i : i + 2], 16) / 255, 3) for i in (0, 2, 4)] if len(h) >= 6 else [1.0, 1.0, 1.0]


def _caps(ch) -> list[dict]:
    out = []
    for c in ch.findall("q:Capability", NS):
        out.append(
            {
                "min": int(c.get("Min", 0)),
                "max": int(c.get("Max", 255)),
                "preset": c.get("Preset", ""),
                "res": c.get("Res1") or c.get("Res") or "",
                "name": (c.text or "").strip(),
            }
        )
    return out


def _quiet_default(caps: list[dict], default: int) -> int:
    for c in caps:
        if c["preset"] in QUIET_PRESETS or "open" in c["name"].lower() and "close" not in c["name"].lower():
            return (c["min"] + c["max"]) // 2 if c["preset"] == "ShutterOpen" else c["min"]
    for c in caps:
        n = c["name"].lower()
        if "no function" in n or n in ("none", "off", "nothing"):
            return c["min"]
    return default


def _classify(ch) -> dict:
    name = ch.get("Name", "")
    preset = ch.get("Preset", "")
    if preset in PRESET_ATTR:
        return {"attr": PRESET_ATTR[preset]}
    group = (ch.find("q:Group", NS).text or "").strip() if ch.find("q:Group", NS) is not None else ""
    caps = _caps(ch)
    default = int(ch.get("Default", 0))
    if preset in ("BeamZoomBigSmall", "BeamZoomSmallBig"):
        big_first = preset == "BeamZoomBigSmall"  # DMX 0 = widest
        return {"attr": "zoom", "tight": 255 if big_first else 0, "wide": 0 if big_first else 255}
    if preset == "BeamZoomFine":
        return {"attr": "zoom_fine", "default": 0}
    if preset in QUIET_INTENSITY:
        words = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", preset.removeprefix("Intensity"))
        return {"attr": words.lower(), "default": 0}  # IntensityUV → uv, IntensityRedFine → red_fine
    if group == "Intensity" or preset.startswith("Intensity"):
        colour = ch.find("q:Colour", NS)
        c = (colour.text or "").strip().lower() if colour is not None else ""
        if c in ("red", "green", "blue", "white", "cyan", "magenta", "yellow"):
            return {"attr": c}
        if c:
            return {"attr": c, "default": 0}
        if "dimmer" in name.lower() or "intensity" in name.lower():
            return {"attr": "dimmer_fine" if "fine" in name.lower() else "dimmer"}
        # an "Intensity" group channel that is not a dimmer (e.g. an effect setting): quiet
        return {
            "attr": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "channel",
            "default": _quiet_default(caps, default),
        }
    if group == "Pan":
        return {"attr": "pan_fine" if ch.find("q:Group", NS).get("Byte") == "1" else "pan"}
    if group == "Tilt":
        return {"attr": "tilt_fine" if ch.find("q:Group", NS).get("Byte") == "1" else "tilt"}
    if group == "Colour" and any(c["preset"] == "ColorMacro" for c in caps):
        open_c = next((c for c in caps if c["name"].lower().startswith("open") or c["name"].lower() == "white"), None)
        slots = [
            {
                "name": "open",
                "from": open_c["min"] if open_c else 0,
                "to": open_c["max"] if open_c else 0,
                "rgb": [1.0, 1.0, 1.0],
            }
        ]
        for c in caps:
            if c["preset"] == "ColorMacro" and c is not open_c and c["res"].startswith("#"):
                slots.append({"name": c["name"].lower(), "from": c["min"], "to": c["max"], "rgb": _hex_rgb(c["res"])})
        return {"attr": "color_wheel", "_slots": slots}
    if group == "Gobo":
        gobos = [c for c in caps if c["preset"] == "GoboMacro" and not c["name"].lower().startswith("open")]
        open_c = next((c for c in caps if c["name"].lower().startswith("open")), None)
        spin = [c for c in caps if "Rotation" in c["preset"] and "Stop" not in c["preset"]]
        return {
            "attr": "gobo",
            "default": open_c["min"] if open_c else 0,
            "_gobos": [(c["min"] + c["max"]) // 2 for c in gobos],
            "_gobo_names": [c["name"] for c in gobos],
            "_shake": [(c["min"] + c["max"]) // 2 for c in caps if c["preset"] == "GoboShakeMacro"],
            "_spin": [[c["min"], c["max"]] for c in spin[:1]],
        }
    if group == "Prism":
        on = next((c for c in caps if c["preset"] == "PrismEffectOn"), None)
        off = next((c for c in caps if c["preset"] == "PrismEffectOff"), None)
        cw = next((c for c in caps if c["preset"].startswith("RotationClockwise")), None)
        ccw = next((c for c in caps if c["preset"].startswith("RotationCounterClockwise")), None)
        spin = {}
        for key, c in (("range", cw), ("reverse", ccw)):
            if c:  # always [slow, fast]
                spin[key] = [c["max"], c["min"]] if "FastToSlow" in c["preset"] else [c["min"], c["max"]]
        return {
            "attr": "prism",
            "default": (off["min"] + off["max"]) // 2 if off else _quiet_default(caps, default),
            "_on": (on["min"] + on["max"]) // 2 if on else None,
            "_spin": spin,
        }
    if group == "Speed":  # pan/tilt speed: run the motors at full speed, the engine times the moves itself
        fast = next((c for c in caps if "fast" in c["name"].lower()), None)
        v = default if fast is None else fast["min"] if "fast to slow" in fast["name"].lower() else fast["max"]
        return {"attr": re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "speed", "default": v}
    if group == "Beam" and "frost" in name.lower():
        inn = [c for c in caps if "in" in c["name"].lower().split()]
        return {
            "attr": "frost",
            "default": _quiet_default(caps, default),
            "_on": (inn[-1]["min"] + inn[-1]["max"]) // 2 if inn else None,
        }
    if group == "Shutter":
        return {"attr": "shutter", "default": _quiet_default(caps, default)}
    attr = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "channel"
    return {"attr": attr, "default": _quiet_default(caps, default)}


def convert(rel: str) -> dict:
    root = _load(rel)
    channels = {ch.get("Name"): ch for ch in root.findall("q:Channel", NS)}
    ftype = _text(root, "Type")
    kind = {"Moving Head": "moving_head", "Scanner": "moving_head", "Laser": "laser", "Smoke": "smoke"}.get(
        "Smoke" if ftype == "Hazer" else ftype, "par"
    )
    dark = kind in ("laser", "smoke")  # never driven: every channel off (fixtures.inert)
    unsafe: list[str] = []
    out = {
        "manufacturer": _text(root, "Manufacturer"),
        "model": _text(root, "Model"),
        "kind": kind,
        "source": f"QLC+ fixture library ({rel}), converted automatically: check it once with `amadeus test`",
        "qlc": {"key": rel, "type": ftype, "converter": CONVERTER_VERSION},
        "physical": {"pan_deg": 540, "tilt_deg": 270, "beam_deg": 25},
        "modes": {},
    }
    wheel_slots, beam_fx, gobo_names = None, {"open": {}}, None
    for mode in root.findall("q:Mode", NS):
        phys = mode.find("q:Physical", NS)
        phys = phys if phys is not None else root.find("q:Physical", NS)
        if phys is not None and phys.find("q:Focus", NS) is not None:
            f = phys.find("q:Focus", NS)
            out["physical"]["pan_deg"] = int(f.get("PanMax", 540)) or 540
            out["physical"]["tilt_deg"] = int(f.get("TiltMax", 270)) or 270
        if phys is not None and phys.find("q:Dimensions", NS) is not None:
            dm = phys.find("q:Dimensions", NS)
            size = [int(float(dm.get(k, 0))) for k in ("Width", "Height", "Depth")]
            if all(size):
                out["physical"]["size_mm"] = size
        if phys is not None and phys.find("q:Lens", NS) is not None:
            lens = phys.find("q:Lens", NS)
            lo, hi = float(lens.get("DegreesMin", 25) or 25), float(lens.get("DegreesMax", 0) or 0)
            out["physical"]["beam_deg"] = lo
            if hi > lo:
                out["physical"]["beam_deg_max"] = hi  # zoom range
        if phys is not None:
            bulb, tech = phys.find("q:Bulb", NS), phys.find("q:Technical", NS)
            lumens = int(float(bulb.get("Lumens", 0) or 0)) if bulb is not None else 0
            watts = int(float(tech.get("PowerConsumption", 0) or 0)) if tech is not None else 0
            if watts:
                out["physical"]["watts"] = watts
            if lumens >= 100:  # some library files have nonsense like "2"
                out["physical"]["lumens"] = lumens
            elif watts and ftype != "Laser":  # estimate: LED fixtures make roughly 20 lm per watt
                out["physical"]["lumens"] = watts * 20
                out["physical"]["_lumens_note"] = "estimated from the power (20 lm/W)"
        order = {int(c.get("Number")): c.text.strip() for c in mode.findall("q:Channel", NS)}
        heads = [[int(x.text) for x in h.findall("q:Channel", NS)] for h in mode.findall("q:Head", NS)]
        head_of = {n: i + 1 for i, h in enumerate(heads) for n in h} if len(heads) > 1 else {}
        chans = []
        for n in range(len(order)):
            ch = channels.get(order.get(n))
            spec = _classify(ch) if ch is not None else {"attr": "unused", "default": 0}
            if dark and ch is not None:
                caps = [(c["min"], c["name"]) for c in _caps(ch)]
                spec = {"attr": spec["attr"]}  # held at its off value
                spec["default"], safe = fxlib.off_value(ch.get("Name", ""), caps)
                if not safe:
                    unsafe.append(ch.get("Name", ""))
                if kind == "smoke":  # the output and the fan are played (engine/fog.py)
                    have = any(c["attr"] == "fog" for c in chans)
                    full = [(c["min"], c["max"], c["name"]) for c in _caps(ch)]
                    spec = fxlib.smoke_channel(ch.get("Name", ""), full, have) or spec
            if spec.get("_slots"):
                wheel_slots = wheel_slots or spec["_slots"]
            if spec["attr"] == "gobo":
                if spec.get("_gobos"):
                    beam_fx["gobo"] = {"gobo": spec["_gobos"]}
                    gobo_names = gobo_names or spec["_gobo_names"]
                if spec.get("_shake"):
                    beam_fx["gobo_shake"] = {"gobo": spec["_shake"]}
                if spec.get("_spin"):
                    beam_fx["gobo_spin"] = {"gobo": {"range": spec["_spin"][0]}}
            if spec["attr"] == "prism" and spec.get("_on") is not None:
                beam_fx["prism"] = {"prism": spec["_on"]}
                if spec.get("_spin"):
                    beam_fx["prism_spin"] = {
                        "prism": spec["_spin"] if "range" in spec["_spin"] else {"range": spec["_spin"]["reverse"]}
                    }
            if spec["attr"] == "frost" and spec.get("_on") is not None:
                beam_fx["frost"] = {"frost": spec["_on"]}
            spec = {k: v for k, v in spec.items() if not k.startswith("_")}
            if n in head_of and spec["attr"] in ("red", "green", "blue", "white", "dimmer", *fxlib.DARK_EMITTERS):
                spec["head"] = head_of[n]
            chans.append(spec)
        out["modes"][
            re.sub(r"\s*channels?\b", "ch", mode.get("Name", f"{len(chans)}ch"), flags=re.I).replace(" ", "")
        ] = chans
    if wheel_slots:
        out["color_wheel"] = {"verified": True, "_note": "Slot colours from the QLC+ library.", "slots": wheel_slots}
    if len(beam_fx) > 1:
        out["beam_fx"] = beam_fx
    if gobo_names:
        out["gobo_names"] = gobo_names
    if dark:
        for k in ("beam_fx", "color_wheel", "gobo_names"):
            out.pop(k, None)
        if kind == "smoke" and any(c["attr"] == "fog" for m in out["modes"].values() for c in m):
            fxlib.mark_smoke(out, haze=ftype == "Hazer" or "haz" in out["model"].lower())
        else:
            fxlib.mark_inert(out, unsafe)
        return out
    _refine(out, ftype)
    if out["kind"] in ("moving_head", "moving_bar"):
        out["motion"] = {
            "estimated": True,
            "pan_speed_dps": 200,
            "tilt_speed_dps": 160,
            "accel_dps2": 800,
            "_note": "Estimated; measure with `amadeus motion`.",
        }
    return out


def _refine(out: dict, ftype: str):
    """What kind of fixture this really is, from its channels (QLC+ types are loose: a DTS Katana is an
    "LED Bar (Beams)", a MAC Aura's beam and backlight are two "heads"), and lens and colour fix-ups."""
    attrs = {c["attr"] for m in out["modes"].values() for c in m}
    multi = any(len({c.get("head") for c in m if c.get("head")}) > 1 for m in out["modes"].values())
    phys = out["physical"]
    if "pan" in attrs and "tilt" in attrs:
        out["kind"] = "moving_head"
        for m in out["modes"].values():  # one beam: cells of a moving head (beam + aura) light together
            for c in m:
                c.pop("head", None)
    elif "tilt" in attrs:
        out["kind"] = "moving_bar"  # cells on one tilting bar (DTS Katana, COLORband PiX-M)
        phys["pan_deg"] = 0
    elif ftype == "Strobe":
        out["kind"] = "strobe"
    elif multi:
        out["kind"] = "par_bar"
    if out["kind"] not in ("moving_head", "moving_bar"):
        phys.pop("pan_deg", None)
        phys.pop("tilt_deg", None)
    # lenses: QLC+ often says 0° (a beam light's "0–3.8°", or no lens data for a strobe)
    lo, hi = float(phys.get("beam_deg", 0) or 0), float(phys.get("beam_deg_max", 0) or 0)
    if lo < 1.0:
        phys["beam_deg"] = 110.0 if out["kind"] == "strobe" else max(1.5, hi * 0.5) if hi else 25.0
        if hi and hi <= phys["beam_deg"]:
            phys.pop("beam_deg_max", None)
    # RGB(W) fixtures: the "colour wheel" channel is a macro that would override the mix: keep it off
    if {"red", "green", "blue"} <= attrs:
        for m in out["modes"].values():
            for c in m:
                if c["attr"] == "color_wheel":
                    c["attr"], c["default"] = "color_macro", 0
        out.pop("color_wheel", None)


def details(rel: str) -> dict:
    """Modes with channel counts (needs the definition file)."""
    d = convert(rel)
    return {
        "manufacturer": d["manufacturer"],
        "model": d["model"],
        "kind": d["kind"],
        "modes": {m: len(c) for m, c in d["modes"].items()},
    }


def add_to_library(qlc_key: str) -> str:
    from amadeus.library import shadow

    rel = qlc_key.removeprefix("qlc:")
    d = shadow.get(f"qlc:{rel}") or convert(rel)
    brand = re.sub(r"[^a-z0-9]+", "", d["manufacturer"].lower()) or "other"
    model = re.sub(r"[^a-z0-9]+", "-", d["model"].lower()).strip("-")
    key = f"{brand}/{model}"
    if key not in fxlib.library():
        fxlib.save(key, d)
    return key
