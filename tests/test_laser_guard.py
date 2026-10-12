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
