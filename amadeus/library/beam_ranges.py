"""Gobos, prisms and frost for any fixture that has them: a fixture's beam effects (`beam_fx`, the DMX value of
each gobo, of the prism in, of the frost) read from its channels' value ranges when its file doesn't give them.

The show only puts a gobo or a prism in the beam when it knows the value that does it; without one the head
plays an open beam. The converters write that table from the libraries' presets, a hand-written file has its
own, but a fixture made from a manual's chart or mapped by hand has only the chart's words ("Gobos 1 to 14",
"24 Prism", "Prism rotates from slow to fast"), and some library files name a prism or a frost without the
preset the converters look for. This reads those words, in the chart's order, as the library loads: what a file
gives is kept, only what it lacks is filled in. A channel with no ranges at all gets the usual cheap layout,
the way a template guesses it (generic.py), to check on the fixture.
"""

from __future__ import annotations

import re

NOTE = "_filled"  # in beam_fx: the effects read here (not in the file)
MOVING = ("moving_head", "scanner")  # the lights with gobo wheels and prisms (an LED bar's "pattern" is no gobo)

# which channel is which, by its attr or its chart name (the first of each in a mode; a fine or timing channel,
# a rotation channel or a combined colour/gobo wheel is not the wheel itself)
GOBO = re.compile(r"gobo|pattern", re.I)
PRISM = re.compile(r"prism", re.I)
FROST = re.compile(r"frost", re.I)
NOT_THE_WHEEL = re.compile(r"rot|index|time|fine|speed|flash|freq|strobe|chase|laser|colou?r|macro|shake|effect", re.I)

# a range's words
SPIN = re.compile(r"rotat|spin|scroll|clockwise|\bcw\b|\bccw\b|rainbow|automatic|switch|cycl|\bflow|turn|\brun\b", re.I)
INDEXED = re.compile(r"index|position|\d+\s*°|stop|no rotation", re.I)  # a still angle, not a rotation
NOT_A_GOBO = re.compile(r"random|audio|sound|\bauto|macro|program|reducer|small beam|\bhole\b|iris|stop", re.I)
SHAKE = re.compile(r"shak|jitter|wobbl|vibrat|bounc|swing", re.I)
OPEN = re.compile(r"open|white|no gobo|^\s*off\b|none|no function|blank|no effect|nothing", re.I)
# "Open" alone is the prism out; "Open prism" (a translated chart) is the prism in
PRISM_OFF = re.compile(r"\boff\b|clos|\bout\b|exclud|no prism|no function|none|no effect|nothing|without|"
                       r"^\W*open\W*$|^\W*open\b(?!.*prism)", re.I)  # fmt: skip
FROST_OFF = re.compile(r"\boff\b|\bout\b|\bno\b|open|none|nothing|without|clear", re.I)
NOT_FROST = re.compile(r"puls|ramp|raming|rainbow|rianbow|strob|macro|random|\bauto|colou?r", re.I)
FROST_FULL = re.compile(r"100\s*%|\bfull|\bmax", re.I)
FROST_SWEEP = re.compile(r"0\s*[-–~]\s*100|linea|linéa|\bto\b|\bfrom\b", re.I)  # a range that fades the frost in
COUNT = re.compile(r"(\d+)\s*(?:to|-|–|~|…|\.\.)\s*(\d+)")
HERTZ = re.compile(r"\(?\d+(?:\.\d+)?\s*hz\s*(?:[-~–]\s*\d+(?:\.\d+)?\s*hz)?\)?", re.I)

# a channel the chart gives no ranges for (the usual cheap layout: open 0-7, then gobos 8 values wide)
GUESS_GOBOS = [12, 20, 28, 36, 44, 52, 60]
GUESS_PRISM = 128
GUESS_FROST = 255


def _words(text: str) -> str:
    return HERTZ.sub(" ", str(text or ""))


def _count(text: str) -> int:
    """How many gobos one range holds ("Gobos 1 to 14": 14), 1 when it doesn't say."""
    m = COUNT.search(_words(text))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= b - a + 1 <= 32:
            return b - a + 1
    return 1


