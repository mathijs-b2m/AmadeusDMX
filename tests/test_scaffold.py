"""Scaffold: the tube wall of a festival stage, fixtures on its ledgers at any height."""

from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig import automount, hangsheet, store, templates
from amadeus.rig import trusses as T
from amadeus.rig.groups import head_groups
from amadeus.rig.loader import load_rig_dict
from tests.synthetic import synthetic_analysis

W = 16.0


def festival_rig(heads: int = 24, screen: bool = True) -> dict:
    """The "festival" template with auto-mounted heads and pars."""
    rig = templates.rig("festival", width=W, height=9.0, screen=screen)
    rig["fixtures"] = [{"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1 + k // 20, "address": 1 + 20 * (k % 20)}
                       for k in range(heads)]  # fmt: skip
    rig["fixtures"] += [{"id": f"p{k}", "fixture": "cameo/flat-pro-18", "universe": 5, "address": 1 + 10 * k}
                        for k in range(4)]  # fmt: skip
    for fid, spot in automount.automount(rig).items():
        next(f for f in rig["fixtures"] if f["id"] == fid).update(spot)
    return rig


def test_a_scaffold_shares_its_size_into_bays_and_lifts():
    t = T.scaffold("w", 16.0, 9.0, 8.0, -7.0)
    assert T.is_scaffold(t) and not T.is_stand(t) and not T.is_loop(t)
    assert T.scaffold_bays(t) == 6 and T.scaffold_lifts(t) == 9
    assert T.lift_height(t, 9) == 9.0 and T.lift_height(t, 3) == 3.0
    assert T.nearest_lift(t, 4.2) == 4 and T.nearest_lift(t, 0.0) == 1 and T.nearest_lift(t, 30.0) == 9
    big = {**t, "bay_m": 4.0, "lift_m": 2.0, "z_m": 10.0}
    assert T.scaffold_bays(big) == 4 and T.scaffold_lifts(big) == 5


def test_a_fixture_clamps_to_a_ledger_of_the_front_frame():
    t = T.scaffold("w", 16.0, 9.0, 8.0, -7.0, depth=1.0)
    f = T.place({"truss_lift": 4}, t, 2.0, W, "under")
    assert f["truss"] == "w" and f["truss_lift"] == 4 and f["truss_pos_m"] == 2.0
    assert f["x"] * W == pytest.approx(10.0) and f["y_m"] == -6.5 and f["z_m"] == pytest.approx(4 - T.TUBE_DROP)
    assert f["mount"] == "hang"
    assert T.place({}, t, 0.0, W, "under")["truss_lift"] == 9  # new on it: the top ledger
    assert T.place({"truss_lift": 40}, t, 0.0, W)["truss_lift"] == 9  # the wall got lower: the highest there is
    front = T.place({"truss_lift": 4}, t, 0.0, W, "front")
    assert front["y_m"] == pytest.approx(-6.5 + T.TUBE_OUT) and front["mount_roll_deg"] == 90
    assert T.place({"truss_lift": 4}, t, 99.0, W)["truss_pos_m"] == 8.0  # no further than its end
    other = T.place(dict(f), {"id": "b", "length_m": 4, "x_m": 8, "y_m": -2, "z_m": 5}, 0.0, W)
    assert "truss_lift" not in other and other["truss"] == "b"  # off the scaffold: no lift left behind


def test_a_turned_scaffold_keeps_its_front_frame_to_the_front():
    t = T.scaffold("w", 8.0, 6.0, 2.0, -4.0, depth=1.0, rot=90.0)
    led = T.ledger(t, 3)
    assert (led["x_m"], led["y_m"]) == pytest.approx((1.5, -4.0))  # turned to face -x
    f = T.place({"truss_lift": 3}, t, 0.0, W, "under")
    assert f["x"] * W == pytest.approx(1.5, abs=0.01) and f["rot_deg"] == 90.0


def test_heads_on_a_scaffold_play_out_to_the_audience():
    t = T.scaffold("w", 16.0, 9.0, 8.0, -7.0)
    assert T.light_aim(t) == "audience"
    assert T.light_aim({**t, "aim": "down"}) == "down"


def test_the_template_puts_the_wall_behind_a_raised_outdoor_stage():
    rig = templates.rig("festival", width=W, height=9.0, screen=True)
    (t,) = rig["trusses"]
    assert T.is_scaffold(t) and t["z_m"] == 9.0 and t["length_m"] >= W
    assert rig["stage"]["deck_m"] == templates.FESTIVAL_DECK_M and rig["stage"]["deck_scaffold"]
    assert rig["stage"]["outdoor"] and t["y_m"] < -6


@pytest.mark.parametrize("width", [8.0, 12.0, 16.0, 24.0])
def test_auto_mount_fills_the_wall_mirrored_and_clear_of_the_led_wall(width):
    rig = templates.rig("festival", width=width, height=9.0, screen=True)
    rig["fixtures"] = [{"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1 + k // 20, "address": 1 + 20 * (k % 20)}
                       for k in range(16)]  # fmt: skip
    spots = automount.automount(rig)
    half, bottom, top = T.screen_rect(rig)
    on = [s for s in spots.values() if s.get("truss") == "wall"]
    assert on and len({s["truss_lift"] for s in on}) >= 2
    deck = rig["stage"]["deck_m"]
    for s in on:
        assert s["z_m"] > deck + 1.0
        behind = abs(s["truss_pos_m"]) < half and bottom - 0.2 < s["z_m"] < top + 0.2
        assert not behind, s
    for lift in {s["truss_lift"] for s in on}:  # every row is symmetric
        us = sorted(s["truss_pos_m"] for s in on if s["truss_lift"] == lift)
        assert us == pytest.approx([-u for u in reversed(us)], abs=0.01)


def test_floor_rows_stand_in_front_of_the_wall_not_behind_it():
    rig = festival_rig(heads=24)
    wall = rig["trusses"][0]
    for f in rig["fixtures"]:
        if not f.get("truss"):
            assert f["y_m"] > wall["y_m"] + T.scaffold_depth(wall) / 2


def test_a_fixture_already_on_a_ledger_keeps_its_spot():
    rig = festival_rig(heads=2)
    rig["fixtures"] = rig["fixtures"][:2]
    t = rig["trusses"][0]
    keep = rig["fixtures"][0]
    keep.update(T.place({"truss_lift": T.scaffold_lifts(t)}, t, 0.0, W, "under"))
    rig["fixtures"][1] = {k: v for k, v in rig["fixtures"][1].items() if k not in store.PLACEMENT_KEYS}
    spot = automount.automount(rig, [rig["fixtures"][1]["id"]])[rig["fixtures"][1]["id"]]
    if spot.get("truss_lift") == keep["truss_lift"]:
        assert abs(spot["truss_pos_m"] - keep["truss_pos_m"]) >= automount.MIN_SPACING["head"]


def test_a_ledger_with_three_heads_is_a_row_and_side_stacks_are_columns():
    rig = templates.rig("festival", width=W, height=9.0)
    t = rig["trusses"][0]
    fixtures = []
    grid = [(9, u) for u in (-5, -3, -1, 1, 3, 5)] + [(8, u) for u in (-5, -3, -1, 1, 3, 5)]
    grid += [(lift, u) for lift in (3, 4, 5) for u in (-7, 7)]
    for k, (lift, u) in enumerate(grid):
        f = {"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1 + k // 20, "address": 1 + 20 * (k % 20),
             "truss_lift": lift}  # fmt: skip
        fixtures.append(T.place(f, t, float(u), W, "under"))
    rig["fixtures"] = fixtures
    groups = head_groups(load_rig_dict(rig))
    rows = [g for g in groups if g["kind"] == "row"]
    cols = [g for g in groups if g["kind"] == "column"]
    assert sorted(len(g["ids"]) for g in rows) == [6, 6]
    assert sorted(len(g["ids"]) for g in cols) == [3, 3] and {g["name"] for g in cols} == {"tower left", "tower right"}


def test_the_hang_sheet_says_which_lift():
    rig = festival_rig()
    lay = hangsheet.layout(rig)
    st = next(s for s in lay["structures"] if s["id"] == "wall")
    assert st["kind"] == "scaffold" and st["ends"]
    assert all(r["where"].startswith("lift ") for r in st["fixtures"])
    assert [r["lift"] for r in st["fixtures"]] == sorted((r["lift"] for r in st["fixtures"]), reverse=True)
    html = hangsheet.html(rig, "set", "rig")
    assert "scaffold" in html and 'class="wall"' in html


def test_a_show_plays_on_it_without_shining_back_through_the_wall():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    e = Engine(a, plan, load_rig_dict(festival_rig()), real_output=False)
    on_wall = [j for j, aim in enumerate(e.truss_aim) if aim == "audience"]
    assert on_wall
    for d in plan[:: max(1, len(plan) // 8)]:
        for j in on_wall:
            v = e._head_dir_v(d, np.array([d.start + 1.0]), j)[0]
            assert v[1] > -0.25, (d.section, j, v)  # out of the wall, not back through it
