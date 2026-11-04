"""Looks where all the beams meet (focus, cross) don't meet on the DJ, who stands in the middle of the rig. A single
beam sweeping over them in another look is fine."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine, motion
from amadeus.rig import geometry
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis
from tests.test_beams_clear import _bridge_rig

RIGS = sorted(p.stem for p in Path("tests/sets").glob("*.json")) + ["bridge"]
FACE_M = 0.5  # a beam passing this close is in the DJ's face


@pytest.fixture(scope="module")
def track():
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(), verbose=False)


def _on_the_dj(e: Engine, d, ts) -> np.ndarray:
    """Share of the heads with their beam in the DJ's face, per moment."""
    pos = np.array(e.head_pos)
    dirs = np.stack([e._head_dir_v(d, ts, j) for j in range(len(pos))], axis=1)
    v = e.dj_head - pos
    s = (dirs * v).sum(axis=2)
    off = np.linalg.norm(v - s[..., None] * dirs, axis=2)
    return ((s > 0.3) & (off < FACE_M)).mean(axis=1)


@pytest.mark.parametrize("rig_name", RIGS)
def test_the_beams_dont_meet_on_the_dj(track, rig_name):
    a, plan = track
    rig = _bridge_rig() if rig_name == "bridge" else load_rig(f"tests/sets/{rig_name}.json")
    e = Engine(a, list(plan), rig, real_output=False)
    if len(e.heads) < 3:
        pytest.skip("too few heads to meet anywhere")
    shares = []
    for d0 in e.plan[:6]:
        ts = np.arange(d0.start + 0.1, d0.end, 0.25)
        for aim in ("stage", "crowd", "sky"):
            for f in ("focus", "cross"):
                for m in ("sweep", "circle", "none"):
                    d = replace(d0, aim=aim, formation=f, movement=m, grouping="unison", dynamics="steady")
                    shares.append(_on_the_dj(e, d, ts))
    x = np.concatenate(shares)
    assert (x >= 0.3).mean() < 0.005, "a third of the heads on the DJ"
    assert (x >= 0.15).mean() < 0.05


def test_a_beam_clear_of_the_dj_is_left_alone_and_one_on_them_goes_just_past():
    head, dj = np.array([0.0, 0.0, 5.0]), np.array([0.0, -4.0, 2.0])
    aimed = (dj - head) / 5.0
    wide = np.array([[0.6, 0.0, -0.8]])
    assert np.array_equal(motion.clear_of_dj(head, wide, dj), wide)
    turned = motion.clear_of_dj(head, aimed[None], dj)[0]
    s = (dj - head) @ turned
    assert np.linalg.norm(dj - head - s * turned) == pytest.approx(motion.DJ_CLEAR_M, abs=0.05)
    assert turned[1] > aimed[1] or turned[2] > aimed[2]  # up and towards the audience
    behind = -aimed[None]  # shining away from them
    assert np.array_equal(motion.clear_of_dj(head, behind, dj), behind)


def test_the_djs_head_is_where_the_booth_is_drawn():
    def at(**stage):
        return geometry.dj_head({"stage": {"width_m": 6, **stage}}, [-1.0], 8)

    assert at().tolist() == pytest.approx([3, -3.8, 2.57])  # a big rig: on the riser
    assert at(dj_floor=True)[2] == pytest.approx(1.62)  # no riser and no deck: on the floor
    assert at(room_back_m=2.5).tolist() == pytest.approx([3, -1.6, 2.57])  # in front of a back wall the rig fixes
    small = geometry.dj_head({"stage": {"width_m": 3}}, [-0.5], 2)
    assert small.tolist() == pytest.approx([1.5, -2.2, 1.62])
