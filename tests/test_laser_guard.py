"""The laser guard: with real lights, lasers stay dark without a laser zone; with one, no beam enters it."""

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis


def engine(set_name: str, real_output: bool) -> Engine:
    rig = load_rig(f"tests/sets/{set_name}.json")
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    return Engine(a, plan, rig, real_output=real_output)


@pytest.fixture(scope="module")
def times():
    a = synthetic_analysis()
    return np.arange(0, a.duration - 0.1, 0.5)


def test_real_lights_without_a_laser_zone_keep_lasers_dark(times):
    eng = engine("concert60", real_output=True)
    lasers = [e["id"] for e in eng.lasers]
    for t in times:
        _, states = eng.render(float(t))
        assert all(states[i].dimmer == 0 and states[i].white == 0 for i in lasers)


def test_the_visualiser_alone_shows_lasers_without_zones(times):
    eng = engine("concert60", real_output=False)
    ids = {e["id"] for e in eng.lasers}
    lit = sum(any(s.dimmer > 0.05 for i, s in eng.render(float(t))[1].items() if i in ids) for t in times)
    assert lit > 0


def test_no_beam_enters_a_laser_zone(times):
    eng = engine("laser-zones", real_output=True)
    for t in times:
        _, states = eng.render(float(t))
        for e, info in zip(eng.lasers, eng.laser_info):
            s = states[e["id"]]
            if max(s.dimmer, s.white) <= 0.05 or s.fx in ("off", "open"):
                continue
            dirs = eng._laser_dirs(s, info, float(t))
            assert eng.zones.laser_violation(info["pos"], dirs) is None


def test_a_spinning_pattern_is_checked_over_its_turn_at_once():
    """The guard checks a spinning pattern at every TURN rotation in one go: the same beams as one rotation at
    a time, for every shape."""
    from amadeus.engine.lasers import LASER_SHAPES, TURN
    from amadeus.engine.state import State

    eng = engine("laser-zones", real_output=True)
    info = eng.laser_info[0]
    for fx in LASER_SHAPES:
        s = State(fx=fx, size=0.6, pan=0.3, tilt=0.7, spin=0.4)
        turned = eng._laser_dirs_turned(s, info, 12.3, TURN)
        one_by_one = np.stack([eng._laser_dirs(s, info, 12.3, rot=a) for a in TURN])
        assert turned.shape == one_by_one.shape and np.array_equal(turned, one_by_one), fx


def test_the_laser_guard_keeps_a_big_rig_in_time():
    """Ten lasers the guard has to raise, shrink or blank, every frame: well inside one 40 fps frame."""
    import time

    eng = engine("concert60", real_output=False)
    _, states = eng.render(30.0)
    eng.laser_info = [{**info, "min_el": 89.0} for info in eng.laser_info]  # nothing is safe: raise, shrink, blank
    best = float("inf")
    for _ in range(5):  # the best of five: what the guard costs, not what the other tests on this computer do
        for e in eng.lasers:  # every laser spinning low, where the guard works hardest
            s = states[e["id"]]
            s.fx, s.dimmer, s.white, s.size, s.tilt, s.spin = "fan", 1.0, 1.0, 1.0, 0.0, 0.5
        t0 = time.perf_counter()
        eng._laser_guard(states, 30.0)
        best = min(best, time.perf_counter() - t0)
        assert all(states[e["id"]].dimmer == 0 for e in eng.lasers)
    assert best < 0.02  # was ~47 ms: the light loop fell behind the music
