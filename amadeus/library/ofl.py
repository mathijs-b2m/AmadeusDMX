"""Open Fixture Library (https://open-fixture-library.org, MIT): search and convert to our fixture format.

Every OFL fixture ships already converted in fixtures/catalog/ofl.json.gz (library/shadow.py); the OFL
itself is downloaded into .cache/ofl only to rebuild that or for a fixture newer than it. A fixture the user
adds is saved into fixtures/<manufacturer>/<model>.json, after which it is a normal library fixture.

Conversion rules (safety first): channels the engine drives get an attribute (dimmer, red/green/
blue/white, pan/tilt + fine, color_wheel, gobo (one wheel; its rotation), prism, frost, zoom); every other channel gets
a default that keeps the fixture quiet: shutter "Open", programs/effects/macros "no function".
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import urllib.request
from functools import cache
from pathlib import Path

from amadeus import paths
from amadeus.library import fixtures as fxlib

OFL_DIR = paths.CACHE / "ofl"
OFL_TARBALL = "https://codeload.github.com/OpenLightingProject/open-fixture-library/tar.gz/refs/heads/master"
INDEX = OFL_DIR / "index.json"
CONVERTER_VERSION = 5

COLOR_ATTR = {
    "Red": "red",
    "Green": "green",
    "Blue": "blue",
    "White": "white",
    "Warm White": "white",
    "Cold White": "white",
}
QUIET_TYPES = ("NoFunction",)


def ensure_downloaded() -> Path:
    if not (OFL_DIR / "fixtures").exists():
        print("Downloading the Open Fixture Library …")
        OFL_DIR.mkdir(parents=True, exist_ok=True)
        data = urllib.request.urlopen(OFL_TARBALL, timeout=120).read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for m in tar.getmembers():
                parts = m.name.split("/", 1)
                if len(parts) == 2 and (parts[1].startswith("fixtures/") or parts[1] == "LICENSE"):
                    m.name = parts[1]
                    tar.extract(m, OFL_DIR, filter="data")
    return OFL_DIR / "fixtures"


# ---------------------------------------------------------------- helpers


def _shift(ch: dict) -> int:
    """Bits to drop to get a channel's values in bytes: a 16-bit channel (it has a fine channel) gives its
    ranges and default in 16-bit values unless it says otherwise."""
    res = ch.get("dmxValueResolution")
    fine = len(ch.get("fineChannelAliases", []))
    bits = {"8bit": 8, "16bit": 16, "24bit": 24}.get(res, 8 + 8 * fine)
    return bits - 8


def _caps(ch: dict) -> list[dict]:
    if "capability" in ch:
        return [{**ch["capability"], "dmxRange": [0, 255]}]
    n = _shift(ch)
    caps = ch.get("capabilities", [])
    return [{**c, "dmxRange": [v >> n for v in c["dmxRange"]]} for c in caps] if n else caps


def _mid(cap: dict) -> int:
    lo, hi = cap.get("dmxRange", [0, 255])
    return (lo + hi) // 2


def _hex_rgb(h: str) -> list[float]:
    h = h.lstrip("#")
    return [round(int(h[i : i + 2], 16) / 255, 3) for i in (0, 2, 4)]


def _quiet_default(ch: dict) -> int:
    """A value that keeps an undriven channel harmless: shutter open, no function, no program."""
    caps = _caps(ch)
    for cap in caps:
        if cap["type"] == "ShutterStrobe" and cap.get("shutterEffect") == "Open":
            return _mid(cap)
    for cap in caps:
        if cap["type"] in QUIET_TYPES:
            return cap["dmxRange"][0]
    if "defaultValue" in ch and isinstance(ch["defaultValue"], int):
        return ch["defaultValue"] >> _shift(ch)
    return 0


def _cap_text(cap: dict) -> str:
    """What a capability does, in words (to find the range that keeps a laser or smoke machine off)."""
    t = cap.get("type", "")
    words = [cap.get("comment", ""), cap.get("effectName", ""), cap.get("shutterEffect", "")]
    if t == "NoFunction":
        words.append("no function")
    for k in ("brightness", "brightnessStart", "fogOutput", "fogOutputStart"):
        if str(cap.get(k, "")).lower() in ("off", "0%", "0"):
            words.append("off")
    return " ".join(w for w in words if w) or t


def _resolve_channel(d: dict, key: str) -> tuple[str, dict | None, str | None]:
    """Channel key → (base key, channel definition, fine-of) handling fine channel aliases."""
    chans = {**d.get("availableChannels", {}), **d.get("_expanded_templates", {})}
    if key in chans:
        return key, chans[key], None
    for base, ch in chans.items():
        if key in ch.get("fineChannelAliases", []):
            return base, ch, base
    return key, None, None


def _wheel_slots(d: dict, ch: dict, slot_type: str, key: str = ""):
    """WheelSlot capabilities of the given slot type with their DMX ranges, plus the 'open' capability. A capability
    that doesn't name its wheel is on the wheel named like the channel (OFL's rule), else the first."""
    wheels = d.get("wheels", {})
    out, open_cap = [], None
    for cap in _caps(ch):
        if cap["type"] != "WheelSlot" or "slotNumber" not in cap:
            continue
        wheel = wheels.get(cap.get("wheel", ch.get("name", key)), wheels.get(next(iter(wheels), ""), {}))
        n = cap["slotNumber"]
        if not isinstance(n, (int, float)) or n != int(n):
            continue  # split colours between two slots
        slots = wheel.get("slots", [])
        if not 1 <= int(n) <= len(slots):
            continue
        slot = slots[int(n) - 1]
        if slot.get("type") == "Open" and open_cap is None:
            open_cap = cap
        elif slot.get("type") == slot_type:
            out.append((slot, cap))
    return out, open_cap


def _gobo_image(slot: dict | None) -> str:
    """A gobo slot's picture in the gobo catalogue (library/gobos.py), "" if the library draws none."""
    res = (slot or {}).get("resource")
    return "ofl/" + res.split("/")[-1] if isinstance(res, str) and res.startswith("gobos/") else ""


