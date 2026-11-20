"""A fixture's manual read with AI (your own OpenAI key): the DMX chart of the mode the fixture runs in, as the
DMX mapper shows and saves it (mapper.py), so nobody has to map a cheap head's channels by eye. The manual is a
PDF, or pictures of its DMX chart (a screenshot pasted from the clipboard, a photo of the page).

The whole PDF (or every picture) goes to OpenAI in one request (the Responses API, the answer in a fixed JSON
form, cached like the document import's, rig/importer/pdf.py): every mode the manual lists, channel by channel,
with what the channel does, the value where it leaves the light alone, its value ranges in the manual's words,
and the colours of a colour wheel. A manual lists several modes: the one with the fixture's channel count is
used (by name when two have that count) and the answer says which. Nothing is saved here: the mapper is filled,
checked by the user and saved as usual; the chart's names and ranges are saved with it, and the gobos, the
prism, the frost and the strobe are read from those words (beam_ranges.py, strobe.py).
"""

from __future__ import annotations

import base64
import re

from amadeus.library import beam_ranges, mapper
from amadeus.library import fixtures as fxlib

NO_KEY = "Reading a manual needs your own OpenAI API key (Settings › Director); nothing was sent."
NOT_READABLE = "{name} isn't a PDF or a picture (PNG, JPEG, WebP, GIF)."
NOTHING = "No manual to read."
PICTURES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}

# what a channel does, as the manual is asked: the mapper's roles, and the ones the show holds or plays by name
HELD = {
    "amber": "amber",
    "shutter": "shutter",
    "gobo": "gobo",
    "gobo_rotation": "gobo_rotation",
    "prism": "prism",
    "prism_rotation": "prism_rotation",
    "frost": "frost",
    "focus": "focus",
    "zoom": "zoom",
    "pan_tilt_speed": "pan_tilt_speed",
    "color_macro": "color_macro",
    "auto": "auto",
    "reset": "reset",
}
OTHER = "other"
FUNCTIONS = [r["role"] for r in mapper.ROLES] + list(HELD) + [OTHER]
TYPES = ["spot", "wash", "beam", "par", "bar", "strobe", "blinder", "other"]
DRIVEN = re.compile(r"^(fog|fog_fan|lens_roll|laser_.*)$")  # attrs the show drives by name: never a held one's


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


_INT = {"type": "integer"}
_NUM = {"type": "number"}
_STR = {"type": "string"}
CHANNEL = _obj(
    {
        "name": {"type": "string", "description": "the channel's name as the manual prints it, in English"},
        "function": {"type": "string", "enum": FUNCTIONS},
        "cell": {
            "type": "integer",
            "description": "for a bar or a fixture with several separately controlled lights: which one this "
            "channel belongs to (1, 2, …); 0 when it is for the whole fixture",
        },
        "value": {
            "type": "integer",
            "description": "the DMX value at which this channel leaves a plain, steady, open beam: shutter open "
            "without strobe, gobo wheel open, prism out, frost out, no rotation, programs and sound mode off, "
            "pan/tilt speed fastest, focus in the middle, no reset; 0 for dimmer, colours, pan and tilt",
        },
        "ranges": {
            "type": "array",
            "items": _obj({"from": _INT, "to": _INT, "what": _STR}),
            "description": "every row of this channel's value table, in DMX order, in the manual's own words "
            "(English); one row 0–255 when the manual gives none",
        },
        "colours": {
            "type": "array",
            "items": _obj({"name": _STR, "from": _INT, "to": _INT, "r": _NUM, "g": _NUM, "b": _NUM}),
            "description": "only for a colour wheel (or a ring colour) channel: each fixed full colour, the open "
            "or white position included, with its DMX range and how it looks (r, g, b 0..1); no half colours, "
            "no rainbow or rotation ranges. Empty for every other channel",
        },
    }
)
SCHEMA = _obj(
    {
        "manufacturer": {"type": "string", "description": "the brand, '' when the manual has none"},
        "model": _STR,
        "type": {"type": "string", "enum": TYPES},
        "modes": {
            "type": "array",
            "items": _obj({"name": _STR, "channels": {"type": "array", "items": CHANNEL}}),
        },
    }
)

