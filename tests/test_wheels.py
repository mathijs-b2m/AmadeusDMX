"""Colour wheels turn in the dark: on every rig, no wheel is ever seen moving by a lit beam, the new colour still
comes (near) its moment, and the gaps the show makes for it don't chop the look."""

from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.engine import wheels as W
from amadeus.engine.looks import XFADE
from amadeus.engine.realism import Realism
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
FPS = 40


@pytest.fixture(scope="module")
def track():
    return synthetic_analysis()


def played(track, path):
    rig = load_rig(path)
    plan = direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    e = Engine(track, plan, rig)
    ts = np.arange(0.0, track.duration - 0.1, 1 / FPS)
    frames = [e.render(float(t))[1] for t in ts]
    return e, ts, frames


def level(s):
    return max(s.dimmer, s.white)


@pytest.mark.parametrize("bpm", [100.0, 128.0, 174.0])
@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_no_wheel_turns_in_a_lit_beam(path, bpm):
    e, ts, frames = played(synthetic_analysis(bpm=bpm), path)
    for eid, w in e.wheel_heads.items():
        n = len(w.slots)
        sent = [w.index((f[eid].r, f[eid].g, f[eid].b)) for f in frames]
        busy_until = -1.0
        for k in range(1, len(sent)):
            if sent[k] != sent[k - 1]:
                busy_until = ts[k] + W.travel_s(n, w.slot_s, sent[k - 1], sent[k]) - 1 / W.TRACE_FPS
            if ts[k] < busy_until:
                assert level(frames[k][eid]) <= W.DARK, f"{eid} lit at {ts[k]:.2f}s with its wheel turning"


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_a_wheel_changes_at_a_wheels_pace(track, path):
    """No hopping through the colours of a fade."""
    e, ts, frames = played(track, path)
    for eid, w in e.wheel_heads.items():
        sent = np.array([w.index((f[eid].r, f[eid].g, f[eid].b)) for f in frames])
        changes = ts[1:][np.diff(sent) != 0]
        lit_after = [t for t in changes if level(frames[min(int(t * FPS) + 8, len(frames) - 1)][eid]) > W.DARK]
        assert (np.diff(lit_after) >= 0.25).all(), eid


def test_wheels_still_follow_the_show(track):
    """The colours aren't simply frozen: most of what the show asks for gets played."""
    path = next(p for p in SETS if p.stem == "ring")
    e, ts, frames = played(track, path)
    agree, lit = 0, 0
    for w in e.wheel_heads.values():
        f = (ts * W.TRACE_FPS).astype(int)
        on = w.lit[f]
        agree += int((w.want[f] == w.slot[f])[on].sum())
        lit += int(on.sum())
    assert agree / lit > 0.8


def test_a_made_gap_ends_on_the_new_note_and_is_rare(track):
    path = next(p for p in SETS if p.stem == "ring")
    e, _, _ = played(track, path)
    beats, starts = e.beats, np.array(e.starts)
    every = W.DIP_EVERY_BARS * e.wheel_bar / W.TRACE_FPS
    for w in e.wheel_heads.values():
        ends = [d[2] for d in w.dips]
        assert (np.diff(ends) >= every - 1e-6).all()
        for end in ends:
            in_fade = 0 <= end - starts[starts <= end].max() < XFADE  # (a phrase's look fades in from dark)
            assert in_fade or np.abs(beats - end).min() < 0.08


def test_cmy_and_lasers_have_no_wheel_plan(track):
    for stem in ("encore60", "concert60", "laser-zones"):
        rig = load_rig(next(p for p in SETS if p.stem == stem))
        plan = direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
        assert not Engine(track, plan, rig).wheel_heads


def test_a_jump_in_time_does_not_stall(track):
    """After a seek the look-ahead fills up a little per render: no render looks far ahead at once."""
    rig = load_rig(next(p for p in SETS if p.stem == "ring"))
    plan = direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    e = Engine(track, plan, rig)
    calls = []
    look = e._look
    e._look = lambda t, peek=False: (calls.append(t), look(t, peek))[1]
    e.render(10.0)
    e.render(60.0)
    assert len(calls) <= 2 * (W.FILL_PER_RENDER + 1)
    e.render(60.025)
    assert e.wheel_t == 60.025


def test_travel_goes_the_short_way_round():
    assert W.travel_s(8, 0.1, 1, 7) == pytest.approx(W.SETTLE_S + 2 * 0.1)
    assert W.slot_seconds({"color_wheel": {"slot_s": 9}}) == W.SLOT_S_RANGE[1]
    assert W.slot_seconds({"color_wheel": {}}) == W.SLOT_S


def test_the_visualiser_turns_at_the_speed_the_show_counts_on(track):
    rig = load_rig(next(p for p in SETS if p.stem == "ring"))
    r = Realism(rig)
    eid, info = next((k, v) for k, v in r.info.items() if v["wheel"])
    slots = info["defn"]["color_wheel"]["slots"]
    r.wheel_pos[eid] = 0.0
    r._wheel(eid, slots, 3, 1 / 25 / W.slot_seconds(info["defn"]))
    assert r.wheel_pos[eid] == pytest.approx(0.5)


def test_two_decks_mixing_dont_blend_a_wheels_colour():
    from amadeus.engine.state import State
    from amadeus.show.mixer import Mixer

    rig = load_rig(next(p for p in SETS if p.stem == "ring"))
    eid = next(iter(W.wheel_fixtures(rig)))
    ids = [e["id"] for e in rig["elements"]]
    red = {i: State(dimmer=1.0, r=1.0) for i in ids}
    blue = {i: State(dimmer=1.0, b=1.0) for i in ids}

    class Deck:
        def __init__(self, deck):
            self.deck = deck

    mixed, _ = Mixer(rig).mix([(0.7, red, Deck(1), None, 0, 0), (0.3, blue, Deck(2), None, 0, 0)])
    assert (mixed[eid].r, mixed[eid].b) == (1.0, 0.0)


def test_looking_ahead_never_skips_the_laser_guard(track):
    """The guard runs on everything played, also around a drop (where the heads look ahead themselves)."""
    rig = load_rig(next(p for p in SETS if p.stem == "fuze24"))
    plan = direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    e = Engine(track, plan, rig)
    seen = []
    guard = e._laser_guard
    e._laser_guard = lambda states, t: (seen.append(t), guard(states, t))[1]
    ts = np.arange(0.0, track.duration - 0.1, 0.25)
    for t in ts:
        e.render(float(t))
    assert seen == list(ts)
