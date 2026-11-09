"""Wall uplighters: tilting bars on the floor by a wall shine straight up, light up in a run on the beat grid, and
lean in only at the night's surprise."""

import json
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.engine.uplights import SURPRISE_HOLD_BEATS
from amadeus.rig import geometry
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig_dict
from amadeus.rig.uplights import is_uplight
from tests.synthetic import synthetic_analysis

FUZE = Path(__file__).parent / "sets" / "fuze24.json"
BAR = "chauvet/colorband-pix-m"  # a tilting bar of 12 cells


def _rig():
    rig = json.loads(FUZE.read_text())
    w = rig["stage"]["width_m"]  # 12 m, 2 m of room either side
    for k, (x, y) in enumerate([(-1.7, 3), (-1.7, 8), (-1.7, 13), (13.7, 3), (13.7, 8), (13.7, 13)]):
        rig["fixtures"].append(
            {
                "id": f"up{k + 1}",
                "fixture": BAR,
                "mode": "38ch",
                "universe": 2,
                "address": 1 + 40 * k,
                "x": x / w,
                "y_m": y,
                "z_m": 0.2,
                "mount": "floor",
                "rot_deg": 270 if x < 0 else 90,
            }  # fmt: skip
        )
    rig["fixtures"].append(  # the same bar on the stage, in the middle: an ordinary head
        {
            "id": "stagebar",
            "fixture": BAR,
            "mode": "38ch",
            "universe": 2,
            "address": 241,
            "x": 0.5,
            "y_m": -1,
            "z_m": 0.2,
            "mount": "floor",
        }  # fmt: skip
    )
    return load_rig_dict(rig)


@pytest.fixture(scope="module")
def show():
    rig = _rig()
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    return Engine(a, plan, rig, real_output=False), plan


def _fx(e, fid):
    return next(f for f in e.rig["fixtures"] if f["id"] == fid)


def _beam(e, eid, s):
    fx = _fx(e, eid.split(".")[0])
    from amadeus.library import fixtures as fxlib

    return geometry.fk(fx, fxlib.get(fx["fixture"]), s.pan, s.tilt)


def test_only_floor_bars_by_a_wall_are_uplighters(show):
    e, _ = show
    rig = e.rig
    assert {f["id"] for f in rig["fixtures"] if is_uplight(rig, f)} == {f"up{k}" for k in range(1, 7)}
    assert all(not h["id"].startswith("up") for h in e.heads)  # no head to the motion
    assert any(h["fixture"] == "stagebar" for h in e.heads)
    assert not any(i.startswith("up") for g in head_groups(rig) for i in g["ids"])
    pairs = [sorted({i.split(".")[0] for i in s}) for s in e.up_steps]
    assert pairs == [["up1", "up4"], ["up2", "up5"], ["up3", "up6"]]  # mirrored across the room, stage → back


def test_they_shine_straight_up_all_through(show):
    e, plan = show
    for t in np.arange(0.5, e.a.duration - 0.5, 0.37):
        states = e.render(t)[1]
        for eid in e.uplight_ids:
            assert _beam(e, eid, states[eid])[2] > 0.999, (t, eid)
            assert states[eid].dmx_tilt == pytest.approx(states[eid].tilt)


def test_the_run_steps_on_the_beat_from_the_stage_back(show):
    e, plan = show
    i = next(k for k, d in enumerate(plan) if d.section == "drop")
    d = plan[i]
    beats = e.beats[(e.beats >= d.start - 0.02) & (e.beats < d.end - 1)]
    order = []
    for b, nb in zip(beats[:6], beats[1:7]):
        states = e.render(float(b + (nb - b) / 4))[1]  # early in the beat: the step it hit is the brightest
        lv = [max(states[x].dimmer for x in s) for s in e.up_steps]
        order.append(int(np.argmax(lv)))
    assert order == [0, 1, 2, 0, 1, 2]


def test_their_level_follows_the_phrase_not_the_loudness(show):
    e, plan = show
    i = next(k for k, d in enumerate(plan) if d.section == "drop")
    d = plan[i]
    peaks = []
    bs = e.beats[(e.beats >= d.start + 1) & (e.beats < d.end - 1)]
    for b, nb in zip(bs, bs[1:]):
        states = e.render(float(b + (nb - b) / 4))[1]
        peaks.append(max(states[x].dimmer for s in e.up_steps for x in s))
    assert max(peaks) - min(peaks) < 0.02  # every beat's step lands at the same level


def test_they_lean_in_at_the_surprise_only_and_stand_back_up(show):
    e, plan = show
    i = next(k for k, d in enumerate(plan) if d.section == "drop")
    e.surprise = i
    try:
        k = int(np.searchsorted(e.beats, plan[i].start - 0.02))
        mid = float(e.beats[k + 8])  # every step leaning by now
        states = e.render(mid)[1]
        for eid in e.uplight_ids:
            d = _beam(e, eid, states[eid])
            fx = _fx(e, eid.split(".")[0])
            inward = 1 if fx["x"] < 0.5 else -1
            assert d[0] * inward > 0.5 and d[2] > 0.75, eid  # in towards the room, well above the heads
            assert states[eid].dimmer > 0.5  # lit through the move
        after = float(e.beats[k + SURPRISE_HOLD_BEATS + 6])
        for eid in e.uplight_ids:
            assert _beam(e, eid, e.render(after)[1][eid])[2] > 0.999
    finally:
        e.surprise = None


