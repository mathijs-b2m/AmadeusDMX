"""The beat grid against audio whose beats are known exactly."""

import numpy as np
import soundfile as sf

from amadeus.audio.analysis import analyze
from amadeus.audio.beats import attack_offset, constant_grid, refine_beats

SR = 44100
BEAT = 31 / 64  # 123.87 BPM: not a round number of analysis frames


def click_track(path, seconds=60.0, offbeat_bass_until=0.0):
    """A click on every beat (first at 0.0 s); optionally a louder mid-bass note on every off-beat at first,
    so that a tracker is tempted to lock half a beat off there."""
    y = np.zeros(int(SR * seconds), dtype=np.float32)
    n = int(0.03 * SR)
    env = np.exp(-np.arange(n) / (0.006 * SR))
    kick = (
        0.8 * np.sin(2 * np.pi * 55 * np.arange(n) / SR) * env
        + 0.3 * np.sin(2 * np.pi * 1500 * np.arange(n) / SR) * env
    )
    for k in range(int(seconds / BEAT)):
        i = int(round(k * BEAT * SR))
        y[i : i + n] += kick[: len(y) - i]
        o = int(round((k + 0.5) * BEAT * SR))
        if o * 1.0 / SR < offbeat_bass_until and o + n < len(y):
            y[o : o + n] += 1.0 * np.sin(2 * np.pi * 150 * np.arange(n) / SR) * env
    sf.write(path, y, SR)


def errors_ms(beats):
    return (beats - np.round(beats / BEAT) * BEAT) * 1000


def test_beats_land_on_the_clicks(tmp_path):
    click_track(tmp_path / "click.wav")
    a = analyze(tmp_path / "click.wav", cache_dir=tmp_path, verbose=False)
    e = errors_ms(np.asarray(a.beats))
    assert abs(a.bpm - 60 / BEAT) < 0.05
    assert abs(np.median(e)) < 3 and np.max(np.abs(e)) < 8


def test_a_half_beat_off_stretch_is_put_back_on_the_kick(tmp_path):
    click_track(tmp_path / "offbeat.wav", seconds=90.0, offbeat_bass_until=30.0)
    a = analyze(tmp_path / "offbeat.wav", cache_dir=tmp_path, verbose=False)
    e = errors_ms(np.asarray(a.beats))
    assert np.max(np.abs(e)) < 8  # also in the first 30 s, where the off-beats are louder in the mid-bass


def test_constant_grid_keeps_out_of_a_changing_tempo():
    beats = np.cumsum(np.linspace(0.5, 0.45, 400))  # 120 → 133 BPM over the track
    assert constant_grid(beats, np.ones(int(beats[-1] * 50) + 10), 50.0) is None


def test_attack_offset_finds_where_the_hit_is_heard():
    audio = np.zeros(SR * 20, dtype=np.float32)
    beats = np.arange(1, 19, 0.5)
    n = int(0.02 * SR)
    for b in beats:  # each hit starts 15 ms after its beat
        i = int((b + 0.015) * SR)
        audio[i : i + n] = 0.8 * np.sin(2 * np.pi * 60 * np.arange(n) / SR)
    assert abs(attack_offset(audio, SR, beats) - 0.015) < 0.004


def test_constant_grid_stays_inside_the_track():
    """The tracker's last beat half a beat off the grid, right at the end: the grid's beat after it would fall
    past the last frame (and past the end of every envelope indexed by it)."""
    fps, period = 50.0, 0.5
    beats = np.r_[np.arange(0, 100) * period, 99.5 * period]
    low_rise = np.zeros(int(beats[-1] * fps) + 2)
    low_rise[np.round(np.arange(0, 100) * period * fps).astype(int)] = 1.0
    grid = constant_grid(beats, low_rise, fps)
    assert grid is not None
    assert np.round(grid * fps).max() < len(low_rise)


def test_refine_beats_stays_near_the_tracker():
    """An onset still rising past the window's edge, on an almost straight line: the parabola through it has
    its top seconds away (a cinematic intro put its first beat 0.19 s before the track started)."""
    fps = 50.0
    frames = np.array([6, 31, 56, 81])
    env = np.zeros(100)
    for b in frames:
        env[b + 1], env[b + 2], env[b + 3] = 0.0, 0.5 + 1e-9, 1.0  # the top of the window, still rising
    t = refine_beats(frames, env, fps)
    assert np.all(np.abs(t * fps - frames) <= 3)
