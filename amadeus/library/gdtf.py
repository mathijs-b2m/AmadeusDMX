"""GDTF fixture files (DIN SPEC 15800, https://gdtf.eu): convert a .gdtf the user has into our fixture format.

GDTF is what manufacturers publish for new fixtures (GDTF Share has ~10,000, a third from the makers
themselves), but its terms only allow downloads for personal reference and no derivative works: so GDTF
fixtures are never in the shipped catalogue (library/shadow.py). A user converts their own file here, and it
lands in their fixtures like any added fixture.

A .gdtf is a zip with description.xml: FixtureType → Wheels, DMXModes/DMXMode/DMXChannels/DMXChannel
(Offset "1,2" = coarse, fine) → LogicalChannel (Attribute) → ChannelFunction (DMXFrom "128/1") → ChannelSet.
Conversion follows the QLC+ and OFL converters' safety rules: channels the engine drives get an attribute
(dimmer, red/green/blue/white, pan/tilt + fine, color_wheel, gobo, prism, frost, zoom); every other channel
gets a default that keeps the fixture quiet (shutter open, no function, programs off); lasers stay dark.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from amadeus.library import fixtures as fxlib

CONVERTER_VERSION = 1

ATTR = {
    "Dimmer": "dimmer",
    "Pan": "pan",
    "Tilt": "tilt",
    "ColorAdd_R": "red",
    "ColorAdd_G": "green",
    "ColorAdd_B": "blue",
    "ColorAdd_W": "white",
    "ColorAdd_WW": "white",
    "ColorAdd_CW": "white",
    "ColorSub_C": "cyan",
    "ColorSub_M": "magenta",
    "ColorSub_Y": "yellow",
}
# colour emitters the show does not drive (yet): kept dark, as the other converters do
QUIET_COLOR = {
    "ColorAdd_UV": "uv",
    "ColorAdd_A": "amber",
    "ColorAdd_RY": "amber",
    "ColorAdd_L": "lime",
    "ColorAdd_GY": "lime",
    "ColorAdd_I": "indigo",
}
FOG_ATTRS = re.compile(r"^(Fog|Haze)\d*$")
OPEN_WORDS = re.compile(r"\bopen\b", re.I)
QUIET_WORDS = re.compile(r"\b(no function|off|nothing|none|stop|open|closed?|no prism|no frost|no gobo)\b", re.I)


def _dmx(value: str | None, bytes_: int = 1) -> int:
    """'128/1' → its value in bytes (8-bit); a 16-bit channel's '32768/2' → 128. '/1s' shifts, as GDTF says."""
    if not value:
        return 0
    v, _, n = value.partition("/")
    n = int(n.rstrip("s") or 1)
    v = int(v)
    if n > bytes_:  # a value given in more bytes than this channel has
        v >>= 8 * (n - bytes_)
    elif n < bytes_:  # stretch to the channel's bytes ("mirror": 255/1 in 16 bit = 65535; "s" shifts)
        v = v << 8 * (bytes_ - n) if value.endswith("s") else v * ((1 << 8 * bytes_) - 1) // ((1 << 8 * n) - 1)
    return min(v >> 8 * (bytes_ - 1), 255)


def _xyY_rgb(text: str) -> list[float]:
    """A wheel slot's CIE 1931 'x,y,Y' → normalised sRGB (brightest channel 1)."""
    try:
        x, y, _ = (float(t) for t in text.split(","))
    except ValueError:
        return [1.0, 1.0, 1.0]
    if y <= 0:
        return [1.0, 1.0, 1.0]
    X, Y, Z = x / y, 1.0, (1 - x - y) / y
    lin = [
        3.2406 * X - 1.5372 * Y - 0.4986 * Z,
        -0.9689 * X + 1.8758 * Y + 0.0415 * Z,
        0.0557 * X - 0.2040 * Y + 1.0570 * Z,
    ]
    lin = [max(c, 0.0) for c in lin]
    top = max(lin) or 1.0
    rgb = [c / top for c in lin]
    return [round(c**0.4545, 3) for c in rgb]


