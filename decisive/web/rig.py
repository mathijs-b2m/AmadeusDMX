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
    return json.loads(req.rig_path.read_text())


def save_rig(req):
    from decisive.dmx import outputs

    rig = req.body()
    problems = fxlib.validate(rig) + outputs.validate(rig)
    if not problems:
        req.rig_path.write_text(json.dumps(rig, indent=2))
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
    rig = json.loads(req.rig_path.read_text())
    rig["director"] = director
    req.rig_path.write_text(json.dumps(rig, indent=2))
    return {"saved": True, "director": director}


def outputs_info(req):
    from decisive.dmx import outputs

    rig = json.loads(req.rig_path.read_text())
    return {
        "current": outputs.describe(rig),
        "output": rig.get("output"),
        "types": list(outputs.TYPES),
        "usb": outputs.usb_ports(),
    }


def list_sets(req):
    from decisive.rig import sets

    return {"sets": sets.info(), "fixed": str(req.fixed_rig) if req.fixed_rig else None}


def change_sets(req):
    """{"active": name} switches; {"name", "copy"|"grid"} creates (and switches); {"delete": name} deletes."""
    from decisive.rig import sets

    b = req.body()
    if req.fixed_rig:
        return {"error": f"this server was started with --rig {req.fixed_rig}"}, 409
    if b.get("delete"):
        name = sets.safe_name(b["delete"])
        if len(sets.names()) <= 1:
            return {"error": "can't delete the only set"}, 409
        sets.path(name).unlink(missing_ok=True)
        event(f"{req.client} set: deleted {name}")
        b["active"] = sets.active_name() if sets.active_name() != name else next(n for n in sets.names() if n != name)
    elif b.get("name"):
        name = sets.safe_name(b["name"])
        if name in sets.names():
            return {"error": f"a set '{name}' already exists"}, 409
        rig = _new_set(b)
        sets.save(name, rig)
        event(f"{req.client} set: created {name} ({len(rig['fixtures'])} fixtures)")
        b["active"] = name
    sets.switch(sets.safe_name(b["active"]))
    event(f"{req.client} set: active = {b['active']}")
    return {"sets": sets.info()}


def _new_set(b: dict) -> dict:
    from decisive.rig import sets

    if b.get("copy"):
        rig = json.loads(sets.path(sets.safe_name(b["copy"])).read_text())
        rig["description"] = f"copy of {b['copy']}"
        return rig
    if b.get("grid"):
        from decisive.rig.grid import concert_rig, grid_rig

        g = b["grid"]
        size = {
            "width": float(g.get("width", 16)),
            "height": float(g.get("height", 7)),
            "depth": float(g.get("depth", 6)),
        }
        if g.get("layout") == "concert":
            return concert_rig(g["model"], int(g["count"]), lasers=int(g.get("lasers", 0)), **size)
        return grid_rig(g["model"], int(g["count"]), rows=int(g.get("rows", 3)), **size)
    # empty: keep the node and safety settings of the current set
    current = json.loads(sets.path().read_text()) if sets.path().exists() else {}
    return {
        "description": "",
        "artnet": current.get("artnet", {"ip": "127.0.0.1", "port": 6454, "fps": 40}),
        "safety": current.get("safety", {"max_flash_hz": 3, "master": 1.0}),
        "fixtures": [],
        "stage": current.get("stage", {}),
        "director": current.get("director", "rules"),
    }


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


GET = {"/api/rig": get_rig, "/api/directors": directors, "/api/outputs": outputs_info, "/api/sets": list_sets}
POST = {
    "/api/rig": save_rig,
    "/api/director": set_director,
    "/api/sets": change_sets,
    "/api/autopatch": autopatch,
    "/api/discover": discover,
    "/api/identify": identify,
    "/api/log": page_log,
}