def _slot(slots: list[dict], cap: dict) -> dict | None:
    n = cap.get("slotNumber")
    return slots[int(n) - 1] if isinstance(n, (int, float)) and n == int(n) and 1 <= n <= len(slots) else None


def _angle(v) -> float:
    """A zoom angle: "10deg", "narrow", "wide", "50%" → comparable numbers."""
    v = str(v).lower()
    if v in ("narrow", "small"):
        return 0.0
    if v in ("wide", "big"):
        return 1000.0
    m = re.match(r"([\d.]+)", v)
    return float(m.group(1)) if m else 0.0


def _rotation(caps: list[dict]) -> dict:
    """A rotation's DMX ranges, always [slow, fast]: {range: clockwise, reverse: counter-clockwise}."""
    spin = {}
    for c in caps:
        a, b = str(c.get("speedStart", "")).lower(), str(c.get("speedEnd", "")).lower()
        if not a or not b:
            continue
        key = "reverse" if "ccw" in a + b or "reverse" in a + b else "range"
        lo, hi = c["dmxRange"]
        spin.setdefault(key, [hi, lo] if a.startswith("fast") else [lo, hi])
    return spin


def _classify(d: dict, key: str, ch: dict | None, fine_of: str | None) -> dict:
    if ch is None:
        return {"attr": "unknown", "default": 0}
    if fine_of:
        base = _classify(d, fine_of, ch, None)["attr"]
        return {"attr": f"{base}_fine"} if base in ("pan", "tilt") else {"attr": f"{base}_fine", "default": 0}
    caps = _caps(ch)
    types = [c["type"] for c in caps]
    if len(caps) == 1:
        c = caps[0]
        if c["type"] == "Intensity":
            return {"attr": "dimmer"}
        if c["type"] == "ColorIntensity":
            attr = COLOR_ATTR.get(c.get("color", ""))
            return {"attr": attr} if attr else {"attr": c.get("color", "color").lower().replace(" ", "_"), "default": 0}
        if c["type"] in ("Pan", "Tilt"):
            return {"attr": c["type"].lower()}
    # a dimmer channel with extra ranges (e.g. 0-200 dimmer, 201-255 strobe): drive only the dimmer range
    dims = [c for c in caps if c["type"] == "Intensity"]
    if dims and (dims[0]["dmxRange"][1] - dims[0]["dmxRange"][0]) >= 128:
        return {"attr": "dimmer", "range": [dims[0]["dmxRange"][0], dims[0]["dmxRange"][1]]}
    if "WheelSlot" in types:
        colors, open_cap = _wheel_slots(d, ch, "Color", key)
        if colors:
            slots = [
                {
                    "name": "open",
                    "from": open_cap["dmxRange"][0] if open_cap else 0,
                    "to": open_cap["dmxRange"][1] if open_cap else 0,
                    "rgb": [1.0, 1.0, 1.0],
                }
            ]
            for slot, cap in colors:
                rgb = _hex_rgb(slot["colors"][0]) if slot.get("colors") else [1.0, 1.0, 1.0]
                slots.append(
                    {
                        "name": slot.get("name", "colour").lower(),
                        "from": cap["dmxRange"][0],
                        "to": cap["dmxRange"][1],
                        "rgb": rgb,
                    }
                )
            return {"attr": "color_wheel", "_slots": slots}
        gobos, open_cap = _wheel_slots(d, ch, "Gobo", key)
        if gobos:
            wheel = gobos[0][1].get("wheel", ch.get("name", key))
            slots = d.get("wheels", {}).get(wheel, {}).get("slots", [])
            shakes = [c for c in caps if c["type"] == "WheelShake"]
            return {
                "attr": "gobo",
                "default": open_cap["dmxRange"][0] if open_cap else 0,
                "_gobos": [_mid(cap) for _, cap in gobos],
                "_gobo_names": [slot.get("name", "") for slot, _ in gobos],
                "_gobo_images": [_gobo_image(slot) for slot, _ in gobos],
                "_shake": [_mid(c) for c in shakes],
                "_shake_images": [_gobo_image(_slot(slots, c)) for c in shakes],
                "_spin": [c["dmxRange"] for c in caps if c["type"] == "WheelRotation"],
                "_wheel": wheel,
            }
    if "WheelSlotRotation" in types:  # turns the gobo in its slot (a rotating gobo wheel)
        rot = [c for c in caps if c["type"] == "WheelSlotRotation"]
        stop = next((c for c in rot if str(c.get("speed", "")).lower() == "stop" or "angleStart" in c), None)
        return {
            "attr": "gobo_rotation",
            "default": stop["dmxRange"][0] if stop else _quiet_default(ch),
            "_rot": _rotation(rot),
            "_wheel": rot[0].get("wheel", ""),
        }
    zoom = [c for c in caps if c["type"] == "Zoom"]
    if zoom and all(c["type"] in ("Zoom", "NoFunction") for c in caps):
        z = zoom[0]
        lo, hi = z["dmxRange"]
        narrow_first = _angle(z.get("angleStart", z.get("angle", "narrow"))) <= _angle(z.get("angleEnd", "wide"))
        return {"attr": "zoom", "tight": lo if narrow_first else hi, "wide": hi if narrow_first else lo}
    if "Prism" in types:
        on = next((c for c in caps if c["type"] == "Prism"), None)
        return {
            "attr": "prism",
            "default": _quiet_default(ch),
            "_on": _mid(on) if on else None,
            "_spin": [c["dmxRange"] for c in caps if c["type"] == "PrismRotation"],
        }
    if "Frost" in types:
        on = [c for c in caps if c["type"] == "Frost"]
        return {"attr": "frost", "default": _quiet_default(ch), "_on": on[-1]["dmxRange"][1] if on else None}
    name = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_") or "channel"
    return {"attr": name, "default": _quiet_default(ch)}


