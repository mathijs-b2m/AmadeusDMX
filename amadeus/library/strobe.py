"""A fixture's own strobe: which values of a channel make it strobe, and how fast.

A channel that can strobe says so with "strobe_range": [slowest value, fastest value] (the two can be either way
round) and, when its source gives the speeds, "strobe_hz": [slowest, fastest]. While the engine strobes a light
that has one, its dimmer stays open and this channel flashes it; everywhere else the channel keeps its quiet
"default". Only the steady strobe counts: random strobes, pulses and ramps are not what the show asks for.

Without known speeds the range is taken to run over ASSUMED_HZ, on the high side: a fixture that really tops out
lower plays slower than asked, not faster, so the set's flash limit holds.
"""

from __future__ import annotations

import re

ASSUMED_HZ = (1.0, 25.0)
CHANNEL = re.compile(r"shutter|strobe|flash|^rate$", re.I)  # what a channel that can strobe is called
STROBE = re.compile(r"strob|flash rate|flashes|^\s*[\d.]+\s*(hz)?\s*(to|-|–|→)\s*[\d./]+\s*hz", re.I)
NOT_STROBE = re.compile(
    r"random|rnd|puls|ramp|burst|sync|lightning|duration|\bopen|\bclos|sound|music|audio|macro|program"
    r"|\bauto|\bms\b|thunder|sparkle|double|triple|group|\bno\b|\boff\b|\bstop",
    re.I,
)
FAST_FIRST = re.compile(r"fast\w*\s*(to|-|–|→|->|>)\s*slow|fast\s*-\s*slow", re.I)
SPEEDS = re.compile(
    r"([\d.]+)\s*(?:hz|flash\w*(?:\s*/\s*\w+)?)?\s*(?:to|-|–|→|->|…)\s*(?:fast\s*)?([\d.]+)\s*(?:/[\d.]+\s*)?(?:hz|flash)",
    re.I,
)
PERIODS = re.compile(r"([\d.,]+)\s*s(?:ec\w*)?\s*(?:to|-|–|→|->)\s*([\d.,]+)\s*ms", re.I)  # "from 3,27 s to 30 ms"
NARROWEST = 8  # a range of unknown speeds this wide at least: a few values are a setting, not a slow-to-fast


def _number(v) -> float | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _speeds(text: str, a, b) -> tuple[float | None, float | None]:
    """The speeds at a range's two ends: from the source's own fields, else from its words."""
    a, b = _number(a), _number(b)
    if a is None and (m := SPEEDS.search(text)):
        a, b = _number(m[1]), _number(m[2])
    return a, b


def pick(ranges: list) -> dict:
    """{"strobe_range", "strobe_hz"} for a channel from its value ranges: (from, to, what it does in words, speed
    at from, speed at to), the speeds optional (None). A row of steps at one speed each ("Strobe 1 Hz", "Strobe
    2 Hz", …) counts as one range. {} when none of them is a steady strobe."""
    found = []
    for lo, hi, text, *hz in ranges:
        text = str(text or "")
        if m := PERIODS.search(text):  # a flash every so long: its speeds, and no flash's duration
            hz = [1 / _number(m[1].replace(",", ".")), 1000 / _number(m[2].replace(",", "."))]
            text = PERIODS.sub("", text)
        if not STROBE.search(text) or NOT_STROBE.search(text):
            continue
        a, b = _speeds(text, *(list(hz) + [None, None])[:2])
        a, b = (round(v, 2) if v else v for v in (a, b))
        if a is not None or hi - lo >= NARROWEST:
            found.append((int(lo), int(hi), text, a, b))
    if not found:
        return {}
    steps = sorted(f for f in found if f[3] is not None and f[4] is None)
    if len(steps) >= 2:
        first, last = steps[0], steps[-1]
        a, b = first[3], last[3]
        return {"strobe_range": [first[0], last[1]] if a <= b else [last[1], first[0]], "strobe_hz": sorted((a, b))}
    lo, hi, text, a, b = max(found, key=lambda f: f[1] - f[0])
    if b is None:  # one speed only: a fixed strobe
        b = a
    if a is not None and a != b:
        fast_first = a > b
    else:
        fast_first = bool(FAST_FIRST.search(text))
    out = {"strobe_range": [hi, lo] if fast_first else [lo, hi]}
    if a is not None:
        out["strobe_hz"] = sorted((a, b))
    return out


def mark(spec: dict, ranges: list) -> dict:
    """Add what `pick` finds to a channel the show holds at a default (a driven channel is no strobe channel)."""
    if "default" in spec and CHANNEL.search(spec["attr"]) and "duration" not in spec["attr"]:
        spec.update(pick(ranges))
        slow, fast = spec.get("strobe_range", (0, 0))
        if slow != fast and min(slow, fast) <= spec["default"] <= max(slow, fast):  # the quiet value is no strobe
            end = 0 if abs(spec["default"] - slow) <= abs(spec["default"] - fast) else 1  # the end it's nearest
            spec["strobe_range"][end] = spec["default"] + (1 if (fast > slow) == (end == 0) else -1)
    return spec


def value(c: dict, hz: float) -> int | None:
    """The DMX value that strobes this channel at about `hz`, never faster. None when it can't go that slowly:
    its slowest strobe is known to be faster than asked."""
    slow, fast = c["strobe_range"]
    known = "strobe_hz" in c
    a, b = c["strobe_hz"] if known else ASSUMED_HZ
    if known and hz < a - 1e-6:
        return None
    share = min(max((hz - a) / (b - a), 0.0), 1.0) if b > a else 0.0
    return slow + int(share * (fast - slow)) if fast >= slow else slow - int(share * (slow - fast))
