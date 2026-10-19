"""COLORado PXL Curve 12: a bar of 12 RGBW cells, each on its own tilt motor with its own zoom."""

from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.rig.loader import load_rig_dict
from amadeus.show.feed import element_info
from tests.synthetic import synthetic_analysis

KEY = "chauvet/colorado-pxl-curve-12"


def _rig(mode: str = "179ch") -> dict:
    curve = {"fixture": KEY, "mode": mode, "universe": 1, "mount": "floor", "y_m": -0.5, "z_m": 0.3}
    return load_rig_dict(
        {
            "fixtures": [
                {**curve, "id": "curveL", "address": 1, "x": 0.25},
                {**curve, "id": "curveR", "address": 1, "universe": 2, "x": 0.75},
                {"fixture": "dts/katana", "mode": "Extended", "id": "katana", "universe": 3, "address": 1,
                 "mount": "floor", "x": 0.5, "y_m": -0.5, "z_m": 0.3},
            ],
            "stage": {"width_m": 6, "ceiling_m": 4, "room_depth_m": 8, "eye_safety": False},
            "safety": {"max_flash_hz": 3, "master": 1.0},
        }
    )


def _ch(defn, mode, attr, head=None):
    return [i for i, c in enumerate(fxlib.channels(defn, mode)) if c["attr"] == attr and c.get("head") == head]


def test_every_mode_from_the_manual():
    defn = fxlib.get(KEY)
    assert {m: len(c) for m, c in defn["modes"].items()} == {
        "179ch": 179, "169ch": 169, "155ch": 155, "101ch": 101, "53ch": 53, "20ch": 20
    }
    assert fxlib.default_mode(defn) == "179ch"
    for mode in defn["modes"]:
        assert fxlib.cell_motors(defn, mode) == (mode != "20ch")  # 20ch: one tilt for all twelve
        assert len(fxlib.heads(defn, mode)) == (1 if mode == "20ch" else 12)
    assert not fxlib.cell_motors(fxlib.get("dts/katana"), "Extended")  # one motor for the whole bar
    assert not fxlib.high_risk(defn)


@pytest.mark.parametrize("mode", ["179ch", "169ch", "155ch", "101ch", "53ch", "20ch"])
def test_each_cell_tilts_to_its_own_angle(mode):
    rig = _rig(mode)
    fx = rig["fixtures"][0]
    defn = fxlib.get(KEY)
    els = [e for e in rig["elements"] if e["fixture"] == "curveL"]
    states = {e["id"]: State(dimmer=1.0, r=1.0, g=0.0, b=0.0, tilt=k / 11) for k, e in enumerate(els)}
    buf = bytearray(512)
    fxlib.patch(buf, fx, states, limit=1.0)
    for k, e in enumerate(els):
        head = e["head"] or None
        want = round(k / 11 * 65535) if head else 0
        coarse, fine = _ch(defn, mode, "tilt", head)[0], _ch(defn, mode, "tilt_fine", head)[0]
        assert abs((buf[coarse] << 8 | buf[fine]) - want) <= 1
    control = _ch(defn, mode, "control")[0]
    assert buf[control] == 22  # RGBW colour mixing, whatever the menu says
    strobe = _ch(defn, mode, "strobe")[0]
    assert 20 <= buf[strobe] <= 24  # open, no strobe
    red = _ch(defn, mode, "red", None if mode in ("53ch", "20ch") else 1)[0]
    assert buf[red] == 255


def test_cells_have_their_own_colour_and_zoom():
    rig = _rig()
    fx = rig["fixtures"][0]
    defn = fxlib.get(KEY)
    els = [e for e in rig["elements"] if e["fixture"] == "curveL"]
    states = {e["id"]: State(dimmer=0.5, r=1.0 if e["head"] % 2 else 0.0, b=0.0 if e["head"] % 2 else 1.0) for e in els}
    states[els[2]["id"]].fx = "frost"  # a wide wash from one cell
    buf = bytearray(512)
    fxlib.patch(buf, fx, states, limit=1.0)
    assert buf[_ch(defn, "179ch", "dimmer")[0]] == 255  # the master open: the cells' dimmers set the level
    assert buf[_ch(defn, "179ch", "dimmer", 1)[0]] == 128
    assert (buf[_ch(defn, "179ch", "red", 1)[0]], buf[_ch(defn, "179ch", "blue", 1)[0]]) == (255, 0)
    assert (buf[_ch(defn, "179ch", "red", 2)[0]], buf[_ch(defn, "179ch", "blue", 2)[0]]) == (0, 255)
    assert [buf[_ch(defn, "179ch", "zoom", h)[0]] for h in (1, 2, 3, 4)] == [0, 0, 255, 0]
    assert all(buf[i] == 0 for a in ("red", "green", "blue", "white") for i in _ch(defn, "179ch", a))  # master colour


@pytest.fixture(scope="module")
def show():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    k = next(i for i, d in enumerate(plan) if d.section == "groove")
    plan[k] = replace(plan[k], movement="tilt_wave", formation="wave", aim="crowd", intensity=2)
    return a, plan, k, Engine(a, plan, _rig(), real_output=False)


def test_the_cells_move_on_their_own_motors(show):
    _, plan, k, e = show
    d = plan[k]
    lo, hi = int((d.start + 1) * 50), int((d.end - 1) * 50)
    curve = [e.traj[f"curveL.{h}"][1][lo:hi] for h in range(1, 13)]
    assert max(float(np.max(np.abs(c - curve[0]))) for c in curve[1:]) > 0.05  # a wave runs along the bar
    katana = [h["id"] for h in e.heads if h["fixture"] == "katana"]
    assert len(katana) > 1 and all(e.traj[i] is e.traj[katana[0]] for i in katana)  # still one motor there


def test_a_fan_bends_the_bar_into_a_curve(show):
    a, plan, k, _ = show
    plan = list(plan)
    plan[k] = replace(plan[k], movement="still", formation="fan", aim="sky", intensity=1)
    e = Engine(a, plan, _rig(), real_output=False)
    d = plan[k]
    ts = np.linspace(d.start + 1, d.end - 1, 50)
    idx = {h["id"]: j for j, h in enumerate(e.heads)}

    def elevation(h):
        dirs = e._head_dir_v(d, ts, idx[f"curveL.{h}"])
        return float(np.mean(np.degrees(np.arcsin(np.clip(dirs[:, 2], -1, 1)))))

    ends, middle = (elevation(1) + elevation(12)) / 2, (elevation(6) + elevation(7)) / 2
    assert ends - middle > 20


def test_the_visualisers_draw_cells_that_tilt_on_their_own():
    rig = _rig()
    info = {e["id"]: element_info(rig, e) for e in rig["elements"]}
    assert info["curveL.1"]["body"] == "curve_bar" and info["curveL.1"]["cells"] == 12
    assert info["katana.1"]["body"] == "moving_bar"
    assert element_info(_rig("20ch"), _rig("20ch")["elements"][0])["body"] == "moving_bar"
