"""Sections that start before their downbeat (an anacrusis): found, and played into."""

from dataclasses import replace

import numpy as np
import pytest

from decisive.audio.phrases import vocal_pickups
from decisive.director import RuleDirector, direct
from decisive.engine import Engine
from decisive.rig.loader import load_rig
from tests.synthetic import synthetic_analysis


def test_a_vocal_line_coming_in_before_a_downbeat_starts_the_section_there():
    a = synthetic_analysis()
    beats = a.beats
    bars = beats[::4]
    p = a.phrases[2]
    k_down = int(np.searchsorted(beats, p.start - 0.05)) - 4  # the bar before the boundary
    fps = 20.0
    env = np.full(int(a.duration * fps) + 1, -60.0)
    entry = beats[k_down - 2]  # the line comes in two beats before that bar's downbeat…
    env[int(entry * fps) : int((entry + 8) * fps)] = -10.0  # …and sings on
    env[: int(5 * fps)] = -10.0  # (something to set the levels by)
    vocal_pickups(a.phrases, beats, bars, env, fps)
    q = a.phrases[2]
    assert q.start == pytest.approx(beats[k_down], abs=1e-6)  # the section starts on that downbeat
    assert (q.pickup_beats, q.pickup_kind) == (2, "early") and q.pickup_start == pytest.approx(entry)
    assert a.phrases[1].end == q.start


@pytest.fixture(scope="module")
def led():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    i = next(k for k in range(1, len(plan)) if plan[k].section != "drop" and plan[k].look() != plan[k - 1].look())
    a.phrases[i] = replace(a.phrases[i], pickup_beats=2, pickup_kind="early", pickup_start=plan[i].start - 0.94)
    rig = load_rig("tests/sets/showcase.json")
    return a, plan, i, Engine(a, plan, rig, real_output=False)


def test_a_lead_in_brings_the_next_look_in_early_and_lands_on_the_downbeat(led):
    a, plan, i, e = led
    p = a.phrases[i]
    mid = (p.pickup_start + plan[i].start) / 2
    before = e._scene(plan[i - 1], mid)
    ahead = e._scene(plan[i], mid)
    got = e.render(mid)[1]
    moved = [fid for fid in got if abs(ahead[fid].dimmer - before[fid].dimmer) > 0.2]
    assert moved and all(  # partly the next look already
        min(before[f].dimmer, ahead[f].dimmer) - 1e-6 <= got[f].dimmer <= max(before[f].dimmer, ahead[f].dimmer) + 1e-6
        for f in moved
    )
    assert any(abs(got[f].dimmer - before[f].dimmer) > 0.05 for f in moved)


def test_the_heads_move_into_the_next_section_during_the_lead_in(led):
    a, plan, i, e = led
    p = a.phrases[i]
    ts = np.array([p.pickup_start - 0.2, plan[i].start - 0.05])
    for j in range(len(e.heads)):
        dirs = e._head_dirs_v(ts, j)
        own = e._head_dir_v(plan[i - 1], ts, j)
        nxt = e._head_dir_v(plan[i], ts, j)
        assert np.allclose(dirs[0], own[0], atol=1e-6)  # before the pickup: its own section
        assert np.dot(dirs[1], nxt[1]) > np.dot(own[1], nxt[1]) - 1e-6  # by the downbeat: close to the next


def test_a_fill_is_played_by_the_lights():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    i = next(k for k in range(1, len(plan)) if plan[k].section != "drop")
    t0 = plan[i].start - 0.94
    a.phrases[i] = replace(a.phrases[i], pickup_beats=2, pickup_kind="fill", pickup_start=t0)
    e = Engine(a, plan, load_rig("tests/sets/showcase.json"), real_output=False)
    e.fill_t = np.array([t0 + 0.1, t0 + 0.5])
    lit = e.render(t0 + 0.52)[1]
    assert max(lit[f["id"]].dimmer for f in e.pars + e.heads) > 0.6  # a hit of the fill, bright


def test_a_long_section_before_a_drop_gets_its_build_as_its_own_section():
    from types import SimpleNamespace

    from decisive.audio.phrases import _split_builds

    n = 40
    bars = np.zeros((n, 5))
    bars[:, 0] = 1.0
    bars[10:24, 0] = 3.0  # a loud chorus…
    bars[24:30, 0] = 0.5  # …a dip…
    bars[30:39, 0] = np.linspace(0.6, 3.0, 9)  # …and the build rising into the drop at bar 40… (well, 39 here)
    bars[:, 3] = bars[:, 0]
    segments = [(0, 10), (10, 39), (39, 40)]
    phrases = [SimpleNamespace(drop_score=0.0), SimpleNamespace(drop_score=0.0), SimpleNamespace(drop_score=0.9)]
    out = _split_builds(segments, phrases, bars)
    starts = [s for s, _ in out]
    assert 39 - 10 in starts or any(29 <= s <= 31 for s in starts)  # the build starts after the dip, not at the chorus
    assert 10 in starts and 39 in starts
