"""The rig: the set file itself, its decision model, DMX outputs, sets, patching and finding nodes."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

from decisive import paths
from decisive.director import MODEL
from decisive.library import fixtures as fxlib
from decisive.web.events import event

OLLAMA_TAGS = "http://localhost:11434/api/tags"


def get_rig(req):
    return req.show.load()


def save_rig(req):
    from decisive.dmx import outputs

    rig = req.body()
    problems = fxlib.validate(rig) + outputs.validate(rig)
    if not problems:
        req.show.save(rig)
    return {"saved": not problems, "problems": problems}


def directors(req=None) -> list[dict]:
    """The decision models available right now: rules, the OpenAI Decisions API, local Ollama models."""
    out = [{"value": "rules", "label": "Rules (no AI)", "available": True, "note": "instant, offline"}]
    has_key = bool(os.environ.get("OPENAI_API_KEY")) or paths.ENV_FILE.exists()
    out.append(
        {
            "value": "openai",
            "label": f"OpenAI Decisions API ({MODEL})",
            "available": has_key,
            "note": "~1.3 s per phrase, needs OPENAI_API_KEY" if has_key else "no OPENAI_API_KEY / .env found",
        }
    )
    try:
        with urllib.request.urlopen(OLLAMA_TAGS, timeout=2) as r:
            models = json.loads(r.read()).get("models", [])
        for m in models:
            if "decision" in m.get("capabilities", []):
                name = m["name"].removesuffix(":latest")
                note = "free, offline; ~7 s per phrase on a laptop" if name == "nimble" else "free, offline"
                out.append(
                    {"value": f"ollama:{name}", "label": f"Local: {name} (Ollama)", "available": True, "note": note}
                )
    except OSError:
        out.append(
            {
                "value": "ollama:nimble",
                "label": "Local: nimble (Ollama)",
                "available": False,
                "note": "Ollama is not running",
            }
        )
    return out


def set_director(req):
    director = req.body()["director"]
    if director not in {d["value"] for d in directors() if d["available"]}:
        return {"error": f"'{director}' is not available right now"}, 400
    rig = req.show.load()
    rig["director"] = director
    req.show.save(rig)
    return {"saved": True, "director": director}


def outputs_info(req):
    from decisive.dmx import outputs

    rig = req.show.load()
    return {
        "current": outputs.describe(rig),
        "output": rig.get("output"),
        "types": list(outputs.TYPES),
        "usb": outputs.usb_ports(),
    }


def list_sets(req):
    """The sets (your gear) and the rigs (venues), which ones are active, and which ones this server is fixed to."""
    from decisive.rig import store, templates

    fixed = req.fixed
    return {
        "sets": store.set_info(),
        "rigs": store.rig_info(),
        "active": {"set": store.sets.active(), "rig": store.rigs.active()},
        "templates": templates.TEMPLATES,
        "fixed": fixed.label if fixed else None,
    }


def change_sets(req):
    """{"active": name} switches; {"name", "copy"|"grid"} creates (and switches); {"delete": name} deletes;
    {"rename": old, "to": new} renames."""
    from decisive.rig import manage, store

    b = req.body()
    if req.fixed:
        return {"error": f"this server was started for {req.fixed.label}"}, 409
    if b.get("delete"):
        store.sets.delete(store.safe_name(b["delete"]))
        event(f"{req.client} set: deleted {b['delete']}")
    elif b.get("rename"):
        name = store.sets.rename(store.safe_name(b["rename"]), b["to"])
        _rename_placements(b["rename"], name)
        event(f"{req.client} set: renamed {b['rename']} → {name}")
    elif b.get("name"):
        generated = _generated(b["grid"]) if b.get("grid") else None
        name = manage.new_set(b["name"], copy_of=b.get("copy"), generated=generated)
        event(f"{req.client} set: created {name}")
        store.sets.switch(name)
        if generated:
            store.rigs.switch(name)
    if b.get("active"):
        store.sets.switch(store.safe_name(b["active"]))
        event(f"{req.client} set: active = {b['active']}")
    return list_sets(req)


def change_rigs(req):
    """{"active": name} switches; {"name", "template"|"copy", "width", "height", "depth", "screen"} creates (and
    switches); {"delete": name} deletes; {"rename": old, "to": new} renames."""
    from decisive.rig import manage, store

    b = req.body()
    if req.fixed:
        return {"error": f"this server was started for {req.fixed.label}"}, 409
    if b.get("delete"):
        store.rigs.delete(store.safe_name(b["delete"]))
        event(f"{req.client} rig: deleted {b['delete']}")
    elif b.get("rename"):
        name = store.rigs.rename(store.safe_name(b["rename"]), b["to"])
        event(f"{req.client} rig: renamed {b['rename']} → {name}")
    elif b.get("name"):
        name = manage.new_rig(b["name"], b.get("template", "booth"), float(b.get("width", 8)),
                              float(b.get("height", 4.5)), float(b.get("depth", 15)), bool(b.get("screen")),
                              copy_of=b.get("copy"))  # fmt: skip
        event(f"{req.client} rig: created {name}")
        store.rigs.switch(name)
    if b.get("active"):
        store.rigs.switch(store.safe_name(b["active"]))
        event(f"{req.client} rig: active = {b['active']}")
    return list_sets(req)


def _rename_placements(old: str, new: str):
    from decisive.rig import store

    for r in store.rigs.names():
        doc = store.rigs.load(r)
        places = doc.get("placements", {})
        if old in places:
            places[new] = places.pop(old)
            store.rigs.save(r, doc)


def _generated(g: dict) -> dict:
    from decisive.rig.grid import concert_rig, grid_rig

    size = {"width": float(g.get("width", 16)), "height": float(g.get("height", 7)), "depth": float(g.get("depth", 6))}
    if g.get("layout") == "concert":
        return concert_rig(g["model"], int(g["count"]), lasers=int(g.get("lasers", 0)), **size)
    return grid_rig(g["model"], int(g["count"]), rows=int(g.get("rows", 3)), **size)


def automount(req):
    """{"ids": [...]} (else the fixtures not mounted yet; "all": true for every one): mount the set's fixtures
    on the rig. Returns the new placements and the rig as it is now. With "rig": a combined dict (an editor's
    unsaved layout), only the placements come back and nothing is saved."""
    from decisive.rig import automount as am
    from decisive.rig import manage, store

    b = req.body()
    if isinstance(b.get("rig"), dict):
        merged = b["rig"]
        ids = b.get("ids") or [f["id"] for f in merged.get("fixtures", []) if b.get("all") or f.get(store.UNPLACED)]
        for f in merged.get("fixtures", []):
            if f["id"] in ids:
                f[store.UNPLACED] = True
        return {"placements": am.automount(merged, ids)}
    show = req.show
    places = manage.mount(show, b.get("ids"), everything=bool(b.get("all")))
    event(f"{req.client} automount: {len(places)} fixtures of {show.label}")
    return {"placements": places, "rig": show.load()}


def autopatch(req):
    """Non-overlapping addresses and a stage layout for the posted fixtures."""
    from decisive.dmx.discover import assign_addresses, layout, new_ids

    fixtures = req.body()["fixtures"]
    for f in fixtures:
        f.pop("address", None)
        f.pop("x", None)
        f.setdefault("universe", 1)
        f.setdefault("mode", fxlib.default_mode(fxlib.get(f["fixture"])))
    new_ids(fixtures)
    assign_addresses(fixtures)
    layout(fixtures)
    return {"fixtures": fixtures}


def discover(req):
    """ArtPoll on the network: the nodes that answer."""
    from decisive.dmx.discover import Client

    c = Client(None)
    try:
        return {
            "nodes": [
                {"ip": n.ip, "name": n.short_name, "long_name": n.long_name, "outputs": n.outputs, "port": addr[1]}
                for n, addr in c.poll()
            ]
        }
    finally:
        c.sock.close()


def identify(req):
    """{"fixture": id, "rig": {...}}: light that fixture white for 2 s."""
    body = req.body()
    threading.Thread(target=_identify, args=(body["rig"], body["fixture"]), daemon=True).start()
    return {"ok": True}


def _identify(rig: dict, fixture_id: str, seconds: float = 2.0):
    from decisive.dmx.artnet import hold
    from decisive.dmx.outputs import open_output
    from decisive.engine.state import State
    from decisive.rig.loader import load_rig_dict

    rig = load_rig_dict(rig)
    sender = open_output(rig, owner=True)
    hold(seconds + 0.5)
    states = {e["id"]: State(pan=0.5, tilt=0.5) for e in rig["elements"]}
    for e in rig["elements"]:
        if e["fixture"] == fixture_id:
            states[e["id"]] = State(dimmer=0.6, r=1, g=1, b=1, pan=0.5, tilt=0.5)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        unis: dict[int, bytearray] = {}
        for f in rig["fixtures"]:
            fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, states)
        sender.send(unis)
        time.sleep(0.025)
    sender.blackout(sorted({f["universe"] for f in rig["fixtures"]}))


def page_log(req):
    """Events from the phone page, into the same log."""
    event(f"{req.client} page: {str(req.body().get('event', ''))[:300]}")
    return {"ok": True}


GET = {
    "/api/rig": get_rig,
    "/api/directors": directors,
    "/api/outputs": outputs_info,
    "/api/sets": list_sets,
    "/api/rigs": list_sets,
}
POST = {
    "/api/rig": save_rig,
    "/api/director": set_director,
    "/api/sets": change_sets,
    "/api/rigs": change_rigs,
    "/api/automount": automount,
    "/api/autopatch": autopatch,
    "/api/discover": discover,
    "/api/identify": identify,
    "/api/log": page_log,
}
