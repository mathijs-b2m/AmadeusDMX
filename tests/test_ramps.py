"""Tempo ramps (amadeus/audio/ramps.py): a part that speeds up off the grid becomes the beats there, and builds."""

from types import SimpleNamespace

import numpy as np

from amadeus.audio import ramps

FPS = 86.0
GRID = np.arange(0.0, 90.0, 0.4)  # 150 BPM, straight through (what a one-tempo grid gives)


def _flux(times, strength=1.0, n=int(90 * FPS)):
    env = np.zeros(n)
    for t in times:
        env[int(round(t * FPS))] = max(env[int(round(t * FPS))], strength)
    return env


def _build(start=30.0, end=55.0, gap0=0.8, gap1=0.25):
    """Hits whose gap shrinks steadily from gap0 to gap1 (an accelerating build)."""
    out, t = [], start
    while t < end:
        out.append(t)
        t += gap0 + (gap1 - gap0) * (t - start) / (end - start)
    return np.array(out)


def _track(build_hits, kick_under=False):
    """A 150 BPM kick, quiet over the build unless `kick_under`, and the build's hits."""
    kicks = GRID if kick_under else GRID[(build_hits[0] - 0.2 > GRID) | (build_hits[-1] + 0.2 < GRID)]
    return np.maximum(_flux(kicks), _flux(build_hits, 0.9))


def test_an_accelerating_build_off_the_grid_is_a_ramp():
    hits = _build()
    found = ramps.find(_track(hits), FPS, GRID)
    assert len(found) == 1
    r = found[0]
    assert hits[0] <= r.start < hits[0] + 2.0 and r.end > hits[-1] - 1.0  # (its first hits on the grid: left to it)
    assert r.bpm_from < 85 and r.bpm_to > 200
    assert np.all(np.diff(r.beats) >= ramps.MIN_BEAT_S - 0.03)  # a roll at its top is played every second hit


def test_a_steady_beat_under_it_keeps_the_grid():
    """A layer speeding up over a kick that keeps running (a delay, a riser): the kick is the beat."""
    assert ramps.find(_track(_build(), kick_under=True), FPS, GRID) == []


def test_a_steady_tempo_is_no_ramp():
    assert ramps.find(_flux(GRID), FPS, GRID) == []


def test_splice_puts_the_ramp_in_and_keeps_the_bars_outside():
    r = ramps.find(_track(_build()), FPS, GRID)[0]
    bars = GRID[::4]
    beats, lines = ramps.splice(GRID, bars, [r])
    inside = beats[(beats >= r.start) & (beats <= r.end)]
    assert np.allclose(inside, r.beats, atol=1e-6)
    before, after = bars[bars < r.start - 0.2], bars[bars > r.end + 0.2]
    assert set(np.round(before, 3)) <= set(np.round(lines, 3)) and set(np.round(after, 3)) <= set(np.round(lines, 3))
    assert np.all(np.isin(np.round(lines, 6), np.round(beats, 6)))  # every bar line is a beat


def test_a_loud_ramp_builds_and_a_slowdown_winds_down():
    loud = SimpleNamespace(ramp=0.8)
    assert ramps.section(loud, "drop") == "buildup"
    assert ramps.section(SimpleNamespace(ramp=-0.8), "groove") == "breakdown"
    assert ramps.section(SimpleNamespace(ramp=-0.8), "outro") == "outro"
    assert ramps.section(SimpleNamespace(ramp=0.2), "drop") == "drop"
    assert ramps.share([ramps.Ramp(10.0, 20.0, 80, 160, np.zeros(0))], 10.0, 30.0) == 0.5
