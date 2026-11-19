"""The operator's intensity level (1..5): 2 is the show as designed, 1 a step gentler, 3..5 ever harder, 5 with a
lot of strobing and very fast waves through the rig. The set's flash limit holds at every level."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from amadeus.show.arc import DEFAULT_LEVEL, HOT_LIGHT, ShowArc, push_plan, shape_plan
from tests.synthetic import synthetic_analysis

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
RIG = "tests/sets/showcase.json"
FPS = 40
CALM = ("intro", "breakdown", "outro", "verse")


@pytest.fixture(scope="module")
def track():
    return synthetic_analysis()


def _plan(track, rig):
    return direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)


def _arc(tmp_path, rig, level: int) -> ShowArc:
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    arc.control({"level": level, "stage": "peak"}, now=0.0)
    return arc


def test_level_two_is_the_show_as_designed(tmp_path, track):
    rig = load_rig(RIG)
    plan = _plan(track, rig)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    assert arc.level == DEFAULT_LEVEL == 2 and arc.snapshot(0.0)["level"] == 2
    assert push_plan(plan, 2) is plan
    e = Engine(track, shape_plan(plan, arc.plan_shape()), rig)
    assert all(not arc.wave_starts(e, float(t)) for t in np.arange(0.5, track.duration, 0.25))


def test_the_operator_dials_the_level_and_it_stays(tmp_path):
    rig = load_rig(RIG)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    for bad in (0, 6, "x", None):
        arc.control({"level": bad}, now=0.0)
        assert arc.level == 2
    arc.control({"level": 5}, now=0.0)
    assert arc.plan_shape()[4] == 5 and arc.snapshot(0.0)["level"] == 5
    arc.save(0.0)
    assert ShowArc(rig, tmp_path / "arc.json", now=10 * 24 * 3600.0).level == 5  # (a standing choice: next night too)


def test_level_one_is_gentler_not_darker(track):
    rig = load_rig(RIG)
    plan = [replace(d, head_light="strobe", par_accent="run") if d.section == "drop" else d for d in _plan(track, rig)]
    soft = push_plan(plan, 1)
    assert not any(d.head_light in ("strobe", "hammer", "run") or d.par_accent == "run" for d in soft)
    for a, b in zip(plan, soft):
        assert b.intensity <= 2 and (b.brightness if b.brightness >= 0 else b.intensity) == a.intensity


def test_higher_levels_push_harder_and_calm_parts_never_strobe(track):
    rig = load_rig(RIG)
    plan = _plan(track, rig)
    strobing = []
    for level in (2, 3, 4, 5):
        pushed = push_plan(plan, level)
        assert all(b.head_light not in ("strobe", "hammer") for a, b in zip(plan, pushed) if a.section in CALM)
        strobing.append(sum(d.head_light in HOT_LIGHT for d in pushed))  # (hitting hard, each its own way)
        assert sum(d.intensity for d in pushed) >= sum(d.intensity for d in plan)
    assert strobing == sorted(strobing) and strobing[-1] > strobing[0]
    five = push_plan(plan, 5)
    drops = [d.head_light for d in five if d.section == "drop"]
    assert all(light in HOT_LIGHT for light in drops)  # every drop hits hard …
    assert len(set(drops)) > 1  # … each its own way: not one look for all of them


def test_level_five_waves_only_now_and_then(tmp_path, track):
    """The waves are a variation, one of many: a phrase opens with its own look (pushed), the waves come in every
    other passage of it."""
    rig = load_rig(RIG)
    arc = _arc(tmp_path, rig, 5)
    e = Engine(track, shape_plan(_plan(track, rig), arc.plan_shape()), rig)
    big = [b for b in e.beats if e.decision_at(float(b))[1].section in ("drop", "chorus")]
    waving = [b for b in big if any(abs(w[0] - b) < 1e-6 for w in arc.wave_starts(e, float(b)))]
    assert waving and len(waving) < 0.4 * len(big)
    for d in e.plan:
        if d.section == "drop":
            assert not any(arc.wave_starts(e, float(b)) for b in e.beats if d.start <= b < d.start + 8 * 0.47)


def test_levels_lift_the_arcs_knobs_but_not_the_operators(tmp_path):
    rig = load_rig(RIG)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    arc.control({"stage": "warmup", "knob": {"flashes": 0.0}}, now=0.0)
    arc.control({"level": 5}, now=0.0)
    assert arc.values["response"] == 1.0 and arc.values["movement"] == 1.0 and arc.values["groups"] == 1.0
    assert arc.values["flashes"] == 0.0  # the operator holds it: it stays where they put it
    assert not arc.ambient()  # (the warm-up's calm ambience is not a level-5 show)
    arc.control({"level": 1, "auto": "flashes", "stage": "peak"}, now=0.0)
    assert arc.values["flashes"] <= 0.5 and arc.values["response"] <= 0.75


def test_a_wave_runs_through_the_rig_in_sequence(tmp_path, track):
    rig = load_rig(RIG)
    arc = _arc(tmp_path, rig, 5)
    e = Engine(track, shape_plan(_plan(track, rig), arc.plan_shape()), rig)
    drop = next(d for d in e.plan if d.section == "drop")
    hard = lambda b: [w for w in arc.wave_starts(e, float(b)) if not w[3] and abs(w[0] - b) < 1e-6]  # noqa: E731
    t0 = next(float(b) for b in e.beats if b > drop.start + 8 * 0.47 and hard(b))
    start, sweep, way, _ = hard(t0)[-1]
    assert abs(start - t0) < 1e-6 and sweep < 0.2  # very fast: across the whole rig in a quarter beat
    pars = {x["id"] for x in rig["elements"] if x["kind"] == "par"}  # (the heads strobe in a level-5 drop)
    order = sorted((eid for eid in arc.wave_pos if eid in pars), key=arc.wave_pos.get)
    first, last = (order[0], order[-1]) if way == "right" else (order[-1], order[0])
    lit = {}
    for t in np.arange(t0, t0 + sweep + 0.1, 1 / 400):
        st = e.render(float(t))[1]
        arc.apply(st, e, float(t), 1 / 400)
        for eid in (first, last):
            if eid not in lit and st.get(eid) is not None and st[eid].dimmer > 0.9:
                lit[eid] = t
    assert first in lit and last in lit, "the wave lit nothing"
    if way in ("right", "left"):
        assert lit[first] < lit[last] <= lit[first] + sweep + 0.01
    for t in np.arange(drop.start - 1.0, drop.start + 4 * 0.47, 0.05):  # the drop moment is the director's
        assert not arc.wave_starts(e, float(t)) or not e.in_drop_moment(float(t))


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_no_light_flashes_faster_than_the_set_allows(tmp_path, track, path):
    """Level 5, waves and all: a light is never hit again sooner than the set's flash limit allows."""
    rig = load_rig(path)
    hz = 10.0 if rig["safety"].get("allow_fast_strobe") else float(rig["safety"].get("max_flash_hz", 4.0))
    arc = _arc(tmp_path, rig, 5)
    e = Engine(track, shape_plan(_plan(track, rig), arc.plan_shape()), rig)
    ids = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    prev, last, fastest = {}, {}, 0.0
    for t in np.arange(0.05, track.duration - 0.1, 1 / FPS):
        st = e.render(float(t))[1]
        arc.apply(st, e, float(t), 1 / FPS)
        for i in ids:
            s = st.get(i)
            v = 0.0 if s is None else s.dimmer * s.gate
            if v > 0.6 and prev.get(i, 0.0) <= 0.3:
                if i in last:
                    fastest = max(fastest, 1.0 / (t - last[i]))
                last[i] = t
            prev[i] = v
    assert fastest <= hz * 1.15  # (a frame's rounding)


