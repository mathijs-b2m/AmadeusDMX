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


def test_a_pointed_head_says_where_it_is_and_stays_lit_while_looked_at(monkeypatch, tmp_path):
    """The calibration's picture: the head's place, its beam and the stage; and its minute started again for as long
    as the sheet is open (it went dark while the second step was still being looked at)."""
    import socket
    import time

    from amadeus.dmx import artnet
    from amadeus.rig import geometry
    from amadeus.web import rig as web_rig

    monkeypatch.setattr(artnet, "HOLD_FILE", tmp_path / "dmx-hold")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    rig = json.loads((ROOT / "tests" / "sets" / "small.json").read_text(encoding="utf-8"))
    rig["artnet"] = {"ip": "127.0.0.1", "port": sock.getsockname()[1], "fps": 40}
    rig.pop("output", None)
    rig.pop("dmx", None)
    head = next(f for f in rig["fixtures"] if fxlib.is_moving(fxlib.get(f["fixture"])))

    class Req:
        def __init__(self, body):
            self._body = body

        def body(self):
            return self._body

    try:
        assert web_rig.test_light(Req({"fixture": head["id"], "keep": True}))["on"] is False  # not lit: nothing kept
        out = web_rig.test_light(Req({"fixture": head["id"], "rig": rig, "on": True, "point": "front"}))
        loaded = load_rig_dict(rig)
        st = geometry.stage(loaded)
        assert out["stage"] == [st["width_m"], st["ceiling_m"]]
        assert 0 <= out["pos"][0] <= st["width_m"] and len(out["pos"]) == 3
        assert out["dir"][1] > 0.9  # straight out at the audience
        with web_rig._test_lock:
            web_rig._test["lit"][head["id"]] = time.monotonic() + 1.0  # its minute nearly over
        assert web_rig.test_light(Req({"fixture": head["id"], "keep": True}))["on"] is True
        assert web_rig._test["lit"][head["id"]] > time.monotonic() + web_rig.TEST_SECONDS - 5
    finally:
        web_rig.test_light(Req({"fixture": head["id"], "rig": rig, "on": False}))
        deadline = time.monotonic() + 2
        while web_rig._test["thread"] is not None and time.monotonic() < deadline:
            time.sleep(0.01)
        sock.close()


# ---- the pan test: does the head turn the way the software thinks? ------------------------------------------------


def _head(**placing):
    from amadeus.library import fixtures as fxlib

    rig = json.loads((ROOT / "tests" / "sets" / "small.json").read_text(encoding="utf-8"))
    hid = next(f["id"] for f in rig["fixtures"] if fxlib.is_moving(fxlib.get(f["fixture"])))
    rig = load_rig_dict({**rig, "fixtures": [f | placing if f["id"] == hid else f for f in rig["fixtures"]]})
    fx = next(f for f in rig["fixtures"] if f["id"] == hid)
    return fx, fxlib.get(fx["fixture"])


def _deg(a, b) -> float:
    import math

    import numpy as np

    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(a, b))))))


def test_the_pan_test_turns_to_the_audiences_left():
    from amadeus.rig import geometry

    fx, defn = _head()
    a, b, side = hangsheet.pan_sweep(fx, defn)
    da, db = geometry.fk(fx, defn, *a), geometry.fk(fx, defn, *b)
    assert side == "left" and db[0] > da[0] + 0.5  # +x: stage right, the audience's left
    assert abs(a[1] - b[1]) < 1e-9  # its pan alone
    assert abs(_deg(da, db) - hangsheet.PAN_SWEEP_DEG) < 15


def test_turning_the_pan_the_other_way_keeps_straight_out():
    from amadeus.rig import geometry

    for placing in ({}, {"rot_deg": 85}, {"rot_deg": 180, "pan_invert": True}, {"mount": "stand", "rot_deg": 270}):
        fx, defn = _head(**placing)
        fields = hangsheet.flip_pan(fx, defn)
        assert fields["pan_invert"] is (not fx.get("pan_invert", False))
        aim = hangsheet.front_aim(fx, defn)
        assert _deg(geometry.fk(fx, defn, *aim), geometry.fk({**fx, **fields}, defn, *aim)) < 0.5, placing
        _, b, _ = hangsheet.pan_sweep(fx, defn)  # and the turn now goes the other way
        assert _deg(geometry.fk(fx, defn, *b), geometry.fk({**fx, **fields}, defn, *b)) > 90, placing


def test_a_mirrored_head_turned_a_quarter_comes_out_right_everywhere():
    """fx1 on the studio rig: standing, turned 85°, its pan really running the other way. Straight out alone was
    put "right" by half a turn of its pan home, and the show then sent it the opposite way. The front step's half
    turn plus the pan test's flip makes the software's head the real one, in every direction."""
    import numpy as np

    from amadeus.rig import geometry

    fx, defn = _head(mount="stand", rot_deg=85)
    real = {**fx, "pan_invert": not fx.get("pan_invert", False)}  # how it really turns
    front = hangsheet.front_aim(fx, defn)
    assert _deg(geometry.fk(real, defn, *front), geometry.fk(fx, defn, *front)) > 140  # it pointed elsewhere
    cal = {**fx, **hangsheet.fix_front(fx, defn, "back")}  # "Not like it" until straight out looked right …
    front = hangsheet.front_aim(cal, defn)
    assert _deg(geometry.fk(real, defn, *front), geometry.fk(cal, defn, *front)) < 15
    a, b, _ = hangsheet.pan_sweep(cal, defn)  # … but the pan test turns it the wrong way
    turn = geometry.fk(cal, defn, *b) - geometry.fk(cal, defn, *a)
    seen = geometry.fk(real, defn, *b) - geometry.fk(real, defn, *a)
    assert float(np.dot(turn[:2], seen[:2])) < 0
    cal = {**cal, **hangsheet.flip_pan(cal, defn)}  # "It turns the other way"
    for az in range(-150, 181, 30):
        for el in (-40, 0, 30):
            d = geometry.direction(az, el)
            p, t = geometry.to_dmx(cal, defn, *geometry.ik(cal, defn, d, None))
            assert _deg(geometry.fk(real, defn, p, t), geometry.fk(cal, defn, p, t)) < 12, (az, el)


def test_the_pan_test_sweeps_out_and_back():
    from amadeus.web import rig as web_rig

    aim = {"sweep": ((0.2, 0.5), (0.4, 0.5)), "t0": 100.0}
    hold, move = web_rig.SWEEP_HOLD_S, web_rig.SWEEP_MOVE_S
    assert web_rig._aim_now(aim, 100.0) == (0.2, 0.5)
    assert abs(web_rig._aim_now(aim, 100.0 + hold + move / 2)[0] - 0.3) < 1e-9
    assert abs(web_rig._aim_now(aim, 100.0 + hold + move + 0.1)[0] - 0.4) < 1e-9
    assert abs(web_rig._aim_now(aim, 100.0 + 2 * (hold + move))[0] - 0.2) < 1e-9
    assert web_rig._aim_now((0.5, 0.5), 3.0) == (0.5, 0.5)