def _expand_mode(d: dict, mode: dict) -> list[tuple[str | None, int]]:
    """Mode channel list → [(channel key, head number 0 = whole fixture)], expanding matrix inserts."""
    pixel_keys: list[str] = []
    if "matrix" in d:
        m = d["matrix"]
        if "pixelKeys" in m:
            pixel_keys = [k for z in m["pixelKeys"] for y in z for k in y if k]
        elif "pixelCount" in m:
            x, y, z = m["pixelCount"]
            pixel_keys = [str(i + 1) for i in range(x * y * z)]
    out = []
    for entry in mode.get("channels", []):
        if entry is None:
            out.append((None, 0))
        elif isinstance(entry, str):
            out.append((entry, 0))
        elif isinstance(entry, dict) and entry.get("insert") == "matrixChannels":
            keys = (
                pixel_keys
                if entry.get("repeatFor") in ("eachPixel", "eachPixelXYZ", "eachPixelYXZ", "eachPixelZXY")
                else list(entry.get("repeatFor", []))
            )
            if not isinstance(keys, list):
                keys = pixel_keys
            templates = entry.get("templateChannels", [])
            if entry.get("channelOrder") == "perChannel":
                pairs = [(t, k) for t in templates for k in keys]
            else:
                pairs = [(t, k) for k in keys for t in templates]
            for t, k in pairs:
                if t is None:
                    out.append((None, 0))
                    continue
                name = t.replace("$pixelKey", str(k))
                d.setdefault("_expanded_templates", {})[name] = d.get("templateChannels", {}).get(t, {})
                head = pixel_keys.index(k) + 1 if k in pixel_keys else 0
                out.append((name, head))
    return out


