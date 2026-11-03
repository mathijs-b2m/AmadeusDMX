"""Carré: a rectangle of truss standing on its own four legs, played round like a full ring."""

import math
from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig import automount, hangsheet, templates
from amadeus.rig import trusses as T
from amadeus.rig.groups import head_groups
from amadeus.rig.loader import load_rig_dict
from tests.synthetic import synthetic_analysis

HEADS = 8


def carre_rig() -> dict:
    """The "carre" template with auto-mounted heads, and pars on top of it."""
    rig = templates.rig("carre", width=8.0)
    rig["fixtures"] = [{"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1, "address": 1 + 20 * k}
                       for k in range(HEADS)]  # fmt: skip
    rig["fixtures"] += [{"id": f"p{k}", "fixture": "cameo/flat-pro-18", "universe": 2, "address": 1 + 10 * k}
                        for k in range(4)]  # fmt: skip
    for fid, spot in automount.automount(rig).items():
        next(f for f in rig["fixtures"] if f["id"] == fid).update(spot)
    t = rig["trusses"][0]
    for k, f in enumerate(f for f in rig["fixtures"] if f["id"].startswith("p")):
        T.place(f, t, t["length_m"] * (k / 4 - 0.5) + 0.3, 8.0, "top")
    return rig


def test_a_carre_is_a_closed_rectangle_and_fixtures_face_out_of_it():
    t = T.carre("c", 4.0, 3.0, 4.0, -1.0, 3.0)
    assert T.is_carre(t) and T.is_loop(t) and T.is_closed(t) and not T.is_ring(t) and not T.is_stand(t)
    assert t["length_m"] == 14.0
    assert T.carre_corners(t) == [(6.0, 0.5), (6.0, -2.5), (2.0, -2.5), (2.0, 0.5)]
    assert T.point(t, 0.0)[:2] == (4.0, 0.5)  # the middle of the front side
    assert T.point(t, 1.0)[0] > 4.0  # round it towards +x first, like a ring
    assert T.point(t, 7.0)[:2] == pytest.approx((4.0, -2.5))  # half way: the middle of the back
    assert T.point(t, 7.5) == pytest.approx(T.point(t, -6.5))  # no ends
    for u in np.linspace(-6.5, 6.5, 11):
        f = T.place({}, t, float(u), 8.0, "front")
        x, y = f["x"] * 8.0, f["y_m"]
        assert not (2.0 < x < 6.0 and -2.5 < y < 0.5)  # the front face is the outside
        az = math.radians(-f.get("rot_deg", 0.0))  # the fixture's front (az 0 = towards the audience)
        out = np.array([x - 4.0, y + 1.0])
        assert np.dot(out, [math.sin(az), math.cos(az)]) > 0  # faces out


def test_a_turned_carre_turns_its_frame():
    t = T.carre("c", 4.0, 2.0, 0.0, 0.0, 3.0, rot=90.0)
    assert T.carre_corners(t)[0] == pytest.approx((-1.0, 2.0))
    assert T.direction(t, 0.0) == 90.0


def test_fixtures_keep_clear_of_the_corners():
    t = T.carre("c", 3.0, 3.0, 4.0, -1.0, 3.0)
    for u in (1.5, -1.5, 4.5, 6.0):
        f = T.place({}, t, u, 8.0, "under")
        x, y = f["x"] * 8.0, f["y_m"]
        assert min(math.dist((x, y), c) for c in T.carre_corners(t)) >= T.CORNER_CLEAR_M - 1e-6


def test_heads_go_mirrored_along_the_sides():
    rig = carre_rig()
    t = rig["trusses"][0]
    heads = [f for f in rig["fixtures"] if f["id"].startswith("h")]
    assert all(f.get("truss") == "carre" for f in heads)
    xs = sorted(round(f["x"] * 8.0 - t["x_m"], 2) for f in heads)
    assert xs == pytest.approx([-x for x in reversed(xs)], abs=0.02)  # stage left mirrors stage right
    ys = sorted(round(f["y_m"] - t["y_m"], 2) for f in heads)
    assert ys == pytest.approx([-y for y in reversed(ys)], abs=0.02)  # front mirrors back
    assert len({round(f["truss_pos_m"], 2) for f in heads}) == HEADS


def test_the_template_stands_round_the_booth_on_the_floor():
    rig = templates.rig("carre", width=8.0, height=4.5)
    (t,) = rig["trusses"]
    assert T.is_carre(t) and (t["width_m"], t["depth_m"]) in T.CARRE_SIZES_M
    assert t["z_m"] <= T.CARRE_HEIGHT_M + 0.5  # its own legs, not a hall's rigging points
    small = templates.rig("carre", width=3.0)["trusses"][0]
    assert small["width_m"] == T.CARRE_SIZES_M[0][0]


@pytest.fixture(scope="module")
def show():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    k = next(i for i, d in enumerate(plan) if d.section == "groove")
    return a, plan, k, Engine(a, plan, load_rig_dict(carre_rig()), real_output=False)


def test_heads_on_a_carre_play_it_as_a_ring(show):
    _, plan, k, e = show
    (g,) = [g for g in head_groups(e.rig) if g["kind"] == "ring"]
    assert len(g["ids"]) == HEADS
    assert all(r and r["full"] for r in e.rings)
    assert sorted(r["frac"] for r in e.rings) == sorted({round(r["frac"], 6) for r in e.rings})
    d = replace(plan[k], movement="sweep", formation="fan", aim="sky", grouping="unison")
    ts = np.array([d.start + 1.0])
    az = {j: float(np.degrees(np.arctan2(*e._head_dir_v(d, ts, j)[0, :2]))) for j in range(len(e.heads))}
    assert len({round(a) for a in az.values()}) == len(az)  # a crown: every head its own direction
    assert e.par_loop  # the pars chase round it


def test_the_hang_sheet_draws_its_legs_and_names_its_sides():
    rig = carre_rig()
    lay = hangsheet.layout(rig)
    (st,) = lay["structures"]
    assert st["kind"] == "ring" and st["ends"] is None
    assert any("front side" in r["where"] for r in st["fixtures"])
    assert any("back side" in r["where"] for r in st["fixtures"])
    page = hangsheet.html(rig)
    assert "carré 6.0 × 4.0 m on four legs" in page and page.count("class=\"tower\"") >= 8  # its legs, twice
