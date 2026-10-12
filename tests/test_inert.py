"""Lasers and smoke machines from the QLC+ / Open Fixture Library are inert: in a rig, every frame, every one of
their channels stays at its off value, and the show runs around them."""

import json
import shutil
import tempfile
from pathlib import Path

import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine, motion
from amadeus.library import fixtures as fxlib
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig_dict
from tests.synthetic import synthetic_analysis

ROOT = Path(__file__).resolve().parent.parent

LASER = {  # as the converter makes it: kind laser, no hand-made "laser" mapping, off values as defaults
    "manufacturer": "Test",
    "model": "Converted Laser",
    "kind": "laser",
    "physical": {"beam_deg": 2},
    "modes": {
        "4ch": [
            {"attr": "mode", "default": 40},
            {"attr": "dimmer", "default": 0},
            {"attr": "pan", "default": 0},
            {"attr": "red", "default": 0},
        ]
    },
    "inert": "a laser whose channels aren't mapped by hand yet: it stays dark",
}
SMOKE = {
    "manufacturer": "Test",
    "model": "Fogger",
    "kind": "smoke",
    "physical": {},
    "modes": {"2ch": [{"attr": "dimmer", "default": 0}, {"attr": "fan", "default": 0}]},
}


@pytest.fixture
def library(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        shutil.copytree(ROOT / "fixtures", lib, dirs_exist_ok=True)
        (lib / "test").mkdir()
        (lib / "test" / "laser.json").write_text(json.dumps(LASER))
        (lib / "test" / "fogger.json").write_text(json.dumps(SMOKE))
        monkeypatch.setattr(fxlib, "LIB_DIR", lib)
        fxlib.library.cache_clear()
        yield lib
    fxlib.library.cache_clear()


def test_inert_fixtures_never_leave_their_off_values(library, monkeypatch, tmp_path):
    rig = json.loads((ROOT / "tests" / "sets" / "small.json").read_text())
    used = max(f["address"] + fxlib.footprint(f) for f in rig["fixtures"] if f["universe"] == 1)
    rig["fixtures"] += [
        {"id": "laser1", "fixture": "test/laser", "mode": "4ch", "universe": 1, "address": used, "x": 0.5},
        {"id": "fog1", "fixture": "test/fogger", "mode": "2ch", "universe": 1, "address": used + 4, "x": 0.1},
    ]
    rig = load_rig_dict(rig)
    kinds = {e["id"]: e["kind"] for e in rig["elements"]}
    assert kinds["laser1"] == kinds["fog1"] == "inert"
    assert laser_list(rig) == []  # the director isn't told about it either

    monkeypatch.setattr(motion, "TRAJ_CACHE", tmp_path)
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), False), verbose=False)
    eng = Engine(a, plan, rig, real_output=True)
    assert "laser1" not in [e["id"] for e in eng.lasers]
    off = bytes([40, 0, 0, 0, 0, 0])
    lit_elsewhere = 0
    for k in range(0, int(a.duration * 10)):
        _, states = eng.render(k / 10)
        buf = eng.dmx(states)[1]
        assert bytes(buf[used - 1 : used + 5]) == off, f"t={k / 10}"
        lit_elsewhere += any(buf[: used - 1])
    assert lit_elsewhere  # the rest of the rig did play


def test_converter_rules_for_off_values():
    assert fxlib.off_value("Mode", [(0, "Laser off"), (50, "Sound active")]) == (0, True)
    assert fxlib.off_value("Mode", [(0, "Sound active"), (100, "Blackout")]) == (100, True)
    assert fxlib.off_value("Mode Select", [(0, "Sound Active Mode"), (128, "Auto")]) == (0, False)
    assert fxlib.off_value("Zoom", [(0, "Auto zoom")]) == (0, True)  # not a mode channel: 0 is harmless
    assert fxlib.off_value("Laser", [(0, "Laser On/Off")]) == (0, True)  # "on/off" isn't an off range
    assert fxlib.inert({"kind": "laser", "laser": {"on": 200}}) == ""  # mapped by hand: driven
    assert fxlib.inert({"kind": "smoke"})
