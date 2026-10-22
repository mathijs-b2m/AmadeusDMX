"""Loading a show's rig: a set placed on a rig (or an old combined file), defaults filled in, and its fixtures
expanded into elements (pars, heads, cells…)."""

from __future__ import annotations

import json
from pathlib import Path

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry


def load_rig(source) -> dict:
    """`source`: a store.Selection (a set on a rig), or the path of a combined file."""
    if hasattr(source, "load"):
        return load_rig_dict(source.load())
    return load_rig_dict(json.loads(Path(source).read_text(encoding="utf-8")))


def load_rig_dict(rig: dict) -> dict:
    rig = json.loads(json.dumps(rig))  # private copy
    rig.setdefault("safety", {"max_flash_hz": 3.0, "master": 1.0})
    rig.setdefault("artnet", {"ip": "127.0.0.1", "port": 6454, "fps": 40})
    for f in rig["fixtures"]:
        f.setdefault("mode", fxlib.default_mode(fxlib.get(f["fixture"])))
        f.setdefault("universe", 1)  # one waiting for its address may not say (Import from Documents)
    for f in rig["fixtures"]:
        if fxlib.get(f["fixture"]).get("warning"):
            print(f"⚠ {f['id']}: {fxlib.get(f['fixture'])['warning']}")
    for problem in fxlib.validate(rig) + fxlib.overlaps(rig):
        print(f"⚠ patch problem: {problem}")
    if unpatched := [f["id"] for f in rig["fixtures"] if not fxlib.patched(f)]:
        print(f"⚠ no start address yet (visualiser only): {', '.join(unpatched)}")
    w = geometry.stage(rig)["width_m"]
    rig["elements"] = [e for f in rig["fixtures"] for e in fxlib.expand(f, w)]
    return rig
