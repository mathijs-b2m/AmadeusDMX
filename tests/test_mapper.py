"""The DMX mapper: a fixture the show can't play (only effect, macro or unnamed channels) gets its channels mapped
by hand and plays; mapping a fixture that already plays, without changing anything, leaves it as it was."""

import json
import shutil
import socket
from pathlib import Path

import pytest

from amadeus.dmx import artnet
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.library import mapper
from amadeus.web import rig as web_rig

ROOT = Path(__file__).resolve().parent.parent

EFFECT = {  # as a converter leaves an effect light it couldn't read: every channel held
    "manufacturer": "Test",
    "model": "Effect",
    "kind": "par",
    "physical": {"beam_deg": 25},
    "modes": {
        "5ch": [
            {"attr": "programs", "default": 0},
            {"attr": "red_1", "default": 0},
            {"attr": "green_1", "default": 0},
            {"attr": "blue_1", "default": 0},
            {"attr": "unknown", "default": 0},
        ]
    },
}


@pytest.fixture
def library(monkeypatch, tmp_path):
    shutil.copytree(ROOT / "fixtures", tmp_path, dirs_exist_ok=True)
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "effect.json").write_text(json.dumps(EFFECT), encoding="utf-8")
    monkeypatch.setattr(fxlib, "LIB_DIR", tmp_path)
    monkeypatch.setattr(fxlib, "USER_DIR", None)
    fxlib.library.cache_clear()
    yield tmp_path
    fxlib.library.cache_clear()


def _as_shown(key: str, mode: str) -> list[dict]:
    return [{"role": c["role"], "cell": c["cell"], "value": c["value"]} for c in mapper.describe(key, mode)["channels"]]


@pytest.mark.parametrize("key", ["beamz/fuze75b-beam", "ayra/compar-kit-2", "dts/katana", "laserworld/cs-1000rgb-mk3"])
def test_saving_what_it_shows_changes_nothing(library, key):
    defn = fxlib.get(key)
    mode = fxlib.default_mode(defn)
    before = json.loads(json.dumps(defn))
    problems = mapper.apply(key, mode, defn["kind"] if defn["kind"] in mapper.KINDS else "par", _as_shown(key, mode))
    if defn["kind"] == "laser":
        assert problems and "Lasers" in problems[0]
        return
    assert problems == []
    after = fxlib.get(key)
    assert after["modes"] == before["modes"] and after["kind"] == before["kind"]
    assert after["mapped"]["modes"] == [mode]


def test_an_effect_light_plays_once_mapped(library):
    d = mapper.describe("test/effect", "5ch")
    assert not d["plays"] and [c["role"] for c in d["channels"]] == ["hold"] * 5
    chans = [
        {"role": "hold", "value": 0},  # programs off
        {"role": "red"},
        {"role": "green"},
        {"role": "blue"},
        {"role": "hold", "value": 200},
    ]
    assert mapper.apply("test/effect", "5ch", "par", chans) == []
    defn = fxlib.get("test/effect")
    assert mapper.plays(defn, "5ch") and defn["kind"] == "par"
    fx = {"id": "fx1", "fixture": "test/effect", "mode": "5ch", "universe": 1, "address": 1, "x": 0.5}
    buf = bytearray(512)
    fxlib.patch(buf, fx, {"fx1": State(dimmer=1.0, r=1.0, g=0.0, b=0.5)})
    assert list(buf[:5]) == [0, 255, 0, 128, 200]


def test_pan_and_tilt_make_a_moving_head_and_cells_a_bar(library):
    chans = [{"role": "pan"}, {"role": "tilt"}, {"role": "dimmer"}, {"role": "hold"}, {"role": "hold"}]
    assert mapper.apply("test/effect", "5ch", "par", chans) == []
    defn = fxlib.get("test/effect")
    assert defn["kind"] == "moving_head" and defn["physical"]["pan_deg"] == 540 and "motion" in defn
    chans = [{"role": "dimmer"}, {"role": "white", "cell": 1}, {"role": "white", "cell": 2}, {"role": "hold"}] + [
        {"role": "hold"}
    ]
    assert mapper.apply("test/effect", "5ch", "par", chans) == []
    defn = fxlib.get("test/effect")
    assert defn["kind"] == "par_bar" and "pan_deg" not in defn["physical"] and "motion" not in defn
    assert fxlib.heads(defn, "5ch") == [1, 2]


def test_problems_are_said_and_nothing_is_saved(library):
    before = fxlib.get("test/effect")["modes"]
    assert any("lights it" in p for p in mapper.apply("test/effect", "5ch", "par", [{"role": "hold"}] * 5))
    assert any("5 channels" in p for p in mapper.apply("test/effect", "5ch", "par", [{"role": "red"}]))
    assert any("DMX value" in p for p in mapper.apply("test/effect", "5ch", "par", [{"role": "red", "value": 300}] * 5))
    chans = [{"role": "pan"}, {"role": "red"}] + [{"role": "hold"}] * 3
    assert any("pan and tilt" in p for p in mapper.apply("test/effect", "5ch", "moving_head", chans))
    assert fxlib.get("test/effect")["modes"] == before


