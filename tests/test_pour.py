"""The pour: lit high at the top, a fast fall to the floor, let go there, back up in the dark for the next beat."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.director.arc import apply_arc
from amadeus.director.vocabulary import MOVEMENTS
from amadeus.engine import Engine
from amadeus.rig import geometry
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

RIGS = sorted(p.stem for p in Path("tests/sets").glob("*.json"))
DT = 0.02


@pytest.fixture(scope="module")
def track():
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(), verbose=False)


def _play(track, rig_name, formation="sync", grouping="unison"):
    a, plan = track
    plan = list(plan)
    k = next(i for i, d in enumerate(plan) if d.section == "drop")
    plan[k] = replace(plan[k], movement="pour", formation=formation, grouping=grouping, aim="crowd",
                      head_light="steady", intensity=3)
    e = Engine(a, plan, load_rig(f"tests/sets/{rig_name}.json"), real_output=False)
    d = plan[k]
    if not e.heads:
        pytest.skip("no moving heads")
    accents = set().union(*(e._accent_players(d, t) for t in np.arange(d.start, d.end, 0.25)))
    js = [j for j, h in enumerate(e.heads) if h["id"] not in accents]
    if not js:
        pytest.skip("every head plays the synth's accents here")
    ts = np.arange(d.start + 2, d.start + 9, DT)  # (past the drop moment)
    light, el = np.zeros((len(js), len(ts))), np.zeros((len(js), len(ts)))
    for i, t in enumerate(ts):
        states = e.render(float(t))[1]
        for r, j in enumerate(js):
            s = states[e.heads[j]["id"]]
            fx, defn = e.head_fx[j]
            light[r, i] = max(s.dimmer, s.white)
            el[r, i] = np.degrees(np.arcsin(np.clip(geometry.fk(fx, defn, s.pan, s.tilt)[2], -1, 1)))
    return e, d, js, ts, light, el


def _onsets(lit: np.ndarray, ts: np.ndarray) -> np.ndarray:
    on = lit > 0.5 * max(lit.max(), 1e-6)
    return ts[1:][on[1:] & ~on[:-1]]


@pytest.mark.parametrize("rig_name", RIGS)
def test_lit_falling_dark_rising_on_every_rig(track, rig_name):
    e, d, js, ts, light, el = _play(track, rig_name)
    period_s = e._pour_period(d) * float(np.median(np.diff(e.beats)))
    falls = np.ptp(el, axis=1)
    assert np.mean(falls > 25) > (0.5 if rig_name == "zones" else 0.9)  # a real fall, top to floor (not into zones)
    for r in range(len(js)):
        lit = light[r] > 0.5 * light[r].max()
        rising = np.gradient(el[r], DT) > 60  # flying back up
        assert (lit & rising).mean() < 0.03  # (a slow head may finish its climb as the hit comes)
        falling = np.gradient(el[r], DT) < -60
        if falling.any():
            assert lit[falling].mean() > 0.8  # the light rides the fall
        onsets = _onsets(light[r], ts)
        assert len(onsets) <= (ts[-1] - ts[0]) / period_s + 1  # one hit per pour: no flicker, no flashes at the floor
        beats = np.asarray(e.beats)
        assert all(np.min(np.abs(beats - t)) < 0.1 for t in onsets)  # the hit lands on a beat


def test_a_wave_pours_one_head_after_the_other(track):
    e, d, js, ts, light, el = _play(track, "concert60", formation="wave")
    row = sorted(js, key=lambda j: e.head_pos[j][0])
    firsts = [float(_onsets(light[js.index(j)], ts)[0]) for j in row[:: max(1, len(row) // 6)]]
    assert len(set(np.round(firsts, 2))) > 3  # a cascade, not a curtain


def test_individually_each_head_on_its_own_beat(track):
    e, d, js, ts, light, el = _play(track, "concert60", grouping="individual")
    firsts = [float(_onsets(light[r], ts)[0]) for r in range(len(js)) if len(_onsets(light[r], ts))]
    assert len(set(np.round(firsts, 1))) >= 3  # mixed…
    beats = np.asarray(e.beats)
    assert all(np.min(np.abs(beats - t)) < 0.1 for t in firsts)  # …but every hit on a beat


def test_the_directors_offer_it_but_not_in_calm_parts(track):
    assert "pour" in {name for name, _ in MOVEMENTS}
    _, plan = track
    d = replace(plan[0], section="breakdown", movement="pour", intensity=1)
    apply_arc(d, {"role": "breakdown"}, lasers=False, groups=None)
    assert d.movement != "pour"
