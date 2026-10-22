"""DMXControl device definitions (DDF, https://ddf.dmxcontrol.de, CC BY-SA 4.0): convert to our fixture format.

The DDF library has ~1,500 devices, many of them DJ brands QLC+ and the OFL lack (Eurolite, Stairville,
ADJ, lightmaXX). Unlike GDTF its files may be redistributed (with credit, share-alike), so they can join the
shipped catalogue as their own CC BY-SA data file. This converts DMXControl 3 files: one XML per mode,
<functions> naming what each channel does (<dimmer>, <rgb>, <position>, <colorwheel>, <gobowheel>, …,
dmxchannel counted from 0), several files of one device merged into one fixture with a mode per file.

Same safety rules as the QLC+ and OFL converters: channels the engine drives get an attribute, every other
channel a quiet default (shutter open, no function). DDFs carry no fixture category, so lasers are found by
their words (model, channel names) and stay dark; a fixture with no light the show can dim is kept dark too.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

from amadeus import paths
from amadeus.library import fixtures as fxlib

API = "https://ddf.api.dmxc.org/v0/ddfs"
CONVERTER_VERSION = 2

COLORS = {
    **{c: c for c in ("red", "green", "blue", "white", "cyan", "magenta", "yellow")},
    **{"r": "red", "g": "green", "b": "blue", "w": "white", "c": "cyan", "m": "magenta", "y": "yellow"},
}
QUIET_COLORS = {"amber": "amber", "a": "amber", "uv": "uv", "lime": "lime", "indigo": "indigo"}
LASER_WORDS = re.compile(r"laser|ilda|x-?axis|y-?axis|drawing|pattern size", re.I)
QUIET_WORDS = re.compile(
    r"\b(no func\w*|keine funktion|off|aus|nothing|none|stop|open|offen|blackout|excluded|normal)\b", re.I
)
LIGHTS = ("dimmer", "red", "green", "blue", "white", "cyan", "magenta", "yellow")


def _int(el, key, default=0) -> int:
    try:
        return max(0, min(int(float(el.get(key, default))), 255))
    except (TypeError, ValueError):
        return default


def _hex_rgb(h: str) -> list[float]:
    h = (h or "").lstrip("#")
    return [round(int(h[i : i + 2], 16) / 255, 3) for i in (0, 2, 4)] if len(h) >= 6 else [1.0, 1.0, 1.0]


def _steps(el) -> list[tuple[int, int, str, str]]:
    """(from, to, type, caption) of a function's <step>s and <range>s, in DMX order."""
    out = []
    for s in el.iter():
        if s.tag in ("step", "range") and s.get("mindmx") is not None:
            lo, hi = sorted((_int(s, "mindmx"), _int(s, "maxdmx", 255)))
            out.append((lo, hi, s.get("type", ""), s.get("caption", "")))
    return sorted(out)


def _quiet(el, default: int = 0) -> int:
    """A value that keeps a channel the show doesn't drive harmless: open / no function / off, else default."""
    for lo, hi, typ, caption in _steps(el):
        if typ in ("open", "stop") or QUIET_WORDS.search(f"{typ} {caption}") and not re.search(r"\bon\b", caption):
            return (lo + hi) // 2 if typ == "open" and el.tag == "shutter" else lo
    return default


def _outside(el) -> int:
    """For a strobe channel: the first value outside its strobe ranges (no strobe)."""
    taken = [(lo, hi) for lo, hi, *_ in _steps(el)]
    v = 0
    for lo, hi in sorted(taken):
        if lo <= v <= hi:
            v = hi + 1
    return min(v, 255) if v <= 255 else 0


