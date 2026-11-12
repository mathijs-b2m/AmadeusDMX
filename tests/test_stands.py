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


def tbar_rig(fixture: str, n: int) -> dict:
    """Two 1.2 m T-bars left and right of the booth, and `n` fixtures of one model to mount."""
    rig = templates.rig("stands", width=5.0, height=2.5)
    for t in rig["trusses"]:
        t["length_m"] = 1.2
    rig["fixtures"] = [{"id": f"f{k}", "fixture": fixture, "universe": 1, "address": 1 + 20 * k} for k in range(n)]
    return rig


def test_a_tbar_carries_two_small_heads_with_room_to_swing():
    """A light stand's bar is short: its heads hang closer than under a box truss, but never housing to housing,
    and both stands carry the same, mirrored. What they have no room for stands on the floor."""
    from amadeus.rig import automount

    rig = tbar_rig("beamz/fuze75b-beam", 8)
    spots = automount.automount(rig)
    width = automount._housing(rig["fixtures"][0])
    on = {
        t["id"]: sorted(s["truss_pos_m"] for s in spots.values() if s.get("truss") == t["id"]) for t in rig["trusses"]
    }
    a, b = on.values()
    assert len(a) == len(b) == 2 and a == pytest.approx([-u for u in reversed(b)])  # mirrored
    assert a[0] == pytest.approx(-a[1]) and a[1] - a[0] >= width + 0.3  # room to swing
    assert sum(1 for s in spots.values() if not s.get("truss")) == 4  # the rest: on the floor, not squeezed in


def test_pars_go_side_by_side_on_the_stands():
    from amadeus.rig import automount

    rig = tbar_rig("cameo/flat-pro-18", 6)
    spots = automount.automount(rig)
    width = automount._housing(rig["fixtures"][0])
    for t in rig["trusses"]:
        us = sorted(s["truss_pos_m"] for s in spots.values() if s.get("truss") == t["id"])
        assert len(us) == 3 and us == pytest.approx([-u for u in reversed(us)])
        assert all(q - p >= width + automount.STAND_GAP for p, q in zip(us, us[1:]))


def test_a_stand_with_deco_truss_holds_its_fixtures_further_out_than_a_tube():
    bridge = T.stand("b", "bridge", 3.0, 4.0, -1.5, 3.0)
    assert not T.is_deco(bridge)
    deco = {**bridge, "bar": "deco"}
    assert T.is_deco(deco) and T.is_stand(deco) and T.stand_feet(deco) == T.stand_feet(bridge)
    assert not T.is_deco({"id": "t", "type": "quatro", "length_m": 3, "x_m": 4, "y_m": -1, "z_m": 3, "bar": "deco"})
    under = T.place({"id": "f"}, deco, 0.0, 8.0, "under")
    assert under["z_m"] == pytest.approx(3.0 - T.DECO_DROP) and T.DECO_DROP > T.TUBE_DROP
