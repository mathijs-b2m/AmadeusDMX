"""Gobos: their pictures and styles, the wheels the converters drive, what the visualiser is told, and zoom."""

import base64
import json

import numpy as np
import pytest

from amadeus.engine.realism import Realism
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.library import gobos, shadow
from amadeus.show import feed as feedlib


def head(key: str, mode: str | None = None, fid: str = "h1", address: int = 1) -> dict:
    defn = fxlib.get(key)
    return {"id": fid, "fixture": key, "mode": mode or fxlib.default_mode(defn), "universe": 1, "address": address,
            "x": 0.5}  # fmt: skip


def rig_of(*fixtures: dict) -> dict:
    return {"fixtures": list(fixtures), "elements": [e for f in fixtures for e in fxlib.expand(f)]}


def test_the_catalogue_has_the_library_gobos_with_a_style_each():
    cat = gobos.catalog()
    assert len(cat) > 1000  # QLC+ and the Open Fixture Library
    assert {e["style"] for e in cat.values()} == {*gobos.STYLES, gobos.FIGURE}
    pic = base64.b64decode(cat["ofl/10-circles"]["img"])
    assert pic.startswith(b"\x89PNG")
    assert "qlc/Others/open" not in cat  # the open hole is not a gobo


@pytest.mark.parametrize(
    ("key", "style"),
    [("ofl/32-circles", "rings"), ("ofl/circle-outline", "rings"), ("ofl/bubbles", "dots"),
     ("ofl/dot-spiral", "dots"), ("ofl/5-pointed-star", "shapes"), ("ofl/4-vertical-bars", "shapes"),
     ("ofl/3-fold-spiral", "curves"), ("ofl/biohazard", "curves")],
)  # fmt: skip
def test_a_picture_is_read_as_the_kind_of_pattern_it_shows(key, style):
    assert gobos.style(key) == style


def test_a_gobo_known_only_by_name_gets_a_pattern_of_its_kind():
    assert gobos.style("name/stars") == "dots"
    assert gobos.style("name/spiral") == "curves"
    assert gobos.style("name/triangle") == "shapes"
    assert gobos.style("name/gobo-3") in gobos.STYLES  # a number: some pattern, never nothing
    png = base64.b64decode(gobos.picture("name/bubbles"))
    assert png.startswith(b"\x89PNG") and len(png) > 100
    img = gobos.pattern_image("rings")
    assert img.shape == (gobos.SIZE, gobos.SIZE) and 0.2 < img.mean() < 0.8


def test_the_qlc_converter_drives_one_wheel_and_turns_its_gobos():
    """A wheel and a rotation channel (Chauvet Intimidator Spot 375Z): the gobo channel gets the gobos, the rotation
    channel its own values (it used to get the gobo's too), and the gobos can turn."""
    d = shadow.get("qlc:Chauvet/Chauvet-Intimidator-Spot-375Z-IRC.qxf")
    attrs = [c["attr"] for c in d["modes"]["15ch"]]
    assert attrs.count("gobo") == 1 and "gobo_rotation" in attrs
    assert set(d["beam_fx"]["gobo_rotate"]) == {"gobo", "gobo_rotation"}
    assert all(k.startswith("qlc/") for k in d["gobo_images"]["gobo"])
    buf = bytearray(512)
    fx = {
        "id": "h",
        "fixture": "chauvet/intimidator-spot-375z-irc",
        "mode": "15ch",
        "universe": 1,
        "address": 1,
        "x": 0,
    }
    fxlib.patch(buf, fx, {"h": State(dimmer=1, fx="gobo", gobo=1)})
    rot = attrs.index("gobo_rotation")
    still = buf[rot]
    fxlib.patch(buf, fx, {"h": State(dimmer=1, fx="gobo_rotate", gobo=1, fx_speed=1.0)})
    assert buf[attrs.index("gobo")] == d["beam_fx"]["gobo"]["gobo"][1]
    assert buf[rot] != still and buf[rot] in d["beam_fx"]["gobo_rotate"]["gobo_rotation"]["range"]


def test_a_second_gobo_wheel_stays_open():
    """Robe Pointe: a static and a rotating wheel; only one is driven, the other is held at its open hole."""
    d = fxlib.get("robe/pointe")
    for chans in d["modes"].values():
        assert [c["attr"] for c in chans].count("gobo") <= 1


def test_the_open_hole_is_not_a_gobo():
    """The Sharpy's first gobo slot is its open hole (QLC+ calls it White)."""
    d = fxlib.get("claypaky/sharpy")
    assert d["gobo_names"][0] == "Gobo 1"
    assert len(d["gobo_names"]) == len(d["beam_fx"]["gobo"]["gobo"])


def test_ofl_gobos_on_a_wheel_named_like_their_channel():
    """OFL capabilities that don't name their wheel are on the wheel named like the channel (DTS XR4 Spot), not the
    colour wheel."""
    d = shadow.get("ofl:dts/xr4-spot")
    assert "gobo" in d["beam_fx"] and "gobo_rotate" in d["beam_fx"]
    assert d["gobo_names"][:2] == ["Red sun", "Blue splash"]


def test_an_effect_the_fixture_cant_play_is_played_as_the_nearest_it_can():
    d = fxlib.get("claypaky/sharpy")  # a still and a shaking gobo, no rotation
    chans = fxlib.channels(d, fxlib.default_mode(d))
    assert fxlib.beam_effect(d, chans, "gobo_rotate") == "gobo"
    assert fxlib.beam_effect(d, chans, "gobo_shake") == "gobo_shake"
    spot = fxlib.get("chauvet/intimidator-spot-375z-irc")  # a prism that doesn't turn
    assert fxlib.beam_effect(spot, fxlib.channels(spot, "15ch"), "prism_spin") == "prism"
    assert fxlib.beam_effect(fxlib.get("dts/katana"), [], "gobo") == "open"