def test_the_mapper_sends_raw_values_to_try_a_channel(library, monkeypatch, tmp_path):
    monkeypatch.setattr(artnet, "HOLD_FILE", tmp_path / "dmx-hold")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    rig = {
        "artnet": {"ip": "127.0.0.1", "port": sock.getsockname()[1], "fps": 40},
        "fixtures": [{"id": "fx1", "fixture": "test/effect", "mode": "5ch", "universe": 1, "address": 10, "x": 0.5}],
    }

    class Req:
        def __init__(self, body):
            self._body = body

        def body(self):
            return self._body

    try:
        r = web_rig.test_light(Req({"fixture": "fx1", "rig": rig, "on": True, "raw": [7, 0, 255, 0, 99]}))
        assert r["channels"] == [10, 14]
        pkt, _ = sock.recvfrom(1024)
        assert list(pkt[18 + 9 : 18 + 14]) == [7, 0, 255, 0, 99]
        bad = web_rig.test_light(Req({"fixture": "fx1", "rig": rig, "on": True, "raw": [300]}))
        assert isinstance(bad, tuple) and bad[1] == 400
    finally:
        web_rig.test_light(Req({"fixture": "fx1", "rig": rig, "on": False}))
        sock.close()


def test_the_library_names_and_ranges_come_along_when_at_hand():
    from amadeus.library import qlc

    if not (qlc.REPO_DIR / "resources" / "fixtures" / "beamZ" / "beamZ-BUV-463-LED-UV.qxf").exists():
        pytest.skip("the QLC+ library isn't downloaded")
    names = mapper.source_channels({"qlc": {"key": "beamZ/beamZ-BUV-463-LED-UV.qxf"}}, "Default")
    assert [n["name"] for n in names][:3] == ["Master dimmer", "Strobe", "Auto"]
    assert [51, 100, "Auto Program 1"] in names[2]["ranges"]


def test_tried_light_stays_under_the_brightness_limiter(library, tmp_path):
    from amadeus.dmx import limiter

    before = limiter.FILE
    limiter.use(tmp_path / "limiter.json")
    try:
        limiter.save(0.5)
        fx = {"id": "fx1", "fixture": "test/effect", "mode": "5ch", "universe": 1, "address": 1, "x": 0.5}
        buf = bytearray(512)
        fxlib.test_raw(buf, fx, [255, 255, 255, 40, 255], light={1, 2})
        assert list(buf[:5]) == [255, 128, 128, 40, 255]  # programs and unknowns as they are: they aren't light
    finally:
        limiter.use(before)


def test_a_ring_round_the_lens_wears_the_beams_colour_and_rests_with_the_head(library, monkeypatch):
    chans = [{"role": "pan"}, {"role": "tilt"}, {"role": "red"}, {"role": "green"}, {"role": "ring_color"}]
    ring = [
        {"name": "red", "from": 20, "to": 39, "rgb": [1, 0, 0]},
        {"name": "off", "from": 0, "to": 19, "rgb": [0, 0, 0]},  # added last, lowest on the channel
        {"name": "green", "from": 40, "to": 59, "rgb": [0, 1, 0]},
        {"name": "white", "from": 60, "to": 79, "rgb": [1, 1, 1]},
    ]
    assert mapper.apply("test/effect", "5ch", "par", chans, ring=ring) == []
    defn = fxlib.get("test/effect")
    assert [s["name"] for s in defn["ring_color"]["slots"]] == ["off", "red", "green", "white"]
    assert [s["name"] for s in mapper.describe("test/effect", "5ch")["ring"]] == ["off", "red", "green", "white"]

    clock = [100.0]
    monkeypatch.setattr(fxlib.time, "monotonic", lambda: clock[0])
    fxlib._rings.clear()
    fx = {"id": "ring1", "fixture": "test/effect", "mode": "5ch", "universe": 1, "address": 1, "x": 0.5}

    def ring_at(t, **state):
        clock[0] = t
        buf = bytearray(512)
        fxlib.patch(buf, fx, {"ring1": State(**state)})
        return buf[4]

    assert ring_at(100.0, dimmer=0.0) == 9  # resting: off
    assert ring_at(100.1, dimmer=1.0, r=1.0) == 29  # the first hit: red at once
    assert ring_at(100.3, dimmer=1.0, r=1.0, g=1.0, b=1.0) == 29  # a white flash doesn't blip it
    assert ring_at(100.4, dimmer=1.0, r=1.0) == 29
    assert ring_at(101.0, dimmer=0.0) == 29  # between notes it stays lit
    assert ring_at(101.2, dimmer=1.0, g=1.0) == 29  # a new colour, not yet lasted
    assert ring_at(102.3, dimmer=1.0, g=1.0) == 49  # …now it has
    assert ring_at(106.0, dimmer=0.0) == 9  # the head rests: off

    assert mapper.apply("test/effect", "5ch", "par", chans) == []  # mapped again without naming: the named colours stay
    assert fxlib.get("test/effect")["ring_color"]["slots"][0]["name"] == "off"
