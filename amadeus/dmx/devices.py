"""Your DMX devices, apart from your sets: the controllers the light data goes out through.

A DMX device (an Art-Net node, an sACN node, a USB interface) is set up once, in `config/devices.json`: its
name, how to reach it, and how it counts its universes. A set then only says, per universe of its patch, which
device (and which of its outputs) plays it: replace a node, or play the same set at a venue with other
controllers, and only the mapping changes; the set and its patch stay as they are.

    config/devices.json
    {"devices": [
      {"id": "pocket", "name": "NET-2/5 Pocket", "type": "artnet", "ip": "2.0.0.10", "first_universe": 0, "outputs": 2},
      {"id": "sacn-front", "name": "Front of house", "type": "sacn", "ip": null, "priority": 100, "first_universe": 1},
      {"id": "usb", "name": "ENTTEC Pro", "type": "enttec_pro", "port": "auto", "serial": "EN123456"}
    ]}

    a set: "dmx": {"1": {"device": "pocket", "output": 1}, "2": {"device": "pocket", "output": 2},
                   "3": {"device": "usb"}}

An Art-Net node's UDP port is `udp_port` (default 6454); a USB interface's `port` is its device path or
"auto". `first_universe`: the protocol universe of the device's first output (most Art-Net nodes count from 0, sACN from
1); output n plays universe first_universe + n - 1. A USB interface has one output. A set without "dmx" uses its
own "output"/"artnet" blocks, as sets always did.
"""

from __future__ import annotations

import json
import re

from amadeus import paths

TYPES = ("artnet", "sacn", "enttec_pro")
FIRST_UNIVERSE = {"artnet": 0, "sacn": 1}


def path():
    return paths.CONFIG / "devices.json"


def load() -> list[dict]:
    p = path()
    if not p.exists():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("devices", []))


def save(devices: list[dict]) -> list[str]:
    """Validate and save; returns the problems (nothing saved if any)."""
    problems = validate(devices)
    if not problems:
        path().parent.mkdir(parents=True, exist_ok=True)
        path().write_text(json.dumps({"devices": devices}, indent=2) + "\n", encoding="utf-8")
    return problems


def validate(devices: list[dict]) -> list[str]:
    problems, ids = [], set()
    for d in devices:
        did = str(d.get("id", ""))
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", did):
            problems.append(f"device '{d.get('name', did)}': its id may only use letters, digits, - _ .")
        elif did in ids:
            problems.append(f"two devices with the id '{did}'")
        ids.add(did)
        if d.get("type") not in TYPES:
            problems.append(f"device '{did}': type must be one of {', '.join(TYPES)}")
        elif d["type"] == "artnet" and not d.get("ip"):
            problems.append(f"device '{did}': an Art-Net node needs its IP address")
        elif d["type"] == "sacn" and not 0 <= int(d.get("priority", 100)) <= 200:
            problems.append(f"device '{did}': sACN priority must be 0–200")
    return problems


def check_mapping(rig: dict, devices: list[dict] | None = None) -> list[str]:
    """Problems with a set's "dmx" mapping: unknown devices, two universes on one output."""
    known = {d["id"]: d for d in (load() if devices is None else devices)}
    problems, used = [], {}
    for uni, m in (rig.get("dmx") or {}).items():
        dev = known.get((m or {}).get("device"))
        if dev is None:
            problems.append(f"universe {uni}: unknown DMX device '{(m or {}).get('device')}'")
            continue
        out = 1 if dev["type"] == "enttec_pro" else int(m.get("output", 1))
        if (dev["id"], out) in used:
            problems.append(f"universes {used[(dev['id'], out)]} and {uni} both go to {dev['name']} output {out}")
        used[(dev["id"], out)] = uni
    return problems


def resolve(rig: dict, devices: list[dict] | None = None) -> list[dict]:
    """The set's "dmx" mapping as output specs (amadeus/dmx/outputs.py), one per device it uses."""
    known = {d["id"]: d for d in (load() if devices is None else devices)}
    per: dict[str, dict] = {}
    for uni_s, m in sorted((rig.get("dmx") or {}).items(), key=lambda kv: int(kv[0])):
        dev = known.get((m or {}).get("device"))
        if dev is None:
            print(f"⚠ universe {uni_s}: unknown DMX device '{(m or {}).get('device')}' (not sent)")
            continue
        uni = int(uni_s)
        spec = per.get(dev["id"])
        if spec is None:
            spec = {"type": dev["type"], "universes": [], "name": dev.get("name", dev["id"])}
            if dev["type"] == "artnet":
                spec.update(ip=dev["ip"], port=int(dev.get("udp_port", 6454)), universe_map={})
            elif dev["type"] == "sacn":
                spec.update(ip=dev.get("ip"), priority=int(dev.get("priority", 100)), universe_map={})
            else:
                spec.update(port=dev.get("port", "auto"), universe=uni)
            per[dev["id"]] = spec
        spec["universes"].append(uni)
        if dev["type"] in FIRST_UNIVERSE:
            first = int(dev.get("first_universe", FIRST_UNIVERSE[dev["type"]]))
            spec["universe_map"][uni] = first + int(m.get("output", 1)) - 1
    return list(per.values())


def describe(rig: dict, devices: list[dict] | None = None) -> str:
    specs = resolve(rig, devices)
    if not specs:
        return "visualiser only (no universe mapped to a DMX device)"
    return " + ".join(f"{s['name']} (universe {', '.join(map(str, s['universes']))})" for s in specs)
