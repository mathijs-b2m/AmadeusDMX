import numpy as np

from amadeus.engine import zones

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


def test_a_sweep_turned_into_a_keep_in_zone_keeps_moving():
    """A head behind a keep-in zone, sweeping where the zone doesn't reach: the whole sweep is turned in, its
    shape kept (turning each direction just far enough in would land them all on one spot of the edge)."""
    floor = {"id": "f", "kind": "keep_in", "shape": "box", "center": [6, 9.5, 2.9], "size": [14, 18, 6.8],
             "rot_deg": 0, "tilt_deg": 0, "margin_deg": 2, "enabled": True, "applies": "auto"}  # fmt: skip
    zs = zones.Zones({"stage": {**STAGE, "ceiling_m": 9, "room_depth_m": 25}, "zones": [floor]})
    pos = np.array([6.0, -5.75, 0.6])  # on the floor, behind the zone
    az = np.radians(np.linspace(-25, 25, 21))
    el = np.radians(14.0)  # up over the crowd: lands beyond the zone
    d = np.stack([np.cos(el) * np.sin(az), np.cos(el) * np.cos(az), np.full_like(az, np.sin(el))], axis=1)
    out = zs.filter(pos, d)
    assert all(zs._inside(z, pos, out).all() for z in zs.keep_in)  # inside…
    spread = np.degrees(np.arccos(np.clip(out @ out.T, -1, 1))).max()
    assert spread > 20  # …and still a sweep (each turned in on its own: about 2°)
