"""Auto-mount hangs a set the way a lighting tech would: no more on a truss than it carries at ease, twins alike and
mirrored, every model mirrored round the middle of the stage, nothing at an odd place."""

import json
from pathlib import Path

import pytest

from amadeus.library import fixtures as fxlib
from amadeus.rig import automount, store, templates, uplights
from amadeus.rig import trusses as T

SETS = sorted(Path("tests/sets").glob("*.json"))
BEAM, SPOT, WASH = "claypaky/sharpy", "chauvet/intimidator-spot-375z-irc", "martin/mac-aura"
BLINDER, PAR, BAR = "beamz/sb200-stage-blinder", "cameo/flat-pro-18", "chauvet/colorband-pix-m"


def fixtures(*groups: tuple[str, int]) -> list[dict]:
    out = []
    for model, n in groups:
        name = model.split("/")[1].split("-")[0]
        out += [{"id": f"{name}{k + 1}", "fixture": model, "universe": 1, "address": 1} for k in range(n)]
    return out


def mounted(rig: dict, ids: list[str] | None = None) -> dict:
    for fid, spot in automount.automount(rig, ids).items():
        f = next(f for f in rig["fixtures"] if f["id"] == fid)
        for k in store.PLACEMENT_KEYS:
            f.pop(k, None)
        f.pop(store.UNPLACED, None)
        f.update(spot)
    return rig


def on(rig: dict, truss: str, side: str = "under") -> list[tuple[float, str]]:
    return sorted((f["truss_pos_m"], f["fixture"]) for f in rig["fixtures"]
                  if f.get("truss") == truss and f.get("truss_side") == side)  # fmt: skip


def unmirrored(rig: dict) -> list[str]:
    """The fixtures with no fixture of their model at the mirrored place (round the middle of the stage)."""
    w = rig["stage"]["width_m"]
    at = [(f["fixture"], f["x"] * w, f["y_m"], f["z_m"], f["id"]) for f in rig["fixtures"]]
    return [p[4] for p in at if not any(q[0] == p[0] and abs(q[1] + p[1] - w) < 0.03 and abs(q[2] - p[2]) < 0.03
                                        and abs(q[3] - p[3]) < 0.03 for q in at)]  # fmt: skip


def bridges(turn: float = 20.0, **stage) -> dict:
    """Two 3 m light bridges left and right of the booth, turned in like a V, and a short totem under each."""
    trusses = [T.stand("left", "bridge", 3.0, 1.56, -1.24, 3.0), T.stand("right", "bridge", 3.0, 4.44, -1.24, 3.0)]
    trusses[0]["rot_deg"], trusses[1]["rot_deg"] = -turn, turn
    for k, x in enumerate((2.0, 4.0)):
        trusses.append({"id": f"totem{k + 1}", "type": "quatro", "length_m": 1.5, "x_m": x, "y_m": -1.75, "z_m": 0.75,
                        "vertical": True})  # fmt: skip
    return {"stage": {"width_m": 6.0, "ceiling_m": 3.5, **stage}, "trusses": trusses}


# ------------------------------------------------------------------------------------------------ how many


def test_a_truss_carries_no_more_than_it_does_at_ease():
    """Sixteen small heads and two 3 m bridges: four on each, the rest on the stage floor (not seven a bridge)."""
    rig = mounted({**bridges(turn=0.0), "fixtures": fixtures(("beamz/fuze75b-beam", 12))})
    for t in ("left", "right"):
        us = [u for u, _ in on(rig, t)]
        assert len(us) == 4 and all(b - a >= 0.75 for a, b in zip(us, us[1:]))
    assert sum(f["mount"] == "floor" for f in rig["fixtures"]) == 2  # (and one on top of each totem)


def test_heads_keep_the_room_their_housing_needs():
    rig = templates.rig("club", width=10.0)
    rig["fixtures"] = fixtures((BEAM, 40))
    mounted(rig)
    wide = automount._housing(rig["fixtures"][0])
    for t in rig["trusses"]:
        us = [u for u, _ in on(rig, t["id"])]
        assert us and all(b - a >= wide + 0.2 - 1e-3 for a, b in zip(us, us[1:]))  # closer together, never touching
        assert abs(us[0]) <= t["length_m"] / 2 and us == pytest.approx([-u for u in reversed(us)], abs=2e-3)


def test_a_pair_is_never_split():
    """Two heads on a stage with five places to hang them: side by side on one truss, not one here and one there."""
    rig = templates.rig("stage", width=8.0)
    rig["fixtures"] = fixtures((BEAM, 2))
    mounted(rig)
    a, b = rig["fixtures"]
    assert a["truss"] == b["truss"] and a["truss_pos_m"] == pytest.approx(-b["truss_pos_m"])


def test_a_model_stays_together_and_beams_hang_at_the_back():
    rig = templates.rig("club", width=10.0)
    rig["fixtures"] = fixtures((WASH, 4), (BEAM, 4))
    mounted(rig)
    assert {m for _, m in on(rig, "back")} == {BEAM} and {m for _, m in on(rig, "front")} == {WASH}