def _load(src: str | Path | bytes) -> tuple[ET.Element, str]:
    data = src if isinstance(src, bytes) else Path(src).read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("description.xml"))
    for el in root.iter():  # some files carry a namespace: drop it
        el.tag = el.tag.rpartition("}")[2]
    return root, root.get("DataVersion", "")


class _Channel:
    """One DMXChannel: its offsets, bytes, attribute and functions, values already in 8-bit."""

    def __init__(self, el: ET.Element, wheels: dict):
        offs = el.get("Offset") or "None"
        self.offsets = [] if offs == "None" else [int(o) for o in offs.split(",") if o.strip()]
        self.bytes = max(len(self.offsets), 1)
        self.geometry = el.get("Geometry", "")
        self.functions = []  # (attribute, from, name, wheel, sets[(from, name, slot index)], physical from/to)
        initial = el.get("InitialFunction", "")
        self.default = _dmx(el.get("Default"), self.bytes) if el.get("Default") else None  # GDTF 1.0
        for lc in el.findall("LogicalChannel"):
            for cf in lc.findall("ChannelFunction"):
                attr = cf.get("Attribute") or lc.get("Attribute", "")
                sets = [
                    (_dmx(s.get("DMXFrom"), self.bytes), s.get("Name", ""), int(s.get("WheelSlotIndex") or 0))
                    for s in cf.findall("ChannelSet")
                ]
                f = {
                    "attr": attr,
                    "from": _dmx(cf.get("DMXFrom"), self.bytes),
                    "name": cf.get("Name", ""),
                    "wheel": wheels.get(cf.get("Wheel", ""), []),
                    "sets": sets,
                    "phys": (float(cf.get("PhysicalFrom") or 0), float(cf.get("PhysicalTo") or 1)),
                }
                self.functions.append(f)
                if self.default is None and cf.get("Default") and initial.endswith(f".{f['name']}"):
                    self.default = _dmx(cf.get("Default"), self.bytes)
        self.functions.sort(key=lambda f: f["from"])
        for i, f in enumerate(self.functions):
            nxt = self.functions[i + 1]["from"] - 1 if i + 1 < len(self.functions) else 255
            f["to"] = max(nxt, f["from"])
        self.attr = self.functions[0]["attr"] if self.functions else ""

    def ranges(self) -> list[tuple[int, int, str]]:
        """Every value range with what it does in words: (from, to, text)."""
        out = []
        for f in self.functions:
            sets = sorted(f["sets"]) or [(f["from"], f["name"] or f["attr"], 0)]
            for i, (lo, name, _) in enumerate(sets):
                hi = sets[i + 1][0] - 1 if i + 1 < len(sets) else f["to"]
                out.append((lo, max(hi, lo), name or f["name"] or f["attr"]))
        return out

    def quiet(self) -> int:
        """A value that keeps an undriven channel harmless: shutter open, no function, its own default."""
        ranges = self.ranges()
        if self.attr.startswith("Shutter"):
            for lo, hi, text in ranges:
                if OPEN_WORDS.search(text):
                    return (lo + hi) // 2
            opens = [f for f in self.functions if re.fullmatch(r"Shutter\d*", f["attr"])]
            if opens:
                return opens[0]["to"]  # a plain "Shutter" function without sets: its top is open
        for lo, _, text in ranges:
            if QUIET_WORDS.search(text) and not re.search(r"\bon\b", text, re.I):
                return lo
        return self.default if self.default is not None else 0

    def by_attr(self, pattern: str) -> list[dict]:
        return [f for f in self.functions if re.fullmatch(pattern, f["attr"])]


def _slot_sets(f: dict) -> list[tuple[int, int, dict]]:
    """A wheel function's slots with their DMX range: [(from, to, slot)] (slot index 1 = first slot)."""
    sets = sorted(s for s in f["sets"] if s[2] > 0)
    out = []
    for i, (lo, _, idx) in enumerate(sets):
        hi = sets[i + 1][0] - 1 if i + 1 < len(sets) else f["to"]
        if idx <= len(f["wheel"]):
            out.append((lo, max(hi, lo), f["wheel"][idx - 1]))
    return out