def convert(manufacturer_key: str, fixture_key: str) -> dict:
    """OFL fixture → our fixture definition (not yet saved)."""
    base = ensure_downloaded()
    d = json.loads((base / manufacturer_key / f"{fixture_key}.json").read_text(encoding="utf-8"))
    if "redirectTo" in d:  # an alias (renamed, or sold under another brand): the fixture it points to
        target = convert(*d["redirectTo"].split("/", 1))
        return {**target, "model": d.get("name", target["model"])}
    mans = json.loads((base / "manufacturers.json").read_text(encoding="utf-8"))
    cats = d.get("categories", [])
    kind = (
        "laser"
        if "Laser" in cats
        else "smoke"
        if {"Smoke", "Hazer"} & set(cats)
        else "moving_head"
        if {"Moving Head", "Scanner"} & set(cats)
        else "par_bar"
        if "matrix" in d or "Pixel Bar" in cats
        else "strobe"
        if "Strobe" in cats and "Color Changer" not in cats
        else "blinder"
        if "Blinder" in cats
        else "par"
    )
    dark, unsafe = kind in ("laser", "smoke"), []
    focus = d.get("physical", {}).get("focus", {})
    lens = d.get("physical", {}).get("lens", {})
    out = {
        "manufacturer": mans.get(manufacturer_key, {}).get("name", manufacturer_key),
        "model": d["name"],
        "kind": kind,
        "source": f"Open Fixture Library ({manufacturer_key}/{fixture_key}), converted automatically: "
        f"check it once with `amadeus test`",
        "ofl": {"key": f"{manufacturer_key}/{fixture_key}", "categories": cats, "converter": CONVERTER_VERSION},
        "physical": {
            "pan_deg": focus.get("panMax", 540),
            "tilt_deg": focus.get("tiltMax", 270),
            "beam_deg": (lens.get("degreesMinMax") or [25])[0],
            **(
                {"beam_deg_max": lens["degreesMinMax"][1]}
                if len(lens.get("degreesMinMax") or []) > 1 and lens["degreesMinMax"][1] > lens["degreesMinMax"][0]
                else {}
            ),
            **({"size_mm": d["physical"]["dimensions"]} if d.get("physical", {}).get("dimensions") else {}),
        },
        "modes": {},
    }
    wheel_slots, beam_fx, gobo_names, images = None, {"open": {}}, None, {}
    for mode in d.get("modes", []):
        specs, heads = [], []
        for key, head in _expand_mode(d, mode):
            if key is None:
                specs.append({"attr": "unused", "default": 0})
                heads.append(head)
                continue
            _, ch, fine_of = _resolve_channel(d, key)
            spec = _classify(d, key, ch, fine_of)
            if dark and ch is not None:
                spec = {"attr": spec["attr"]}  # held at its off value
                spec["default"], safe = fxlib.off_value(key, [(c["dmxRange"][0], _cap_text(c)) for c in _caps(ch)])
                if not safe:
                    unsafe.append(key)
                if kind == "smoke":  # the output and the fan are played (engine/fog.py)
                    have = any(c["attr"] == "fog" for c in specs)
                    full = [(c["dmxRange"][0], c["dmxRange"][1], _cap_text(c)) for c in _caps(ch)]
                    output = any(c.get("type") == "FogOutput" for c in _caps(ch))
                    spec = fxlib.smoke_channel("output" if output else key, full, have) or spec
            specs.append(spec)
            heads.append(head)
        # the gobo wheel the show drives: the one a rotation channel turns, else the first; the others stay open
        wheels = [sp for sp in specs if sp["attr"] == "gobo" and sp.get("_gobos")]
        rot = next((sp for sp in specs if sp["attr"] == "gobo_rotation" and sp.get("_rot")), None)
        wheel = next((w for w in wheels if rot and w["_wheel"] == rot["_wheel"]), wheels[0] if wheels else None)
        chans = []
        for spec, head in zip(specs, heads):
            if "_slots" in spec:
                wheel_slots = wheel_slots or spec.pop("_slots")
                spec.pop("_slots", None)
            if spec is wheel:
                beam_fx["gobo"] = {"gobo": spec["_gobos"]}
                gobo_names = gobo_names or spec["_gobo_names"]
                images.setdefault("gobo", spec["_gobo_images"])
                if spec.get("_shake"):
                    beam_fx["gobo_shake"] = {"gobo": spec["_shake"]}
                    images.setdefault("gobo_shake", spec["_shake_images"])
                if spec.get("_spin"):
                    lo, hi = spec["_spin"][0]
                    beam_fx["gobo_spin"] = {"gobo": {"range": [lo, hi]}}
                if rot and rot["_wheel"] == spec["_wheel"]:
                    turn = rot["_rot"] if "range" in rot["_rot"] else {"range": rot["_rot"]["reverse"]}
                    beam_fx["gobo_rotate"] = {"gobo": spec["_gobos"], "gobo_rotation": turn}
                    images.setdefault("gobo_rotate", spec["_gobo_images"])
            elif spec["attr"] == "gobo":  # another wheel: left open
                spec = {"attr": "gobo_wheel", "default": spec.get("default", 0)}
            if spec["attr"] == "prism" and spec.get("_on") is not None:
                beam_fx["prism"] = {"prism": spec["_on"]}
                if spec.get("_spin"):
                    lo, hi = spec["_spin"][0]
                    beam_fx["prism_spin"] = {"prism": {"range": [lo, hi]}}
            if spec["attr"] == "frost" and spec.get("_on") is not None:
                beam_fx["frost"] = {"frost": spec["_on"]}
            spec = {k: v for k, v in spec.items() if not k.startswith("_")}
            if head:
                spec["head"] = head
            chans.append(spec)
        name = mode.get("shortName") or mode.get("name") or f"{len(chans)}ch"
        out["modes"][name] = chans
    if dark:
        if kind == "smoke" and any(c["attr"] == "fog" for m in out["modes"].values() for c in m):
            watts = d.get("physical", {}).get("power")
            if watts:
                out["physical"]["watts"] = watts
            fxlib.mark_smoke(out, haze="Hazer" in cats)
        else:
            fxlib.mark_inert(out, unsafe)
        return out
    _refine(out, d)
    if wheel_slots:
        out["color_wheel"] = {
            "verified": True,
            "_note": "Slot colours from the Open Fixture Library.",
            "slots": wheel_slots,
        }
    if len(beam_fx) > 1:
        out["beam_fx"] = beam_fx
    if gobo_names and any(gobo_names):
        out["gobo_names"] = gobo_names
    if any(any(v) for v in images.values()):
        out["gobo_images"] = images
    if out["kind"] in fxlib.MOVING:
        out["motion"] = {
            "estimated": True,
            "pan_speed_dps": 200,
            "tilt_speed_dps": 160,
            "accel_dps2": 800,
            "_note": "Estimated; measure with `amadeus motion`.",
        }
    return out


