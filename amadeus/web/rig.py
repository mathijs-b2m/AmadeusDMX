"""The rig: the set file itself, its decision model, DMX outputs, sets, patching and finding nodes."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request

from amadeus import paths
from amadeus.director import MODEL
from amadeus.library import fixtures as fxlib
from amadeus.web.events import event


def get_rig(req):
    return req.show.load()


def save_rig(req):
    from amadeus.dmx import outputs
    from amadeus.rig import store

    rig = req.body()
    if req.query.get("setonly") and req.query.get("set"):  # the set alone (its fixtures and patch): no rig touched
        problems = fxlib.validate(rig) + outputs.validate(rig)
        if not problems:
            name = store.safe_name(req.query["set"])
            set_doc, _ = store.split(rig, name, {})
            store.sets.save(name, set_doc)
        return {"saved": not problems, "problems": problems}
    if req.query.get("structure") and req.query.get("rig"):  # the rig alone (no set placed on it)
        name = store.safe_name(req.query["rig"])
        doc = store.rigs.load(name)
        for k in store.RIG_KEYS:
            if k in rig:
                doc[k] = rig[k]
            else:
                doc.pop(k, None)
        store.rigs.save(name, doc)
        return {"saved": True, "problems": []}
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
    host = paths.ollama_host()
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as r:
            models = json.loads(r.read()).get("models", [])
    except (OSError, ValueError):
        where = "" if host == "http://localhost:11434" else f" at {host}"
        note = f"Ollama isn't running{where}: start it, then refresh"
        return out + [{"value": "ollama:nimble", "label": "Local: nimble (Ollama)", "available": False, "note": note}]
    local = []
    for m in models:
        name = m["name"].removesuffix(":latest")
        size = (m.get("details") or {}).get("parameter_size", "")
        if "decision" in m.get("capabilities", []):
            note = "free, offline; ~7 s per phrase on a laptop" if name == "nimble" else "free, offline"
            local.append({"value": f"ollama:{name}", "label": f"Local: {name} (Ollama)", "available": True,
                          "note": note + (f"; {size}" if size else "")})  # fmt: skip
        else:  # installed, but can't answer the director's questions with probabilities
            local.append({"value": f"ollama:{name}", "label": f"Local: {name} (Ollama)", "available": False,
                          "note": "no decision support: the director needs a decision model, e.g. nimble"})  # fmt: skip
    if not any(d["available"] for d in local):
        local.append({"value": "ollama:nimble", "label": "Local: nimble (Ollama)", "available": False,
                      "note": "not installed: ollama pull nimble"})  # fmt: skip
    return out + sorted(local, key=lambda d: not d["available"])


def set_director(req):
    director = req.body()["director"]
    if director not in {d["value"] for d in directors() if d["available"]}:
        return {"error": f"'{director}' is not available right now"}, 400
    rig = req.show.load()
    rig["director"] = director
    req.show.save(rig)
    return {"saved": True, "director": director}


def outputs_info(req):
    from amadeus.dmx import outputs

    rig = req.show.load()
    return {
        "current": outputs.describe(rig),
        "output": rig.get("output"),
        "types": list(outputs.TYPES),
        "usb": outputs.usb_ports(),
    }


def get_devices(req):
    """Your DMX devices (config/devices.json), and the USB DMX interfaces plugged in now."""
    from amadeus.dmx import devices, outputs

    return {"devices": devices.load(), "usb": outputs.usb_ports()}


def save_devices(req):
    """{"devices": [...]}: save your DMX devices (nothing saved if there are problems)."""
    from amadeus.dmx import devices

    problems = devices.save(list(req.body().get("devices", [])))
    return {"ok": not problems, "problems": problems}


def list_sets(req):
    """The sets (your gear) and the rigs (venues), which ones are active, and which ones this server is fixed to."""
    from amadeus.rig import store, templates

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
    from amadeus.rig import manage, store

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


def rename_fixture(req):
    """{"set", "from", "to"}: rename a fixture of a set, and where it hangs on every rig."""
    from amadeus.rig import store

    b = req.body()
    set_name, old, new = store.safe_name(b["set"]), str(b["from"]), str(b["to"]).strip()
    doc = store.sets.load(set_name)
    ids = {f["id"] for f in doc.get("fixtures", [])}
    if not new or not all(c.isalnum() or c in "-_." for c in new):
        return {"error": "A fixture name may only use letters, digits, - _ ."}, 400
    if new in ids:
        return {"error": f"The set already has a fixture called {new}"}, 400
    for f in doc.get("fixtures", []):
        if f["id"] == old:
            f["id"] = new
    store.sets.save(set_name, doc)
    for r in store.rigs.names():
        rig = store.rigs.load(r)
        places = rig.get("placements", {}).get(set_name, {})
        if old in places:
            places[new] = places.pop(old)
            store.rigs.save(r, rig)
    event(f"{req.client} set {set_name}: fixture {old} → {new}")
    return {"ok": True}


def change_rigs(req):
    """{"active": name} switches; {"name", "template"|"copy", "width", "height", "depth", "screen"} creates (and
    switches); {"delete": name} deletes; {"rename": old, "to": new} renames. {"rig", "place": set, "auto": bool}
    puts a set on a rig (a combination; "auto": auto-mount it), {"rig", "unplace": set} takes it off."""
    from amadeus.rig import manage, store

    b = req.body()
    if req.fixed:
        return {"error": f"this server was started for {req.fixed.label}"}, 409
    if b.get("place") and b.get("rig"):
        rig, set_name = store.safe_name(b["rig"]), store.safe_name(b["place"])
        doc = store.rigs.load(rig)
        doc.setdefault("placements", {}).setdefault(set_name, {})
        store.rigs.save(rig, doc)
        if b.get("auto"):
            manage.mount(store.Selection(rig=rig, set=set_name))
        event(f"{req.client} rig: {set_name} placed on {rig}")
        return list_sets(req)
    if b.get("unplace") and b.get("rig"):
        rig = store.safe_name(b["rig"])
        doc = store.rigs.load(rig)
        doc.get("placements", {}).pop(store.safe_name(b["unplace"]), None)
        store.rigs.save(rig, doc)
        event(f"{req.client} rig: {b['unplace']} taken off {rig}")
        return list_sets(req)
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
    from amadeus.rig import store

    for r in store.rigs.names():
        doc = store.rigs.load(r)
        places = doc.get("placements", {})
        if old in places:
            places[new] = places.pop(old)
            store.rigs.save(r, doc)


def _generated(g: dict) -> dict:
    from amadeus.rig.grid import concert_rig, grid_rig

    size = {"width": float(g.get("width", 16)), "height": float(g.get("height", 7)), "depth": float(g.get("depth", 6))}
    if g.get("layout") == "concert":
        return concert_rig(g["model"], int(g["count"]), lasers=int(g.get("lasers", 0)), **size)
    return grid_rig(g["model"], int(g["count"]), rows=int(g.get("rows", 3)), **size)


def automount(req):
    """{"ids": [...]} (else the fixtures not mounted yet; "all": true for every one): mount the set's fixtures
    on the rig. Returns the new placements and the rig as it is now. With "rig": a combined dict (an editor's
    unsaved layout), only the placements come back and nothing is saved."""
    from amadeus.rig import automount as am
    from amadeus.rig import manage, store

    b = req.body()
    if isinstance(b.get("rig"), dict):
        merged = b["rig"]
        ids = b.get("ids") or [f["id"] for f in merged.get("fixtures", []) if b.get("all") or f.get(store.UNPLACED)]
        for f in merged.get("fixtures", []):
            if f["id"] in ids:
                f[store.UNPLACED] = True
        had = bool(merged.get("trusses"))
        places = am.automount(merged, ids)
        return {"placements": places, "trusses": None if had else merged.get("trusses", [])}
    show = req.show
    places = manage.mount(show, b.get("ids"), everything=bool(b.get("all")))
    event(f"{req.client} automount: {len(places)} fixtures of {show.label}")
    return {"placements": places, "rig": show.load()}


def autopatch(req):
    """Non-overlapping addresses and a stage layout for the posted fixtures."""
    from amadeus.dmx.discover import assign_addresses, layout, new_ids

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
    from amadeus.dmx.discover import Client

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
    from amadeus.dmx.artnet import hold
    from amadeus.dmx.outputs import open_output
    from amadeus.engine.state import State
    from amadeus.rig.loader import load_rig_dict

    rig = load_rig_dict(rig)
    sender = open_output(rig, owner=True)
    hold(seconds + 0.5)
    states = {e["id"]: State(pan=0.0, tilt=0.0) for e in rig["elements"]}  # the others stay where a blackout left them
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


# The light test: fixtures switched on one by one from the Set page stay lit (and the show paused) until
# switched off, or for TEST_SECONDS at most.
TEST_SECONDS = 60.0
_test_lock = threading.Lock()
_test: dict = {"rig": None, "lit": {}, "raw": {}, "thread": None}


def test_light(req):
    """{"fixture": id, "rig": {...}, "on": bool}: light that fixture (or stop), to see it is patched and
    connected. Says where its DMX goes. With "raw": [v, …] its channels get those values as they are (the DMX
    mapper: what does this channel do?)."""
    from amadeus.dmx import outputs
    from amadeus.rig.loader import load_rig_dict

    body = req.body()
    rig, fixture_id, on = load_rig_dict(body["rig"]), body["fixture"], bool(body.get("on", True))
    fx = next((f for f in rig["fixtures"] if f["id"] == fixture_id), None)
    if fx is None:
        return {"error": f"The set has no fixture called {fixture_id}"}, 400
    defn, raw = fxlib.get(fx["fixture"]), body.get("raw")
    if raw is not None and not (isinstance(raw, list) and all(isinstance(v, int) and 0 <= v <= 255 for v in raw)):
        return {"error": "raw: a list of DMX values (0–255)"}, 400
    refusal = fxlib.test_refusal(defn) or (raw is not None and defn["kind"] == "laser" and "Lasers aren't driven raw.")
    if on and refusal:
        return {"error": refusal}, 400
    with _test_lock:
        ids = {f["id"] for f in rig["fixtures"]}
        _test["lit"] = {fid: until for fid, until in _test["lit"].items() if fid in ids}  # another set's: dark
        _test["rig"] = rig
        _test["raw"] = {fid: v for fid, v in _test["raw"].items() if fid in _test["lit"]}
        if on:
            _test["lit"][fixture_id] = time.monotonic() + TEST_SECONDS
            if raw is not None:
                _test["raw"][fixture_id] = raw[: fxlib.footprint(fx)]
            else:
                _test["raw"].pop(fixture_id, None)
        else:
            _test["lit"].pop(fixture_id, None)
            _test["raw"].pop(fixture_id, None)
        if _test["lit"] and not (_test["thread"] and _test["thread"].is_alive()):
            _test["thread"] = threading.Thread(target=_test_loop, daemon=True)
            _test["thread"].start()
    return {
        "on": on,
        "seconds": TEST_SECONDS,
        "output": outputs.describe(rig),
        "universe": fx["universe"],
        "wire_universe": outputs.wire_universe(rig, fx["universe"]),
        "channels": [fx["address"], fx["address"] + fxlib.footprint(fx) - 1],
    }


def _test_loop():
    from amadeus.dmx.artnet import hold, release
    from amadeus.dmx.outputs import open_output
    from amadeus.engine.state import State

    rig, sender = None, None
    try:
        while True:
            with _test_lock:
                now = time.monotonic()
                for fid, until in list(_test["lit"].items()):
                    if until < now:
                        del _test["lit"][fid]
                lit, raw = set(_test["lit"]), dict(_test["raw"])
                if _test["rig"] is not rig:
                    if sender:
                        sender.blackout(sorted({f["universe"] for f in rig["fixtures"]}))
                        sender.close()
                    rig, sender = _test["rig"], open_output(_test["rig"], owner=True)
                if not lit:
                    _test["thread"] = None
                    break
            hold(1.0)  # a running show pauses while fixtures are tested
            unis: dict[int, bytearray] = {}
            for f in rig["fixtures"]:
                buf = unis.setdefault(f["universe"], bytearray(512))
                if f["id"] in raw:  # as they are: the mapper tries what a channel does
                    for off, v in enumerate(raw[f["id"]]):
                        if 0 <= f["address"] - 1 + off < 512:
                            buf[f["address"] - 1 + off] = v
                elif f["id"] in lit:
                    fxlib.test_light(buf, f)
                else:  # dark, and heads where a blackout leaves them (DMX 0): they don't move on every test
                    fxlib.patch(buf, f, {e["id"]: State(pan=0.0, tilt=0.0) for e in fxlib.expand(f)})
            sender.send(unis)
            time.sleep(0.025)
    finally:
        if sender:
            sender.blackout(sorted({f["universe"] for f in rig["fixtures"]}))
            sender.close()
        release()


def get_limiter(req=None):
    """The brightness limiter (dmx/limiter.py): {"level": 0.05..1}, 1 is off."""
    from amadeus.dmx import limiter

    return {"level": limiter.read()}


def set_limiter(req):
    """{"level": 0.05..1}: the ceiling every light is limited to, in every running engine (1: off)."""
    from amadeus.dmx import limiter

    level = limiter.save(req.body().get("level", 1.0))
    event(f"{req.client} brightness limiter: " + ("off" if level >= 1.0 else f"{round(level * 100)}%"))
    return {"level": level}


def page_log(req):
    """Events from the phone page, into the same log."""
    event(f"{req.client} page: {str(req.body().get('event', ''))[:300]}")
    return {"ok": True}


GET = {
    "/api/rig": get_rig,
    "/api/directors": directors,
    "/api/outputs": outputs_info,
    "/api/devices": get_devices,
    "/api/sets": list_sets,
    "/api/rigs": list_sets,
    "/api/limiter": get_limiter,
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
    "/api/test-light": test_light,
    "/api/log": page_log,
    "/api/devices": save_devices,
    "/api/fixture/rename": rename_fixture,
    "/api/limiter": set_limiter,
}
