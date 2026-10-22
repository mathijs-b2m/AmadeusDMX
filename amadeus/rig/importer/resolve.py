"""Which library fixture and mode each fixture type of the documents is.

A name is searched in every library (ours, QLC+, the Open Fixture Library); a match must name the same model
numbers ("X4 Bar 20" is not an "X4 Bar 10") and have a mode as long as the document's footprint, when it says.
What fits best is taken; anything short of every word and the footprint matching is marked for a check. A type
nothing matches is made from a generic template (conventional lights on a dimmer: a PAR 64 on one channel), so
the rig is complete and plays, and the report says to check it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from amadeus.library import catalog, generic
from amadeus.library import fixtures as fxlib
from amadeus.library.ofl import _tokens
from amadeus.rig.importer.draft import Draft, Item
from amadeus.rig.importer.sheet import CONVENTIONAL

NOISE = {
    "custom",
    "fixture",
    "the",
    "lighting",
    "lights",
    "systems",
    "professional",
    "professionel",
    "inc",
    "gmbh",
    "ltd",
    "co",
    "gdtf",
}
DIMMER_KEY = "generic/par-64"


@dataclass
class Choice:
    key: str  # in our library (added from the catalogue when needed)
    mode: str
    footprint: int
    sure: bool  # every word and the footprint matched
    why: str = ""  # for the report, when not sure


SHORT = {"clr": "color", "col": "color", "colour": "color", "lt": "light", "mh": "moving"}  # as patch lists write


def _words(text: str) -> list[str]:
    return [SHORT.get(t, t) for t in _tokens(text) if t not in NOISE]


def _modes(c: dict) -> dict[str, int]:
    if isinstance(c.get("modes"), dict) and all(isinstance(v, int) for v in c["modes"].values()):
        return c["modes"]
    try:
        return {m: len(chs) for m, chs in catalog.details(c["key"])["modes"].items()}
    except (OSError, KeyError, ValueError):
        return {}


def mode_like(modes: dict[str, int], channels: int, named: str) -> str | None:
    """The mode with `channels` channels (the one named most like `named` when several); without a footprint,
    the one named like `named`; None when neither says."""
    fit = [m for m, n in modes.items() if n == channels] if channels else list(modes)
    if not fit:
        return None
    want = _words(named)

    def likeness(m: str) -> int:
        have = _words(m)
        return sum(1 for w in want if any(h.startswith(w) or w.startswith(h) for h in have))

    best = max(fit, key=likeness)
    if channels or (want and likeness(best)):
        return best
    return None


def match(name: str, channels: int, mode: str) -> Choice | None:
    """The best library fixture for a type name (None: nothing close)."""
    q = _words(re.sub(r"\(.*?\)", " ", name))
    if not q:
        return None
    q_numbers = {w for w in q if w.isdigit()}
    best = None
    for rank, c in enumerate(catalog.search(" ".join(q), 12)):
        bare = re.sub(r"\(.*?\)", " ", c["model"])  # "PAR 64 (on a dimmer)": the note isn't part of the name
        words, model, brand_words = _words(f"{c['manufacturer']} {bare}"), _words(bare), _words(c["manufacturer"])
        found = [w for w in q if w in words or any(x.startswith(w) for x in words)]
        hit = len(found) / len(q)
        covered = sum(1 for w in model if w in q) / max(len(model), 1)
        numbers_ok = q_numbers <= set(words) and {w for w in model if w.isdigit()} <= set(q)
        brand = any(w in q for w in brand_words)
        rest = [w for w in q if w not in brand_words]
        if not (covered == 1 or (brand and all(w in found for w in rest))):  # the whole model, or brand and words
            continue
        modes = _modes(c)
        m = mode_like(modes, channels, mode)
        score = (m is not None or not channels, numbers_ok, hit + covered, -rank)
        if best is None or score > best[0]:
            best = (score, c, m or fxlib_default(modes), modes, hit, covered, numbers_ok)
    if best is None:
        return None
    _, c, m, modes, hit, covered, numbers_ok = best
    fits = not channels or modes.get(m) == channels
    if channels == 1 and not fits:  # one dimmer channel ("Dim Clr Command"): a light on a dimmer, not that fixture
        return None
    sure = fits and numbers_ok and hit == 1 and covered == 1
    why = []
    if not numbers_ok or hit < 1 or covered < 1:
        why.append(f"named “{name}”, taken as {c['manufacturer']} {c['model']}")
    if not fits:
        why.append(f"no mode of {channels} channels; {m} ({modes.get(m, '?')} ch) is used")
    elif not channels and not mode:
        why.append(f"the documents don't say the mode: {m}")
    return Choice(c["key"], m, modes.get(m, 0), sure, "; ".join(why))


def fxlib_default(modes: dict[str, int]) -> str:
    return max(modes, key=lambda k: modes[k]) if modes else ""


def _template(name: str) -> str:
    n = name.lower()
    if "wash" in n:
        return "wash-14"
    if "beam" in n:
        return "beam-16"
    if re.search(r"spot|profile|moving|head", n):
        return "spot-prism-14"
    return "par-rgbw-8"


def make(name: str, channels: int) -> Choice:
    """A type nothing matches: a PAR 64 on a dimmer for a conventional light, else a fixture from a template."""
    if channels == 1 or CONVENTIONAL.search(name):
        return Choice(
            DIMMER_KEY, "1ch", 1, False, f"“{name}” isn't in any library: played as a light on one dimmer channel"
        )
    template = _template(name)
    count = min(channels or len(generic.TEMPLATES[template]["channels"]), 64)
    r = generic.create("", name, template, count)
    if "problems" in r:
        return Choice(DIMMER_KEY, "1ch", 1, False, f"“{name}”: {'; '.join(r['problems'])}")
    return Choice(
        r["key"],
        r["mode"],
        count,
        False,
        f"“{name}” isn't in any library: made from the "
        f"{generic.TEMPLATES[template]['label']} template; check its channels (Map Channels…)",
    )


def resolve(draft: Draft) -> dict[int, Choice]:
    """A choice per item (by its index in `draft.items`); the types are looked up once each."""
    footprint_from_spacing(draft.items)
    seen: dict[tuple, Choice] = {}
    out = {}
    for i, it in enumerate(draft.items):
        k = (it.name.lower(), it.channels, it.mode.lower())
        if k not in seen:
            c = match(it.name, it.channels, it.mode) or make(it.name, it.channels)
            if c.key.startswith(("qlc:", "ofl:")):
                c.key = catalog.add(c.key)
            if not c.mode:
                c.mode = fxlib.default_mode(fxlib.get(c.key))
                c.footprint = len(fxlib.get(c.key)["modes"][c.mode])
            seen[k] = c
        out[i] = seen[k]
    return out


def footprint_from_spacing(items: list[Item]) -> None:
    """Fill in a type's footprint from how far apart its fixtures are patched (one after the other in a
    universe), when the documents don't say it."""
    by_type: dict[str, list[tuple[int, int]]] = {}
    for it in items:
        if it.address and not it.channels:
            by_type.setdefault(it.name.lower(), []).append((it.universe, it.address))
    for name, spots in by_type.items():
        gaps = sorted(
            b - a for (u, a), (u2, b) in zip(sorted(spots), sorted(spots)[1:]) if u == u2 and 0 < b - a <= 512
        )
        if len(gaps) >= 2 and gaps[0] == gaps[len(gaps) // 2]:  # the tightest spacing is the usual one
            for it in items:
                if it.name.lower() == name and not it.channels:
                    it.channels = gaps[0]
