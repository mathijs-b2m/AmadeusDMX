"""The tilt wave (a row of heads tilting in a wave) and randomly pulsing heads."""

from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.director.arc import apply_arc
from amadeus.engine import Engine
from amadeus.engine import looks as L
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis


@pytest.fixture(scope="module")
def show():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    k = next(i for i, d in enumerate(plan) if d.section == "groove")
    plan[k] = replace(plan[k], movement="tilt_wave", formation="wave", aim="crowd", head_light="random", intensity=2)
    rig = load_rig("tests/sets/concert60.json")
    return a, plan, k, Engine(a, plan, rig, real_output=False)


def _elevation(dirs: np.ndarray) -> np.ndarray:
    return np.degrees(np.arcsin(np.clip(dirs[:, 2], -1, 1)))


def test_the_heads_tilt_in_a_wave_that_rolls_over_the_row(show):
    _, plan, k, e = show
    d = plan[k]
    ts = np.linspace(d.start + 1, d.end - 1, 400)
    row = sorted(range(len(e.heads)), key=lambda j: e.head_pos[j][0])[:12]  # the front row, left to right
    el = np.array([_elevation(e._head_dir_v(d, ts, j)) for j in row])
    swing = el.max(axis=1) - el.min(axis=1)
    assert np.all(swing > 30)  # every head tilts far up and down…
    az = np.degrees(np.arctan2(*e._head_dir_v(d, ts, row[0])[:, :2].T))
    assert np.ptp(az) < 1  # …without panning
    # …and the wave rolls: the further along the row, the later a head reaches its top
    lags = [int(np.argmax(np.correlate(el[i] - el[i].mean(), el[0] - el[0].mean(), "full"))) for i in range(len(row))]
    assert lags[-1] != lags[0] and np.all(np.diff(lags[1:]) * np.sign(lags[-1] - lags[0]) >= 0)


def test_random_heads_pulse_on_their_own_kicks(show):
    _, plan, k, e = show
    d = plan[k]
    ts = np.arange(d.start + 0.5, d.end - 0.5, 0.02)
    accents = set().union(*(e._accent_players(d, t) for t in np.arange(d.start, d.end, 1.0)))
    heads = [h["id"] for h in e.heads if h["id"] not in accents][:8]  # (the rhythm lights all along)
    lit = np.array([[e.render(float(t))[1][h].dimmer > 0.05 for h in heads] for t in ts])
    share = lit.mean()
    assert 0.1 < share < 0.5  # on part of the time
    assert len({tuple(col) for col in lit.T}) == len(heads)  # every head its own pattern
    for j in range(16):  # never two kicks in a row: pulses, not a flicker into steady light
        on = [L._chance(j, s) and not L._chance(j, s - 1) for s in range(200)]
        assert not any(a and b for a, b in zip(on, on[1:]))


def test_both_stay_out_of_calm_moments():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    calm = replace(plan[0], section="breakdown", movement="tilt_wave", head_light="random", intensity=2)
    apply_arc(calm, {"role": "", "energy": 0.3}, None, None)
    assert calm.movement != "tilt_wave" and calm.head_light != "random"
    busy = replace(plan[0], section="groove", movement="tilt_wave", head_light="random", intensity=2)
    apply_arc(busy, {"role": "", "energy": 0.8}, None, None)
    assert busy.movement == "tilt_wave" and busy.head_light == "random"
