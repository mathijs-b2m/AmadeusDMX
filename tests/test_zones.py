import numpy as np

from decisive.engine import zones

WALL = {
    "id": "w",
    "kind": "avoid",
    "shape": "rect",
    "center": [6, 10, 3],
    "size": [4, 4],
    "rot_deg": 0,
    "tilt_deg": 0,
    "margin_deg": 2,
    "enabled": True,
    "applies": "auto",
}
STAGE = {"width_m": 12, "room_depth_m": 20, "ceiling_m": 8}


def rig(*zs):
    return {"stage": STAGE, "zones": list(zs)}


def test_a_beam_at_the_wall_hits_it():
    z = zones.Zone(WALL)
    pos = np.array([[6.0, 0.0, 3.0]])
    assert z.hit(pos, np.array([[0.0, 1.0, 0.0]]))[0] < 20  # straight at it
    assert np.isinf(z.hit(pos, np.array([[1.0, 0.0, 0.0]]))[0])  # sideways: misses


def test_filter_turns_beams_away_from_avoid_zones():
    zs = zones.Zones(rig(WALL))
    pos = np.array([6.0, 0.0, 3.0])
    d = np.array([[0.0, 1.0, 0.0], [0.6, 0.8, 0.0]])
    out = zs.filter(pos, d)
    assert not zs.crossing(pos, out).any()


def test_disabled_zones_are_ignored():
    assert not zones.Zones(rig({**WALL, "enabled": False})).avoid
