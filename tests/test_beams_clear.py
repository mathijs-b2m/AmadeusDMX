"""Beams aimed back at the stage play the room, not the rig: the back guard turned them sideways, about level along
the rig, every head straight into the fixtures beside it. Now they turn steep (down onto the floor near the rig, up),
or sideways only where that is the clear way (a tower)."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig.loader import load_rig, load_rig_dict
from tests.synthetic import synthetic_analysis

RIGS = sorted(p.stem for p in Path("tests/sets").glob("*.json")) + ["bridge"]
NEAR_M = 0.5  # a beam passing this close to another head shines into it
MAX_SHARE = 0.15  # (a few, for a moment: a beam sweeping past a neighbour)


def _bridge_rig() -> dict:
    """A mobile DJ: five heads on a light bridge, two on each T-bar stand beside it, six on the floor in front."""
    W, fx = 8.0, []

    def head(**p):
        k = len(fx)
        fx.append({"id": f"h{k}", "fixture": "beamz/fuze75b-beam", "mode": "12ch", "universe": 1,
                   "address": 1 + 12 * k, **p})  # fmt: skip

    for k in range(5):
        head(x=(W / 2 - 1.2 + 0.6 * k) / W, y_m=-0.8, z_m=3.0, mount="hang")
    for x in (0.3, 0.9, 7.1, 7.7):
        head(x=x / W, y_m=-0.3, z_m=3.6, mount="hang")
    for k in range(6):
        head(x=(2.0 + 0.8 * k) / W, y_m=-0.5 + 0.2 * (k % 2), z_m=0.4, mount="floor")
    return load_rig_dict({"stage": {"width_m": W, "ceiling_m": 7, "room_depth_m": 15, "eye_safety": False},
                          "fixtures": fx})  # fmt: skip


@pytest.fixture(scope="module")
def track():
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(), verbose=False)


def _into_others(pos: np.ndarray, dirs: np.ndarray) -> float:
    """Share of the heads whose beam passes close by another head (0.5 to 10 m along it)."""
    hit = 0
    for j in range(len(pos)):
        v = pos - pos[j]
        s = v @ dirs[j]
        near = (s > NEAR_M) & (s < 10) & (np.linalg.norm(v - s[:, None] * dirs[j], axis=1) < NEAR_M)
        near[j] = False
        hit += bool(near.any())
    return hit / len(pos)


@pytest.mark.parametrize("rig_name", RIGS)
def test_aimed_at_the_stage_the_heads_dont_shine_into_each_other(track, rig_name):
    a, plan = track
    rig = _bridge_rig() if rig_name == "bridge" else load_rig(f"tests/sets/{rig_name}.json")
    e = Engine(a, list(plan), rig, real_output=False)
    if len(e.heads) < 2:
        pytest.skip("fewer than two moving heads")
    pos, d0 = np.array(e.head_pos), e.plan[3]
    ts = np.arange(d0.start + 4, d0.end, 1.0)
    shares = {}
    for f in ("sync", "mirror", "wave", "fan", "focus", "cross"):
        for grouping in ("unison", "per_group"):
            d = replace(d0, aim="stage", formation=f, movement="sweep", grouping=grouping, dynamics="steady")
            dirs = np.stack([e._head_dir_v(d, ts, j) for j in range(len(e.heads))], axis=1)
            shares[f, grouping] = float(np.mean([_into_others(pos, dirs[k]) for k in range(len(ts))]))
    assert np.mean(list(shares.values())) <= MAX_SHARE, shares
    if rig_name == "bridge":  # the mobile DJ it was seen on: the plain looks keep every beam clear
        assert all(v <= 0.05 for (f, _), v in shares.items() if f in ("sync", "mirror", "wave")), shares
