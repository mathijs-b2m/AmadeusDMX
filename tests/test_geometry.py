import numpy as np
import pytest

from decisive.library import fixtures as fxlib
from decisive.rig import geometry
from decisive.rig.loader import load_rig


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