def _refine(out: dict, d: dict):
    """What the channels say it is (the categories are loose), and its brightness."""
    attrs = {c["attr"] for m in out["modes"].values() for c in m}
    phys = out["physical"]
    if {"pan", "tilt"} <= attrs:
        out["kind"] = "moving_head"
    elif "tilt" in attrs:
        out["kind"] = "moving_bar"  # cells on one tilting bar
        phys["pan_deg"] = 0
    elif out["kind"] == "moving_head":  # a "moving head" without pan and tilt (e.g. an effect light)
        out["kind"] = "par"
    if out["kind"] not in fxlib.MOVING:
        phys.pop("pan_deg", None)
        phys.pop("tilt_deg", None)
    lumens = d.get("physical", {}).get("bulb", {}).get("lumens") or 0
    watts = d.get("physical", {}).get("power") or 0
    if lumens >= 100:
        phys["lumens"] = int(lumens)
    elif watts:  # LED fixtures make roughly 20 lm per watt
        phys["lumens"] = int(watts * 20)
        phys["_lumens_note"] = "estimated from the power (20 lm/W)"


# ---------------------------------------------------------------- search


def _tokens(s: str) -> list[str]:
    s = s.lower()
    return [t for t in re.split(r"[^a-z0-9]+|(?<=[a-z])(?=[0-9])|(?<=[0-9])(?=[a-z])", s) if t]


