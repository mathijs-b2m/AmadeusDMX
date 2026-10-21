"""Fixtures without a brand: a new fixture made from a common channel layout, then checked on the real fixture.

Cheap moving heads and pars are mostly the same few factory designs sold under many names (whatever the box
says), so their channel tables look alike: a 9-channel LED spot is pan, tilt, colour wheel, gobo, strobe, dimmer,
speed, programs and reset in nearly every manual. A template is such a layout; you pick the one closest to your
manual, say how many channels the fixture has (its display shows it: "9CH", "d-11"), and the fixture is made in
your library. Its channels are then checked one by one on the real fixture in the DMX mapper (mapper.py), because
these manuals are often wrong: channels swapped, a fine channel missing, the wheel in another order.

A channel of a template is played by the show (a role in mapper.ROLES: pan, dimmer, a colour, the colour wheel)
or held at a value (strobe off, programs off, a shutter open); the names and value ranges are what such manuals
usually say, shown in the mapper as a help.
"""

from __future__ import annotations

import re

from amadeus.library import fixtures as fxlib

# What it is, as the new-fixture sheet asks it: (type, label, kind, beam angle)
TYPES = [
    ("spot", "Spot moving head (gobos)", "moving_head", 14.0),
    ("wash", "Wash moving head (LEDs)", "moving_head", 25.0),
    ("beam", "Beam moving head (narrow)", "moving_head", 3.0),
    ("par", "Par / wash light", "par", 25.0),
    ("other", "Something else", "par", 25.0),
]
TYPE = {t[0]: t for t in TYPES}


def _c(attr: str, name: str, default: int | None = None, ranges: list | None = None) -> dict:
    """One template channel: played when it has no default, else held at it."""
    c = {"attr": attr, "name": name, "ranges": ranges or []}
    if default is not None:
        c["default"] = default
    return c


# What such manuals usually say a channel's values do
STROBE = [[0, 9, "no strobe (light on)"], [10, 255, "strobe, slow to fast"]]
SHUTTER = [[0, 7, "closed"], [8, 15, "open"], [16, 131, "strobe, slow to fast"], [132, 255, "open"]]
SPEED = [[0, 255, "pan/tilt speed, fast to slow"]]
AUTO = [[0, 59, "DMX (no programs)"], [60, 159, "auto programs"], [160, 255, "sound programs"]]
RESET = [[0, 249, "no function"], [250, 255, "reset (hold 5 s)"]]
MACRO = [[0, 7, "off (RGBW as set)"], [8, 255, "colour macros"]]
WHEEL = [[0, 9, "open / white"], [10, 127, "colours"], [128, 255, "rainbow, slow to fast"]]
GOBO = [[0, 7, "open"], [8, 63, "gobos"], [64, 127, "gobo shake"], [128, 255, "gobo scroll"]]
PRISM = [[0, 7, "no prism"], [8, 255, "prism"]]
PRISM_ROT = [[0, 127, "prism position"], [128, 255, "prism rotation"]]
FROST = [[0, 7, "no frost"], [8, 255, "frost"]]
LAMP = [[0, 199, "no function"], [200, 255, "lamp on/off (hold)"]]

# The wheel of a cheap spot: open, then colours of equal width; the colours are named in the check
WHEEL_SLOTS = [
    ("open", [1.0, 1.0, 1.0]),
    ("red", [1.0, 0.0, 0.0]),
    ("green", [0.0, 1.0, 0.0]),
    ("blue", [0.0, 0.2, 1.0]),
    ("yellow", [1.0, 0.9, 0.0]),
    ("magenta", [1.0, 0.0, 0.8]),
    ("cyan", [0.0, 0.9, 1.0]),
    ("orange", [1.0, 0.45, 0.0]),
]
GOBO_VALUES = [12, 20, 28, 36, 44, 52, 60]  # the middle of each gobo's range (GOBO above, 8 values wide)

