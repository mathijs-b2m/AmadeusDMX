"""The whole-track tempo against the beat tracker's: a band's tempo off the whole numbers isn't traded for one at
two thirds of it, and a tempo the tracker counted double is still halved."""

import numpy as np

from amadeus.audio.analysis import whole_track_tempo

FPS = 46.875


def low_end(bpm: float, every: int, seconds: float = 240.0, also: tuple = (), seed: int = 1) -> np.ndarray:
    """The low end's rise per frame: a kick on every `every`-th beat, bass notes (`also`: beats, level) around it."""
    rng = np.random.default_rng(seed)
    env = rng.uniform(0, 0.08, int(seconds * FPS))
    beat = 60 / bpm
    for k in range(int(seconds / beat)):
        t = k * beat + rng.normal(0, 0.006)  # a drummer, not a machine
        if k % every == 0:
            env[int(round(t * FPS))] += 1.0
        for off, level in also:
            j = int(round((t + off * beat) * FPS))
            if k % every == 0 and j < len(env):
                env[j] += level
    return env / env.max()


def test_a_band_keeps_the_tempo_the_tracker_counted():
    # AC/DC's "Thunderstruck": 133.3 BPM, a kick every two beats, the bass on the beats between and around them;
    # the tracker counts whole frames (136.0)
    env = low_end(133.34, 2, also=((1.0, 0.5), (1.5, 0.45), (3.0, 0.3)))
    bpm, _ = whole_track_tempo(env, FPS, 136.0)
    assert abs(bpm / 133.34 - 1) < 0.01


def test_a_tempo_counted_double_is_still_halved():
    env = low_end(83.0, 1)  # a kick on every beat at 83; the tracker counted 161.5
    bpm, _ = whole_track_tempo(env, FPS, 161.5)
    assert abs(bpm / 83.0 - 1) < 0.01


def test_the_trackers_own_tempo_is_measured_finer():
    env = low_end(104.0, 1)
    bpm, _ = whole_track_tempo(env, FPS, 107.7)
    assert abs(bpm / 104.0 - 1) < 0.005