def test_styles_group_a_converted_wheel_and_pictures_stay_out():
    d = shadow.get("qlc:Chauvet/Chauvet-Intimidator-Spot-375Z-IRC.qxf")
    groups = gobos.groups(d)
    assert groups and set(groups) <= set(gobos.STYLES)
    assert sorted(i for g in groups.values() for i in g) == sorted(
        i + 1 for i, k in enumerate(gobos.wheel(d, "gobo")) if gobos.style(k) != gobos.FIGURE
    )
    hand_made = fxlib.get("beamz/fuze75b-beam")
    assert gobos.groups(hand_made)["rings"] == hand_made["gobo_groups"]["rings"]


def test_the_visualiser_sees_the_wheel_turn_rotate_and_shake():
    fx = head("chauvet/intimidator-spot-375z-irc", "15ch")
    rig = rig_of(fx)
    real = Realism(rig)
    pics = real.gobo_pictures()
    assert pics and all(p["img"] for p in pics)
    dt = 0.025
    s = State(dimmer=1, fx="gobo", gobo=3)
    first = real.beams({"h1": s}, dt)["h1"]
    assert first[0] == "gobo" and first[1][2] > 0  # on its way from the open hole
    for _ in range(80):
        shown = real.beams({"h1": s}, dt)["h1"]
    pic, nxt, frac, turn, shake, prism = shown[1]
    assert frac == 0 and turn == 0 and shake == 0 and prism == 0
    assert pics[pic]["key"] == gobos.wheel(fxlib.get(fx["fixture"]), "gobo")[3]
    turning = real.beams({"h1": State(dimmer=1, fx="gobo_rotate", gobo=3, fx_speed=0.5)}, dt)["h1"][1]
    assert turning[3] > 0
    back = real.beams({"h1": State(dimmer=1, fx="gobo_rotate", gobo=3, fx_speed=0.5, fx_reverse=True)}, dt)["h1"][1]
    assert back[3] == -turning[3]
    shaking = real.beams({"h1": State(dimmer=1, fx="gobo_shake", gobo=3)}, dt)["h1"][1]
    assert shaking[4] > 0
    for _ in range(80):
        gone = real.beams({"h1": State(dimmer=1, fx="open")}, dt)["h1"]
    assert gone == ("open", None, 0.0)  # back to the open hole, zoom tight


def test_a_spinning_wheel_scrolls():
    real = Realism(rig_of(head("chauvet/intimidator-spot-375z-irc", "15ch")))
    seen = {tuple(real.beams({"h1": State(dimmer=1, fx="gobo_spin", fx_speed=1)}, 0.1)["h1"][1][:2]) for _ in range(40)}
    assert len(seen) > 3


def test_zoom_opens_for_gobos_and_frost_and_the_motor_takes_a_moment():
    fx = head("chauvet/intimidator-spot-375z-irc", "15ch")
    real = Realism(rig_of(fx))
    assert real.beams({"h1": State(fx="open")}, 0.025)["h1"][2] == 0.0
    z = [real.beams({"h1": State(fx="frost", zoom=0.0)}, 0.025)["h1"][2] for _ in range(30)]
    assert 0 < z[0] < 1 and z[-1] == 1.0
    d = fxlib.get(fx["fixture"])
    zc = next(c for c in fxlib.channels(d, "15ch") if c["attr"] == "zoom")
    buf = bytearray(512)
    fxlib.patch(buf, fx, {"h1": State(dimmer=1, fx="gobo", zoom=0.5)})
    at = [c["attr"] for c in fxlib.channels(d, "15ch")].index("zoom")
    assert buf[at] == round(zc["tight"] + (zc["wide"] - zc["tight"]) * 0.5)


def test_the_feed_sends_the_pictures_once_and_the_gobos_per_frame():
    a, b = head("chauvet/intimidator-spot-375z-irc", "15ch"), head("claypaky/sharpy", fid="h2", address=40)
    rig = rig_of(a, b)
    real = Realism(rig)
    feed = feedlib.Feed({**rig, "safety": {"max_flash_hz": 3}}, real, 0.025)
    feed.head_fk = {}  # no geometry needed for this
    states = {"h1": State(dimmer=1, fx="gobo_rotate", gobo=1), "h2": State(dimmer=1, fx="gobo_rotate", gobo=1)}
    out = feed.fixture_fields(states)
    assert out["beam"] == ["gobo_rotate", "gobo"]  # the Sharpy can't turn its gobos
    assert len(out["gobo"]) == 2 and all(g and len(g) == 6 for g in out["gobo"])
    assert out["zoom"][0] is not None and out["zoom"][1] is None  # the Sharpy has no zoom channel
    json.dumps(out)
    assert {p["key"] for p in real.gobo_pictures()} >= set(gobos.wheel(fxlib.get("claypaky/sharpy"), "gobo"))


def test_classify_reads_simple_patterns():
    assert gobos.classify(gobos.pattern_image("rings")) == "rings"
    assert gobos.classify(gobos.pattern_image("dots")) == "dots"
    assert gobos.classify(gobos.pattern_image("triangle")) == "shapes"
    assert gobos.classify(np.zeros((gobos.SIZE, gobos.SIZE))) in (*gobos.STYLES, gobos.FIGURE)
