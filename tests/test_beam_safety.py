"""Beam safety: risk group 2/3 fixtures stay dark with real lights, and beams never all meet in one spot."""

from dataclasses import replace

import numpy as np
import pytest

from decisive.director import RuleDirector, direct
from decisive.engine import Engine, motion
from decisive.library import fixtures as fxlib
from decisive.rig.loader import load_rig
from tests.synthetic import synthetic_analysis


@pytest.mark.parametrize(
    "key, risky",
    [("claypaky/sharpy", True), ("robe/pointe", True), ("beamz/fuze75b-beam", False), ("dts/katana", False),
     ("martin/mac-encore-performance", False), ("martin/mac-aura", False)],
)  # fmt: skip
def test_unrated_fixtures_are_estimated_from_their_beam(key, risky):
    assert fxlib.high_risk(fxlib.get(key)) is risky


def test_a_risk_group_rating_decides_when_known():
    def rated(key, rg):
        defn = fxlib.get(key)
        return {**defn, "physical": {**defn["physical"], "risk_group": rg}}

    assert not fxlib.high_risk(rated("claypaky/sharpy", 1))
    assert fxlib.high_risk(rated("beamz/fuze75b-beam", 2))
    assert fxlib.high_risk(rated("beamz/fuze75b-beam", 3))


@pytest.fixture(scope="module")
def plan_and_rig():
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(), verbose=False), load_rig("tests/sets/showcase.json")


def test_high_risk_fixtures_stay_dark_only_with_real_lights(plan_and_rig):
    a, plan, rig = plan_and_rig
    sim, real = Engine(a, plan, rig), Engine(a, plan, rig, real_output=True)
    assert not sim.dark_high_risk and real.dark_high_risk
    risky = set(real.dark_high_risk)
    lit_sim = lit_real = lit_other = 0.0
    for t in np.arange(plan[0].start, plan[-1].end, 0.5):
        s, r = sim.render(float(t))[1], real.render(float(t))[1]
        lit_sim += sum(s[h].dimmer for h in risky)
        lit_real += sum(max(r[h].dimmer, r[h].white) for h in risky)
        lit_other += sum(r[e["id"]].dimmer for e in real.heads if e["id"] not in risky)
    assert lit_sim > 0 and lit_real == 0 and lit_other > 0  # the visualiser shows them; the rest plays on


def test_focus_spreads_the_beams_instead_of_one_spot(plan_and_rig):
    a, plan, rig = plan_and_rig
    e = Engine(a, plan, rig)
    d = replace(plan[0], formation="focus", aim="crowd")
    t = np.array([(d.start + d.end) / 2])
    spots = []
    for j, p in enumerate(e.head_pos):  # where each beam passes the focus distance
        out = e._head_dir_v(d, t, j)[0]
        spots.append(p + out * np.linalg.norm(np.mean(e.head_pos, axis=0) - p + 3.0))
    spots = np.array(spots)
    assert np.ptp(spots[:, 0]) > 0.8  # spread out across…
    pts = motion.focus_spread(np.zeros(3), np.array([0.0, 1.0, 0.0]), 1.0, 0.0)
    assert np.isclose(np.linalg.norm(pts), motion.FOCUS_SPREAD_M / 2)  # …about 1.5 m wide
