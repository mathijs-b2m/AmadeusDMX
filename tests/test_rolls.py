"""A snare roll into a drop: the analysis hears its steps and the pause, the lights flash on the roll's own hits
(denser, brighter, more lights per step) within the flash limits, go dark for the pause and hit on the drop."""

import contextlib
import io
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import analysis, genre
from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.engine import rolls as R
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests import roll_track
from tests.synthetic import synthetic_analysis
from tests.test_flicker import fast_cycles

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
FPS = 200


@pytest.mark.parametrize("bpm,riser", [(128, False), (150, True), (174, False)])
def test_the_analysis_hears_the_steps_and_the_pause(tmp_path, monkeypatch, bpm, riser):
    monkeypatch.setattr(genre, "from_model", lambda *a, **k: None)  # (no AI call for the genre)
    truth = roll_track.make(tmp_path / "roll.wav", bpm=bpm, riser=riser)
    with contextlib.redirect_stdout(io.StringIO()):
        a = analysis.analyze(tmp_path / "roll.wav", cache_dir=tmp_path / "cache")
    drops = [p.start for p in a.phrases if p.drop_score >= 0.6]
    assert len(drops) == 1 and abs(drops[0] - truth["drop"]) < 0.05
    (start, drop), *_ = a.pauses
    assert abs(drop - drops[0]) < 1e-6 and abs(start - truth["pause"]) < (0.15 if riser else 0.03)
    build = (a.beats >= truth["build"] - 0.03) & (a.beats < start - 0.03)
    played = a.roll[build]
    steps = np.array(truth["steps"])[: len(played)]
    assert np.mean(played == steps) >= 0.9, "".join(map(str, played))
    assert not a.roll[a.beats < truth["build"] - 8 * 4 * 60 / bpm].any()  # no roll in the groove's first half
    assert not a.roll[a.beats >= start].any()  # the roll stops where the pause starts


def test_a_steady_groove_is_no_roll():
    """Kick on every beat with offbeat hats doesn't speed up: no roll, whatever its subdivision."""
    from amadeus.audio import rolls

    fps, beat = 200.0, 60 / 128
    beats = np.arange(0, 64 * beat, beat)
    flux = np.zeros(int(beats[-1] * fps) + 200)
    for b in beats:
        flux[int(b * fps)] = 1.0
        flux[int((b + beat / 2) * fps)] = 0.4  # the hats, weaker than the beat
    bars = beats[::4]
    roll, pauses = rolls.snare_rolls(flux, np.full(len(flux), -10.0), fps, beats, bars, [(0.0, 0.0, float(bars[-2]))])
    assert not roll.any() and not len(pauses)


# ------------------------------------------------------------------------------------------- the lights


@pytest.fixture(scope="module")
def rolled():
    """The synthetic track with a roll in its first build-up (4 bars quarters, 2 eighths, 1 sixteenths, 1
    thirty-seconds whose last beat is a pause) into the drop."""
    a = synthetic_analysis()
    drop = a.phrases[3].start
    first = int(np.searchsorted(a.beats, a.phrases[2].start - 0.01))
    roll = np.zeros(len(a.beats), np.int8)
    roll[first : first + 32] = [1] * 16 + [2] * 8 + [4] * 4 + [8] * 3 + [0]
    period = 60 / 128
    return replace(a, roll=roll, pauses=np.array([[drop - period, drop]])), first, drop


def _engine(a, path=SETS[0], **safety):
    rig = load_rig(path)
    rig["safety"].update(safety)
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    return Engine(a, plan, rig), rig


def _trace(e, rig, t0, t1, kinds=("head", "par", "strobe")):
    ids = [x["id"] for x in rig["elements"] if x["kind"] in kinds]
    ts = np.arange(t0, t1, 1 / FPS)
    tr = np.array([[max(st[i].dimmer, st[i].white) for i in ids] for st in (e.render(float(t))[1] for t in ts)])
    return ts, tr, ids


def _flashes(e, ts):
    """Per frame and light: how bright its flash is."""
    return np.array([[(e.roll_flashes(float(t)) or {}).get(eid, 0.0) for eid in e.roll_order] for t in ts])


def _ons(ts, x, threshold=0.2):
    up = (x[1:] >= threshold) & (x[:-1] < threshold)
    return ts[1:][up]