PROMPT = (
    "This is the user manual of a DMX lighting fixture: a PDF, or pictures of the pages with its DMX chart "
    "(several pictures are parts of one manual, in order). Read its DMX channel charts. List every DMX mode the "
    "manual gives (e.g. '9 channel', '13CH', 'Basic', 'Extended'), each with all its channels in order, channel 1 "
    "first: a mode with 13 channels has exactly 13 entries. Where the manual prints one table with a column per "
    "mode, work out each mode's own channel order from its column. Per channel: its name; what it does (function); "
    "its value table (ranges); and the value at which it leaves a plain open beam (value).\n"
    "Functions: dimmer (master intensity; dimmer_fine its 16-bit low byte); red, green, blue, white, amber, uv, "
    "cyan, magenta, yellow (colour mixing, per cell on a bar); color_wheel (a wheel of fixed colours); ring_color "
    "(the colour of an LED ring or strip round the lens, on one channel); pan, tilt and pan_fine, tilt_fine "
    "(the 16-bit low bytes); pan_tilt_speed; shutter (a shutter and/or strobe channel); gobo (a gobo wheel: "
    "which gobo, with shake or scroll ranges if it has them); gobo_rotation (turns or indexes the gobo); prism "
    "(prism in or out); prism_rotation; frost; focus; zoom; color_macro (colour presets or colour programs on a "
    "colour-mixing fixture); auto (built-in programs, sound mode, program speed, function or mode channels); "
    "reset (reset, lamp on/off, special or control functions); other (anything else). A channel that combines "
    "dimmer and strobe is a dimmer if it mostly dims, else a shutter.\n"
    "Copy DMX values exactly as printed; a table printed in percent is converted to 0–255. Never invent a mode, "
    "a channel or a range the manual doesn't give. If there is no DMX chart in it, return no modes."
)


def _kind(data: bytes) -> str:
    """What a file is, by how it starts: "application/pdf", a picture's type, '' for anything else."""
    head = data.lstrip()[:16] if data[:1].isspace() else data[:16]
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return next((kind for magic, kind in PICTURES.items() if head.startswith(magic)), "")


def read(data: bytes | list[tuple[str, bytes]], name: str = "manual.pdf", client=None) -> dict:
    """The manual's own answer: {"manufacturer", "model", "type", "modes": [{"name", "channels": […]}]}. `data`: a
    PDF or a picture, or several as [(name, bytes)] (a chart over two screenshots): all in one request."""
    from amadeus.rig.importer import pdf

    files = data if isinstance(data, list) else [(name, data)]
    if not files or not any(d for _, d in files):
        raise ValueError(NOTHING)
    content = [{"type": "input_text", "text": PROMPT}]
    for n, d in files:
        kind = _kind(d)
        url = f"data:{kind};base64," + base64.b64encode(d).decode()
        if kind == "application/pdf":
            content.append(
                {"type": "input_file", "filename": re.sub(r"[^\w.-]+", "-", n) or "manual.pdf", "file_data": url}
            )
        elif kind:
            content.append({"type": "input_image", "image_url": url, "detail": "high"})
        else:
            raise ValueError(NOT_READABLE.format(name=n or "The file"))
    if client is None:
        if not pdf.has_key():
            raise ValueError(NO_KEY)
        from openai import OpenAI

        client = OpenAI()
    return pdf._ask(client, content, SCHEMA, "manual")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+", text.lower())) - {"ch", "channel", "channels", "mode", "dmx"}


def pick_mode(answer: dict, count: int, mode: str = "") -> tuple[dict | None, str]:
    """The manual's mode for a fixture patched with `count` channels (in `mode`, as our library calls it): the one
    with that many channels, by name when several have. (None, why) when the manual has none."""
    modes = [m for m in answer.get("modes", []) if m.get("channels")]
    if not modes:
        return None, "No DMX chart found in this manual."
    fit = [m for m in modes if len(m["channels"]) == count]
    if not fit:
        have = ", ".join(sorted({str(len(m["channels"])) for m in modes}, key=int))
        return None, f"The manual has no mode with {count} channels (it has: {have}). Set the fixture's mode first."
    want = _words(mode)
    return max(fit, key=lambda m: len(_words(m.get("name", "")) & want)), ""


def _attr(name: str, n: int) -> str:
    attr = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    if not mapper.ATTR.fullmatch(attr) or attr in mapper.ROLE:
        return f"channel_{n}"
    return f"{attr}_held" if DRIVEN.match(attr) else attr


