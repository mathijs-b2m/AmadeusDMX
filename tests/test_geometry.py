import numpy as np
import pytest

from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry
from amadeus.rig.loader import load_rig


@pytest.fixture(scope="module")
def head():
    rig = load_rig("tests/sets/showcase.json")
    e = next(e for e in rig["elements"] if e["kind"] == "head")
    fx = next(f for f in rig["fixtures"] if f["id"] == e["fixture"])
    return fx, fxlib.get(fx["fixture"])


@pytest.mark.parametrize("rot", [0, 45, 180])
@pytest.mark.parametrize("roll", [0, 90, 180, 270])
def test_ik_inverts_fk(head, rot, roll):
    fx, defn = head
    fx = {**fx, "rot_deg": rot, "mount_roll_deg": roll}
    rng = np.random.default_rng(1)
    for pan, tilt in rng.uniform(0.05, 0.95, (40, 2)):
        d = geometry.fk(fx, defn, pan, tilt)
        assert np.isclose(np.linalg.norm(d), 1.0)
        phi, theta = geometry.ik(fx, defn, d, None)
        back = geometry.fk(fx, defn, *geometry.to_dmx(fx, defn, phi, theta))
        assert np.allclose(back, d, atol=1e-6)


def test_beams_stay_off_the_ceiling_and_never_shine_back_at_the_dj():
    import numpy as np

    from amadeus.rig import geometry as g

    room = {**g.DEFAULT_STAGE, "ceiling_m": 2.6, "room_depth_m": 4.0}
    up, back, back_down, crowd = (
        g.direction(0, 60),
        g.direction(170, -20),
        g.direction(180, -70),
        g.direction(30, -30),
    )
    out = g.room_safe_v(np.array([up, back, back_down, crowd]), (0, -1, 2.2), room)
    assert np.degrees(np.arcsin(out[0, 2])) < 3  # a living room: about level, not onto the ceiling
    assert out[1, 1] >= -g.BACK_Y - 1e-9  # not back at the DJ
    assert np.allclose(out[2], back_down) and np.allclose(out[3], crowd)  # steeply down, and onto the crowd: fine
    free = {**room, "ceiling_guard": False, "back_guard": False}
    assert np.allclose(g.room_safe_v(np.array([up, back]), (0, -1, 2.2), free), [up, back])  # switched off