def _split(lo: int, hi: int, n: int) -> list[int]:
    """The middle of each of `n` equal parts of a DMX range."""
    width = (hi - lo + 1) / n
    return [round(lo + width * (k + 0.5) - 0.5) for k in range(n)]


def _turn(ranges: list[tuple[int, int, str]]) -> dict | None:
    """A rotation's ranges as the show plays them: {range: [slow, fast]} one way, {reverse: [slow, fast]} the other."""
    ways = {}
    for lo, hi, text in ranges:  # the first range each way (a second prism's rotation is not the way back)
        back = bool(re.search(r"anti|counter|\bccw\b|backward|reverse|\bleft\b", text, re.I))
        ways.setdefault(back, [hi, lo] if re.search(r"fast\s*(?:to|-|–|>)\s*slow", text, re.I) else [lo, hi])
    if not ways:
        return None
    out = {"range": ways.get(False) or ways[True]}
    if False in ways and True in ways:
        out["reverse"] = ways[True]
    return out


def _gobo_fx(attr: str, ranges: list[tuple[int, int, str]]) -> dict:
    if not ranges:
        return {"gobo": {attr: list(GUESS_GOBOS)}}
    gobos, shakes, spins, seen = [], [], [], set()
    for lo, hi, text in ranges:
        if SHAKE.search(text):
            if not NOT_A_GOBO.search(text):  # (a beam reducer shaking is no gobo)
                shakes.append((lo, hi, text))
        elif SPIN.search(text) and not INDEXED.search(text):
            spins.append((lo, hi, text))
        elif NOT_A_GOBO.search(text) or OPEN.search(text) and not COUNT.search(_words(text)):
            continue
        elif text.strip().lower() not in seen:  # (a gobo listed twice: the first; the second is often its shake)
            seen.add(text.strip().lower())
            gobos.append((lo, hi, text))
    out = {}
    values = [v for lo, hi, text in gobos for v in _split(lo, hi, _count(text))]
    if values:
        out["gobo"] = {attr: values}
    shaken = [v for lo, hi, text in shakes for v in _split(lo, hi, _count(text))]
    if shaken:
        out["gobo_shake"] = {attr: shaken}
    if spins and (turn := _turn(spins)):
        out["gobo_spin"] = {attr: turn}
    return out