def test_strobe_free_sets_never_strobe_at_level_five(tmp_path, track):
    rig = load_rig(RIG)
    rig["safety"]["strobe_free"] = True
    arc = _arc(tmp_path, rig, 5)
    e = Engine(track, shape_plan(_plan(track, rig), arc.plan_shape()), rig)
    for t in np.arange(40.0, 70.0, 1 / FPS):
        st = e.render(float(t))[1]
        arc.apply(st, e, float(t), 1 / FPS)
        assert all(s.strobe_hz == 0 for s in st.values())


@pytest.mark.parametrize("level", [4, 5])
def test_the_waves_take_every_way_front_to_back_too(tmp_path, track, level):
    """Across (both ways), front to back and back to front, from the middle out and in: the waves take turns."""
    rig = load_rig(RIG)
    arc = _arc(tmp_path, rig, level)
    e = Engine(track, shape_plan(_plan(track, rig), arc.plan_shape()), rig)
    ways = {w for t in e.beats for _, _, w, _ in arc.wave_starts(e, float(t))}
    assert ways == {"right", "left", "back", "front", "out", "in"}
    front = min(arc.wave_depth, key=arc.wave_depth.get)
    back = max(arc.wave_depth, key=arc.wave_depth.get)
    assert arc.wave_depth[front] == 0.0 and arc.wave_depth[back] == 1.0


