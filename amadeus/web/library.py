"""Fixtures: our library, search across QLC+, the Open Fixture Library and DMXControl, adding fixtures, GDTF
import, label photos."""

from __future__ import annotations

from amadeus.library import fixtures as fxlib
from amadeus.web.events import event, save_photo


def library(req) -> list[dict]:
    """Fixture definitions: model, kind, modes with channel counts."""
    return [
        {
            "key": key,
            "manufacturer": d["manufacturer"],
            "model": d["model"],
            "kind": d["kind"],
            "modes": {m: len(ch) for m, ch in d["modes"].items()},
            "default_mode": fxlib.default_mode(d),
        }
        for key, d in fxlib.library().items()
    ]


def search(req):
    from amadeus.library import catalog

    return catalog.search(req.query.get("q", ""), int(req.query.get("limit", 15)))


def details(req):
    from amadeus.library import catalog

    try:
        return catalog.details(req.query["key"])
    except Exception as e:  # noqa: BLE001 - a broken library entry is reported, not fatal
        return {"error": f"{e.__class__.__name__}: {e}"}, 400


def add_to_library(req):
    from amadeus.library import catalog

    return {"key": catalog.add(req.body()["key"])}


def import_gdtf(req):
    """{"name", "data": base64 of a .gdtf}: convert it into your fixtures; {"key", "mode"} or {"error"}."""
    import base64
    import binascii
    import zipfile
    from xml.etree.ElementTree import ParseError

    from amadeus.library import gdtf

    b = req.body()
    name = str(b.get("name") or "")
    try:
        key = gdtf.add_file(base64.b64decode(b.get("data") or ""), name)
    except (binascii.Error, zipfile.BadZipFile, KeyError, ParseError, AttributeError, ValueError) as e:
        return {"error": f"{name or 'The file'} isn't a GDTF file this can read ({e.__class__.__name__}: {e})"}, 400
    d = fxlib.get(key)
    event(f"{req.client} imported {name} as {key}")
    return {"key": key, "mode": fxlib.default_mode(d), "inert": fxlib.inert(d), "warning": d.get("warning", "")}


def suggest(req):
    """{"key", "mode", "count", "universe"}: free start addresses (packed / easy to dial)."""
    from amadeus.library import catalog

    b = req.body()
    n = len(catalog.details(b["key"])["modes"][b["mode"]])
    rig = req.show.load()
    return {"footprint": n, **catalog.suggest_addresses(rig, n, int(b.get("count", 1)), int(b.get("universe", 1)))}


def add_to_rig(req):
    """{"key", "mode", "addresses", "universe"}: add fixtures to the saved rig."""
    from amadeus.library import catalog

    b = req.body()
    rig = req.show.load()
    new = catalog.add_to_rig(rig, b["key"], b["mode"], [int(a) for a in b["addresses"]], int(b.get("universe", 1)))
    problems = fxlib.validate(rig)
    if not problems:
        req.show.save(rig)
    return {"saved": not problems, "problems": problems, "added": new}


def get_mapping(req):
    """A fixture mode, channel by channel, for the DMX mapper."""
    from amadeus.library import mapper

    try:
        return mapper.describe(req.query["key"], req.query["mode"])
    except SystemExit as e:  # an unknown fixture or mode
        return {"error": str(e)}, 400


def save_mapping(req):
    """{"key", "mode", "kind", "channels": [{"role", "cell", "value"}]}, optionally "wheel" and "ring" (the colour
    wheel's and the ring's named colours) and "checked": save a hand mapping (nothing saved if there are problems)."""
    from amadeus.library import mapper

    b = req.body()
    checked = bool(b.get("checked"))
    problems = mapper.apply(
        b["key"], b["mode"], b.get("kind", "par"), list(b.get("channels", [])), b.get("wheel"), checked, b.get("ring")
    )
    if not problems:
        event(f"{req.client} mapped {b['key']} {b['mode']} by hand{' (checked on the fixture)' if checked else ''}")
    return {"saved": not problems, "problems": problems}


def save_lens(req):
    """{"key", "beam_deg", "beam_deg_max"?, "lumens"?}: a fixture's lens and light as its manual gives them."""
    b = req.body()
    lumens = b.get("lumens")
    problems = fxlib.set_lens(
        b["key"], float(b["beam_deg"]), float(b.get("beam_deg_max") or 0) or None, float(lumens) if lumens else None
    )
    if not problems:
        event(f"{req.client} set the lens of {b['key']}: {b['beam_deg']}° (zoom to {b.get('beam_deg_max')}), {lumens} lm")
    return {"saved": not problems, "problems": problems}


def fixture_templates(req):
    """The common layouts a new fixture is made from, closest to `type` and `channels` first."""
    from amadeus.library import generic

    q = req.query
    return {"types": generic.types(), "templates": generic.templates(q.get("type", ""), int(q.get("channels") or 0))}


def new_fixture(req):
    """{"manufacturer", "model", "template", "channels", "type", "watts", "pan_deg", "tilt_deg", "beam_deg"}: make a fixture in
    your library from a template; returns {"key", "mode"} or {"problems"}."""
    from amadeus.library import generic

    b = req.body()
    r = generic.create(
        str(b.get("manufacturer", "")),
        str(b.get("model", "")),
        str(b.get("template", "")),
        int(b.get("channels") or 0),
        str(b.get("type", "")),
        int(b.get("watts") or 0),
        int(b.get("pan_deg") or 540),
        int(b.get("tilt_deg") or 270),
        float(b.get("beam_deg") or 0),
    )
    if "key" in r:
        event(f"{req.client} made {r['key']} ({r['mode']}) from the template {b.get('template')}")
    return r


def label_engines(req):
    from amadeus.library import label

    return label.engines()


def identify_label(req):
    """{"image": data URL}: recognise a fixture from a photo of its label (or of the fixture)."""
    from amadeus.library import label

    b = req.body()
    img = b["image"]
    saved = save_photo(img)
    event(f"{req.client} label photo {len(img) * 3 // 4 // 1024} kB -> {saved}")
    r = label.identify(img, b.get("engine"))
    read = r.get("read", {})
    event(
        f"  label: engine={r['engine']} photo={r.get('photo')} type={r.get('type')}/{r.get('look')} "
        f"read={read.get('brand', '')!r} {read.get('model', '')!r} ({read.get('reasoning', '')}) "
        f"candidates={r.get('candidates')} direct={r.get('direct')} "
        f"matches={[(m['model'], m.get('probability')) for m in r['matches']]} note={r['note']!r}"
    )
    return r


GET = {
    "/api/library": library,
    "/api/catalog": search,
    "/api/catalog/details": details,
    "/api/fixture/map": get_mapping,
    "/api/label/engines": label_engines,
    "/api/fixture/templates": fixture_templates,
}
POST = {
    "/api/catalog/add": add_to_library,
    "/api/fixture/gdtf": import_gdtf,
    "/api/suggest": suggest,
    "/api/rig/add": add_to_rig,
    "/api/label": identify_label,
    "/api/fixture/map": save_mapping,
    "/api/fixture/new": new_fixture,
    "/api/fixture/lens": save_lens,
}
