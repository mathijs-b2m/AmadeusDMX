"""A track that plays before it is prepared gets a stand-in groove on its tempo: lit, on the beat, no flicker, heads
moving, and it loops on the beat grid."""

from pathlib import Path

import numpy as np
import pytest

from amadeus.rig.loader import load_rig
from amadeus.show import standin
from amadeus.show.sources.base import Deck
from tests.test_flicker import FPS, fast_cycles

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
BPM = 124.0


def _loop(rig):
    return standin.build(rig, BPM, standin.LOOP_PHRASES * standin.BARS * 4 * 60.0 / BPM)


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_standin_lights_follow_the_beat(path):
    rig = load_rig(path)
    a, plan, engine, name = _loop(rig)
    assert name == standin.NAME and a.bpm == BPM
    assert {d.section for d in plan} <= {"groove", "intro"}  # a plain groove: no drops, no breakdowns
    ids = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    heads = [x["id"] for x in rig["elements"] if x["kind"] == "head"]
    ts = np.arange(0.05, a.duration - 0.1, 1 / FPS)
    frames = [engine.render(float(t))[1] for t in ts]
    level = np.array([[max(st[i].dimmer, st[i].white) for i in ids] for st in frames])
    assert (level.max(axis=1) > 0.05).all()  # never dark
    assert sum(fast_cycles(c) for c in level.T) == 0  # no flicker
    if heads:  # heads keep moving
        pan = np.array([[st[h].pan for h in heads] for st in frames])
        assert np.ptp(pan, axis=0).max() > 0.02


def test_beats_on_the_tracks_tempo():
    a = standin.groove_analysis(BPM, 60.0)
    assert np.allclose(np.diff(a.beats), 60.0 / BPM)
    assert a.beats[0] == 0.0 and (a.onsets["kick"][0] == a.beats).all()


def test_loop_wraps_on_the_beat_grid():
    rig = load_rig(SETS[0])
    show = _loop(rig)
    beat = 60.0 / BPM
    loop = show[0].duration
    assert abs(loop / beat - round(loop / beat)) < 1e-6  # a whole number of beats: wrapping keeps the beat
    pos = 3 * loop + 5 * beat
    assert standin.StandIns.position(show, pos) == pytest.approx(5 * beat)


def test_tempo_from_the_deck():
    def deck(bpm, bpm0):
        return Deck(1, "x.mp3", 10.0, 300.0, True, bpm, bpm0, 1.0, 0.0)

    assert standin.track_bpm(deck(130.0, 125.0)) == 125.0  # the track's own tempo: positions are track seconds
    assert standin.track_bpm(deck(0.0, 0.0)) == standin.DEFAULT_BPM
