"""Loading a show's rig: a set placed on a rig (or an old combined file), defaults filled in, and its fixtures
expanded into elements (pars, heads, cells…)."""

from __future__ import annotations

import json
from pathlib import Path

from decisive.library import fixtures as fxlib
from decisive.rig import geometry


def load_rig(source) -> dict:
    """`source`: a store.Selection (a set on a rig), or the path of a combined file."""
    if hasattr(source, "load"):
        return load_rig_dict(source.load())
    return load_rig_dict(json.loads(Path(source).read_text()))


def load_rig_dict(rig: dict) -> dict:
    rig = json.loads(json.dumps(rig))  # private copy
    rig.setdefault("safety", {"max_flash_hz": 3.0, "master": 1.0})
    rig.setdefault("artnet", {"ip": "127.0.0.1", "port": 6454, "fps": 40})
    for f in rig["fixtures"]:
        f.setdefault("mode", fxlib.default_mode(fxlib.get(f["fixture"])))
    for f in rig["fixtures"]:
        if fxlib.get(f["fixture"]).get("warning"):
            print(f"⚠ {f['id']}: {fxlib.get(f['fixture'])['warning']}")
    for problem in fxlib.validate(rig):
        print(f"⚠ patch problem: {problem}")
    w = geometry.stage(rig)["width_m"]
    rig["elements"] = [e for f in rig["fixtures"] for e in fxlib.expand(f, w)]
    return rig
