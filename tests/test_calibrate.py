"""The calibration on the Set page: a bar's cells lit red, green, blue, white along it as it is placed, so a bar that
runs the other way on the stage (reversed) shows at once; a reversed bar's red moves to its other end."""

import json
from pathlib import Path

from amadeus.library import fixtures as fxlib
from amadeus.rig import hangsheet
from amadeus.rig.loader import load_rig_dict

ROOT = Path(__file__).resolve().parent.parent


def _rig(**placing) -> tuple[dict, dict]:
    rig = json.loads((ROOT / "tests" / "sets" / "small.json").read_text(encoding="utf-8"))
    rig = load_rig_dict({**rig, "fixtures": [f | placing if f["id"] == "compar1" else f for f in rig["fixtures"]]})
    return rig, next(f for f in rig["fixtures"] if f["id"] == "compar1")


def _red(rig: dict, fx: dict) -> float:
    """Where the red cell sits across the stage (m)."""
    from amadeus.rig import geometry

    colors, _ = hangsheet.cell_order(rig, fx)
    red = next(e for e in rig["elements"] if colors.get(e["id"]) == (1.0, 0.0, 0.0))
    return geometry.position(rig, red, fx)[0]


def test_red_starts_at_stage_left():
    rig, fx = _rig()
    colors, words = hangsheet.cell_order(rig, fx)
    cells = [e for e in rig["elements"] if e["fixture"] == "compar1"]
    assert len(colors) == len(cells) > 1
    assert abs(_red(rig, fx) - min(e["x"] for e in cells) * rig["stage"]["width_m"]) < 0.01
    assert words.startswith("Red at stage left (your right, facing the stage), then green")


def test_a_reversed_bar_has_red_at_its_other_end():
    rig, fx = _rig()
    flipped, fxr = _rig(reverse=True)
    assert hangsheet.cell_order(rig, fx)[0] != hangsheet.cell_order(flipped, fxr)[0]  # other cells are red
    assert abs(_red(rig, fx) - _red(flipped, fxr)) < 1e-6  # still at stage left: the words stay true


def test_turned_round_it_still_starts_at_stage_left():
    rig, fx = _rig(rot_deg=180)
    assert abs(_red(rig, fx) - _red(*_rig())) < 0.01


def test_a_bar_up_and_down_the_stage_starts_at_the_back():
    rig, fx = _rig(rot_deg=90)
    assert "the back of the stage" in hangsheet.cell_order(rig, fx)[1]


def test_one_cell_has_no_order():
    rig = load_rig_dict(json.loads((ROOT / "tests" / "sets" / "small.json").read_text(encoding="utf-8")))
    assert hangsheet.cell_order(rig, rig["fixtures"][0]) == ({}, "")


def test_the_light_test_lights_the_cells_in_their_colours():
    rig, fx = _rig()
    colors, _ = hangsheet.cell_order(rig, fx)
    coloured, white = bytearray(512), bytearray(512)
    fxlib.test_light(coloured, fx, colors=colors)
    fxlib.test_light(white, fx)
    assert coloured != white
    assert any(coloured) and fxlib.patched(fx)