# ------------------------------------------------------------------------------------------------ symmetry


def test_twins_carry_the_same_at_mirrored_places():
    """Two bridges turned in like a V: what hangs on the one hangs on the other, mirrored; the blinders two each."""
    rig = mounted({**bridges(), "fixtures": fixtures((BEAM, 4), (SPOT, 2), (WASH, 2), (BLINDER, 4))})
    assert not unmirrored(rig)
    for side, n in (("under", 3), ("front", 2)):  # (the two washes stand on the totems)
        left, right = on(rig, "left", side), on(rig, "right", side)
        assert len(left) == len(right) == n
        assert [(round(-u, 2), m) for u, m in reversed(left)] == [(round(u, 2), m) for u, m in right]
    us = [u for u, _ in on(rig, "left")]
    assert us == pytest.approx([-u for u in reversed(us)], abs=2e-3)  # and each bar is even in itself


def test_trusses_that_mirror_each_other_are_found_as_twins():
    rig = bridges()
    pairs = [g for g in automount.twins(rig["trusses"], 6.0) if len(g) == 2]
    assert [[t["id"] for t in g] for g in pairs] == [["left", "right"], ["totem1", "totem2"]]
    apart = [T.stand("a", "bridge", 3.0, 3.0, 0.4, 3.0), T.stand("b", "bridge", 3.0, 3.0, -1.75, 3.0)]
    assert all(len(g) == 1 for g in automount.twins(apart, 6.0))  # one behind the other: no twins


@pytest.mark.parametrize("template", [t for t in templates.TEMPLATES])
@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_every_model_is_mirrored_round_the_middle_of_the_stage(path, template):
    """Every set in tests/sets on every template: each fixture has one of its model at the mirrored place. Only a
    model with an odd number has one that can't be (it stands in the middle where there is one)."""
    merged = json.loads(path.read_text(encoding="utf-8"))
    rig = templates.rig(template, width=10.0, height=5.0, screen=True)
    rig["fixtures"] = [{k: v for k, v in f.items() if k not in store.PLACEMENT_KEYS} for f in merged["fixtures"]]
    mounted(rig)
    assert all(f.get("mount") for f in rig["fixtures"])
    odd: dict[str, int] = {}
    for f in rig["fixtures"]:
        odd[f["fixture"]] = odd.get(f["fixture"], 0) ^ 1
    lone = unmirrored(rig)
    models = [next(f["fixture"] for f in rig["fixtures"] if f["id"] == i) for i in lone]
    assert all(odd[m] for m in models) and len(models) == len(set(models)), lone


def test_two_models_in_one_row_take_turns_mirrored():
    rig = templates.rig("booth", width=10.0)
    rig["fixtures"] = fixtures((BEAM, 4), (SPOT, 2), (WASH, 1))
    mounted(rig)
    row = [m for _, m in on(rig, "truss1")]
    assert row == [BEAM, SPOT, BEAM, WASH, BEAM, SPOT, BEAM]  # the odd one out in the middle


# ------------------------------------------------------------------------------------------------ where


def test_a_head_stands_on_top_of_a_short_totem():
    rig = mounted({**bridges(), "fixtures": fixtures((BEAM, 8), (WASH, 2))})
    tops = [f for f in rig["fixtures"] if f.get("truss", "").startswith("totem")]
    assert len(tops) == 2 and all(f["truss_side"] == "top" and f["mount"] == "stand" for f in tops)
    assert {f["fixture"] for f in tops} == {WASH}  # the pair, not two of the eight


def test_a_tall_tower_carries_one_on_top_and_more_down_its_front():
    rig = templates.rig("stage", width=10.0, height=5.0)
    rig["trusses"] = [t for t in rig["trusses"] if t.get("vertical")]
    rig["fixtures"] = fixtures((BEAM, 6))
    mounted(rig)
    for t in rig["trusses"]:
        mine = [f for f in rig["fixtures"] if f.get("truss") == t["id"]]
        assert sorted(f["truss_side"] for f in mine) == ["front", "front", "top"]
        assert all(f["z_m"] >= automount.HEAD_MIN_M for f in mine)
    assert not unmirrored(rig)


def test_nothing_stands_in_the_booth_or_behind_the_back_wall():
    """A small room with the booth at the stage's edge and its back wall 2 m behind it: the floor rows stay in
    front of that wall, and left and right of the DJ."""
    rig = bridges(room_back_m=2.0, dj_y_m=-0.2, dj_floor=True)
    rig["fixtures"] = fixtures((BEAM, 14), (PAR, 6), ("smoke-factory/data-ii", 2))
    if "smoke-factory/data-ii" not in fxlib.library():
        rig["fixtures"] = rig["fixtures"][:-2]
    mounted(rig)
    floor = [f for f in rig["fixtures"] if f["mount"] == "floor"]
    assert floor and all(-2.0 < f["y_m"] < 0 for f in floor)
    for f in floor:
        if fxlib.get(f["fixture"])["kind"] == "moving_head":
            assert abs(f["x"] * 6.0 - 3.0) >= automount.BOOTH_HALF_M  # not where the DJ stands
    assert not unmirrored(rig)


