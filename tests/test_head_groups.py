"""Head groups (amadeus/rig/groups.py): rows on the trusses stay whole, towers are real towers."""

from amadeus.rig import trusses as T
from amadeus.rig.groups import head_groups
from amadeus.rig.loader import load_rig_dict

W = 6.0
HEAD = "claypaky/sharpy"


def head(k: int, **place) -> dict:
    return {"id": f"h{k}", "fixture": HEAD, "universe": 1, "address": 1 + 20 * k, **place}


def bridge(tid: str, x: float, y: float = -1.4, rot: float = 0.0) -> dict:
    return {"id": tid, "type": "bridge", "length_m": 3.0, "x_m": x, "y_m": y, "z_m": 3.0, "rot_deg": rot}


def studio(rot: float = 0.0) -> dict:
    """Two light stands end to end over the DJ, four heads under each, with heads on the floor and on two totems
    right under them: the layout of the studio where the truss heads were cut up into towers."""
    left, right = bridge("left", 1.5, rot=-rot), bridge("right", 4.5, rot=rot)
    totems = [{"id": f"totem{i}", "type": "quatro", "vertical": True, "length_m": 1.5, "x_m": x, "y_m": -1.7,
               "z_m": 0.75} for i, x in ((1, 1.5), (2, 4.5))]  # fmt: skip
    fixtures, k = [], 0
    for t in (left, right):
        for u in (-1.0, -0.4, 0.4, 1.0):
            fixtures.append(T.place(head(k), t, u, W, "under"))
            k += 1
    for t in totems:
        fixtures.append(T.place(head(k), t, 1.5, W, "top"))
        k += 1
    for x in (0.15, 0.3, 0.7, 0.85):  # on the floor under the truss heads
        fixtures.append(head(k, x=x, y_m=-1.3, z_m=0.25, mount="floor"))
        k += 1
    return {"stage": {"width_m": W, "ceiling_m": 4.0}, "trusses": [left, right, *totems], "fixtures": fixtures}


def groups_of(rig: dict) -> dict[str, list[str]]:
    return {g["name"]: g["ids"] for g in head_groups(load_rig_dict(rig))}


def test_heads_on_two_trusses_end_to_end_are_one_row_not_towers_with_the_floor():
    g = groups_of(studio())
    assert not any(n.startswith("tower") for n in g), g
    overhead = [ids for ids in g.values() if set(ids) & {f"h{k}" for k in range(8)}]
    assert overhead == [[f"h{k}" for k in range(8)]]  # one line, left to right
    assert sorted(len(ids) for ids in g.values()) == [2, 4, 8]  # the totems a pair, the floor a row


def test_a_v_of_trusses_is_one_row():
    g = groups_of(studio(rot=20.0))
    assert sum(1 for ids in g.values() if set(ids) & {f"h{k}" for k in range(8)}) == 1


def test_rows_close_in_depth_join_and_rows_apart_stay_apart():
    near = [head(k, x=0.1 + 0.2 * k, y_m=-5.5 - 0.25 * (k % 2), z_m=0.6, mount="floor") for k in range(4)]
    assert len(groups_of({"stage": {"width_m": W}, "fixtures": near})) == 1
    apart = [head(k, x=0.1 + 0.2 * k, y_m=-0.5 - 0.6 * (k % 2), z_m=0.3, mount="floor") for k in range(4)]
    assert len(groups_of({"stage": {"width_m": W}, "fixtures": apart})) == 2


def test_a_real_tower_is_still_a_column():
    tower = {"id": "t", "type": "quatro", "vertical": True, "length_m": 4.0, "x_m": 0.5, "y_m": -1.0, "z_m": 2.0}
    fixtures = [T.place(head(k), tower, p, W, "front") for k, p in enumerate((0.8, 2.0, 3.2))]
    g = head_groups(load_rig_dict({"stage": {"width_m": W}, "trusses": [tower], "fixtures": fixtures}))
    assert [x["kind"] for x in g] == ["column"]


def test_a_totem_with_floor_heads_at_its_foot_is_no_tower_on_either_side():
    # the studio: one head up each totem, floor heads round its foot, standing a little nearer it on the right; that
    # right side was called a tower (and played a part the left didn't have)
    totems = [{"id": f"totem{i}", "type": "quatro", "vertical": True, "length_m": 1.5, "x_m": x, "y_m": -0.85,
               "z_m": 0.75} for i, x in ((1, 1.5), (2, 4.5))]  # fmt: skip
    fixtures = [T.place(head(0), totems[0], 1.5, W, "top"), T.place(head(1), totems[1], 1.5, W, "top")]
    fixtures += [
        head(2, x=0.22, y_m=-1.5, z_m=0.25, mount="floor"),
        head(3, x=0.29, y_m=-1.76, z_m=0.25, mount="floor"),
    ]
    fixtures += [head(4, x=0.70, y_m=-1.3, z_m=0.25, mount="floor"), head(5, x=0.76, y_m=-1.3, z_m=0.25, mount="floor")]
    g = head_groups(load_rig_dict({"stage": {"width_m": W}, "trusses": totems, "fixtures": fixtures}))
    assert all(x["kind"] == "row" for x in g), g
    assert sorted(len(x["ids"]) for x in g) == [2, 4]  # the totem heads a pair, the floor a row


def test_the_cells_of_one_motor_follow_their_middle_cell():
    from amadeus.engine.motion import MotionMixin

    units = {
        "l": (0.11, 0.17, 0.22),  # three heads on one yoke, stage left …
        "r": (0.78, 0.83, 0.89),  # … and its mirror twin on the right
        "b": (0.10, 0.15, 0.20, 0.25),  # a bar of four on the left: the middle cell nearer the centre
    }

    class Unit:
        heads = [{"id": f"{u}.{c}", "x": x} for u, xs in units.items() for c, x in enumerate(xs)]

        def _motor_owner(self, j):
            return self.heads[j]["id"].split(".")[0]

    lead = {o: Unit.heads[j]["id"] for o, j in MotionMixin._motor_leaders(Unit()).items()}
    assert lead == {"l": "l.1", "r": "r.1", "b": "b.2"}  # was the first cell: the outer end left, the inner right
