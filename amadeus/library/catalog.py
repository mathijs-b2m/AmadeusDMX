"""One fixture search over every source: our own library, the QLC+ library, the Open Fixture Library and the
DMXControl DDF library.

Keys tell the source apart: "beamz/fuze75b-beam" (ours), "qlc:beamZ/beamZ-Fuze-75B-Beam.qxf",
"ofl:cameo/flat-pro-18", "ddf:eurolite/led-tmh-13". A fixture found in several libraries is listed once, from
the first source in that order (ours is checked on the real hardware; QLC+ has more DJ brands than the OFL; the
DDF library fills in DJ brands both lack, and is only in the shipped catalogue).
"""

from __future__ import annotations

import re
from functools import cache

from amadeus.library import ddf, ofl, qlc, shadow
from amadeus.library import fixtures as fxlib
from amadeus.library.ofl import _tokens

SOURCES = {
    "local": "your library",
    "qlc": "QLC+ library",
    "ofl": "Open Fixture Library",
    "ddf": "DMXControl DDF library",
}
REMOTE = ("qlc:", "ofl:", "ddf:")


OFL_TYPES = [
    ("Moving Head", "moving head"),
    ("Scanner", "scanner"),
    ("Barrel Scanner", "scanner"),
    ("Laser", "laser"),
    ("Pixel Bar", "led bar"),
    ("Strobe", "strobe"),
    ("Blinder", "par"),
    ("Flower", "effect"),
    ("Effect", "effect"),
    ("Smoke", "smoke"),
    ("Hazer", "smoke"),
    ("Matrix", "led bar"),
    ("Color Changer", "par"),
    ("Dimmer", "par"),
]
LOCAL_TYPES = {
    "moving_head": "moving head",
    "moving_bar": "moving bar",
    "par": "par",
    "par_bar": "led bar",
    "strobe": "strobe",
    "blinder": "blinder",
    "laser": "laser",
    "smoke": "smoke",
}


def _typed(c: dict) -> dict:
    """Fill in "type" (moving head, par, led bar, …) and for moving heads "look" (beam/spot/wash/hybrid)."""
    if "type" not in c:
        cats = c.get("categories", [])
        c["type"] = next((t for cat, t in OFL_TYPES if cat in cats), LOCAL_TYPES.get(c.get("kind"), "other"))
    if c["type"] == "moving head" and not c.get("look"):
        from amadeus.library.qlc import LOOKS

        name = c["model"].lower()
        c["look"] = next(("hybrid" if w == "profile" else w for w in LOOKS if w in name), "")
    return c


def _ident(c: dict) -> str:
    return "".join(_tokens(f"{c['manufacturer']} {c['model']}"))


@cache
def _candidates_cached() -> tuple:
    return tuple(_candidates_uncached())


def _candidates() -> list[dict]:
    """Every fixture of every source (deduplicated); cached until our own library changes."""
    if fxlib.library.cache_info().currsize == 0:
        _candidates_cached.cache_clear()
    return [dict(c) for c in _candidates_cached()]


def _candidates_uncached() -> list[dict]:
    out = []
    for key, d in fxlib.library().items():
        out.append(
            {
                "key": key,
                "manufacturer": d["manufacturer"],
                "model": d["model"],
                "source": "local",
                "kind": d["kind"],
                "modes": {m: len(c) for m, c in d["modes"].items()},
            }
        )
        if d["kind"] == "moving_head" and "gobo_names" in d and "beam" not in d["model"].lower():
            out[-1]["look"] = "spot"
    for source, index in (("qlc", qlc.index), ("ofl", ofl.index)):
        out += [_typed(dict(c, source=source)) for c in _source_index(source, index)]
    out += [_typed(dict(c, source="ddf")) for c in shadow.index("ddf") or []]
    seen, unique = set(), []
    for c in out:
        _typed(c)
        if _ident(c) not in seen:
            seen.add(_ident(c))
            unique.append(c)
    return unique


def _source_index(source: str, live) -> list[dict]:
    """The shipped catalogue's entries, plus any newer ones of a library already downloaded here; without a
    catalogue, the library itself (downloaded on first use)."""
    shipped = shadow.index(source)
    downloaded = qlc.FIXTURES_DIR.exists() if source == "qlc" else (ofl.OFL_DIR / "fixtures").exists()
    if shipped is not None and not downloaded:
        return shipped
    try:
        fresh = live()
    except OSError:  # offline and not cached yet: search what we have
        return shipped or []
    if shipped is None:
        return fresh
    known = {c["key"] for c in shipped}
    return shipped + [c for c in fresh if c["key"] not in known]