def test_tilting_bars_in_a_narrow_room_stand_by_its_walls():
    """They are wall uplighters there (rig/uplights.py): the same number left and right, along the room."""
    rig = bridges(room_width_m=6.2, room_depth_m=16.0)
    rig["fixtures"] = fixtures((BEAM, 4), (BAR, 4))
    mounted(rig)
    bars = [f for f in rig["fixtures"] if f["fixture"] == BAR]
    assert all(uplights.is_uplight(rig, f) for f in bars)
    assert sorted(round(f["x"] * 6.0, 2) for f in bars) == [0.2, 0.2, 5.8, 5.8] and not unmirrored(rig)
    wide = bridges()  # the walls far off: they are heads like the others
    wide["fixtures"] = fixtures((BAR, 2))
    assert not any(uplights.is_uplight(wide, f) for f in mounted(wide)["fixtures"])


def test_pars_hang_on_a_stand_only_where_they_clear_the_heads():
    rig = templates.rig("bridge", width=5.0, height=2.5)
    rig["fixtures"] = fixtures((BEAM, 2), (PAR, 4))
    mounted(rig)
    row = on(rig, "bridge")
    assert [m for _, m in row] == [BEAM, PAR, PAR, BEAM]  # two between the heads, the others on the floor
    for (a, ma), (b, mb) in zip(row, row[1:]):
        assert b - a >= (automount._housing({"fixture": ma}) + automount._housing({"fixture": mb})) / 2 + 0.05


def test_strobes_and_blinders_hang_on_the_front_truss_over_the_stage():
    """Not on the truss furthest out over the crowd."""
    rig = templates.rig("club", width=10.0)
    rig["trusses"].append({"id": "hall", "type": "quatro", "length_m": 8.0, "x_m": 5.0, "y_m": 9.0, "z_m": 5.0})
    rig["fixtures"] = fixtures(("martin/atomic-3000-led", 2), (BLINDER, 4), (BEAM, 6))
    mounted(rig)
    assert len(on(rig, "front", "front")) == 6 and not on(rig, "hall", "front")
    strobes = [u for u, m in on(rig, "front", "front") if m != BLINDER]
    blinders = [u for u, m in on(rig, "front", "front") if m == BLINDER]
    assert max(abs(u) for u in strobes) < min(abs(u) for u in blinders)  # strobes in the middle


def test_new_fixtures_take_mirrored_places_between_the_ones_that_hang():
    rig = templates.rig("club", width=10.0)
    rig["fixtures"] = fixtures((WASH, 6))
    mounted(rig)
    before = {f["id"]: dict(f) for f in rig["fixtures"]}
    rig["fixtures"] += [{"id": f"new{k}", "fixture": BEAM, "universe": 2, "address": 1, "_unplaced": {}}
                        for k in range(2)]  # fmt: skip
    mounted(rig, ["new0", "new1"])
    assert all(before[i] == f for i, f in ((f["id"], f) for f in rig["fixtures"]) if i in before)
    a, b = rig["fixtures"][-2:]
    assert a["truss"] == b["truss"] and a["truss_pos_m"] == pytest.approx(-b["truss_pos_m"])
    assert not unmirrored(rig)


# ------------------------------------------------------------------------------------------------ the arithmetic


def test_a_row_is_spread_evenly_and_clear_of_what_hangs_there():
    assert automount.spread(4, -1.5, 1.5, 0.75) == pytest.approx([-1.216, -0.405, 0.405, 1.216], abs=1e-3)
    assert automount.spread(9, -1.5, 1.5, 0.75) == automount.spread(4, -1.5, 1.5, 0.75)  # no more than fit
    busy = [(-1.0, -1.0, 1.0), (1.0, 1.0, 1.0)]  # two fixtures: the new ones between them and mirrored
    assert automount.spread(1, -4.0, 4.0, 0.75, busy) == [0.0]
    us = automount.spread(4, -4.0, 4.0, 0.75, busy)
    assert us == pytest.approx([-u for u in reversed(us)]) and all(min(abs(u - 1), abs(u + 1)) >= 0.75 for u in us)
    wings = automount.spread(4, -4.0, 4.0, 0.75, [(-1.5, 1.5, 0.5)])  # a stretch to keep clear: two each side
    assert [u < 0 for u in wings] == [True, True, False, False] and all(abs(u) >= 1.5 for u in wings)


def test_housings_of_different_widths_get_the_same_gap():
    us = automount.justify([0.2, 1.0, 0.2], -2.0, 2.0, 0.3)
    assert us[1] == pytest.approx(0.0) and us[0] == pytest.approx(-us[2])
    gaps = [us[1] - us[0] - 0.6, us[2] - us[1] - 0.6]
    assert gaps[0] == pytest.approx(gaps[1]) and gaps[0] >= 0.3
    assert automount.justify([1.0] * 5, -2.0, 2.0, 0.3) is None  # no room for that