def test_in_driving_phrases_the_cells_play_a_waterfall_along_the_bar(show):
    e, plan = show
    d = next(d for d in plan if d.section == "drop")
    was, d.wall_cells = d.wall_cells, "fall"
    _waterfall(e, d)
    d.wall_cells = was


def _waterfall(e, d):
    b = float(e.beats[np.searchsorted(e.beats, d.start - 0.02) + 4])
    length = float(e.beats[np.searchsorted(e.beats, b) + 1]) - b
    states = e.render(b + length / 4)[1]
    first = max((x for x in e.uplight_ids if e.up_rank[x] == 0), key=lambda x: states[x].dimmer)  # the step it hit
    bar = sorted((x for x in e.uplight_ids if x.split(".")[0] == first.split(".")[0]), key=lambda x: e.up_rank[x])
    firsts = []
    for x in bar:  # the moment each cell comes on: stage end first, back end last
        ts = np.arange(b, b + length, length / 60)
        firsts.append(next(t for t in ts if e.render(float(t))[1][x].dimmer > 0.05))
    assert firsts == sorted(firsts) and firsts[-1] - firsts[0] > length * 0.5
    mid = e.render(b + length * 0.5)[1]
    assert 0 < sum(mid[x].dimmer > 0.05 for x in bar) < len(bar)  # only part of the bar lit: it travels


def test_they_stay_under_the_heads_but_at_the_surprise(show):
    e, plan = show
    from amadeus.engine.uplights import RUN_LEVEL

    for t in np.arange(0.5, e.a.duration - 0.5, 0.29):
        states = e.render(t)[1]
        assert max(states[x].dimmer for x in e.uplight_ids) <= RUN_LEVEL + 1e-6, t


def test_the_director_picks_from_every_pattern_and_keeps_calm_phrases_whole():
    from amadeus.director.decision import Decision
    from amadeus.director.rules import WALL_CELLS, wall_cells_for
    from amadeus.engine.uplights import PATTERNS

    assert set(WALL_CELLS) == set(PATTERNS)
    base = dict(start=0, end=8, palette="", par_base="", par_accent="", trigger="", head_light="", movement="")
    base |= dict(formation="", aim="", head_color="", dynamics="", beam_fx="", gobo_style="", source="rules")
    seen = {wall_cells_for(Decision(phrase=i, section="drop", intensity=3, **base), i) for i in range(16)}
    assert seen == {"fall", "out", "bounce", "comet", "split", "rise", "scatter", "in"}
    assert {wall_cells_for(Decision(phrase=i, section="breakdown", intensity=1, **base), 0) for i in range(8)} == {
        "whole"
    }


@pytest.mark.parametrize("pattern", ["fall", "rise", "bounce", "out", "in", "split", "halves", "comet", "scatter"])
def test_every_pattern_plays_each_cell_once_a_step_on_the_grid(show, pattern):
    e, plan = show
    d = next(d for d in plan if d.section == "drop")
    was, d.wall_cells = d.wall_cells, pattern
    try:
        k = int(np.searchsorted(e.beats, d.start - 0.02)) + 2
        n = len(e.up_steps)
        t0, t1 = float(e.beats[k]), float(e.beats[k + n])  # one round of the run: each step once
        bar = [x for x in e.uplight_ids if x.split(".")[0] == "up1"]
        ts = np.linspace(t0, t1, 400)
        lv = np.array([[e.render(float(t))[1][x].dimmer for x in bar] for t in ts])
        rises = ((lv[1:] > 0.3) & (lv[:-1] <= 0.3)).sum(axis=0)
        assert (rises <= 1).all(), pattern  # a note per cell, no flicker
        assert lv.max() > 0.3
        starts = sorted({float(ts[i + 1]) for i, c in zip(*np.nonzero((lv[1:] > 0.3) & (lv[:-1] <= 0.3)))})
        assert len(starts) >= (1 if pattern in ("split", "halves") else 3) or pattern == "whole"
    finally:
        d.wall_cells = was


def test_they_black_out_to_make_room_on_a_heavy_streak_of_the_heads(show):
    from amadeus.director.decision import Decision
    from amadeus.director.rules import wall_cells_for

    base = dict(start=0, end=8, palette="", par_base="", par_accent="", trigger="", formation="", aim="")
    base |= dict(head_color="", dynamics="", beam_fx="", gobo_style="", source="rules", section="drop", intensity=3)
    assert wall_cells_for(Decision(phrase=3, head_light="strobe", movement="sweep", **base), 0) == "dark"
    hard = [Decision(phrase=i, head_light="pulse", movement="ballyhoo", **base) for i in range(4)]
    last = None
    for d in hard:
        d.wall_cells = wall_cells_for(d, 0, last)
        last = d
    assert [d.wall_cells == "dark" for d in hard] == [False, True, False, True]  # every other phrase: room
    calm = Decision(phrase=1, head_light="steady", movement="sweep", **base)
    assert wall_cells_for(calm, 0, hard[0]) != "dark"

    e, plan = show
    d = next(d for d in plan if d.section == "drop")
    was, d.wall_cells = d.wall_cells, "dark"
    try:
        for t in np.arange(d.start, d.end, 0.2):
            assert max(e.render(float(t))[1][x].dimmer for x in e.uplight_ids) == 0.0
    finally:
        d.wall_cells = was
