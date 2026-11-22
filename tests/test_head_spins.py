"""Heads never spin a whole turn for a small change of aim: past the end of the tilt, or across the front of a head
whose home is at an end stop of its pan."""

import numpy as np

from amadeus.rig import geometry

MINI = {"physical": {"pan_deg": 540, "tilt_deg": 180}}  # a 540° head
HUNG_AT_END = {"mount": "hang", "pan_home_deg": 540}  # calibrated with its front at DMX 255: front again at 180°


def _unit(*v):
    d = np.array(v, float)
    return d / np.linalg.norm(d)


def test_an_aim_just_past_the_tilt_keeps_the_pan_on_its_turn():
    # a tilt wave at the crowd: the beam a little under the horizon, then a little over it (out of a hung head's reach)
    below = geometry.ik(HUNG_AT_END, MINI, _unit(0.13, 0.98, -0.14), None)
    over = geometry.ik(HUNG_AT_END, MINI, _unit(0.14, 0.99, 0.03), below)
    assert abs(over[0] - below[0]) < 30  # was a whole turn (pan 0.347 ↔ 1.0 on every beat)
    back = geometry.ik(HUNG_AT_END, MINI, _unit(0.13, 0.98, -0.14), over)
    assert abs(back[0] - below[0]) < 30


def test_a_head_homed_at_its_end_stop_starts_on_the_middle_turn():
    front = geometry.ik(HUNG_AT_END, MINI, _unit(0.0, 0.97, -0.25), None)
    assert abs(front[0] - -360) < 5  # front on the turn with room either side, not at the stop (0°)


def test_a_beam_crossing_the_front_moves_only_a_little():
    prev = geometry.ik(HUNG_AT_END, MINI, _unit(-0.14, 0.99, -0.03), None)
    for x in (-0.1, -0.05, 0.0, 0.04, 0.1, 0.15, 0.04, -0.14):  # side to side across the front, as a sway does
        nxt = geometry.ik(HUNG_AT_END, MINI, _unit(x, 0.97, -0.25), prev)
        assert abs(nxt[0] - prev[0]) < 45 and abs(nxt[1] - prev[1]) < 45
        prev = nxt


def test_a_head_homed_in_the_middle_starts_where_it_did():
    mid = {"mount": "hang"}  # home 270°: the middle already
    assert abs(geometry.ik(mid, MINI, _unit(0.0, 0.97, -0.25), None)[0]) < 5
