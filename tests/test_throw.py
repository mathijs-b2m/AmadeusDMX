"""Beams thrown over the crowd: never onto the floor at the stage's feet, off the side walls of a narrow hall
(geometry.throw_v, applied to every head's beams in MotionMixin._room_safe_v)."""

import math
from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig import geometry
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

LOOKS = [
    ("sync", "step_on_beat", "crowd"),
    ("mirror", "figure8", "crowd"),
    ("fan", "swing", "crowd"),
    ("cross", "step_on_beat", "crowd"),
    ("focus", "circle", "crowd"),
    ("wave", "tilt_wave", "crowd"),
    ("mirror", "sweep", "sky"),
]


def _first_hit(p, d, st):
    """(y, surface) where a beam first meets the floor or a side wall (None: neither, before the far wall)."""
    W, side = st["width_m"], geometry.room_side(st)
    cands = []
    if d[2] < -1e-3:
        cands.append((-p[2] / d[2], "floor"))
    if d[0] > 1e-3:
        cands.append(((W + side - p[0]) / d[0], "wall"))
    if d[0] < -1e-3:
        cands.append(((-side - p[0]) / d[0], "wall"))
    if not cands:
        return None
    t, surf = min(cands)
    return float(p[1] + d[1] * t), surf


@pytest.fixture(scope="module", params=["concert60", "small"])
def narrow(request):
    """A rig in a hall hardly wider than its stage and 16 m deep."""
    rig = load_rig(f"tests/sets/{request.param}.json")
    rig["stage"] = {**rig.get("stage", {}), "room_width_m": rig["stage"]["width_m"] + 0.2, "room_depth_m": 16.0}
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    return a, plan, Engine(a, plan, rig, real_output=False)


def test_beams_towards_the_crowd_land_over_it_not_by_the_stage(narrow):
    _, plan, e = narrow
    k = next(i for i, d in enumerate(plan) if d.section == "groove")
    st = e.stage
    floor_at, wall_at = geometry.throw_m(st), geometry.throw_m(st, wall=True)
    for f, m, aim in LOOKS:
        d = replace(plan[k], formation=f, movement=m, aim=aim, intensity=3)
        ts = np.linspace(d.start + 0.5, d.end - 0.5, 120)
        for j in range(len(e.heads)):
            p = np.asarray(e.head_pos[j], float)
            for v in e._head_dir_v(d, ts, j):
                el = math.degrees(math.asin(np.clip(v[2], -1, 1)))
                if v[1] <= 0 or el <= geometry.BACK_DOWN_DEG:  # the back guard's own beams
                    continue
                hit = _first_hit(p, v, st)
                if hit is None:
                    continue
                y, surf = hit
                if surf == "floor" and geometry.over_ground(p, st) >= 1.0:
                    assert y > floor_at - 0.3, (f, m, j, y)  # (the squeeze's last few cm)
                if surf == "wall":
                    assert y > min(floor_at, wall_at) - 0.5, (f, m, j, y)


def test_a_swing_past_the_limit_is_squeezed_not_clipped():
    st = {**geometry.DEFAULT_STAGE, "width_m": 6.0, "room_width_m": 6.2, "room_depth_m": 16.0}
    p = np.array([0.5, -1.2, 3.0])
    az = np.linspace(-90, 90, 361)
    d = np.stack([geometry.direction(a, -40) for a in az])
    out = geometry.throw_v(d, p, st)
    oaz = np.degrees(np.arctan2(out[:, 0], out[:, 1]))
    oel = np.degrees(np.arcsin(out[:, 2]))
    assert np.all(np.diff(oaz) > 0)  # still moves all the way: never frozen on the limit
    assert oaz.min() > -15 and oaz.max() < 45  # inwards, off the wall 10 cm beside it
    assert np.all(oel > -40)  # lifted to land out over the crowd
    guess = geometry.throw_v(d, p, {**st, "room_width_m": None})  # no hall width given: walls a guess, only lifted
    assert np.allclose(np.degrees(np.arctan2(guess[:, 0], guess[:, 1])), az)