def _byte(v) -> int:
    try:
        return min(max(int(v), 0), 255)
    except (TypeError, ValueError):
        return 0


def _ranges(c: dict) -> list[list]:
    out = []
    for r in c.get("ranges") or []:
        lo, hi = _byte(r.get("from")), _byte(r.get("to"))
        out.append([min(lo, hi), max(lo, hi), str(r.get("what") or "")[:120]])
    return sorted(out, key=lambda r: r[0])


def _slots(c: dict) -> list[dict]:
    out = []
    for s in c.get("colours") or []:
        lo, hi = _byte(s.get("from")), _byte(s.get("to"))
        rgb = [round(min(max(float(s.get(k) or 0), 0.0), 1.0), 3) for k in ("r", "g", "b")]
        out.append({"name": str(s.get("name") or "colour")[:40], "from": min(lo, hi), "to": max(lo, hi), "rgb": rgb})
    return sorted(out, key=lambda s: s["from"])


def chart(found: dict) -> dict:
    """One mode of the manual as the mapper takes it: {"channels": [{"role", "attr", "cell", "value", "name",
    "ranges"}], "wheel", "ring"}."""
    out, used, wheel, ring = [], set(), [], []
    for n, c in enumerate(found["channels"], 1):
        fn = c.get("function", OTHER)
        name = str(c.get("name") or f"Channel {n}")[:60]
        if fn in mapper.ROLE and fn not in used | {OTHER}:
            role, attr, value = fn, fn, 0
            cell = max(int(c.get("cell") or 0), 0) if mapper.ROLE[fn]["cell"] else 0
            if not cell:
                used.add(fn)  # one of each for the whole fixture (a second "dimmer" is held, to check)
            if fn == "color_wheel":
                wheel = _slots(c)
            if fn == "ring_color":
                ring = _slots(c)
        else:
            role, cell, value = mapper.HOLD, 0, _byte(c.get("value"))
            attr = HELD.get(fn) or _attr(name, n)
            if fn in mapper.ROLE:
                attr = f"{fn}_2"
            k = 2
            while attr in used:  # a second gobo wheel, a second prism
                attr = f"{HELD.get(fn) or _attr(name, n)}_{k}"
                k += 1
            used.add(attr)
        out.append({"role": role, "attr": attr, "cell": cell, "value": value, "name": name, "ranges": _ranges(c)})
    return {"channels": out, "wheel": wheel, "ring": ring}


def mapping(key: str, mode: str, answer: dict, file: str = "") -> dict:
    """The mapper's view of the fixture's mode (mapper.describe), filled from the manual. {"error"} when the
    manual has no mode that fits."""
    shown = mapper.describe(key, mode)
    if shown["refusal"]:
        return {"error": shown["refusal"]}
    found, why = pick_mode(answer, len(shown["channels"]), mode)
    if found is None:
        return {"error": why}
    got = chart(found)
    for old, new in zip(shown["channels"], got["channels"], strict=True):
        if old["role"] == mapper.KEEP and old["attr"] == new["attr"]:
            new = {**new, "role": mapper.KEEP}  # played as converted (a zoom with its range): left so
        old.update(new)
    roles = {c["role"] for c in shown["channels"]}
    if {"pan", "tilt"} <= roles:
        shown["kind"] = "moving_head"
    elif answer.get("type") in ("strobe", "blinder"):
        shown["kind"] = answer["type"]
    elif shown["kind"] not in mapper.KINDS or shown["kind"] == "moving_head":
        shown["kind"] = "par"
    if got["wheel"]:
        shown["wheel"] = got["wheel"]
    if got["ring"]:
        shown["ring"] = got["ring"]
    shown["plays"] = bool(roles & mapper.LIGHT)
    shown["manual"] = _about(answer, found, file)
    return shown


def _about(answer: dict, found: dict, file: str) -> dict:
    return {
        "file": file,
        "mode": str(found.get("name") or f"{len(found['channels'])} channels"),
        "modes": [
            {"name": str(m.get("name") or ""), "channels": len(m["channels"])}
            for m in answer.get("modes", [])
            if m.get("channels")
        ],
    }


