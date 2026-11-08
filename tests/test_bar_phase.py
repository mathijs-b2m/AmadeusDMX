"""The bar phase only flips where the music in that stretch backs it: the 64-beat vote looks far beyond its window."""

import numpy as np

from amadeus.audio.beats import _chord_changes, _settled, downbeats

BEAT = 25  # frames


def on(n: int, beats: list[int]) -> np.ndarray:
    out = np.zeros(n)
    out[beats] = 1.0
    return out


NONE = np.zeros(384)
OUTSIDE = [0, 16, 32, 48, 256, 272, 288, 304]  # low-end changes on phase 0, before and after the stretch
PHASES = [0, 0, 1, 1, 0, 0]  # the vote's phase per 64 beats: beats 128..255 stand on phase 1


def settled(changes, chords=NONE, slams=NONE) -> list[list[int]]:
    return _settled(PHASES, 384, changes, chords, slams.astype(bool))


def test_a_stretch_with_nothing_of_its_own_joins_its_neighbours():
    assert settled(on(384, OUTSIDE)) == [[0, 384, 0]]


def test_one_change_of_its_own_is_not_enough():
    assert settled(on(384, [*OUTSIDE, 129])) == [[0, 384, 0]]


def test_low_end_changes_of_its_own_keep_a_flip():
    runs = settled(on(384, [*OUTSIDE, 129, 161, 193]))
    assert [r[2] for r in runs] == [0, 1, 0]


def test_chord_changes_of_its_own_keep_a_flip():
    runs = settled(on(384, OUTSIDE), chords=on(384, [129, 145, 161, 177, 193, 136]))
    assert [r[2] for r in runs] == [0, 1, 0]


def test_a_slam_stays_on_a_bar_line_or_keeps_its_stretch_apart():
    assert [r[2] for r in settled(on(384, OUTSIDE), slams=on(384, [161]))] == [0, 1, 0]
    # on a third phase: joining would not reach it either, and it is no sign the stretch is wrong
    assert [r[2] for r in settled(on(384, OUTSIDE), slams=on(384, [162]))] == [0, 1, 0]
    # on the neighbour's bar lines: that says the stretch is wrong
    assert settled(on(384, OUTSIDE), slams=on(384, [160])) == [[0, 384, 0]]


def test_chord_changes_mark_where_the_harmony_turns():
    chords = np.zeros((64, 12))
    chords[:, 0] = 1.0
    chords[32:, 0] = 0.0
    chords[32:, 7] = 1.0
    assert int(np.argmax(_chord_changes(chords))) == 32


def test_accents_in_a_quiet_ending_do_not_flip_the_bars():
    # the low end changes on the one for 256 beats and then stays; the ending's accents happen to lean on beat 2
    beats = 640
    low = np.full(beats * BEAT, 20.0)
    for i, b in enumerate(range(16, 256, 16)):
        low[b * BEAT :] = 32.0 if i % 2 == 0 else 20.0
    frames = np.arange(beats) * BEAT
    accents = np.ones(beats * BEAT)
    accents[frames[(np.arange(beats) >= 384) & (np.arange(beats) % 4 == 1)]] = 2.0
    chroma = np.ones((beats * BEAT, 12))
    assert set(downbeats(frames, accents, low) % 4) == {0, 1}
    assert set(downbeats(frames, accents, low, chroma) % 4) == {0}
