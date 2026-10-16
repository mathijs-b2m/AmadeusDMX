"""Round truss: fixtures round a circle, and the heads playing it as a circle (amadeus/engine/rings.py)."""

import math
from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig import automount, templates
from amadeus.rig import trusses as T
from amadeus.rig.groups import head_groups
from amadeus.rig.loader import load_rig_dict
from tests.synthetic import synthetic_analysis

HEADS = 8


def ring_rig(pars_on_ring: bool = False) -> dict:
    """The "ring" template (a 5 m circle and an 8 m half circle behind it) with auto-mounted heads."""
    rig = templates.rig("ring", width=10.0)
    rig["fixtures"] = [{"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1, "address": 1 + 20 * k}
                       for k in range(HEADS)]  # fmt: skip
    rig["fixtures"] += [{"id": f"p{k}", "fixture": "cameo/flat-pro-18", "universe": 2, "address": 1 + 10 * k}
                        for k in range(6)]  # fmt: skip
    rig["trusses"] = [t for t in rig["trusses"] if t["id"] == "ring"]  # every head on the circle
    for fid, spot in automount.automount(rig).items():
        next(f for f in rig["fixtures"] if f["id"] == fid).update(spot)
    if pars_on_ring:
        ring = rig["trusses"][0]
        pars = [f for f in rig["fixtures"] if f["id"].startswith("p")]
        for k, f in enumerate(pars):
            T.place(f, ring, ring["length_m"] * (k / len(pars) - 0.5) + 0.3, 10.0, "top")
    return load_rig_dict(rig)


def test_a_ring_is_a_circle_and_fixtures_face_out_of_it():
    t = T.ring("r", 4.0, 5.0, -3.0, 5.0)
    assert t["length_m"] == pytest.approx(math.pi * 4, abs=1e-3)
    for u in np.linspace(-6, 6, 9):
        f = T.place({}, t, float(u), 10.0, "under")
        x, y = f["x"] * 10.0, f["y_m"]
        assert math.hypot(x - 5.0, y + 3.0) == pytest.approx(2.0, abs=0.01)  # on the circle
        out = np.array([x - 5.0, y + 3.0]) / 2.0
        az = math.radians(-f.get("rot_deg", 0.0))  # the fixture's front (az 0 = towards the audience)
        assert np.dot(out, [math.sin(az), math.cos(az)]) == pytest.approx(1.0, abs=0.01)  # faces out
    front = T.place({}, t, 0.0, 10.0, "front")
    assert front["y_m"] > -3.0 + 2.0  # the front face is the outside
    half = T.ring("a", 4.0, 5.0, -3.0, 5.0, arc=180, rot=180)
    ends = [T.place({}, half, u, 10.0, "under") for u in (-half["length_m"] / 2, half["length_m"] / 2)]
    assert all(e["y_m"] == pytest.approx(-3.0, abs=0.01) for e in ends)  # a half circle opening to the audience
    assert T.place({}, half, 0.0, 10.0, "under")["y_m"] == pytest.approx(-5.0, abs=0.01)


def test_heads_go_evenly_round_a_full_ring():
    rig = ring_rig()
    heads = [f for f in rig["fixtures"] if f["id"].startswith("h")]
    assert all(f.get("truss") == "ring" for f in heads)
    ring = rig["trusses"][0]
    angles = sorted(math.atan2(f["y_m"] - ring["y_m"], f["x"] * 10.0 - ring["x_m"]) for f in heads)
    gaps = np.diff(angles + [angles[0] + 2 * math.pi])
    assert np.ptp(gaps) < 0.05  # the same spacing all the way round
    (g,) = head_groups(rig)
    assert g["kind"] == "ring" and len(g["ids"]) == HEADS


@pytest.fixture(scope="module")
def show():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    k = next(i for i, d in enumerate(plan) if d.section == "groove")
    return a, plan, k, Engine(a, plan, ring_rig(pars_on_ring=True), real_output=False)


def _az(d):
    return np.degrees(np.arctan2(d[:, 0], d[:, 1]))


def test_fan_is_a_crown_of_beams_out_of_the_circle(show):
    _, plan, k, e = show
    d = replace(plan[k], movement="sweep", formation="fan", aim="sky", grouping="unison")
    ts = np.array([d.start + 1.0])
    az = {j: float(_az(e._head_dir_v(d, ts, j))[0]) for j in range(len(e.heads))}
    ring = e.rings[0]
    for j, a in az.items():  # each beam leans out of the circle where its head hangs (the back half squeezed
        out = np.array(e.head_pos[j][:2]) - ring["centre"][:2]  # towards the front: not at the DJ)
        beam = np.array([math.sin(math.radians(a)), math.cos(math.radians(a))])
        if out[1] > 0:  # the front half: straight out
            assert np.dot(out / np.linalg.norm(out), beam) > 0.7
        else:  # the back half: out to its own side, never back at the DJ
            assert beam[1] > -0.25 and (abs(out[0]) < 0.3 * ring["radius"] or beam[0] * out[0] > 0)
    assert len({round(a) for a in az.values()}) == len(az)  # every head its own direction


def test_focus_is_a_cone_and_cross_a_twister(show):
    _, plan, k, e = show
    ts = np.array([plan[k].start + 1.0])
    reach = 2 * e.rings[0]["radius"]
    for f in ("focus", "cross"):
        d = replace(plan[k], movement="still", formation=f, aim="crowd", grouping="unison")
        ends = np.array([e.head_pos[j] + e._head_dir_v(d, ts, j)[0] * reach for j in range(len(e.heads))])
        spread = np.linalg.norm(ends[:, :2] - ends[:, :2].mean(0), axis=1).mean()
        if f == "focus":  # the beams close in: a cone
            assert spread < e.rings[0]["radius"] * 0.6
        else:  # the beams cross over and fan out again: an hourglass
            assert spread > e.rings[0]["radius"] * 0.6
            centre = e.rings[0]["centre"][:2]
            crossed = [np.dot(e.head_pos[j][:2] - centre, ends[j, :2] - centre) < 0 for j in range(len(e.heads))]
            assert sum(crossed) >= len(e.heads) // 2


def test_a_wave_runs_round_the_ring(show):
    _, plan, k, e = show
    d = replace(plan[k], movement="nod", formation="wave", aim="crowd", grouping="unison")
    ts = np.linspace(d.start + 1, d.start + 9, 400)
    order = sorted(range(len(e.heads)), key=lambda j: e.rings[j]["frac"])
    el = [np.degrees(np.arcsin(e._head_dir_v(d, ts, j)[:, 2])) for j in order]
    lags = [int(np.argmax(np.correlate(x - x.mean(), el[0] - el[0].mean(), "full"))) for x in el]
    step = np.diff(lags)  # later round the ring, later the nod: the same step from head to head (a full circle
    # of 8 heads: half a beat, ~12 frames here; one step wraps round the nod's own cycle)
    assert sum(8 <= x <= 16 for x in step) >= HEADS - 2


def test_pars_on_a_full_ring_chase_round_it(show):
    _, _, _, e = show
    assert e.par_loop
    ring = next(t for t in e.rig["trusses"] if t["id"] == "ring")
    fx = {f["id"]: f for f in e.rig["fixtures"]}
    pos = [fx[p["fixture"]]["truss_pos_m"] for p in e.pars]
    assert pos == sorted(pos) and ring["length_m"] > 0  # in order round the circle
