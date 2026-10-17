"""The light test on the Set page: one fixture lit (and the rest dark) until switched off, the emitters the show
keeps dark lit too, so a UV bar shows whether it is patched and connected. Lasers and smoke machines are left
alone."""

import json
import socket
import time
from pathlib import Path

import pytest

from amadeus.dmx import artnet
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.library import shadow
from amadeus.web import rig as web_rig

ROOT = Path(__file__).resolve().parent.parent
BUV = "qlc:beamZ/beamZ-BUV-463-LED-UV.qxf"


@pytest.fixture
def uv_bar(monkeypatch):
    defn = shadow.get(BUV)
    lib = dict(fxlib.library())
    lib["beamz/buv-463-led-uv"] = defn | {"key": "beamz/buv-463-led-uv"}
    monkeypatch.setattr(fxlib, "library", lambda: lib)
    return defn


def test_a_uv_bar_converts_to_a_bar_of_uv_cells(uv_bar):
    chans = uv_bar["modes"]["Default"]
    assert uv_bar["kind"] == "par_bar"
    assert [c.get("head") for c in chans if c["attr"] == "uv"] == [1, 2, 3, 4]


def test_the_light_test_lights_every_uv_section(uv_bar):
    fx = {"id": "buv1", "fixture": "beamz/buv-463-led-uv", "mode": "Default", "universe": 1, "address": 43, "x": 0.5}
    test = bytearray(512)
    fxlib.test_light(test, fx)
    assert test[42] == 255  # master dimmer
    assert all(v > 100 for v in test[46:50])  # every UV section
    assert test[44] == 0  # auto programs stay off


def test_the_show_plays_a_blacklight_in_uv_at_its_level(uv_bar):
    """A UV-only bar plays like the other bars, whatever colour the look gives it; the visualiser shows UV."""
    from amadeus.engine.realism import Realism

    fx = {"id": "buv1", "fixture": "beamz/buv-463-led-uv", "mode": "Default", "universe": 1, "address": 43, "x": 0.5}
    for level, cells in ((0.0, 0), (0.5, 128), (1.0, 255)):
        show = bytearray(512)
        fxlib.patch(show, fx, {e["id"]: State(dimmer=level, r=1, g=0.3, b=0) for e in fxlib.expand(fx)})
        assert list(show[46:50]) == [cells] * 4, level
    rig = {"fixtures": [fx], "elements": fxlib.expand(fx)}
    seen = Realism(rig).step({e["id"]: State(dimmer=0.7, r=1, g=0.3, b=0) for e in rig["elements"]}, 0.025)
    assert all(v == (0.7, *fxlib.UV_RGB, 0.0) for v in seen.values())
    assert not fxlib.uv_only(fxlib.get("ayra/compar-kit-2"))  # RGB(+UV) fixtures mix as before


def test_lasers_and_smoke_are_not_tested():
    for defn in (
        {"kind": "laser", "inert": "a laser whose channels aren't mapped by hand yet: it stays dark", "modes": {}},
        {"kind": "smoke", "modes": {"1ch": [{"attr": "fog", "on_from": 10}]}},
    ):
        assert fxlib.test_refusal(defn)
    assert not fxlib.test_refusal({"kind": "par", "modes": {}})


def test_the_endpoint_keeps_it_lit_until_switched_off(uv_bar, monkeypatch, tmp_path):
    monkeypatch.setattr(artnet, "HOLD_FILE", tmp_path / "dmx-hold")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(1.0)
    rig = json.loads((ROOT / "tests" / "sets" / "small.json").read_text(encoding="utf-8"))
    rig["artnet"] = {"ip": "127.0.0.1", "port": sock.getsockname()[1], "fps": 40}
    rig.pop("output", None)
    rig.pop("dmx", None)
    rig["fixtures"].append(
        {"id": "buv1", "fixture": "beamz/buv-463-led-uv", "mode": "Default", "universe": 1, "address": 300, "x": 0.5}
    )

    class Req:
        def __init__(self, body):
            self._body = body

        def body(self):
            return self._body

    try:
        out = web_rig.test_light(Req({"fixture": "buv1", "rig": rig, "on": True}))
        assert out["channels"] == [300, 307] and out["universe"] == 1 and out["wire_universe"] == 1
        data = _frame(sock)
        assert data[299] == 255 and all(v > 100 for v in data[303:307])
        dark = bytearray(512)
        for f in rig["fixtures"][:-1]:
            fxlib.patch(dark, f | {"x": f.get("x", 0.5)}, {e["id"]: State(pan=0.0, tilt=0.0) for e in fxlib.expand(f)})
        assert data[:299] == dark[:299]  # the rest of the set stays dark
        for f in rig["fixtures"][:-1]:  # and its heads stay where a blackout left them: they don't swing
            for off, c in enumerate(fxlib.channels(fxlib.get(f["fixture"]), f["mode"])):
                if c["attr"] in fxlib.PAN_TILT:
                    assert data[f["address"] - 1 + off] == 0, (f["id"], c["attr"])
        web_rig.test_light(Req({"fixture": "buv1", "rig": rig, "on": False}))
        deadline = time.monotonic() + 2
        while web_rig._test["thread"] is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert web_rig._test["thread"] is None
        assert not any(_last_frame(sock))  # ends in a blackout
        refused = web_rig.test_light(Req({"fixture": "nope", "rig": rig, "on": True}))
        assert isinstance(refused, tuple) and refused[1] == 400
    finally:
        web_rig.test_light(Req({"fixture": "buv1", "rig": rig, "on": False}))
        sock.close()


def _frame(sock) -> bytes:
    """The DMX data of the next ArtDMX packet."""
    pkt, _ = sock.recvfrom(1024)
    return pkt[18:]


def _last_frame(sock) -> bytes:
    sock.settimeout(0.2)
    last = None
    try:
        while True:
            last = _frame(sock)
    except TimeoutError:
        pass
    assert last is not None
    return last
