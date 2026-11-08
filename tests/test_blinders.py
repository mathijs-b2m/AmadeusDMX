"""Blinders light at the song's heaviest moments only, in every program, and never along with the booms."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.director.cinematic import CinematicDirector
from amadeus.director.lightshow import LightshowDirector
from amadeus.engine import Engine
from amadeus.engine.blinders import heavy_phrases, pick_punches
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis
from tests.test_cinematic import cinematic_analysis

FUZE = Path(__file__).parent / "sets" / "fuze24.json"  # (the test set with blinders)


@pytest.fixture(scope="module")
def track():
    return synthetic_analysis()


def _engine(program=""):
    rig = load_rig(FUZE)
    if program == "cinematic":
        a = cinematic_analysis()
        plan = direct(a, CinematicDirector(), verbose=False)
    else:
        a = cinematic_analysis() if program else synthetic_analysis()
        director = (
            LightshowDirector() if program else RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")))
        )
        plan = direct(a, director, verbose=False)
    e = Engine(a, plan, rig, real_output=False)
    assert e.program == program
    return e, plan


def _lit(e, plan, fps=20):
    ts = np.arange(0, e.a.duration, 1 / fps)
    lv = np.array([max(e.render(t)[1][b].dimmer for b in e.blinder_ids) for t in ts])
    return ts, lv


def test_the_heaviest_phrases_are_the_loudest_drops(track):
    # the synthetic track: drops at phrases 3 (95/95), 4 (90/90) and 7 (97/96); the second half of the first
    # drop is just a little lighter, but three phrases are too many
    assert heavy_phrases(track.phrases) == {3, 7}


def test_a_quieter_song_still_has_its_heaviest_moment():
    track = synthetic_analysis()
    soft = [replace(p, loudness_pct=p.loudness_pct * 0.5, low_pct=p.low_pct * 0.5) for p in track.phrases]
    assert heavy_phrases(soft) == {3, 7}


def test_a_flat_quiet_track_has_none():
    track = synthetic_analysis()
    assert heavy_phrases([replace(p, loudness_pct=20, low_pct=20) for p in track.phrases]) == set()


def test_punches_are_few_and_apart():
    times = np.arange(0, 16, 0.5)
    got = pick_punches(times, np.linspace(0.5, 1, len(times)), 0, 16, 0.5, 2.0, avoid=(0.0,))
    assert len(got) == 2 and abs(got[1] - got[0]) >= 4 - 0.02 and all(t >= 4 - 0.02 for t in got)


@pytest.mark.parametrize("program", ["", "cinematic", "lightshow"])
def test_blinders_stay_dark_outside_the_heaviest_moments(program):
    e, plan = _engine(program)
    track = e.a
    ts, lv = _lit(e, plan)
    on = lv > 0.05
    assert on.any(), "the heaviest drops slam them in"
    assert on.mean() < 0.05, f"lit {on.mean():.0%} of the track"
    period = 60.0 / track.bpm
    for t in ts[on]:
        i = e.decision_at(t)[0]
        swell = i + 1 in e.blinder_heavy and plan[i + 1].start - t <= 2 * period
        assert i in e.blinder_heavy or swell, f"blinders lit at {t:.1f}s in phrase {i} ({plan[i].section})"
    starts = int(np.sum(on[1:] & ~on[:-1]))
    assert starts <= 2 * (1 + 2 + 1), f"{starts} punches"  # per heavy phrase: swell, slam, two punches