def test_a_flat_rig_waves_only_across(tmp_path):
    arc = ShowArc(load_rig("tests/sets/small.json"), tmp_path / "arc.json", now=0.0)
    assert "back" not in arc.wave_ways and "front" not in arc.wave_ways and not arc.wave_depth


def test_some_waves_are_soft_the_lights_dissolving(tmp_path, track):
    """A variation, not a replacement: now and then a passage of soft waves, slower, once a bar, each light swelling
    up and dissolving; the hard, fast shots stay the rest of the time."""
    rig = load_rig(RIG)
    arc = _arc(tmp_path, rig, 5)
    e = Engine(track, shape_plan(_plan(track, rig), arc.plan_shape()), rig)
    waves = {w[0]: w for t in e.beats for w in arc.wave_starts(e, float(t))}.values()
    soft = [w for w in waves if w[3]]
    assert soft and len(soft) < len(waves) / 2
    start, sweep, way, _ = soft[0]
    assert sweep > 2 * max(w[1] for w in waves if not w[3])  # slower across the rig
    order = sorted(arc.wave_pos, key=arc.wave_pos.get)  # one light in the middle of the wave, from its start on
    ways = {"right": arc.wave_pos, "left": {k: 1 - v for k, v in arc.wave_pos.items()}}
    eid = min(order, key=lambda k: abs(ways.get(way, arc.wave_pos)[k] - 0.5)) if way in ways else order[0]
    levels = []
    for t in np.arange(start, start + sweep + 1.0, 1 / FPS):
        st = e.render(float(t))[1]
        arc.apply(st, e, float(t), 1 / FPS)
        levels.append(st[eid].dimmer if eid in st else 0.0)
    lit = [k for k, v in enumerate(levels) if v > 0.5]
    assert lit and len(lit) >= 0.3 * FPS  # it lingers: a swell, not a shot


def test_a_strobe_free_set_only_waves_softly(tmp_path, track):
    rig = load_rig(RIG)
    rig["safety"]["strobe_free"] = True
    arc = _arc(tmp_path, rig, 5)
    e = Engine(track, shape_plan(_plan(track, rig), arc.plan_shape()), rig)
    waves = [w for t in e.beats for w in arc.wave_starts(e, float(t))]
    assert waves and all(w[3] for w in waves)


@pytest.mark.parametrize("movement", ["circle", "ballyhoo", "tilt_wave", "pendulum"])
def test_the_heads_pan_and_tilt_faster_at_four_and_five(track, movement):
    """Levels 4 and 5: the heads cover more ground in the same time (the paths faster, a move a beat where the
    motors took two), the motors still allowing (the realism predicts where a head really is)."""
    rig = load_rig(RIG)
    plan = [replace(d, movement=movement, formation="sync", section="drop", intensity=3) for d in _plan(track, rig)]
    assert {d.pace for d in push_plan(plan, 4)} == {1.5} and {d.pace for d in push_plan(plan, 5)} == {2.0}
    heads = [x["id"] for x in rig["elements"] if x["kind"] == "head"]
    travel = []
    for pace in (1.0, 2.0):
        e = Engine(track, [replace(d, pace=pace) for d in plan], rig)
        last, moved = {}, 0.0
        for t in np.arange(50.0, 62.0, 1 / FPS):
            st = e.render(float(t))[1]
            for i in heads:
                if i in st:
                    p = (st[i].dmx_pan if st[i].dmx_pan is not None else st[i].pan, st[i].dmx_tilt or st[i].tilt)
                    if i in last:
                        moved += abs(p[0] - last[i][0]) + abs(p[1] - last[i][1])
                    last[i] = p
        travel.append(moved)
    assert travel[1] > 1.2 * travel[0], travel
