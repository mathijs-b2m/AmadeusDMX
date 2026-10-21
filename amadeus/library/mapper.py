"""The DMX mapper: what each channel of a fixture's mode does, set by hand, for the fixtures the converters can't
read (effect lights with only program channels, colour macros, numbered emitters, channels a library leaves
undefined). The Set page's mapper shows each channel with the name and ranges the QLC+ or Open Fixture Library
gives it, lets you try values on the real fixture (the light test's raw mode, amadeus/web/rig.py) and saves the
roles into your copy of the definition: every fixture of that model plays by it.

A channel is either played by the show (a role: dimmer, a colour, pan or tilt, optionally for one cell of a
bar) or held at a value (an effect channel parked on a useful setting, a macro on a colour, a shutter open).
"""

from __future__ import annotations

import copy
import json
import re

from amadeus.library import fixtures as fxlib

# The roles the show plays (patch in fixtures.py), in the order the mapper offers them. "cell": per bar cell;
# "light": it carries light (kept under the brightness limiter when tried); "check": its value while another
# channel is checked (the light on and steady, the head in the middle)
ROLES = [
    {"role": "dimmer", "label": "Dimmer", "group": "Intensity", "cell": True, "light": True, "check": 255},
    {"role": "dimmer_fine", "label": "Dimmer (fine)", "group": "Intensity", "cell": False, "light": True, "check": 255},
    {"role": "red", "label": "Red", "group": "Colour", "cell": True, "light": True, "check": 255},
    {"role": "green", "label": "Green", "group": "Colour", "cell": True, "light": True, "check": 255},
    {"role": "blue", "label": "Blue", "group": "Colour", "cell": True, "light": True, "check": 255},
    {"role": "white", "label": "White", "group": "Colour", "cell": True, "light": True, "check": 255},
    {"role": "uv", "label": "UV", "group": "Colour", "cell": True, "light": True, "check": 0},
    {"role": "cyan", "label": "Cyan", "group": "Colour", "cell": False, "light": True, "check": 0},
    {"role": "magenta", "label": "Magenta", "group": "Colour", "cell": False, "light": True, "check": 0},
    {"role": "yellow", "label": "Yellow", "group": "Colour", "cell": False, "light": True, "check": 0},
    {"role": "color_wheel", "label": "Colour wheel", "group": "Colour", "cell": False, "light": False, "check": 0},
    {"role": "pan", "label": "Pan", "group": "Position", "cell": False, "light": False, "check": 128},
    {"role": "pan_fine", "label": "Pan (fine)", "group": "Position", "cell": False, "light": False, "check": 0},
    {"role": "tilt", "label": "Tilt", "group": "Position", "cell": False, "light": False, "check": 128},
    {"role": "tilt_fine", "label": "Tilt (fine)", "group": "Position", "cell": False, "light": False, "check": 0},
]
ROLE = {r["role"]: r for r in ROLES}
HOLD = "hold"  # not played: held at its value
KEEP = "keep"  # played as the converter or a hand-made file has it (a colour wheel, zoom, a laser's channels)
LIGHT = {"dimmer", "red", "green", "blue", "white", "uv", "cyan", "magenta", "yellow"}
# What it is, when its channels don't say (pan and tilt make a moving head, cells a bar)
KINDS = {"par": "Par / wash / effect", "strobe": "Strobe", "blinder": "Blinder", "moving_head": "Moving head"}