TEMPLATES = {
    "spot-9": {
        "label": "LED spot, 9 channels",
        "type": "spot",
        "about": (
            "The usual cheap 30–100 W LED spot: pan, tilt, colour wheel, gobo, strobe, dimmer, speed, programs, reset."
        ),
        "channels": [
            _c("pan", "Pan"),
            _c("tilt", "Tilt"),
            _c("color_wheel", "Colour wheel", ranges=WHEEL),
            _c("gobo", "Gobo", 0, GOBO),
            _c("strobe", "Strobe", 0, STROBE),
            _c("dimmer", "Dimmer"),
            _c("pan_tilt_speed", "Pan/tilt speed", 0, SPEED),
            _c("auto", "Auto / sound programs", 0, AUTO),
            _c("reset", "Reset", 0, RESET),
        ],
    },
    "spot-11": {
        "label": "LED spot, 11 channels (fine pan/tilt)",
        "type": "spot",
        "about": "The 9-channel spot with fine pan and tilt after each.",
        "channels": [
            _c("pan", "Pan"),
            _c("pan_fine", "Pan fine"),
            _c("tilt", "Tilt"),
            _c("tilt_fine", "Tilt fine"),
            _c("color_wheel", "Colour wheel", ranges=WHEEL),
            _c("gobo", "Gobo", 0, GOBO),
            _c("strobe", "Strobe", 0, STROBE),
            _c("dimmer", "Dimmer"),
            _c("pan_tilt_speed", "Pan/tilt speed", 0, SPEED),
            _c("auto", "Auto / sound programs", 0, AUTO),
            _c("reset", "Reset", 0, RESET),
        ],
    },
    "spot-prism-14": {
        "label": "Spot with prism and focus, 14 channels",
        "type": "spot",
        "about": "A bigger LED spot: rotating gobos, a prism and focus.",
        "channels": [
            _c("pan", "Pan"),
            _c("pan_fine", "Pan fine"),
            _c("tilt", "Tilt"),
            _c("tilt_fine", "Tilt fine"),
            _c("pan_tilt_speed", "Pan/tilt speed", 0, SPEED),
            _c("dimmer", "Dimmer"),
            _c("shutter", "Shutter / strobe", 12, SHUTTER),
            _c("color_wheel", "Colour wheel", ranges=WHEEL),
            _c("gobo", "Gobo", 0, GOBO),
            _c("gobo_rotation", "Gobo rotation", 0, [[0, 127, "gobo position"], [128, 255, "rotation"]]),
            _c("prism", "Prism", 0, PRISM),
            _c("prism_rotation", "Prism rotation", 0, PRISM_ROT),
            _c("focus", "Focus", 128, [[0, 255, "focus, near to far"]]),
            _c("reset", "Reset", 0, RESET),
        ],
    },
    "wash-9": {
        "label": "LED wash, 9 channels (RGBW)",
        "type": "wash",
        "about": "The usual 7×10 W / 7×12 W mini wash: pan, tilt, speed, dimmer, strobe, red, green, blue, white.",
        "channels": [
            _c("pan", "Pan"),
            _c("tilt", "Tilt"),
            _c("pan_tilt_speed", "Pan/tilt speed", 0, SPEED),
            _c("dimmer", "Dimmer"),
            _c("strobe", "Strobe", 0, STROBE),
            _c("red", "Red"),
            _c("green", "Green"),
            _c("blue", "Blue"),
            _c("white", "White"),
        ],
    },
    "wash-14": {
        "label": "LED wash, 14 channels (RGBW, fine pan/tilt)",
        "type": "wash",
        "about": "The mini wash with fine pan and tilt, colour macros, programs and reset.",
        "channels": [
            _c("pan", "Pan"),
            _c("pan_fine", "Pan fine"),
            _c("tilt", "Tilt"),
            _c("tilt_fine", "Tilt fine"),
            _c("pan_tilt_speed", "Pan/tilt speed", 0, SPEED),
            _c("dimmer", "Dimmer"),
            _c("strobe", "Strobe", 0, STROBE),
            _c("red", "Red"),
            _c("green", "Green"),
            _c("blue", "Blue"),
            _c("white", "White"),
            _c("color_macro", "Colour macros", 0, MACRO),
            _c("auto", "Auto / sound programs", 0, AUTO),
            _c("reset", "Reset", 0, RESET),
        ],
    },
    "beam-16": {
        "label": "Beam (7R / 230 W), 16 channels",
        "type": "beam",
        "about": (
            "The 230 W lamp beam head, laid out like the beam it copies: colour first, pan and tilt in the middle."
        ),
        "channels": [
            _c("color_wheel", "Colour wheel", ranges=WHEEL),
            _c("shutter", "Shutter / strobe", 12, SHUTTER),
            _c("dimmer", "Dimmer"),
            _c("gobo", "Gobo", 0, GOBO),
            _c("prism", "Prism", 0, PRISM),
            _c("prism_rotation", "Prism rotation", 0, PRISM_ROT),
            _c("effects", "Effect macros", 0, [[0, 7, "off"], [8, 255, "macros"]]),
            _c("frost", "Frost", 0, FROST),
            _c("focus", "Focus", 128, [[0, 255, "focus, near to far"]]),
            _c("pan", "Pan"),
            _c("pan_fine", "Pan fine"),
            _c("tilt", "Tilt"),
            _c("tilt_fine", "Tilt fine"),
            _c("function", "Functions", 0, [[0, 255, "pan/tilt speed and special functions"]]),
            _c("reset", "Reset", 0, RESET),
            _c("lamp", "Lamp control", 0, LAMP),
        ],
    },
    "par-rgbw-8": {
        "label": "LED par, 8 channels (RGBW)",
        "type": "par",
        "about": "A par or small wash: dimmer, red, green, blue, white, strobe, programs, program speed.",
        "channels": [
            _c("dimmer", "Dimmer"),
            _c("red", "Red"),
            _c("green", "Green"),
            _c("blue", "Blue"),
            _c("white", "White"),
            _c("strobe", "Strobe", 0, STROBE),
            _c("auto", "Programs", 0, AUTO),
            _c("program_speed", "Program speed", 0, [[0, 255, "slow to fast"]]),
        ],
    },
    "par-rgb-3": {
        "label": "LED par, 3 channels (RGB)",
        "type": "par",
        "about": "Red, green and blue, nothing else: the light is as bright as its colours.",
        "channels": [_c("red", "Red"), _c("green", "Green"), _c("blue", "Blue")],
    },
    "blank": {
        "label": "Start from nothing",
        "type": "other",
        "about": "Every channel unknown: find out what each does in the check.",
        "channels": [],
    },
}