class _Mode:
    """One DDF file: the channels it fills, by DMX offset (from 0)."""

    def __init__(self, root: ET.Element):
        self.root = root
        self.ch: dict[int, dict] = {}
        self.wheel, self.gobo_names, self.beam_fx, self.unsafe = None, None, {"open": {}}, []
        self.dmx_count = int(root.get("dmxaddresscount") or 0)

    def put(self, n: str | None, spec: dict, override: bool = False):
        if n is None or not n.lstrip("-").isdigit():
            return
        i = int(n)
        if override or i not in self.ch or self.ch[i]["attr"] in ("strobe", "unknown"):
            self.ch[i] = spec

    def fine(self, el, base: str):
        if el.get("finedmxchannel") is not None:
            spec = {"attr": f"{base}_fine"} if base in ("pan", "tilt") else {"attr": f"{base}_fine", "default": 0}
            self.put(el.get("finedmxchannel"), spec)


def _functions(m: _Mode, funcs: ET.Element, head: int = 0):
    for el in funcs:
        tag, n = el.tag, el.get("dmxchannel")
        if tag == "position":
            for axis in ("pan", "tilt"):
                a = el.find(axis)
                if a is not None:
                    m.put(a.get("dmxchannel"), {"attr": axis}, override=True)
                    m.fine(a, axis)
        elif tag in ("rgb", "cmy"):
            for c in el:
                attr = COLORS.get(c.tag) or QUIET_COLORS.get(c.tag)
                if attr:
                    spec = {"attr": attr} if c.tag in COLORS else {"attr": attr, "default": 0}
                    if head:
                        spec["head"] = head
                    m.put(c.get("dmxchannel"), spec, override=True)
                    m.fine(c, attr)
        elif tag in COLORS or tag in QUIET_COLORS:  # a lone <white>/<amber>/<uv>
            spec = {"attr": COLORS.get(tag) or QUIET_COLORS[tag]}
            if tag in QUIET_COLORS:
                spec["default"] = 0
            m.put(n, spec, override=True)
        elif tag == "dimmer":
            steps = _steps(el)
            lo, hi = (steps[0][0], steps[-1][1]) if steps else (0, 255)
            spec = {"attr": "dimmer"} if (lo, hi) == (0, 255) else {"attr": "dimmer", "range": [lo, hi]}
            if head:
                spec["head"] = head
            m.put(n, spec, override=True)
            m.fine(el, "dimmer")
        elif tag == "strobe":
            m.put(n, {"attr": "strobe", "default": _outside(el)})
        elif tag == "shutter":
            m.put(n, {"attr": "shutter", "default": _quiet(el, 255)}, override=True)
        elif tag == "colorwheel":
            slots, opened = [], None
            for s in el.findall("step"):
                lo, hi = sorted((_int(s, "mindmx"), _int(s, "maxdmx", 255)))
                rgb = _hex_rgb(s.get("val", ""))
                name = (s.get("caption") or "colour").lower()
                if opened is None and (s.get("type") == "open" or rgb == [1.0, 1.0, 1.0] or "open" in name):
                    opened = (lo, hi)
                elif s.get("type") in ("color", "") and s.get("val"):
                    slots.append({"name": name, "from": lo, "to": hi, "rgb": rgb})
            if slots:
                o = opened or (0, 0)
                m.wheel = m.wheel or [{"name": "open", "from": o[0], "to": o[1], "rgb": [1.0, 1.0, 1.0]}, *slots]
                m.put(n, {"attr": "color_wheel"}, override=True)
            else:
                m.put(n, {"attr": "color_wheel_macro", "default": _quiet(el)})
        elif tag == "gobowheel":
            gobos = [s for s in el.findall("step") if s.get("type") == "gobo"]
            opened = next((s for s in el.findall("step") if s.get("type") == "open"), None)
            mids = [(_int(s, "mindmx") + _int(s, "maxdmx", 255)) // 2 for s in gobos]
            shake = [
                (_int(r, "mindmx") + _int(r, "maxdmx", 255)) // 2
                for s in gobos
                for r in s.findall("range")
                if r.get("handler") == "goboshake"
            ]
            spin = [r for r in el.iter("range") if r.get("type") in ("cw", "ccw")]
            m.put(n, {"attr": "gobo", "default": _int(opened, "mindmx") if opened is not None else 0}, override=True)
            if mids:
                m.beam_fx["gobo"] = {"gobo": mids}
                m.gobo_names = m.gobo_names or [s.get("caption") or f"gobo {i + 1}" for i, s in enumerate(gobos)]
            if shake:
                m.beam_fx["gobo_shake"] = {"gobo": shake}
            if spin:
                m.beam_fx["gobo_spin"] = {"gobo": {"range": sorted((_int(spin[0], "mindmx"), _int(spin[0], "maxdmx")))}}
            for sub in el:  # <goborotation>/<goboindex> name their own channel
                if sub.get("dmxchannel") is not None:
                    m.put(sub.get("dmxchannel"), {"attr": sub.tag, "default": _quiet(sub)})
        elif tag == "prism":
            on = next((s for s in el.findall("step") if s.get("type") == "prism"), None)
            m.put(n, {"attr": "prism", "default": _quiet(el)}, override=True)
            if on is not None:
                m.beam_fx["prism"] = {"prism": (_int(on, "mindmx") + _int(on, "maxdmx", 255)) // 2}
            for sub in el:
                if sub.get("dmxchannel") is not None:
                    m.put(sub.get("dmxchannel"), {"attr": "prism_rotation", "default": _quiet(sub)})
        elif tag == "frost":
            steps = _steps(el)
            lo, hi = (steps[0][0], steps[-1][1]) if steps else (0, 255)
            m.put(n, {"attr": "frost", "default": lo}, override=True)
            m.beam_fx["frost"] = {"frost": hi}
        elif tag == "zoom":
            r = el.find("range")
            wide_low = r is not None and float(r.get("minval") or 0) > float(r.get("maxval") or 1)
            lo, hi = (_int(r, "mindmx"), _int(r, "maxdmx", 255)) if r is not None else (0, 255)
            tight, wide = (hi, lo) if wide_low else (lo, hi)
            m.put(n, {"attr": "zoom", "tight": tight, "wide": wide}, override=True)
            m.fine(el, "zoom")
        elif tag == "ptspeed":  # run the motors at full speed: the engine times the moves itself
            r = el.find("range")
            fast = (
                _int(r, "maxdmx", 0)
                if r is not None and float(r.get("maxval") or 0) > float(r.get("minval") or 0)
                else (_int(r, "mindmx", 0) if r is not None else 0)
            )
            m.put(n, {"attr": "pt_speed", "default": fast})
        elif tag == "fog":
            m.put(n, {"attr": "fog_output", "_fog": _steps(el)}, override=True)
        elif tag == "const":
            m.put(n, {"attr": _name(el.get("name") or "const"), "default": _int(el, "val")}, override=True)
        elif tag == "matrix":
            for i, cell in enumerate(el, 1):
                _functions(m, [cell], head=i)
        elif n is not None:  # raw, rawstep, rawranges, focus, iris, colortemp, rotation, …
            name = el.get("name") or tag
            if LASER_WORDS.search(name):
                m.unsafe.append(name)  # marks it as a laser (see convert)
            default = _quiet(el)
            if tag == "iris":  # fully open: the end with the biggest value
                r = el.find("range")
                if r is not None:
                    default = _int(
                        r, "maxdmx" if float(r.get("maxval") or 1) >= float(r.get("minval") or 0) else "mindmx"
                    )
            m.put(n, {"attr": _name(name), "default": default, "_text": _steps(el)})
            m.fine(el, _name(name))


def _name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "channel"


def parse_mode(xml: bytes | str) -> tuple[dict, _Mode]:
    """One DDF file → (its information, the mode)."""
    root = ET.fromstring(xml)
    info = root.find("information")
    m = _Mode(root)
    funcs = root.find("functions")
    if funcs is not None:
        _functions(m, funcs)
    meta = {
        "manufacturer": (info.findtext("vendor") or "").strip(),
        "model": (info.findtext("model") or "").strip(),
        "author": (info.findtext("author") or "").strip(),
        "id": (info.findtext("ddf-library-id") or "").strip(),
        "mode": root.get("mode", "") or (info.findtext("mode") or "").strip(),
    }
    return meta, m


def convert(files: list[bytes | str], modes: list[str] | None = None) -> dict:
    """A device's DDF files (one per mode, DMXControl 3) → our fixture definition (not yet saved)."""
    parsed = [parse_mode(x) for x in files]
    meta = parsed[0][0]
    words = " ".join([meta["model"], *(n for _, m in parsed for n in m.unsafe)])
    attrs = {c["attr"] for _, m in parsed for c in m.ch.values()}
    kind = (
        "laser"
        if LASER_WORDS.search(words)
        else "smoke"
        if "fog_output" in attrs
        else "moving_head"
        if {"pan", "tilt"} <= attrs
        else "moving_bar"
        if "tilt" in attrs
        else "par_bar"
        if any(c.get("head") for _, m in parsed for c in m.ch.values())
        else "par"
    )
    if not attrs - {"unused"}:
        raise ValueError(f"DDF-{meta['id']}: no channels this converter understands (HSV, shorthand matrix)")
    # nothing to dim: a laser effect without "laser" in its words, an LED bar with only colour macros
    dim = kind != "smoke" and not attrs & set(LIGHTS)
    dark = kind in ("laser", "smoke") or dim
    authors = sorted({mt["author"] for mt, _ in parsed if mt["author"]})
    ids = [mt["id"] for mt, _ in parsed]
    out = {
        "manufacturer": meta["manufacturer"],
        "model": meta["model"],
        "kind": kind,
        "source": f"DMXControl DDF library (DDF-{', '.join(ids)}, by {', '.join(authors) or 'unknown'}, "
        "CC BY-SA 4.0), converted automatically: check it once with `amadeus test`",
        "ddf": {"ids": ids, "authors": authors, "license": "CC-BY-SA-4.0", "converter": CONVERTER_VERSION},
        "physical": {"pan_deg": 540, "tilt_deg": 270, "beam_deg": 25.0},
        "modes": {},
    }
    unsafe, wheel, gobo_names, beam_fx = [], None, None, {"open": {}}
    for i, (mt, m) in enumerate(parsed):
        pos = m.root.find("functions/position")
        for axis in ("pan", "tilt"):
            r = pos.find(f"{axis}/range") if pos is not None else None
            if r is not None and r.get("range"):
                out["physical"][f"{axis}_deg"] = int(float(r.get("range")))
        size = max([*m.ch, m.dmx_count - 1], default=-1) + 1
        chans = []
        for n in range(size):
            spec = dict(m.ch.get(n, {"attr": "unused", "default": 0}))
            text = [(lo, f"{typ} {cap}".strip()) for lo, hi, typ, cap in spec.pop("_text", [])]
            fog = spec.pop("_fog", None)
            if dark:
                spec = {"attr": spec["attr"]}
                if fog is not None and kind == "smoke":
                    spec = fxlib.smoke_channel(
                        "output", [(lo, hi, f"{t} {c}") for lo, hi, t, c in fog] or [(0, 255, "")], False
                    ) or {"attr": "fog_output", "default": 0}
                else:
                    spec["default"], safe = fxlib.off_value(spec["attr"], text or [(0, "")])
                    if not safe:
                        unsafe.append(spec["attr"])
                    if kind == "smoke" and re.search(r"\bfan\b", spec["attr"]):
                        spec = {"attr": "fog_fan", "default": spec["default"]}
            chans.append(spec)
        name = (modes[i] if modes and i < len(modes) and modes[i] else mt["mode"]) or f"{len(chans)}ch"
        name = re.sub(r"\s*(channels?|kanal|kan[äa]le)\b", "ch", name, flags=re.I).replace(" ", "")
        while name in out["modes"]:
            name += "'"
        if chans:
            out["modes"][name] = chans
        wheel = wheel or m.wheel
        gobo_names = gobo_names or m.gobo_names
        for k, v in m.beam_fx.items():
            beam_fx.setdefault(k, v)
    if dark:
        if kind == "smoke" and any(c["attr"] == "fog" for ch in out["modes"].values() for c in ch):
            fxlib.mark_smoke(out, haze="haz" in out["model"].lower())
        else:
            if dim and kind != "laser":
                out["inert"] = "no channel the show can dim (only macros, patterns or a wheel): it stays dark"
                if kind in fxlib.MOVING:  # a scanner with only a shutter: dark, its pan and tilt mapped by hand
                    out["kind"] = "par"
            fxlib.mark_inert(out, unsafe)
        return out
    if wheel:
        out["color_wheel"] = {"verified": True, "_note": "Slot colours from the DMXControl DDF.", "slots": wheel}
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
    attrs = {c["attr"] for m in out["modes"].values() for c in m}
    phys = out["physical"]
    if out["kind"] == "moving_head":
        for m in out["modes"].values():  # one beam: its cells light together
            for c in m:
                c.pop("head", None)
    if out["kind"] == "moving_bar":
        phys["pan_deg"] = 0
    if out["kind"] not in fxlib.MOVING:
        phys.pop("pan_deg", None)
        phys.pop("tilt_deg", None)
    if {"red", "green", "blue"} <= attrs:  # RGB: a colour wheel channel is a macro that would override the mix
        for m in out["modes"].values():
            for c in m:
                if c["attr"] == "color_wheel":
                    c["attr"], c["default"] = "color_macro", 0
        out.pop("color_wheel", None)
    if attrs == {"strobe"} or (out["kind"] == "par" and "strobe" in out["model"].lower()):
        out["kind"] = "strobe"


# The library itself: one listing call, then one file per mode (kept in the cache, so a rebuild only fetches
# what is new). Only tools/build_catalog.py downloads; the app reads the shipped catalogue (library/shadow.py).

CACHE_DIR = paths.CACHE / "ddf"


def _get(url: str, tries: int = 4) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "AmadeusDMX fixture catalogue (open source)"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except OSError:  # a dropped connection or a DNS hiccup: wait and try again
            if attempt == tries - 1:
                raise
            time.sleep(2 * 2**attempt)
    raise AssertionError("unreachable")


def listing(refresh: bool = False) -> list[dict]:
    """Every file in the library (as the API lists it), cached."""
    path = CACHE_DIR / "ddfs.json"
    if refresh or not path.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(API))
    return json.loads(path.read_text(encoding="utf-8"))["data"]


def file(ddf_id: int) -> bytes:
    path = CACHE_DIR / f"{ddf_id}.xml"
    if not path.exists():
        data = _get(f"{API}/{ddf_id}/file")
        path.with_suffix(".part").write_bytes(data)
        path.with_suffix(".part").replace(path)  # never a half file in the cache
        time.sleep(0.2)  # a volunteer project's server: politely
    return path.read_bytes()


def devices(items: list[dict]) -> dict[int, list[dict]]:
    """DMXControl 3 files grouped by device (a mode each), without files a later update replaced."""
    replaced = {i["parent_id"] for i in items if i.get("parent_type") == "update" and i.get("parent_id")}
    out: dict[int, list[dict]] = {}
    for i in sorted(items, key=lambda i: i["id"]):
        if i["dmxc_type"] == 3 and i["id"] not in replaced and not i.get("deleted_at"):
            out.setdefault(i["device_id"], []).append(i)
    return out


def slug(manufacturer: str, model: str) -> str:
    brand = re.sub(r"[^a-z0-9]+", "", manufacturer.lower()) or "other"
    return f"{brand}/{re.sub(r'[^a-z0-9]+', '-', model.lower()).strip('-')}"


def add_to_library(ddf_key: str) -> str:
    """Copy a DDF fixture from the shipped catalogue into your fixtures and return its library key (it stays
    CC BY-SA 4.0: its "ddf" block and source say so)."""
    from amadeus.library import shadow

    d = shadow.get(ddf_key)
    if d is None:
        raise KeyError(f"{ddf_key} is not in the DDF catalogue")
    key = slug(d["manufacturer"], d["model"])
    if key not in fxlib.library():
        fxlib.save(key, d)
    return key