def _prism_fx(attr: str, ranges: list[tuple[int, int, str]]) -> dict:
    if not ranges:
        return {"prism": {attr: GUESS_PRISM}}
    turning = [SPIN.search(text) and not INDEXED.search(text) for _, _, text in ranges]
    on = [(lo, hi) for (lo, hi, text), t in zip(ranges, turning) if not t and not PRISM_OFF.search(text)
          and not NOT_A_GOBO.search(text)]  # fmt: skip
    spins = [(lo, hi, text) for (lo, hi, text), t in zip(ranges, turning) if t and not PRISM_OFF.search(text)]
    out = {}
    if on:
        lo, hi = on[0]
        out["prism"] = {attr: (lo + hi) // 2}
    if spins and (turn := _turn(spins)):
        out["prism_spin"] = {attr: turn}
        if "prism" not in out:  # a prism that only turns: in, turning slowly
            lo, hi = turn["range"]
            out["prism"] = {attr: lo}
    return out


def _frost_fx(attr: str, ranges: list[tuple[int, int, str]]) -> dict:
    if not ranges:
        return {"frost": {attr: GUESS_FROST}}
    if len(ranges) == 1 and ranges[0][0] <= 5 and ranges[0][1] >= 250:  # one sweep, out to in ("Frost off…high")
        return {"frost": {attr: ranges[0][1]}}
    on = [(lo, hi, text) for lo, hi, text in ranges if not FROST_OFF.search(text) and not NOT_FROST.search(text)]
    if not on:
        return {}
    lo, hi, text = next((r for r in on if FROST_FULL.search(r[2])), on[0])  # all the way in, else the first
    return {"frost": {attr: hi if FROST_SWEEP.search(text) and not FROST_FULL.search(text) else (lo + hi) // 2}}


def _ranges(src: dict | None) -> list[tuple[int, int, str]]:
    out = []
    for r in (src or {}).get("ranges") or []:
        try:
            lo, hi, text = int(r[0]), int(r[1]), str(r[2] if len(r) > 2 else "")
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= lo <= hi <= 255:
            out.append((lo, hi, text))
    return out


def _pick(chans: list[dict], names: list[dict | None], rx: re.Pattern, own: str) -> tuple[str, list] | None:
    """The mode's channel for a wheel (its attr and its ranges): the one called `own`, else the first whose attr or
    chart name says it."""
    found = []
    for n, c in enumerate(chans):
        if c["attr"] != own and "default" not in c:
            continue  # a channel the show plays (a dimmer the chart calls "Pattern white light") is no wheel
        src = names[n] if n < len(names) else None
        words = f"{c['attr']} {(src or {}).get('name', '')}"
        if c["attr"] == own or (rx.search(words) and not NOT_THE_WHEEL.search(words.replace(own, ""))):
            found.append((c["attr"] != own, n, c["attr"], _ranges(src)))
    if not found:
        return None
    _, _, attr, ranges = min(found)
    return attr, ranges


def missing(defn: dict) -> bool:
    """Has a gobo, prism or frost channel the beam effects don't play."""
    table = defn.get("beam_fx", {})
    for chans in defn.get("modes", {}).values():
        if not isinstance(chans, list):
            continue
        attrs = {c.get("attr", "") for c in chans}
        for rx, fx in ((GOBO, "gobo"), (PRISM, "prism"), (FROST, "frost")):
            entry = table.get(fx)
            if isinstance(entry, dict) and set(entry) <= attrs:
                continue
            if any(rx.search(a) and not NOT_THE_WHEEL.search(a.replace(fx, "")) or a == fx for a in attrs):
                return True
    return False


def fill(defn: dict, sources=None, guess: bool = True) -> list[str]:
    """Fill in the beam effects a fixture's file lacks, from its channels' ranges (`sources(defn, mode)`: the
    chart's [{"name", "ranges"}] per channel, None when unknown). `guess`: a channel without ranges gets the usual
    cheap layout (never for a library's fixture whose file isn't at hand). Returns the effects filled in."""
    if defn.get("kind") not in MOVING or defn.get("inert") or not missing(defn):
        return []
    table = defn.setdefault("beam_fx", {"open": {}})
    table.setdefault("open", {})
    added = []
    for mode, chans in defn.get("modes", {}).items():
        if not isinstance(chans, list):
            continue
        attrs = {c.get("attr", "") for c in chans}
        names = (sources(defn, mode) if sources else None) or []
        for rx, own, read in ((GOBO, "gobo", _gobo_fx), (PRISM, "prism", _prism_fx), (FROST, "frost", _frost_fx)):
            entry = table.get(own)
            if isinstance(entry, dict) and set(entry) <= attrs:
                continue  # the file plays it in this mode
            picked = _pick(chans, names, rx, own)
            if not picked or not (picked[1] or guess):
                continue
            for fx, values in read(*picked).items():
                have = table.get(fx)
                if isinstance(have, dict) and set(have) <= attrs:
                    continue
                if fx not in table:
                    table[fx] = values
                    added.append(fx)
    if added:
        table[NOTE] = sorted(set(table.get(NOTE, [])) | set(added))
    return added


def unfilled(defn: dict) -> dict:
    """The definition without what `fill` read (a file keeps only what it says; the library reads the rest again
    as it loads, from the ranges as they are then)."""
    table = defn.get("beam_fx")
    if not isinstance(table, dict) or NOTE not in table:
        return defn
    out = dict(defn)
    out["beam_fx"] = {k: v for k, v in table.items() if k != NOTE and k not in table[NOTE]}
    if set(out["beam_fx"]) <= {"open"}:
        out.pop("beam_fx")
    return out


# the converters' reading of a library channel whose capabilities carry no preset, only names
def gobo_words(ranges: list[tuple[int, int, str]]) -> dict:
    return _gobo_fx("gobo", ranges) if ranges else {}


def prism_words(ranges: list[tuple[int, int, str]]) -> dict:
    return _prism_fx("prism", ranges) if ranges else {}


def frost_words(ranges: list[tuple[int, int, str]]) -> dict:
    return _frost_fx("frost", ranges) if ranges else {}