# The check, channel by channel on the real fixture (a channel sweeps, the others hold the light on): what it did,
# and what that makes the channel. A held one gets "attr" (beam effects find a gobo or prism by its name) and the
# value where the light looks right.
CHECK = [
    {"answer": "Turns left and right", "role": "pan"},
    {"answer": "Tilts up and down", "role": "tilt"},
    {"answer": "Moves a little sideways", "role": "pan_fine"},
    {"answer": "Moves a little up and down", "role": "tilt_fine"},
    {"answer": "Gets brighter", "role": "dimmer"},
    {"answer": "Red", "role": "red"},
    {"answer": "Green", "role": "green"},
    {"answer": "Blue", "role": "blue"},
    {"answer": "White", "role": "white"},
    {"answer": "Colours change (wheel)", "role": "color_wheel"},
    {"answer": "Gobos change", "role": "hold", "attr": "gobo", "value": 0},
    {"answer": "Prism", "role": "hold", "attr": "prism", "value": 0},
    {"answer": "Focus", "role": "hold", "attr": "focus", "value": 128},
    {"answer": "Strobes or flashes", "role": "hold", "attr": "strobe", "value": 0},
    {"answer": "Opens or closes the light", "role": "hold", "attr": "shutter", "value": 255},
    {"answer": "Changes the speed", "role": "hold", "attr": "pan_tilt_speed", "value": 0},
    {"answer": "Starts programs", "role": "hold", "attr": "auto", "value": 0},
    {"answer": "Resets or goes dark", "role": "hold", "attr": "reset", "value": 0},
    {"answer": "Nothing I can see", "role": "hold", "value": 0},
]


def refusal(defn: dict) -> str:
    """Why the mapper leaves this fixture alone ('' if it maps it)."""
    if defn.get("kind") == "laser":
        return "Lasers aren't mapped here: a laser's patterns and safety are mapped by hand (docs/fixture-catalog.md)."
    if defn.get("kind") == "smoke":
        return "Smoke machines are played from their output channel (engine/fog.py), not mapped here."
    return ""


def plays(defn: dict, mode: str) -> bool:
    """Does the show light anything in this mode? (A fixture that plays nothing is what the mapper is for.)"""
    blacklight = fxlib.uv_only(defn)
    return any(
        c["attr"] in LIGHT and ("default" not in c or (c["attr"] == "uv" and blacklight))
        for c in defn["modes"].get(mode, [])
    )


def describe(key: str, mode: str) -> dict:
    """A mode, channel by channel, as the mapper shows it."""
    defn = fxlib.get(key)
    chans = fxlib.channels(defn, mode)
    names = source_channels(defn, mode) or [None] * len(chans)
    blacklight = fxlib.uv_only(defn)
    out = []
    for n, (c, src) in enumerate(zip(chans, names, strict=False)):
        played = c["attr"] in ROLE and ("default" not in c or (c["attr"] == "uv" and blacklight))
        out.append(
            {
                "n": n + 1,
                "attr": c["attr"],
                "role": c["attr"] if played else HOLD if "default" in c else KEEP,
                "cell": c.get("head", 0),
                "value": int(c.get("default", 0)),
                "name": src["name"] if src else c["attr"].replace("_", " "),
                "ranges": src["ranges"] if src else [],
            }
        )
    made = defn.get("made", {})
    return {
        "key": key,
        "name": f"{defn['manufacturer']} {defn['model']}",
        "mode": mode,
        "kind": defn["kind"],
        "kinds": KINDS,
        "roles": ROLES,
        "channels": out,
        "plays": plays(defn, mode),
        "mapped": mode in defn.get("mapped", {}).get("modes", []),
        "refusal": refusal(defn),
        "made": bool(made),  # made here from a template (generic.py): it wants the check
        "checked": bool(made.get("checked")) or not made,
        "check": CHECK,
        "wheel": defn.get("color_wheel", {}).get("slots", []),
    }