def templates(type_: str = "", channels: int = 0) -> list[dict]:
    """The templates for the new-fixture sheet, those of `type_` first and the closest channel count first."""
    out = []
    for tid, t in TEMPLATES.items():
        n = len(t["channels"])
        out.append(
            {
                "id": tid,
                "label": t["label"],
                "type": t["type"],
                "about": t["about"],
                "channels": [c["name"] for c in t["channels"]],
                "count": n,
            }
        )

    def rank(t: dict):
        blank = t["id"] == "blank"
        return (blank, type_ and t["type"] != type_, abs(t["count"] - channels) if channels else t["count"])

    return sorted(out, key=rank)


def types() -> list[dict]:
    return [{"type": t, "label": label, "kind": kind} for t, label, kind, _ in TYPES]


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def fit(template: str, count: int) -> list[dict]:
    """The template's channels for a fixture of `count` channels: cut off, or with unknown channels added."""
    chans = [dict(c) for c in TEMPLATES[template]["channels"][:count]]
    for n in range(len(chans), count):
        chans.append(_c(f"channel_{n + 1}", f"Channel {n + 1}", 0))
    return chans


def create(
    manufacturer: str,
    model: str,
    template: str,
    count: int,
    type_: str = "",
    watts: int = 0,
    pan_deg: int = 540,
    tilt_deg: int = 270,
) -> dict:
    """Make a fixture in your library from a template; returns {"key", "mode"} (or {"problems"})."""
    manufacturer, model = manufacturer.strip(), model.strip()
    problems = []
    if not model:
        problems.append("Give it a name (what the box or the label calls it, or what you call it)")
    if template not in TEMPLATES:
        problems.append(f"Unknown template '{template}'")
    if not 1 <= count <= 64:
        problems.append("A fixture has 1 to 64 channels (the manual or the fixture's display says how many)")
    if problems:
        return {"problems": problems}
    type_ = type_ if type_ in TYPE else TEMPLATES[template]["type"]
    _, _, kind, beam = TYPE[type_]
    chans = fit(template, count)
    attrs = {c["attr"] for c in chans if "default" not in c}
    if kind == "moving_head" and not {"pan", "tilt"} <= attrs:
        kind = "par"  # until the check finds pan and tilt
    mode = f"{count}ch"
    defn = {
        "manufacturer": manufacturer or "Generic",
        "model": model,
        "kind": kind,
        "source": f"Made from the template '{TEMPLATES[template]['label']}': check it channel by channel on the "
        "fixture (Set page, Check Channels)",
        "physical": {"beam_deg": beam},
        "modes": {mode: [{k: v for k, v in c.items() if k in ("attr", "default")} for c in chans]},
        "made": {
            "template": template,
            "type": type_,
            "checked": False,
            "channels": {mode: [{"name": c["name"], "ranges": c["ranges"]} for c in chans]},
        },
    }
    if watts > 0:
        defn["physical"].update(
            {"watts": watts, "lumens": watts * 20, "_lumens_note": "estimated from the power (20 lm/W)"}
        )
    if "color_wheel" in attrs:
        defn["color_wheel"] = wheel()
    if any(c["attr"] == "gobo" for c in chans):
        defn["beam_fx"] = {
            "_note": "Guessed from a common layout (gobos 8 values wide from 8); check them on the fixture.",
            "open": {},
            "gobo": {"gobo": list(GOBO_VALUES)},
        }
        if any(c["attr"] == "prism" for c in chans):
            defn["beam_fx"]["prism"] = {"prism": 128}
    if kind == "moving_head":
        defn["physical"].update({"pan_deg": pan_deg, "tilt_deg": tilt_deg})
        defn["motion"] = {
            "estimated": True,
            "pan_speed_dps": 200,
            "tilt_speed_dps": 160,
            "accel_dps2": 800,
            "_note": "Estimated; measure with `amadeus motion`.",
        }
    key = _free_key(_slug(manufacturer) or "generic", _slug(model) or "fixture")
    fxlib.save(key, defn)
    return {"key": key, "mode": mode}


def wheel(slots: list[dict] | None = None) -> dict:
    """A colour wheel: the named slots from the check, else the usual cheap wheel (open and seven colours
    across 0–127)."""
    if slots:
        return {"verified": True, "slots": slots}
    width = 128 // len(WHEEL_SLOTS)
    return {
        "_note": "The usual layout of a cheap wheel; name the colours in the check.",
        "verified": False,
        "slots": [
            {"name": name, "from": i * width, "to": (i + 1) * width - 1, "rgb": rgb}
            for i, (name, rgb) in enumerate(WHEEL_SLOTS)
        ],
    }


def _free_key(folder: str, name: str) -> str:
    lib = fxlib.library()
    key, n = f"{folder}/{name}", 2
    while key in lib:
        key, n = f"{folder}/{name}-{n}", n + 1
    return key
