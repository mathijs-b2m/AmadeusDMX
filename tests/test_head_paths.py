"""Head paths: a path that comes back is drawn another way each time, and the paths beyond the classic few."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.director.rules import RULE_LOOKS
from amadeus.director.vocabulary import MOVEMENTS
from amadeus.engine import Engine
from amadeus.engine import motion as M
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

RIGS = sorted(p.stem for p in Path("tests/sets").glob("*.json"))
NEW = ("pendulum", "spiral", "rose", "knot", "scissor", "zigzag")
SHAPED = ("sweep", "nod", "circle", "figure8", "step_on_beat", "bounce", "swing") + NEW


@pytest.fixture(scope="module")
def track():
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(), verbose=False)


@pytest.fixture(scope="module")
def engine(track):
    a, plan = track
    return Engine(a, list(plan), load_rig("tests/sets/concert60.json"), real_output=False)


def _trace(e, m, var, beats=32.0, alt=1.0):
    e._reach_uv = e.reach_uv[0]["crowd"]
    pos = np.arange(0, beats, 0.05)
    return np.stack(e._shape_v(m, pos, 0, 1.0, 0, var, alt))


def test_every_path_is_one_the_directors_can_name():
    names = {n for n, _ in MOVEMENTS}
    assert set(NEW) <= names
    assert {look[4] for looks in RULE_LOOKS.values() for look in looks} <= names
    assert set(NEW) <= {look[4] for looks in RULE_LOOKS.values() for look in looks}  # the rules play them all


@pytest.mark.parametrize("m", SHAPED)
def test_a_path_that_comes_back_is_drawn_another_way(engine, m):
    traces = [_trace(engine, m, var) for var in range(4)]
    assert all(np.isfinite(t).all() for t in traces)
    assert not np.allclose(traces[0], traces[1], atol=0.02)


@pytest.mark.parametrize("m", ("sweep", "circle", "figure8", "pendulum", "spiral", "rose", "knot", "scissor"))
def test_no_drawing_is_smaller_than_the_path(engine, m):
    """Variety never by shrinking: every drawing still reaches the full swing on its main axis."""
    for var in range(12):
        u, v = _trace(engine, m, var)
        assert max(np.abs(u).max(), np.abs(v).max()) > 0.95, var
        assert np.abs(u).max() <= 1.01 and np.abs(v).max() <= 1.41  # (a line above the middle: up to 1.4)


def test_step_paths_keep_their_motor_sized_moves(engine):
    for m in ("step_on_beat", "bounce", "swing", "zigzag"):
        for var in range(4):
            u, v = _trace(engine, m, var)
            assert np.ptp(u) + np.ptp(v) > 0.3, (m, var)


def test_each_return_of_a_path_gets_the_next_drawing_and_a_held_look_keeps_it(track):
    _, plan = track
    looks = ("ice", "fire", "neon")
    plan = [replace(d, movement="circle", movement2="sweep", palette=looks[i]) for i, d in enumerate(plan[:3])]
    plan.append(replace(plan[2], phrase=plan[2].phrase + 1, start=plan[2].end, end=plan[2].end + 8))  # held
    var = M.path_variants(plan, "a.wav")
    circles = [var[(d.phrase, "circle")] for d in plan]
    assert circles[:3] == [circles[0], circles[0] + 1, circles[0] + 2]
    assert circles[3] == circles[2]


def test_the_scissor_crosses_its_neighbours(engine, track):
    _, plan = track
    d = replace(plan[2], movement="scissor", formation="sync", grouping="unison", aim="crowd", dynamics="steady")
    ts = np.arange(d.start + 1, d.end - 1, 0.05)
    row = sorted(range(len(engine.heads)), key=lambda j: engine.head_pos[j][0])
    az = [np.degrees(np.arctan2(*engine._head_dir_v(d, ts, j)[:, :2].T)) for j in row[:4]]
    vel = [np.diff(a) for a in az]
    for j in range(3):
        if np.ptp(az[j]) > 10 and np.ptp(az[j + 1]) > 10:
            idx = engine._role(d, row[j])["idx"], engine._role(d, row[j + 1])["idx"]
            if (idx[0] - idx[1]) % 2:
                assert np.corrcoef(vel[j], vel[j + 1])[0, 1] < 0  # one goes left as the other goes right


def test_the_pendulum_lands_on_the_one(engine):
    u, _ = _trace(engine, "pendulum", 0, beats=16.0)
    pos = np.arange(0, 16.0, 0.05)
    for bar in (4, 8, 12):
        at = np.argmin(np.abs(pos - bar))
        assert abs(abs(u[at]) - 1) < 1e-6  # at the end of its swing as the bar starts…
        assert abs(abs(u[at + int(0.15 * 4 / 0.05)]) - 1) < 1e-6  # …and hangs there a moment
        assert abs(u[at + int(0.6 * 4 / 0.05)]) < 0.9  # …then swings through


@pytest.mark.parametrize("rig_name", RIGS)
def test_every_new_path_plays_on_every_rig(track, rig_name):
    a, plan = track
    e = Engine(a, list(plan), load_rig(f"tests/sets/{rig_name}.json"), real_output=False)
    if not e.heads:
        pytest.skip("no moving heads")
    d0 = plan[2]
    ts = np.arange(d0.start + 1, d0.end - 1, 0.1)
    for m in NEW:
        for f in ("sync", "mirror", "wave", "fan", "focus", "cross"):
            d = replace(d0, movement=m, formation=f, grouping="unison", aim="crowd", dynamics="steady", intensity=2)
            for j in range(0, len(e.heads), max(1, len(e.heads) // 6)):
                dirs = e._head_dir_v(d, ts, j)
                assert np.isfinite(dirs).all()
                assert np.allclose(np.linalg.norm(dirs, axis=1), 1, atol=1e-6)
                assert np.ptp(dirs, axis=0).max() > 0.02, (m, f, j)  # it moves