def apply(
    key: str, mode: str, kind: str, channels: list[dict], wheel: list[dict] | None = None, checked: bool = False
) -> list[str]:
    """Save a mode's channels ({"role", "cell", "value"} per channel, in order; a held one may get its "attr",
    what the check found it does) into your copy of the definition. `wheel`: the colour wheel's slots as named in
    the check; `checked`: every channel was checked on the fixture. Returns the problems (nothing saved if any)."""
    defn = copy.deepcopy(fxlib.get(key))
    defn.pop("key", None)
    if refusal(defn):
        return [refusal(defn)]
    old = fxlib.channels(defn, mode)
    problems = []
    if len(channels) != len(old):
        problems.append(f"The mode has {len(old)} channels, not {len(channels)}")
    if kind not in KINDS:
        problems.append(f"Unknown kind '{kind}'")
    new = []
    for n, (c, o) in enumerate(zip(channels, old, strict=False)):
        role, cell, value = c.get("role", HOLD), int(c.get("cell", 0) or 0), int(c.get("value", 0) or 0)
        if not 0 <= value <= 255:
            problems.append(f"Channel {n + 1}: {value} is not a DMX value (0–255)")
        if role == KEEP and "default" not in o and o["attr"] not in ROLE:
            new.append(copy.deepcopy(o))
            continue
        if role == HOLD:  # keeps its name (beam effects refer to it), held at the value
            attr = c["attr"] if ATTR.fullmatch(str(c.get("attr", ""))) else o["attr"]
            spec = {"attr": attr if attr not in ROLE else f"channel_{n + 1}", "default": value}
        elif role in ROLE:
            spec = {"attr": role}
            if cell and ROLE[role]["cell"]:
                spec["head"] = cell
        else:
            problems.append(f"Channel {n + 1}: unknown role '{role}'")
            continue
        for k in ("range", "tight", "wide", "on_from", "_note"):  # what the converter knew about the channel
            if k in o and o["attr"] == spec["attr"]:
                spec[k] = o[k]
        new.append(spec)
    roles = [s["attr"] for s in new if "default" not in s]
    if ("pan" in roles) != ("tilt" in roles) and kind == "moving_head":
        problems.append("A moving head needs both pan and tilt")
    if not any(r in LIGHT for r in roles):
        problems.append("No channel lights it: give one a dimmer or a colour")
    slots = _slots(wheel, problems) if wheel else None
    if problems:
        return problems

    if "color_wheel" in roles and (slots or "color_wheel" not in defn):
        from amadeus.library import generic

        defn["color_wheel"] = generic.wheel(slots)
    if "made" in defn:
        _follow_names(defn, mode, old, new, checked)
    defn["modes"][mode] = new
    _set_kind(defn, kind, roles, len({s["head"] for s in new if "head" in s}))
    mapped = defn.setdefault("mapped", {"modes": []})
    mapped["modes"] = sorted(set(mapped["modes"]) | {mode})
    mapped["_note"] = "Channels mapped by hand in the DMX mapper (Set page)."
    fxlib.save(key, defn)
    return []


ATTR = re.compile(r"[a-z][a-z0-9_]{0,40}")


def _slots(wheel: list[dict], problems: list[str]) -> list[dict]:
    """The colour wheel's slots as the check named them: {"name", "from", "to", "rgb"}, open first."""
    out = []
    for s in wheel:
        try:
            lo, hi = int(s["from"]), int(s["to"])
            rgb = [min(max(float(v), 0.0), 1.0) for v in s["rgb"]]
        except (KeyError, TypeError, ValueError):
            problems.append("A colour wheel slot needs from, to and rgb")
            return []
        if not 0 <= lo <= hi <= 255 or len(rgb) != 3:
            problems.append(f"Colour wheel slot {s.get('name', '')}: {lo}–{hi} is not a DMX range")
            return []
        out.append({"name": str(s.get("name") or "colour")[:40], "from": lo, "to": hi, "rgb": rgb})
    return out


def _follow_names(defn: dict, mode: str, old: list[dict], new: list[dict], checked: bool):
    """A fixture made from a template: the names shown follow what the check found (the template's ranges no
    longer apply to a channel that turned out to do something else)."""
    shown = defn["made"].setdefault("channels", {}).get(mode) or []
    names = []
    for n, s in enumerate(new):
        if n < len(shown) and old[n]["attr"] == s["attr"]:
            names.append(shown[n])
        else:
            label = ROLE[s["attr"]]["label"] if s["attr"] in ROLE else s["attr"].replace("_", " ").capitalize()
            names.append({"name": label, "ranges": []})
    defn["made"]["channels"][mode] = names
    if checked:
        defn["made"]["checked"] = True
        defn["source"] = re.sub(r": check it.*$", ": checked channel by channel on the fixture", defn["source"])


