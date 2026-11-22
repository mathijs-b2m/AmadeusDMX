"""A colour wave through the heads (head_color "wave"): every head in the look's colour, a white (or accent) crest
running through them once a bar, stage left to right, then back. Heads that mix their colour show the crest's
colour; a colour wheel can't blend (and never turns lit), so its beam carries the wave in its light instead."""

from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.director.rules import RULE_LOOKS
from amadeus.director.vocabulary import HEAD_COLOR
from amadeus.engine import Engine
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis


@pytest.fixture(scope="module")
def track():
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(), verbose=False)


def _engine(track, rig_name, **look):
    a, plan = track
    plan = list(plan)
    k = next(i for i, d in enumerate(plan) if d.section == "groove")
    look = {"head_light": "steady", "grouping": "unison", "dynamics": "steady", "beam_fx": "open", **look}
    plan[k] = replace(plan[k], **look)
    e = Engine(a, plan, load_rig(f"tests/sets/{rig_name}.json"), real_output=False)
    return e, plan[k]


def _bars(e, d):
    bars = [float(b) for b in e.downbeat_times if d.start + 1.0 <= b < d.end - 4 * e._beat_s()]
    assert len(bars) >= 2
    return bars[:2]


def test_the_director_can_pick_it():
    assert {"wave", "wave_accent"} <= {name for name, _ in HEAD_COLOR}
    looks = [look[7] for section in RULE_LOOKS.values() for look in section]
    assert "wave" in looks and "wave_accent" in looks


def test_the_crest_crosses_the_row_and_comes_back(track):
    e, d = _engine(track, "concert60", head_color="wave")
    rank, n = e._x_rank(e.heads), len(e.heads)
    order = sorted(e.heads, key=lambda h: rank[h["id"]])
    for bar, way in zip(_bars(e, d), (1, -1), strict=True):
        b = bisect_bar(e, bar)
        ts = np.arange(bar, bar + 4 * e._beat_s(), 0.01)
        first = [next(t for t in ts if e._colour_wave(float(t), rank[h["id"]], n) > 0.5) for h in order]
        steps = np.diff(first) * (1 if b % 2 == 0 else -1)
        assert (steps >= -1e-9).all(), "the crest runs one way across the row"
        assert abs(first[-1] - first[0]) > e._beat_s(), "and takes its time doing it"
        del way


def bisect_bar(e, t):
    return int(np.searchsorted(e.downbeat_times, t + 1e-6)) - 1


def test_mixing_heads_turn_white_as_it_passes_and_keep_their_level(track):
    e, d = _engine(track, "concert60", head_color="wave")
    plain, _ = _engine(track, "concert60", head_color="base")
    bar = _bars(e, d)[0]
    whites = []
    for t in np.arange(bar, bar + 4 * e._beat_s(), 0.05):
        states, same = e.render(float(t))[1], plain.render(float(t))[1]
        for h in e.heads:
            s = states[h["id"]]
            whites.append(min(s.r, s.g, s.b))
            assert s.dimmer == pytest.approx(same[h["id"]].dimmer), "the colour moves, the beams' level stays"
    assert max(whites) > 0.9 and min(whites) < 0.5, "white at the crest, the look's colour between"


@pytest.mark.parametrize("light", ["pulse", "steady"])
def test_wheel_heads_wipe_to_the_next_colour_and_never_turn_lit(track, light):
    """A wheel plays the wave as a wipe to the next colour round the wheel and back. The look asks for it once a
    bar; the wheels hide each turn in the dark (a pulse's gaps: every pass; a steady beam: some are skipped) and the
    wave never darkens a beam itself."""
    from amadeus.engine.wheels import DARK, TRACE_FPS, travel_s

    e, d = _engine(track, "fuze24", head_color="wave", head_light=light)
    plain, _ = _engine(track, "fuze24", head_color="base", head_light=light)
    bar = _bars(e, d)[0]
    dt = 1 / TRACE_FPS
    ts = np.arange(bar - 0.9 * e._beat_s(), bar + 7.6 * e._beat_s(), dt)  # (a wipe ends on beat 3, before the next)
    looks = [e._look(float(t))[1] for t in ts]  # (the look itself, before the wheels play their slots)
    same = [plain._look(float(t))[1] for t in ts]
    played = 0
    for h in e.heads:
        w = e.wheel_heads[h["id"]]
        cols = [(round(s[h["id"]].r, 3), round(s[h["id"]].g, 3), round(s[h["id"]].b, 3)) for s in looks]
        lit = [max(s[h["id"]].dimmer, s[h["id"]].white) for s in looks]
        assert lit == pytest.approx([max(s[h["id"]].dimmer, s[h["id"]].white) for s in same]), "light as the look's"
        if np.mean(np.array(lit) > DARK) < 0.5:
            continue  # (a head the look keeps dark)
        played += 1
        changes = [i for i in range(1, len(cols)) if cols[i] != cols[i - 1]]
        assert len(changes) == 2 and len(set(cols)) == 2, "asked once a bar: there, then back"
        a = w.index(cols[0])
        b = next(i for i, sl in enumerate(w.slots) if tuple(round(x, 3) for x in sl["rgb"]) == cols[changes[0]])
        assert travel_s(len(w.slots), w.slot_s, a, b) < 0.6, "a short turn: the next colour round the wheel"
    assert played, "the look lights some heads"
    # as played: a wheel never turns under a lit beam (as test_wheels checks for every look)
    ts = np.arange(d.start, d.end, 0.025)
    frames = [e.render(float(t))[1] for t in ts]
    for h in e.heads:
        w = e.wheel_heads[h["id"]]
        sent = [w.index((f[h["id"]].r, f[h["id"]].g, f[h["id"]].b)) for f in frames]
        busy = -1.0
        for k in range(1, len(sent)):
            if sent[k] != sent[k - 1]:
                busy = ts[k] + travel_s(len(w.slots), w.slot_s, sent[k - 1], sent[k]) - 1 / TRACE_FPS
            if ts[k] < busy:
                assert max(frames[k][h["id"]].dimmer, frames[k][h["id"]].white) <= DARK, "lit with its wheel turning"
