"""Light stands: a light bridge (a bar on two tripods) and a T-bar stand, the cheaper kind of truss."""

from __future__ import annotations

import pytest

from amadeus.rig import templates
from amadeus.rig import trusses as T


def test_a_bridge_stands_on_its_ends_and_a_tbar_on_its_middle():
    bridge = T.stand("b", "bridge", 3.0, 4.0, -0.8, 3.0)
    assert T.is_stand(bridge)
    assert T.stand_feet(bridge) == [pytest.approx((2.55, -0.8)), pytest.approx((5.45, -0.8))]
    tbar = T.stand("s", "tbar", 1.0, 1.0, -0.8, 2.5)
    assert T.stand_feet(tbar) == [(1.0, -0.8)]
    assert not T.is_stand(templates.rig("booth")["trusses"][0])


def test_fixtures_clamp_closer_to_a_tube_than_to_a_box_truss():
    box = templates.rig("booth")["trusses"][0]
    tube = T.stand("b", "bridge", 3.0, box["x_m"], box["y_m"], box["z_m"])
    for side, axis, sign in (("under", "z_m", -1), ("top", "z_m", 1), ("front", "y_m", 1)):
        on_box, on_tube = T.place({}, box, 0.0, 8.0, side), T.place({}, tube, 0.0, 8.0, side)
        start = box[axis]
        assert 0 < sign * (on_tube[axis] - start) < sign * (on_box[axis] - start)


def test_a_stand_goes_no_higher_or_lower_than_it_does():
    t = {"id": "s", "type": "tbar", "length_m": 1.2, "x_m": 1, "y_m": -1, "z_m": 4.2, "min_height_m": 1.6,
         "max_height_m": 3.5}  # fmt: skip
    assert T.normalise(t)["z_m"] == 3.5
    t["z_m"] = 0.5
    assert T.normalise(t)["z_m"] == 1.6
    del t["max_height_m"]  # only a lowest
    t["z_m"] = 0.5
    assert T.normalise(t)["z_m"] == 1.6


@pytest.mark.parametrize("template", ["stands", "bridge"])
def test_the_mobile_dj_templates_use_light_stands(template):
    rig = templates.rig(template, width=5.0, height=2.5)
    assert rig["trusses"] and all(T.is_stand(t) for t in rig["trusses"])