def test_the_roll_flashes_on_its_hits_within_the_flash_limit(rolled):
    a, first, drop = rolled
    e, rig = _engine(a, allow_fast_strobe=False)
    ts = np.arange(a.beats[first] - 0.2, drop - 60 / 128, 1 / FPS)
    tr = _flashes(e, ts)
    max_hz = rig["safety"]["max_flash_hz"]
    for c in tr.T:
        on = _ons(ts, c)
        assert np.all(np.diff(on) >= 1 / max_hz - 2 / FPS)  # no light faster than the limit
    rig_on = _ons(ts, tr.max(axis=1))
    assert np.all(np.diff(rig_on) >= 1 / max_hz - 2 / FPS)  # nor the rig as a whole
    beats = a.beats[first : first + 31]
    assert all(np.min(np.abs(beats - t)) < 0.012 for t in rig_on)  # on the beats (quarters fit 3 Hz at 128)


def test_more_lights_flash_brighter_as_the_roll_speeds_up(rolled):
    a, first, drop = rolled
    e, rig = _engine(a, path=next(p for p in SETS if p.stem == "concert60"))
    period = 60 / 128
    ts = np.array([a.beats[first + k] + 0.01 for k in (0, 16, 24, 28)])  # each step, just after a hit
    lit = [row[row > 0] for row in _flashes(e, ts)]
    assert [len(x) for x in lit] == sorted(len(x) for x in lit) and len(lit[-1]) > 2 * len(lit[0])
    assert lit[0].max() < lit[1].max() < lit[2].max() < lit[3].max()
    gap = _flashes(e, [a.beats[first] + 0.6 * period])[0]  # between the quarter notes: dark
    assert gap.max() == 0
    st = e.render(float(ts[0]))[1]  # and in the show: white
    assert all(min(st[eid].r, st[eid].g, st[eid].b) > 0.95 and st[eid].dimmer > 0.4 for eid in e.roll_order[:3])


def test_with_fast_strobe_the_lights_take_turns_on_the_fast_hits(rolled):
    a, first, drop = rolled
    e, rig = _engine(a, path=next(p for p in SETS if p.stem == "concert60"), allow_fast_strobe=True)
    t0 = float(a.beats[first + 28])  # the thirty-seconds (until the heads move in black to the drop's picture)
    ts = np.arange(t0 - 0.01, drop - 2 * 60 / 128 - 0.01, 1 / FPS)
    tr = _flashes(e, ts)
    for c in tr.T:
        assert np.all(np.diff(_ons(ts, c)) >= 1 / R.FAST_FLASH_HZ - 2 / FPS)  # each light within its limit
    rig_on = _ons(ts, tr.max(axis=1), threshold=0.05)
    assert len(rig_on) >= 2 * 8 - 1  # …while the rig plays every thirty-second


def test_strobe_free_plays_the_roll_in_steps(rolled):
    a, first, drop = rolled
    for path in SETS:
        e, rig = _engine(a, path=path, strobe_free=True)
        assert not len(e.flash_t)
        ts, tr, _ = _trace(e, rig, a.beats[first] - 0.5, drop + 4, kinds=("head", "par"))
        assert sum(fast_cycles(np.interp(np.arange(ts[0], ts[-1], 1 / 40), ts, c)) for c in tr.T) == 0, path.stem
        _, st, ids = _trace(e, rig, a.beats[first] - 0.5, drop - 0.01, kinds=("strobe",))
        assert not len(ids) or st.max() == 0  # (the drop's one hit is no strobe)


def test_dark_for_the_pause_then_the_drop_hits(rolled):
    a, first, drop = rolled
    e, rig = _engine(a)
    period = 60 / 128
    for t in np.arange(drop - period + 0.01, drop - 0.005, 0.02):  # the music's pause: a full beat
        assert all(max(s.dimmer, s.white) == 0 for s in e.render(float(t))[1].values())
    hit = e.render(drop + 0.01)[1]
    assert max(max(s.dimmer, s.white) for s in hit.values()) > 0.9


def test_without_a_roll_nothing_changes(rolled):
    a, first, drop = rolled
    with_roll, _ = _engine(a)
    without, _ = _engine(replace(a, roll=None, pauses=None))
    for t in (a.beats[first] - 1.0, drop + 0.3, drop + 30):
        assert with_roll.render(float(t))[1] == without.render(float(t))[1]
