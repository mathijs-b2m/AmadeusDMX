"""Loading a rig (a set file): defaults filled in, its fixtures expanded into elements (pars, heads, cells…)."""

from __future__ import annotations

import json
from pathlib import Path

from decisive.library import fixtures as fxlib
from decisive.rig import geometry


def load_rig(path: str | Path) -> dict:
    return load_rig_dict(json.loads(Path(path).read_text()))


def load_rig_dict(rig: dict) -> dict:
    rig = json.loads(json.dumps(rig))  # private copy
    rig.setdefault("safety", {"max_flash_hz": 3.0, "master": 1.0})
    rig.setdefault("artnet", {"ip": "127.0.0.1", "port": 6454, "fps": 40})
    for f in rig["fixtures"]:
        f.setdefault("mode", fxlib.default_mode(fxlib.get(f["fixture"])))
    for problem in fxlib.validate(rig):
        print(f"⚠ patch problem: {problem}")
    w = geometry.stage(rig)["width_m"]
    rig["elements"] = [e for f in rig["fixtures"] for e in fxlib.expand(f, w)]
    return rig
