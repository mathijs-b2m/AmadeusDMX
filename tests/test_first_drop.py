"""A pop song's first drop: bars from the music rather than from its first sound, and a drop that ends where the
kick does (the shape of Coldplay's "A Sky Full of Stars", which came out as a groove a beat early)."""

import numpy as np

from amadeus.audio.beats import downbeats
from amadeus.audio.model import DROP_THRESHOLD
from amadeus.audio.phrases import build_phrases

FPS = 50
BEAT = 25  # frames: 120 BPM


def low_end(levels: list[tuple[int, float]], beats: int) -> np.ndarray:
    """The low end in dB, frame by frame: (from this beat on, this level)."""
    low = np.empty(beats * BEAT)
    for start, level in levels:
        low[start * BEAT :] = level
    return low


def test_the_first_sound_after_silence_does_not_set_the_bars():
    # digital silence, the piano comes in on beat 6, and everything after it changes on beats 4n + 3
    beats = 400
    low = low_end(
        [
            (0, -90.0),
            (6, 20.0),
            (71, 32.0),
            (119, 20.0),
            (167, 32.0),
            (199, 20.0),
            (239, 32.0),
            (295, 20.0),
            (359, 32.0),
        ],
        beats,
    )
    frames = np.arange(beats) * BEAT
    accents = np.ones(beats * BEAT)
    assert set(downbeats(frames, accents, low) % 4) == {3}


def song() -> tuple:
    """Quiet bars and sung bars with a few kicks climbing to a drop of 8 bars, 6 bars on its way out, a loud bridge
    and the big drop. Next to the climb, the first drop with its way out averaged in is no jump at all."""
    bars = [
        ("quiet", 40),
        ("verse", 40),
        ("climb", 14),
        ("drop", 8),
        ("out", 6),
        ("bridge", 30),
        ("drop", 16),
        ("verse", 8),
    ]
    level = {
        "quiet": (8.0, 12.0, 14.0),
        "verse": (10.0, 16.0, 17.0),
        "climb": (11.5, 25.0, 17.0),
        "out": (12.0, 26.0, 16.0),
        "bridge": (14.5, 30.0, 18.0),
        "drop": (15.5, 32.0, 15.0),
    }
    n = sum(b for _, b in bars) * 4 * BEAT
    beat_times = np.arange(n // BEAT) * BEAT / FPS
    rms, low, mid = np.zeros(n), np.zeros(n), np.zeros(n)
    kicks, at, starts = [], 0, {}
    for part, length in bars:
        frames = slice(at * 4 * BEAT, (at + length) * 4 * BEAT)
        rms[frames], low[frames], mid[frames] = level[part]
        starts.setdefault(part, []).append(at)
        step = {"drop": 1, "out": 2}.get(part, 4)
        kicks += list(beat_times[at * 4 : (at + length) * 4 : step])
        at += length
    feats = {
        "rms": rms,
        "sub": low,
        "bass": low - 3,
        "mid": mid,
        "high": mid - 15,
        "air": mid - 20,
        "centroid": np.full(n, 2000.0),
    }
    none = (np.zeros(0), np.zeros(0))
    onsets = {"kick": (np.array(kicks), np.ones(len(kicks))), "snare": none, "hat": none, "accent": none}
    return feats, beat_times, onsets, starts


def test_a_first_drop_ends_with_its_kick_and_stays_a_drop():
    feats, beat_times, onsets, starts = song()
    phrases = build_phrases(feats, FPS, beat_times, np.arange(0, len(beat_times), 4), onsets)
    at = starts["drop"][0] * 2.0  # seconds: two to the bar
    drop = next(p for p in phrases if abs(p.start - at) < 0.01)
    assert drop.end == at + 16.0  # its 8 bars, not the way out behind them
    assert drop.drop_score >= DROP_THRESHOLD