def _classify(ch: _Channel, byte: int) -> dict:
    """What the engine does with this channel (byte 0 = coarse, 1 = fine)."""
    a = ch.attr  # only the first wheel, prism and frost are played: Gobo2 and the like stay put
    if byte:
        base = ATTR.get(a, re.sub(r"[^a-z0-9]+", "_", a.lower()).strip("_") or "channel")
        return {"attr": f"{base}_fine"} if base in ("pan", "tilt") else {"attr": f"{base}_fine", "default": 0}
    if a in ("Pan", "Tilt"):
        return {"attr": a.lower()}
    if a in QUIET_COLOR:
        return {"attr": QUIET_COLOR[a], "default": 0}
    if a in ATTR:
        dims = ch.by_attr(a)
        if a == "Dimmer" and len(ch.functions) > 1 and dims and dims[0]["to"] - dims[0]["from"] >= 128:
            return {"attr": "dimmer", "range": [dims[0]["from"], dims[0]["to"]]}  # e.g. 0-200 dim, then strobe
        return {"attr": ATTR[a]}
    if a == "Color1":
        f = ch.functions[0]
        slots = _slot_sets(f)
        opened = next(((lo, hi) for lo, hi, s in slots if OPEN_WORDS.search(s["name"])), (0, 0))
        out = [{"name": "open", "from": opened[0], "to": opened[1], "rgb": [1.0, 1.0, 1.0]}]
        for lo, hi, s in slots:
            if not OPEN_WORDS.search(s["name"]):
                out.append({"name": s["name"].lower() or "colour", "from": lo, "to": hi, "rgb": s["rgb"]})
        if len(out) > 1:
            return {"attr": "color_wheel", "_slots": out}
    if a == "Gobo1":
        f = ch.functions[0]
        slots = _slot_sets(f)
        gobos = [(lo, hi, s) for lo, hi, s in slots if not OPEN_WORDS.search(s["name"])]
        opened = next((lo for lo, _, s in slots if OPEN_WORDS.search(s["name"])), ch.quiet())
        shake = ch.by_attr(r"Gobo\d+SelectShake")
        spin = ch.by_attr(r"Gobo\d+(WheelSpin|SelectSpin)")
        return {
            "attr": "gobo",
            "default": opened,
            "_gobos": [(lo + hi) // 2 for lo, hi, _ in gobos],
            "_gobo_names": [s["name"] or f"gobo {i + 1}" for i, (_, _, s) in enumerate(gobos)],
            "_shake": [(s["from"] + s["to"]) // 2 for s in shake],
            "_spin": [[s["from"], s["to"]] for s in spin[:1]],
        }
    if a == "Prism1":
        on = next((lo for lo, _, text in ch.ranges() if not QUIET_WORDS.search(text)), None)
        spin = ch.by_attr(r"Prism\d+PosRotate|Prism\d+Rotate")
        return {
            "attr": "prism",
            "default": ch.quiet(),
            "_on": on,
            "_spin": {"range": [spin[0]["from"], spin[0]["to"]]} if spin else {},
        }
    if a == "Frost1":
        f = ch.functions[0]
        return {"attr": "frost", "default": ch.quiet(), "_on": f["to"]}
    if a == "Zoom":
        lo, hi = ch.functions[0]["phys"]
        return {"attr": "zoom", "tight": 0 if lo <= hi else 255, "wide": 255 if lo <= hi else 0}
    if a in ("PanTiltMSpeed", "PanMSpeed", "TiltMSpeed", "MSpeed", "PanTiltMTime"):
        return {"attr": re.sub(r"[^a-z0-9]+", "_", a.lower()), "default": 0}  # tracking: the engine times moves
    if a.startswith("Shutter"):
        return {"attr": "shutter", "default": ch.quiet()}
    return {"attr": re.sub(r"[^a-z0-9]+", "_", a.lower()).strip("_") or "channel", "default": ch.quiet()}


def _instances(geometries: ET.Element, mode_root: str) -> dict[str, list[tuple[int, str]]]:
    """Per referenced geometry (a pixel, a cell) its instances in this mode: [(DMX offset - 1, name)]."""
    root = next((g for g in geometries if g.get("Name") == mode_root), None)
    out: dict[str, list[tuple[int, str]]] = {}
    for ref in root.iter("GeometryReference") if root is not None else []:
        brk = ref.find("Break")
        offset = int(brk.get("DMXOffset", 1)) - 1 if brk is not None else 0
        out.setdefault(ref.get("Geometry", ""), []).append((offset, ref.get("Name", "")))
    return out


def _physical(root: ET.Element) -> dict:
    """Lens, brightness, power and size, from the beam geometries and the body's model."""
    beams = [g for g in root.iter("Beam")]
    phys: dict = {"beam_deg": 25.0}
    if beams:
        angles = [float(b.get("BeamAngle") or 0) for b in beams]
        if max(angles) >= 1:
            phys["beam_deg"] = max(angles)
        lumens = sum(float(b.get("LuminousFlux") or 0) for b in beams)
        watts = sum(float(b.get("PowerConsumption") or 0) for b in beams)
        if lumens >= 100:
            phys["lumens"] = int(lumens)
        elif watts:
            phys["lumens"] = int(watts * 20)
            phys["_lumens_note"] = "estimated from the power (20 lm/W)"
        if watts:
            phys["watts"] = int(watts)
    geos = root.find("Geometries")
    body = geos[0] if geos is not None and len(geos) else None
    model = next((m for m in root.iter("Model") if body is not None and m.get("Name") == body.get("Model")), None)
    if model is not None:
        size = [int(float(model.get(k) or 0) * 1000) for k in ("Width", "Height", "Length")]
        if all(size):
            phys["size_mm"] = size
    return phys


def convert(src: str | Path | bytes, name: str = "") -> dict:
    """A .gdtf file (path or bytes) → our fixture definition (not yet saved)."""
    root, version = _load(src)
    ft = root.find("FixtureType")
    wheels = {
        w.get("Name", ""): [
            {"name": s.get("Name", ""), "rgb": _xyY_rgb(s.get("Color", "")), "media": s.get("MediaFileName", "")}
            for s in w.findall("Slot")
        ]
        for w in ft.iter("Wheel")
    }
    geometries = ft.find("Geometries")
    attrs_all = {lc.get("Attribute", "") for lc in ft.iter("LogicalChannel")}
    laser = any(True for _ in ft.iter("Laser"))
    kind = (
        "laser"
        if laser
        else "smoke"
        if any(FOG_ATTRS.match(a) for a in attrs_all)
        else "moving_head"
        if {"Pan", "Tilt"} & attrs_all
        else "par"
    )
    dark, unsafe = kind in ("laser", "smoke"), []
    out = {
        "manufacturer": ft.get("Manufacturer", ""),
        "model": ft.get("LongName") or ft.get("Name", ""),
        "kind": kind,
        "source": f"GDTF file ({name or ft.get('Name', '')}, GDTF {version}), converted automatically: "
        "check it once with `amadeus test`",
        "gdtf": {"fixture_type_id": ft.get("FixtureTypeID", ""), "converter": CONVERTER_VERSION},
        "physical": {"pan_deg": 540, "tilt_deg": 270, **_physical(ft)},
        "modes": {},
    }
    wheel_slots, beam_fx, gobo_names = None, {"open": {}}, None
    for mode in ft.iter("DMXMode"):
        inst = _instances(geometries, mode.get("Geometry", "")) if geometries is not None else {}
        heads = [n for refs in inst.values() for _, n in refs]
        slots: dict[int, tuple[_Channel, int, int]] = {}  # address in the mode → (channel, byte, head)
        for el in mode.iter("DMXChannel"):
            ch = _Channel(el, wheels)
            if not ch.offsets:
                continue  # virtual channel
            for base, ref in inst.get(ch.geometry, [(0, "")]):
                head = heads.index(ref) + 1 if ref and len(heads) > 1 else 0
                for byte, off in enumerate(ch.offsets):
                    slots[base + off] = (ch, byte, head)
            if ch.attr == "Pan" and ch.functions:
                lo, hi = ch.functions[0]["phys"]
                out["physical"]["pan_deg"] = round(abs(hi - lo)) or 540
            if ch.attr == "Tilt" and ch.functions:
                lo, hi = ch.functions[0]["phys"]
                out["physical"]["tilt_deg"] = round(abs(hi - lo)) or 270
        chans = []
        for addr in range(1, max(slots, default=0) + 1):
            if addr not in slots:
                chans.append({"attr": "unused", "default": 0})
                continue
            ch, byte, head = slots[addr]
            spec = _classify(ch, byte)
            if dark:
                text = [(lo, t) for lo, _, t in ch.ranges()]
                spec = {"attr": spec["attr"]}  # held at its off value
                spec["default"], safe = fxlib.off_value(ch.attr, text)
                if not safe:
                    unsafe.append(ch.attr)
                if kind == "smoke" and not byte:  # the output and the fan are played (engine/fog.py)
                    have = any(c["attr"] == "fog" for c in chans)
                    name_ = "output" if FOG_ATTRS.match(ch.attr) else ch.attr
                    spec = fxlib.smoke_channel(name_, ch.ranges(), have) or spec
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
                    beam_fx["prism_spin"] = {"prism": spec["_spin"]}
            if spec["attr"] == "frost" and spec.get("_on") is not None:
                beam_fx["frost"] = {"frost": spec["_on"]}
            spec = {k: v for k, v in spec.items() if not k.startswith("_")}
            if head and spec["attr"] in ("red", "green", "blue", "white", "dimmer", *fxlib.DARK_EMITTERS):
                spec["head"] = head
            chans.append(spec)
        if chans:
            out["modes"][mode.get("Name") or f"{len(chans)}ch"] = chans
    if dark:
        if kind == "smoke" and any(c["attr"] == "fog" for m in out["modes"].values() for c in m):
            fxlib.mark_smoke(out, haze=any(a.startswith("Haze") for a in attrs_all))
        else:
            fxlib.mark_inert(out, unsafe)
        return out
    if wheel_slots:
        out["color_wheel"] = {"verified": True, "_note": "Slot colours from the GDTF file.", "slots": wheel_slots}
    if len(beam_fx) > 1:
        out["beam_fx"] = beam_fx
    if gobo_names:
        out["gobo_names"] = gobo_names
    _refine(out)
    if out["kind"] in fxlib.MOVING:
        out["motion"] = {
            "estimated": True,
            "pan_speed_dps": 200,
            "tilt_speed_dps": 160,
            "accel_dps2": 800,
            "_note": "Estimated; measure with `amadeus motion`.",
        }
    return out


def _refine(out: dict):
    """What the channels say it is: moving head, moving bar, pixel bar or par; RGB fixtures keep the wheel off."""
    attrs = {c["attr"] for m in out["modes"].values() for c in m}
    multi = any(len({c.get("head") for c in m if c.get("head")}) > 1 for m in out["modes"].values())
    phys = out["physical"]
    if {"pan", "tilt"} <= attrs:
        out["kind"] = "moving_head"
        for m in out["modes"].values():  # one beam: its cells light together
            for c in m:
                c.pop("head", None)
    elif "tilt" in attrs:
        out["kind"] = "moving_bar"
        phys["pan_deg"] = 0
    elif multi:
        out["kind"] = "par_bar"
    else:
        out["kind"] = "par"
    if out["kind"] not in fxlib.MOVING:
        phys.pop("pan_deg", None)
        phys.pop("tilt_deg", None)
    if {"red", "green", "blue"} <= attrs:
        for m in out["modes"].values():
            for c in m:
                if c["attr"] == "color_wheel":
                    c["attr"], c["default"] = "color_macro", 0
        out.pop("color_wheel", None)


def add_file(src: str | Path | bytes, name: str = "") -> str:
    """Convert a .gdtf file (path or bytes) into your fixtures and return its library key. Your copy only: GDTF
    content is never shipped. A fixture of that name from another library is kept; this one gets "-gdtf"."""
    d = convert(src, name or (Path(src).name if not isinstance(src, bytes) else ""))
    brand = re.sub(r"[^a-z0-9]+", "", d["manufacturer"].lower()) or "other"
    model = re.sub(r"[^a-z0-9]+", "-", d["model"].lower()).strip("-")
    key = f"{brand}/{model}"
    old = fxlib.library().get(key)
    if old is not None and "gdtf" not in old:
        key += "-gdtf"
    fxlib.save(key, d)
    return key
