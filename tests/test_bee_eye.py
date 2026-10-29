"""Bee eyes: a head whose front is a honeycomb of lenses, each its own pixel; the show lights them in patterns (its
beam effect) and turns the front (the barrel roll), and the visualisers know how many lenses it has."""

from types import SimpleNamespace

import pytest

from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.library import gobos, qlc
from amadeus.show.feed import element_info

KEY = "test/bee-eye"
LENSES = 19


def _bee(model: str = "Big Bee Eyes LED Wash 19x40W RGBW") -> dict:
    head = [{"attr": a} for a in ("pan", "pan_fine", "tilt", "tilt_fine")]
    head += [{"attr": "zoom", "tight": 0, "wide": 255}, {"attr": "lens_roll", "default": 0, "cw": [156, 205],
             "ccw": [206, 255]}, {"attr": "dimmer"}]  # fmt: skip
    pixels = [{"attr": c} for _ in range(LENSES) for c in ("red", "green", "blue", "white")]
    return {"key": KEY, "kind": "moving_head", "manufacturer": "Test", "model": model, "modes": {"99ch": head + pixels},
            "physical": {"beam_deg": 4.0, "beam_deg_max": 45.0, "size_mm": [434, 298, 530]}}  # fmt: skip


@pytest.fixture
def bee(monkeypatch):
    real = fxlib.get
    monkeypatch.setattr(fxlib, "get", lambda key: _bee() if key == KEY else real(key))
    return {"id": "bee", "fixture": KEY, "mode": "99ch", "universe": 1, "address": 1, "x": 0.5}


def _dmx(fx: dict, s: State) -> bytearray:
    buf = bytearray(512)
    fxlib.patch(buf, fx, {fx["id"]: s}, limit=1.0)
    return buf


def test_bee_eyes_are_known_by_name_or_lenses():
    assert fxlib.bee_eye(_bee()) == 19
    assert fxlib.bee_eye(_bee("JMS WEBB LED Wash BigBeeEye 19X40W")) == 19
    assert fxlib.bee_eye(_bee("A.leda B-EYE K20")) == 37
    assert fxlib.bee_eye(_bee("A.leda B-EYE K10")) == 19  # its 19 pixels
    assert fxlib.bee_eye(_bee("MAC Aura")) == 0
    assert fxlib.bee_eye({**_bee("Custom wash"), "physical": {"lenses": 7}}) == 7
    assert fxlib.bee_eye({**_bee(), "kind": "par"}) == 0
    rings = [r for r, _, _ in fxlib.honeycomb(19)]
    assert rings.count(0) == 1 and rings.count(1) == 6 and rings.count(2) == 12


def test_an_open_beam_lights_every_lens_and_the_front_stays_still(bee):
    buf = _dmx(bee, State(dimmer=1.0, r=1.0, g=0.0, b=0.5, fx="open"))
    reds = [buf[7 + 4 * k] for k in range(LENSES)]
    blues = [buf[9 + 4 * k] for k in range(LENSES)]
    assert reds == [255] * LENSES and all(b == 128 for b in blues)
    assert buf[5] == 0  # the roll at its still position


def test_a_gobo_is_a_pattern_of_lit_lenses_of_its_style(bee):
    groups = gobos.groups(_bee())
    assert set(groups) == {"rings", "dots", "shapes", "curves"}
    assert gobos.usable(_bee()) == list(range(1, len(fxlib.BEE_PATTERNS) + 1))
    outer = groups["rings"][0] - 1
    buf = _dmx(bee, State(dimmer=1.0, r=1.0, fx="gobo", gobo=outer))
    lit = [buf[7 + 4 * k] > 0 for k in range(LENSES)]
    assert lit == [False] * 7 + [True] * 12  # the outer ring only
    for i in range(len(fxlib.BEE_PATTERNS)):  # every pattern lights some lenses and darkens others
        shares, turns = fxlib.bee_look(LENSES, SimpleNamespace(fx="gobo", gobo=i))
        assert 0 < sum(shares) < LENSES and turns == 0


