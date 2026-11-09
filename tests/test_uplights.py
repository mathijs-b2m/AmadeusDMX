"""Wall uplighters: tilting bars on the floor by a wall shine straight up, light up in a run on the beat grid, and
lean in only at the night's surprise."""

import json
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.engine.uplights import SURPRISE_HOLD_BEATS
from amadeus.rig import geometry
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig_dict
from amadeus.rig.uplights import is_uplight
from tests.synthetic import synthetic_analysis

FUZE = Path(__file__).parent / "sets" / "fuze24.json"
BAR = "chauvet/colorband-pix-m"  # a tilting bar of 12 cells


def _rig():
    rig = json.loads(FUZE.read_text())
    w = rig["stage"]["width_m"]  # 12 m, 2 m of room either side
    for k, (x, y) in enumerate([(-1.7, 3), (-1.7, 8), (-1.7, 13), (13.7, 3), (13.7, 8), (13.7, 13)]):
        rig["fixtures"].append(
            {
                "id": f"up{k + 1}",
                "fixture": BAR,
                "mode": "38ch",
                "universe": 2,
                "address": 1 + 40 * k,
                "x": x / w,
                "y_m": y,
                "z_m": 0.2,
                "mount": "floor",
                "rot_deg": 270 if x < 0 else 90,
            }  # fmt: skip
        )
    rig["fixtures"].append(  # the same bar on the stage, in the middle: an ordinary head
        {
            "id": "stagebar",
            "fixture": BAR,
            "mode": "38ch",
            "universe": 2,
            "address": 241,
            "x": 0.5,
            "y_m": -1,
            "z_m": 0.2,
            "mount": "floor",
        }  # fmt: skip
    )
    return load_rig_dict(rig)


@pytest.fixture(scope="module")
def show():
    rig = _rig()
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    return Engine(a, plan, rig, real_output=False), plan


def _fx(e, fid):
    return next(f for f in e.rig["fixtures"] if f["id"] == fid)


def _beam(e, eid, s):
    fx = _fx(e, eid.split(".")[0])
    from amadeus.library import fixtures as fxlib

    return geometry.fk(fx, fxlib.get(fx["fixture"]), s.pan, s.tilt)


def test_only_floor_bars_by_a_wall_are_uplighters(show):
    e, _ = show
    rig = e.rig
    assert {f["id"] for f in rig["fixtures"] if is_uplight(rig, f)} == {f"up{k}" for k in range(1, 7)}
    assert all(not h["id"].startswith("up") for h in e.heads)  # no head to the motion
    assert any(h["fixture"] == "stagebar" for h in e.heads)
    assert not any(i.startswith("up") for g in head_groups(rig) for i in g["ids"])
    pairs = [sorted({i.split(".")[0] for i in s}) for s in e.up_steps]
    assert pairs == [["up1", "up4"], ["up2", "up5"], ["up3", "up6"]]  # mirrored across the room, stage → back


def test_they_shine_straight_up_all_through(show):
    e, plan = show
    for t in np.arange(0.5, e.a.duration - 0.5, 0.37):
        states = e.render(t)[1]
        for eid in e.uplight_ids:
            assert _beam(e, eid, states[eid])[2] > 0.999, (t, eid)
            assert states[eid].dmx_tilt == pytest.approx(states[eid].tilt)


def test_the_run_steps_on_the_beat_from_the_stage_back(show):
    e, plan = show
    i = next(k for k, d in enumerate(plan) if d.section == "drop")
    d = plan[i]
    beats = e.beats[(e.beats >= d.start - 0.02) & (e.beats < d.end - 1)]
    order = []
    for b in beats[:6]:
        states = e.render(float(b) + 0.03)[1]  # just after the beat: the step it hit is the brightest
        lv = [max(states[x].dimmer for x in s) for s in e.up_steps]
        order.append(int(np.argmax(lv)))
    assert order == [0, 1, 2, 0, 1, 2]


def test_their_level_follows_the_phrase_not_the_loudness(show):
    e, plan = show
    i = next(k for k, d in enumerate(plan) if d.section == "drop")
    d = plan[i]
    peaks = []
    for b in e.beats[(e.beats >= d.start + 1) & (e.beats < d.end - 1)]:
        states = e.render(float(b) + 0.03)[1]
        peaks.append(max(states[x].dimmer for s in e.up_steps for x in s))
    assert max(peaks) - min(peaks) < 0.02  # every beat's step lands at the same level


def test_they_lean_in_at_the_surprise_only_and_stand_back_up(show):
    e, plan = show
    i = next(k for k, d in enumerate(plan) if d.section == "drop")
    e.surprise = i
    try:
        k = int(np.searchsorted(e.beats, plan[i].start - 0.02))
        mid = float(e.beats[k + 8])  # every step leaning by now
        states = e.render(mid)[1]
        for eid in e.uplight_ids:
            d = _beam(e, eid, states[eid])
            fx = _fx(e, eid.split(".")[0])
            inward = 1 if fx["x"] < 0.5 else -1
            assert d[0] * inward > 0.5 and d[2] > 0.75, eid  # in towards the room, well above the heads
            assert states[eid].dimmer > 0.5  # lit through the move
        after = float(e.beats[k + SURPRISE_HOLD_BEATS + 6])
        for eid in e.uplight_ids:
            assert _beam(e, eid, e.render(after)[1][eid])[2] > 0.999
    finally:
        e.surprise = None