def create(answer: dict, count: int = 0, file: str = "", manufacturer: str = "", model: str = "") -> dict:
    """A new fixture in your library from the manual (generic.from_chart): the mode with `count` channels, the
    manual's largest when no count is given. {"key", "mode", "manual"} or {"problems"}; like any made fixture it
    wants the channel check."""
    from amadeus.library import generic

    modes = [m for m in answer.get("modes", []) if m.get("channels")]
    if not count and modes:
        count = max(len(m["channels"]) for m in modes)
    found, why = pick_mode(answer, count)
    if found is None:
        return {"problems": [why]}
    got = chart(found)
    kind = answer.get("type") if answer.get("type") in generic.CHART_KINDS else "par"
    channels = [
        # a held one is named after what it does (the beam effects find "gobo", "prism" and "frost" by name)
        {**c, "name": c["attr"].replace("_", " ") if c["role"] == mapper.HOLD else c["name"]}
        for c in got["channels"]
    ]
    made = generic.from_chart(
        manufacturer or str(answer.get("manufacturer") or ""),
        model or str(answer.get("model") or ""),
        kind,
        channels,
        f"{count}ch",
        got["wheel"] or None,
        source=file or "its manual",
        ring_slots=got["ring"] or None,
    )
    if "problems" in made:
        return made
    defn = dict(fxlib.get(made["key"]))
    defn.pop("key", None)
    names = [{"name": c["name"], "ranges": c["ranges"]} for c in got["channels"]]
    defn["made"]["channels"][made["mode"]] = names  # the manual's own names, as the mapper shows them
    keep(defn, made["mode"], names, file)
    fxlib.save(made["key"], defn)
    return {**made, "manual": _about(answer, found, file)}


# ------------------------------------------------------------------ saved with the mapping


def keep(defn: dict, mode: str, names: list[dict], file: str = ""):
    """The manual's chart for a mode into the definition: its names and ranges (what the mapper shows from then
    on), and the gobos, prism and frost its words give (beam_fx), which win over what the file had."""
    manual = defn.setdefault("manual", {"channels": {}})
    manual["_note"] = "The DMX chart as read from the fixture's manual with AI (Set page, Map DMX Channels)."
    if file:
        manual["file"] = file
    manual.setdefault("channels", {})[mode] = [
        {"name": str(c.get("name") or ""), "ranges": [list(r) for r in c.get("ranges") or []]} for c in names
    ]
    chans = defn["modes"][mode]
    if defn.get("kind") not in beam_ranges.MOVING:
        return
    table = defn.setdefault("beam_fx", {"open": {}})
    table.setdefault("open", {})
    wrote = {}
    for rx, own, read_fx in (
        (beam_ranges.GOBO, "gobo", beam_ranges._gobo_fx),
        (beam_ranges.PRISM, "prism", beam_ranges._prism_fx),
        (beam_ranges.FROST, "frost", beam_ranges._frost_fx),
    ):
        picked = beam_ranges._pick(chans, names, rx, own)
        if picked and picked[1]:
            wrote.update(read_fx(*picked))
    # a gobo or a prism turned by a channel of its own
    for fx, base, attr in (("gobo_rotate", "gobo", "gobo_rotation"), ("prism_spin", "prism", "prism_rotation")):
        n = next((i for i, c in enumerate(chans) if c["attr"] == attr), None)
        if n is None or base not in wrote or n >= len(names):
            continue
        spins = [
            r for r in beam_ranges._ranges(names[n])
            if beam_ranges.SPIN.search(r[2]) and not beam_ranges.INDEXED.search(r[2])
        ]  # fmt: skip
        turn = beam_ranges._turn(spins) if spins else None
        if turn:
            wrote[fx] = {**wrote[base], attr: turn}
    for fx, entry in table.items():  # an effect the file keeps (a rotation it knew) plays the manual's gobos
        for base in ("gobo", "prism"):
            if fx not in wrote and base in wrote and isinstance(entry, dict):
                for attr, values in wrote[base].items():
                    if attr in entry and type(entry[attr]) is type(values):
                        entry[attr] = values
    for fx, entry in wrote.items():
        table[fx] = entry
    if beam_ranges.NOTE in table:  # read from the manual now, not guessed as the library loads
        left = [fx for fx in table[beam_ranges.NOTE] if fx not in wrote]
        if left:
            table[beam_ranges.NOTE] = left
        else:
            table.pop(beam_ranges.NOTE)