def test_rotation_turns_the_front_slow_when_calm_fast_in_a_drop_mirrored_the_other_way(bee):
    calm = _dmx(bee, State(dimmer=1.0, r=1.0, fx="gobo_rotate", fx_speed=0.3))[5]
    drop = _dmx(bee, State(dimmer=1.0, r=1.0, fx="gobo_rotate", fx_speed=0.9))[5]
    other = _dmx(bee, State(dimmer=1.0, r=1.0, fx="prism_spin", fx_speed=0.9, fx_reverse=True))[5]
    assert 156 <= calm < drop <= 205
    assert 206 <= other <= 255
    shares, turns = fxlib.bee_look(LENSES, State(fx="prism_spin", fx_reverse=True))
    assert turns < 0 and shares[0] == 1 and 0 < sum(shares) < LENSES  # the flower, turning the other way


def test_master_colour_channels_before_the_pixels_stay_the_beams_colour():
    chans = [{"attr": "red"}, {"attr": "green"}, {"attr": "blue"}] + [
        {"attr": c} for _ in range(LENSES) for c in ("red", "green", "blue")
    ]
    px = fxlib.pixels(_bee(), chans)
    assert px[:3] == [-1, -1, -1] and px[3] == 0 and px[-1] == LENSES - 1


def test_the_visualiser_is_told_the_lenses(bee):
    rig = {"fixtures": [{**bee, "mount": "hang", "z_m": 5.0, "y_m": -1.0}], "stage": {"width_m": 8.0}}
    e = fxlib.expand(rig["fixtures"][0], 8.0)[0]
    assert element_info(rig, e)["lenses"] == LENSES


QXF = """<?xml version="1.0" encoding="UTF-8"?>
<FixtureDefinition xmlns="http://www.qlcplus.org/FixtureDefinition">
 <Manufacturer>Shehds</Manufacturer><Model>Big Bee Eyes LED Wash 7x40W RGB</Model><Type>Moving Head</Type>
 <Channel Name="Pan" Preset="PositionPan"/><Channel Name="Tilt" Preset="PositionTilt"/>
 <Channel Name="Barrel Roll"><Group Byte="0">Beam</Group>
  <Capability Min="0" Max="155">Barrel Roll 0-60°</Capability>
  <Capability Min="156" Max="205">Clockwise Barrel Roll</Capability>
  <Capability Min="206" Max="255">Anti-clockwise Barrel Roll</Capability></Channel>
 <Channel Name="Master dimmer" Preset="IntensityMasterDimmer"/>
 {pixels}
 <Mode Name="{n} Channel">{numbers}{heads}</Mode>
 <Physical><Lens Name="Other" DegreesMin="4" DegreesMax="45"/></Physical>
</FixtureDefinition>"""


def test_the_qlc_converter_keeps_the_roll_and_numbers_the_lenses(tmp_path):
    names = ["Pan", "Tilt", "Barrel Roll", "Master dimmer"]
    pixels = ""
    for k in range(7):
        for c, preset in (("R", "IntensityRed"), ("G", "IntensityGreen"), ("B", "IntensityBlue")):
            pixels += f'<Channel Name="{c}{k + 1}" Preset="{preset}"/>'
            names.append(f"{c}{k + 1}")
    numbers = "".join(f'<Channel Number="{i}">{n}</Channel>' for i, n in enumerate(names))
    heads = "".join(
        "<Head>" + "".join(f"<Channel>{4 + 3 * k + j}</Channel>" for j in range(3)) + "</Head>" for k in range(7)
    )
    path = tmp_path / "bee.qxf"
    path.write_text(QXF.format(pixels=pixels, n=len(names), numbers=numbers, heads=heads), encoding="utf-8")
    defn = qlc.convert(str(path))
    chans = defn["modes"][f"{len(names)}ch"]
    assert defn["kind"] == "moving_head" and fxlib.bee_eye(defn) == 7
    assert chans[2] == {"attr": "lens_roll", "default": 0, "cw": [156, 205], "ccw": [206, 255]}
    assert not any("head" in c for c in chans)  # still one head: one motor, one beam
    assert [c.get("pixel") for c in chans[4:]] == [k for k in range(7) for _ in range(3)]
