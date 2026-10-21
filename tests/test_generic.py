"""Fixtures without a brand: made from a common layout, they play at once; the check on the fixture then puts right
what the manual (or the template) has wrong, names the colour wheel and marks the fixture checked."""

import shutil
from pathlib import Path

import pytest

from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.library import generic, mapper

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def library(monkeypatch, tmp_path):
    shutil.copytree(ROOT / "fixtures", tmp_path, dirs_exist_ok=True)
    monkeypatch.setattr(fxlib, "LIB_DIR", tmp_path)
    monkeypatch.setattr(fxlib, "USER_DIR", None)
    fxlib.library.cache_clear()
    yield tmp_path
    fxlib.library.cache_clear()


def _fx(key: str, mode: str) -> dict:
    return {"id": "h1", "fixture": key, "mode": mode, "universe": 1, "address": 1, "x": 0.5}


def test_templates_closest_first_and_blank_last():
    ts = generic.templates("spot", 11)
    assert ts[0]["id"] == "spot-11" and ts[-1]["id"] == "blank"
    assert [t["type"] for t in ts[:3]] == ["spot"] * 3
    assert generic.templates("wash", 9)[0]["id"] == "wash-9"


@pytest.mark.parametrize("tid", [t for t in generic.TEMPLATES if t != "blank"])
def test_every_template_makes_a_fixture_that_plays(library, tid):
    t = generic.TEMPLATES[tid]
    r = generic.create("Chegit", f"Test {tid}", tid, len(t["channels"]), t["type"], watts=60)
    defn = fxlib.get(r["key"])
    assert r["key"].startswith("chegit/") and r["mode"] == f"{len(t['channels'])}ch"
    assert mapper.plays(defn, r["mode"]) and not defn["made"]["checked"]
    assert defn["kind"] == ("moving_head" if t["type"] != "par" else "par")
    assert fxlib.validate({"fixtures": [_fx(r["key"], r["mode"])]}) == []
    buf = bytearray(512)
    fxlib.patch(buf, _fx(r["key"], r["mode"]), {"h1": State(dimmer=1.0, r=1.0, g=0.0, b=0.0, pan=0.5, tilt=0.5)})
    assert any(buf[: len(t["channels"])])  # something lit
    d = mapper.describe(r["key"], r["mode"])
    assert d["made"] and not d["checked"] and [c["name"] for c in d["channels"]] == [c["name"] for c in t["channels"]]


def test_the_fixtures_own_channel_count_wins(library):
    short = generic.create("", "Seven", "spot-9", 7)
    assert len(fxlib.get(short["key"])["modes"]["7ch"]) == 7 and short["key"].startswith("generic/")
    longer = generic.create("Chegit", "Ten", "spot-9", 10)
    chans = fxlib.get(longer["key"])["modes"]["10ch"]
    assert chans[-1] == {"attr": "channel_10", "default": 0}
    blank = generic.create("Chegit", "Unknown", "blank", 6)
    assert not mapper.plays(fxlib.get(blank["key"]), "6ch")  # nothing known yet: the check finds it
    again = generic.create("Chegit", "Ten", "spot-9", 10)
    assert again["key"] == longer["key"] + "-2"
    assert generic.create("Chegit", "", "spot-9", 0)["problems"]


def test_the_check_puts_a_wrong_manual_right(library):
    r = generic.create("Chegit", "60W Spot", "spot-9", 9, "spot")
    key, mode = r["key"], r["mode"]
    # on the real fixture: tilt and pan the other way round, the strobe channel is really the dimmer's place
    chans = [
        {"role": "tilt"},
        {"role": "pan"},
        {"role": "color_wheel"},
        {"role": "hold", "attr": "gobo", "value": 0},
        {"role": "dimmer"},
        {"role": "hold", "attr": "strobe", "value": 0},
        {"role": "hold", "attr": "pan_tilt_speed", "value": 0},
        {"role": "hold", "attr": "auto", "value": 0},
        {"role": "hold", "attr": "reset", "value": 0},
    ]
    wheel = [
        {"name": "open", "from": 0, "to": 9, "rgb": [1, 1, 1]},
        {"name": "red", "from": 10, "to": 19, "rgb": [1, 0, 0]},
        {"name": "blue", "from": 20, "to": 29, "rgb": [0, 0.2, 1]},
    ]
    assert mapper.apply(key, mode, "moving_head", chans, wheel=wheel, checked=True) == []
    defn = fxlib.get(key)
    assert defn["made"]["checked"] and "checked channel by channel" in defn["source"]
    assert defn["color_wheel"] == {"verified": True, "slots": wheel}
    names = [c["name"] for c in mapper.describe(key, mode)["channels"]]
    assert names[:2] == ["Tilt", "Pan"] and names[4:6] == ["Dimmer", "Strobe"]
    buf = bytearray(512)
    s = State(dimmer=1.0, r=0.0, g=0.1, b=1.0, pan=1.0, tilt=0.0, fx="gobo")
    fxlib.patch(buf, _fx(key, mode), {"h1": s})
    assert buf[0] == 0 and buf[1] == 255  # tilt, pan
    assert buf[2] == 24  # the blue slot's middle
    assert buf[3] in generic.GOBO_VALUES  # the gobo still found by its name
    assert buf[4] == 255 and buf[5] == 0


def test_a_wheel_slot_out_of_range_is_refused(library):
    r = generic.create("Chegit", "Spot", "spot-9", 9)
    chans = [{"role": c["role"], "value": c["value"]} for c in mapper.describe(r["key"], r["mode"])["channels"]]
    bad = [{"name": "open", "from": 0, "to": 300, "rgb": [1, 1, 1]}]
    assert any("DMX range" in p for p in mapper.apply(r["key"], r["mode"], "moving_head", chans, wheel=bad))
    assert not fxlib.get(r["key"])["color_wheel"]["verified"]


def test_a_colour_wheel_role_on_a_fixture_without_one_gets_the_usual_wheel(library):
    r = generic.create("Chegit", "Odd", "blank", 3)
    chans = [{"role": "dimmer"}, {"role": "color_wheel"}, {"role": "hold"}]
    assert mapper.apply(r["key"], r["mode"], "par", chans) == []
    defn = fxlib.get(r["key"])
    assert len(defn["color_wheel"]["slots"]) == len(generic.WHEEL_SLOTS)
    buf = bytearray(512)
    fxlib.patch(buf, _fx(r["key"], r["mode"]), {"h1": State(dimmer=1.0, r=1.0, g=0.0, b=0.0)})
    assert buf[0] == 255 and buf[1] == 23  # red: the second slot of 16 values
