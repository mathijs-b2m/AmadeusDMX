"""Fixtures: our library, search across QLC+ and the Open Fixture Library, adding fixtures, label photos."""

from __future__ import annotations

import json

from decisive.library import fixtures as fxlib
from decisive.web.events import event, save_photo


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
    from decisive.library import catalog

    return catalog.search(req.query.get("q", ""), int(req.query.get("limit", 15)))


def details(req):
    from decisive.library import catalog

    try:
        return catalog.details(req.query["key"])
    except Exception as e:  # noqa: BLE001 - a broken library entry is reported, not fatal
        return {"error": f"{e.__class__.__name__}: {e}"}, 400


def add_to_library(req):
    from decisive.library import catalog

    return {"key": catalog.add(req.body()["key"])}


def suggest(req):
    """{"key", "mode", "count", "universe"}: free start addresses (packed / easy to dial)."""
    from decisive.library import catalog

    b = req.body()
    n = len(catalog.details(b["key"])["modes"][b["mode"]])
    rig = json.loads(req.rig_path.read_text())
    return {"footprint": n, **catalog.suggest_addresses(rig, n, int(b.get("count", 1)), int(b.get("universe", 1)))}


def add_to_rig(req):
    """{"key", "mode", "addresses", "universe"}: add fixtures to the saved rig."""
    from decisive.library import catalog

    b = req.body()
    rig = json.loads(req.rig_path.read_text())
    new = catalog.add_to_rig(rig, b["key"], b["mode"], [int(a) for a in b["addresses"]], int(b.get("universe", 1)))
    problems = fxlib.validate(rig)
    if not problems:
        req.rig_path.write_text(json.dumps(rig, indent=2))
    return {"saved": not problems, "problems": problems, "added": new}


def label_engines(req):
    from decisive.library import label

    return label.engines()


def identify_label(req):
    """{"image": data URL}: recognise a fixture from a photo of its label (or of the fixture)."""
    from decisive.library import label

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
    "/api/label/engines": label_engines,
}
POST = {
    "/api/catalog/add": add_to_library,
    "/api/suggest": suggest,
    "/api/rig/add": add_to_rig,
    "/api/label": identify_label,
}