def _set_kind(defn: dict, kind: str, roles: list[str], cells: int):
    """What it is: pan and tilt make a moving head, tilt alone a moving bar, cells a bar, else as chosen."""
    phys = defn.setdefault("physical", {})
    if "pan" in roles and "tilt" in roles:
        defn["kind"] = "moving_head"
    elif "tilt" in roles:
        defn["kind"] = "moving_bar"
    elif cells > 1 and kind in ("par", "moving_head"):
        defn["kind"] = "par_bar"
    else:
        defn["kind"] = "par" if kind == "moving_head" else kind
    if defn["kind"] in fxlib.MOVING:
        phys.setdefault("pan_deg", 0 if defn["kind"] == "moving_bar" else 540)
        phys.setdefault("tilt_deg", 270)
        defn.setdefault(
            "motion",
            {
                "estimated": True,
                "pan_speed_dps": 200,
                "tilt_speed_dps": 160,
                "accel_dps2": 800,
                "_note": "Estimated; measure with `amadeus motion`.",
            },
        )
    else:
        phys.pop("pan_deg", None)
        phys.pop("tilt_deg", None)
        defn.pop("motion", None)


# ---------------------------------------------------------------- the library's own names and ranges


def source_channels(defn: dict, mode: str) -> list[dict] | None:
    """[{"name", "ranges": [[lo, hi, what]]}] per channel of the mode, from the QLC+ or OFL file it was
    converted from; None when that file isn't at hand (or the fixture is hand-made)."""
    try:
        if "made" in defn:
            return defn["made"].get("channels", {}).get(mode)
        if "qlc" in defn:
            return _qlc_channels(defn["qlc"]["key"], mode)
        if "ofl" in defn:
            return _ofl_channels(*defn["ofl"]["key"].split("/", 1), mode)
    except Exception:  # noqa: BLE001 - names are a help, never a reason the mapper can't open
        return None
    return None


def _qlc_mode_name(name: str) -> str:
    return re.sub(r"\s*channels?\b", "ch", name, flags=re.I).replace(" ", "")  # as qlc.convert names it


def _qlc_channels(rel: str, mode: str) -> list[dict] | None:
    from amadeus.library import qlc

    root = qlc._load(rel)
    channels = {ch.get("Name"): ch for ch in root.findall("q:Channel", qlc.NS)}
    for m in root.findall("q:Mode", qlc.NS):
        if _qlc_mode_name(m.get("Name", "")) != mode:
            continue
        order = {int(c.get("Number")): c.text.strip() for c in m.findall("q:Channel", qlc.NS)}
        out = []
        for n in range(len(order)):
            ch = channels.get(order.get(n))
            caps = qlc._caps(ch) if ch is not None else []
            out.append({"name": order.get(n, ""), "ranges": [[c["min"], c["max"], c["name"]] for c in caps]})
        return out
    return None


def _ofl_channels(manufacturer: str, fixture: str, mode: str) -> list[dict] | None:
    from amadeus.library import ofl

    base = ofl.OFL_DIR / "fixtures"
    if not base.exists():
        return None
    d = json.loads((base / manufacturer / f"{fixture}.json").read_text(encoding="utf-8"))
    if "redirectTo" in d:
        return _ofl_channels(*d["redirectTo"].split("/", 1), mode)
    for m in d.get("modes", []):
        if (m.get("shortName") or m.get("name")) != mode:
            continue
        out = []
        for key, _ in ofl._expand_mode(d, m):
            ch = ofl._resolve_channel(d, key)[1] if key else None
            ranges = [[c["dmxRange"][0], c["dmxRange"][1], ofl._cap_text(c)] for c in ofl._caps(ch)] if ch else []
            out.append({"name": key or "(unused)", "ranges": ranges})
        return out
    return None