def definition(key: str) -> dict:
    """A QLC+ / OFL / DDF entry converted: from the shipped catalogue, else converted now (downloads if needed)."""
    d = shadow.get(key)
    if d is not None:
        return d
    if key.startswith("ddf:"):
        raise KeyError(f"{key} is not in the shipped DDF catalogue")
    if key.startswith("qlc:"):
        return qlc.convert(key[4:])
    return ofl.convert(*key[4:].split("/", 1))


def search(query: str, limit: int = 15) -> list[dict]:
    """Scored by how many query words match (prefix) brand/model; our own library wins ties."""
    q = _tokens(query)
    if not q:
        return []
    rank = {"local": 3, "qlc": 2, "ofl": 1, "ddf": 0}
    scored = []
    for c in _candidates():
        words = _tokens(f"{c['manufacturer']} {c['model']}")
        joined = "".join(words)
        hits = sum(1 for t in q if any(w.startswith(t) for w in words) or t in joined)
        if hits / len(q) >= 0.5:
            exact = sum(1 for t in q if t in words)
            scored.append((hits / len(q), exact, rank[c["source"]], -len(words), c))
    scored.sort(key=lambda x: x[:4], reverse=True)
    return [c for *_, c in scored[:limit]]


def details(key: str) -> dict:
    """Modes and channel layout of any catalogue entry (downloads the definition if needed)."""
    d = definition(key) if key.startswith(REMOTE) else fxlib.get(key)
    return {
        "key": key,
        "manufacturer": d["manufacturer"],
        "model": d["model"],
        "kind": d["kind"],
        "modes": {m: [c["attr"] for c in ch] for m, ch in d["modes"].items()},
        "default_mode": fxlib.default_mode(d),
        "color_wheel": "color_wheel" in d,
        "gobos": len(d.get("gobo_names", [])),
        "inert": fxlib.inert(d),  # not driven by the show (a converted laser, smoke): why
        "warning": d.get("warning", ""),
    }


def add(key: str) -> str:
    """Make a catalogue entry usable in the rig; returns its key in our library."""
    if key.startswith("qlc:"):
        return qlc.add_to_library(key)
    if key.startswith("ofl:"):
        return ofl.add_to_library(key)
    if key.startswith("ddf:"):
        return ddf.add_to_library(key)
    fxlib.get(key)
    return key


def _free(used: set[int], start: int, n: int) -> bool:
    return start + n - 1 <= 512 and not any(ch in used for ch in range(start, start + n))


def suggest_addresses(rig: dict, footprint: int, count: int = 1, universe: int = 1) -> dict:
    """Start addresses for `count` new fixtures that leave the rig's existing fixtures where they are.

    "packed": back-to-back in the first free gaps. "easy": every start ends in 1 (1, 11, 21, …), which
    is quicker to dial in on a fixture's menu and easier to remember; it costs a few unused channels.
    """
    used = {
        ch
        for f in rig.get("fixtures", [])
        if f.get("universe", 1) == universe and fxlib.patched(f)
        for ch in range(f["address"], f["address"] + fxlib.footprint(f))
    }
    out = {}
    for name, step in (("packed", 1), ("easy", 10)):
        taken, starts, a = set(used), [], 1
        while len(starts) < count and a <= 512:
            if _free(taken, a, footprint):
                starts.append(a)
                taken.update(range(a, a + footprint))
                a += footprint
                a = a if step == 1 else a + (-(a - 1)) % step
            else:
                a += step
        out[name] = starts if len(starts) == count else None
    return out


def add_to_rig(rig: dict, key: str, mode: str, addresses: list[int], universe: int = 1) -> list[dict]:
    """Add fixtures (from any catalogue source) to the rig dict; existing fixtures are not touched."""
    from amadeus.dmx.discover import layout, new_ids

    lib_key = add(key)
    new = [{"fixture": lib_key, "mode": mode, "universe": universe, "address": a} for a in addresses]
    taken = {f["id"] for f in rig["fixtures"]}
    new_ids([dict(f) for f in rig["fixtures"]] + new)  # existing ids count along: fuze1, fuze2 → fuze3
    for f in new:
        n = 2
        while f["id"] in taken:
            f["id"] = re.sub(r"\d+$", "", f["id"]) + str(n)
            n += 1
        taken.add(f["id"])
    layout(new)  # positions for the new ones only; the setup photo/scan places them properly
    rig["fixtures"] += new
    return new