@cache
def index() -> list[dict]:
    """Searchable list of all OFL fixtures (built once, cached on disk)."""
    if INDEX.exists():
        data = json.loads(INDEX.read_text(encoding="utf-8"))
        if data.get("version") == CONVERTER_VERSION:
            return data["fixtures"]
    base = ensure_downloaded()
    mans = json.loads((base / "manufacturers.json").read_text(encoding="utf-8"))
    items = []
    for path in sorted(base.glob("*/*.json")):
        mk, fk = path.parent.name, path.stem
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            modes = {}
            for mode in d.get("modes", []):
                modes[mode.get("shortName") or mode.get("name")] = len(_expand_mode(d, mode))
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
        items.append(
            {
                "key": f"ofl:{mk}/{fk}",
                "manufacturer": mans.get(mk, {}).get("name", mk),
                "model": d.get("name", fk),
                "categories": d.get("categories", []),
                "modes": modes,
            }
        )
    INDEX.write_text(json.dumps({"version": CONVERTER_VERSION, "fixtures": items}), encoding="utf-8")
    return items


def search(query: str, limit: int = 15) -> list[dict]:
    """Our own library first, then the OFL; scored by how many query words match (prefix) brand/model."""
    q = _tokens(query)
    if not q:
        return []
    candidates = []
    for key, d in fxlib.library().items():
        candidates.append(
            {
                "key": key,
                "manufacturer": d["manufacturer"],
                "model": d["model"],
                "categories": [d["kind"].replace("_", " ")],
                "modes": {m: len(c) for m, c in d["modes"].items()},
                "local": True,
            }
        )
    local_models = {(_tokens(c["manufacturer"] + c["model"]).__str__()) for c in candidates}
    candidates += [c for c in index() if _tokens(c["manufacturer"] + c["model"]).__str__() not in local_models]
    scored = []
    for c in candidates:
        words = _tokens(f"{c['manufacturer']} {c['model']}")
        hay = " ".join(words)
        hits = sum(1 for t in q if any(w.startswith(t) for w in words) or t in hay.replace(" ", ""))
        if hits:
            exact = sum(1 for t in q if t in words)
            scored.append((hits / len(q), exact, c.get("local", False), -len(words), c))
    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)
    return [c for s, *_, c in scored if s >= 0.5][:limit]


def add_to_library(ofl_key: str) -> str:
    """Convert an OFL fixture into your fixtures and return its library key."""
    mk, fk = ofl_key.removeprefix("ofl:").split("/", 1)
    key = f"{mk}/{fk}"
    if key not in fxlib.library():
        from amadeus.library import shadow

        fxlib.save(key, shadow.get(f"ofl:{key}") or convert(mk, fk))
    return key
