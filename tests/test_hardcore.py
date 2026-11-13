"""Hardcore: its tempo, its sound, and its two faces (Thunderdome's red and white, happy hardcore's rave colours)."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import genre, hardcore
from amadeus.audio.beats import kick_double, strongest_tempo
from amadeus.director import RuleDirector, direct
from amadeus.director.style import (
    HAPPY_DROP,
    HAPPY_HARDCORE,
    HARDCORE_DROP,
    PIANO_BREAK,
    STYLES,
    SetGenre,
    check,
    style_for,
)
from amadeus.engine import Engine
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis
from tests.test_reggaeton import flicker

SETS = sorted(Path("tests/sets").glob("*.json"))
FPS = 43.0

# what the style model heard on real tracks (amadeus/audio/hardcore.py)
RAINBOW = {"hardcore": 1.65, "hardcore_lead": 1.0, "happy": 0.54}  # Paul Elstak, 1995
PARTY_ANIMALS = {"hardcore": 0.87, "hardcore_lead": 0.92, "happy": 0.58}
HARD_REMIX = {"hardcore": 1.05, "hardcore_lead": 0.8, "happy": 0.07}
NOT_GABBER = {"hardcore": 0.45, "hardcore_lead": 0.42, "happy": 0.12}  # hardstyle, called GABBER
HARDSTYLE = {"hardcore": 0.16, "hardcore_lead": 0.11, "happy": 0.31}  # Max Enforcer


def _kicks(bpm: float, seconds: float = 120.0, every: int = 1, off: float = 0.0) -> np.ndarray:
    """A low end that rises on a kick every `every` beats; the beats between rise `off` as much."""
    env = np.zeros(int(seconds * FPS))
    for k, t in enumerate(np.arange(0.5, seconds - 1, 60.0 / bpm)):
        env[int(t * FPS)] = 1.0 if k % every == 0 else off
    return env


def _double(env) -> bool:
    bpm, score = strongest_tempo(env, FPS)
    return kick_double(env, FPS, bpm, score)


def test_a_kick_on_every_beat_at_168_is_not_84():
    assert _double(_kicks(168.0))


def test_a_real_84_stays_84():
    assert not _double(_kicks(84.0))  # nothing between the kicks
    assert not _double(_kicks(168.0, every=2, off=0.4))  # …or a bass note, much softer than the kick


def test_a_band_in_double_time_is_not_counted_up():
    assert not kick_double(_kicks(208.0), FPS, 104.0, 1.0)


def _facts(sound: dict, bpm: float = 168.0, **more) -> dict:
    return {**genre.facts(synthetic_analysis(bpm=bpm)), **sound, **more}


@pytest.mark.parametrize("sound", [RAINBOW, PARTY_ANIMALS, HARD_REMIX], ids=["rainbow", "party-animals", "hard-remix"])
def test_hardcore_sounds_like_hardcore(sound):
    assert genre.from_audio(_facts(sound)) == "hardcore"
    assert genre.from_audio(_facts(sound, song=True)) == "hardcore"  # there is a singer: still hardcore


@pytest.mark.parametrize("sound", [NOT_GABBER, HARDSTYLE], ids=["not-gabber", "hardstyle"])
def test_hardstyle_is_not_hardcore(sound):
    assert genre.from_audio(_facts(sound, bpm=156.0, kick_share=0.83)) == "hardstyle"


def test_without_the_models_the_kick_tells_hardcore_from_drum_and_bass():
    assert genre.from_audio(_facts({}, bpm=170.0, kick_share=0.95, groove=0.8, song=None)) == "hardcore"
    assert genre.from_audio(_facts({}, bpm=174.0, kick_share=0.5, groove=0.8, song=None)) == "dnb"


def test_hardcore_has_hardcore_tempo():
    assert genre.from_audio(_facts(RAINBOW, bpm=84.0)) != "hardcore"


@pytest.mark.parametrize(
    "tag, out",
    [("Happy Hardcore", "hardcore"), ("Gabber", "hardcore"), ("Frenchcore", "hardcore"), ("Hardstyle", "hardstyle"),
     ("Hardcore Punk", "rock"), ("Hardcore Hip-Hop", "hiphop")],
)  # fmt: skip
def test_tags(tag, out):
    assert genre.from_tag({"genre": tag}) == out


def test_a_hard_dance_call_on_clear_hardcore_is_hardcore():
    assert genre._kind_of("hardstyle", _facts(RAINBOW)) == "hardcore"
    assert genre._kind_of("edm", _facts(PARTY_ANIMALS)) == "hardcore"
    assert genre._kind_of("hardstyle", _facts(NOT_GABBER)) == "hardstyle"
    assert genre._kind_of("pop", _facts(RAINBOW)) == "pop"


def test_heard_for_certain_it_keeps_its_own_style_in_a_set(monkeypatch):
    monkeypatch.setattr(genre, "overrides", lambda: {})
    monkeypatch.setattr(genre, "tags", lambda path: {})
    monkeypatch.setattr(genre.sound, "facts", lambda path: RAINBOW)
    call = genre.detect(synthetic_analysis(bpm=168.0), ask_model=False)
    assert (call.genre, call.source) == ("hardcore", "sound")
    s = SetGenre()
    s.genre_for("a", "edm", "audio")
    assert s.genre_for("b", call.genre, call.source) == "hardcore"  # not "played in the set's edm style"


def test_judge_counts_the_family_against_hardstyle_and_dnb():
    names = [*hardcore.FAMILY, *(c for fam in hardcore.RIVALS.values() for c in fam), "Rock---Hardcore"]
    styles = np.zeros((4, len(names)))
    styles[:3, names.index(hardcore.HAPPY)] = 0.6
    styles[:3, names.index("Electronic---Gabber")] = 0.2
    styles[3, names.index("Electronic---Hardstyle")] = 0.7
    styles[:, names.index("Rock---Hardcore")] = 0.9  # a punk band doesn't count
    assert hardcore.judge(styles, names) == {"hardcore": 0.6, "hardcore_lead": 0.75, "happy": 0.75}


def test_the_two_faces():
    assert style_for("hardcore", RAINBOW) is HAPPY_HARDCORE
    assert style_for("hardcore", HARD_REMIX) is STYLES["hardcore"]
    assert style_for("hardcore") is STYLES["hardcore"]
    assert HAPPY_HARDCORE.genre == "hardcore" and "rave" in HAPPY_HARDCORE.palettes
    assert not check()


def _plan(a, rig, style):
    return direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")), style), verbose=False)


@pytest.mark.parametrize("style", [STYLES["hardcore"], HAPPY_HARDCORE], ids=["hardcore", "happy"])
def test_the_kick_plays_the_body_and_the_drops_go_big(style):
    a, rig = synthetic_analysis(bpm=170.0), load_rig(SETS[0])
    plan = _plan(a, rig, style)
    assert all(d.palette in style.palettes for d in plan)
    body = [d for d in plan if d.section in ("groove", "drop") and d.trigger != "accents"]
    assert body and all(d.trigger == "kick" and d.par_accent != "none" for d in body)
    drops = [d for d in plan if d.section == "drop"]
    look = HAPPY_DROP if style.flavour else HARDCORE_DROP
    assert drops and all(d.movement == look["movement"] and d.head_color == "white" for d in drops)


def test_a_kick_on_half_the_beats_is_a_break_in_hardcore():
    a = synthetic_analysis(bpm=170.0)
    rig = load_rig(SETS[0])
    i = len(a.phrases) // 2
    p = a.phrases[i]
    p.kick_ratio, p.drop_score, p.low_pct, p.loudness_pct = 0.54, 0.0, 40.0, 50.0  # a bass note on every other beat
    a.phrases[i + 1].drop_score = 0.0
    assert _plan(a, rig, STYLES["house"])[i].section != "breakdown"
    d = _plan(a, rig, HAPPY_HARDCORE)[i]
    assert d.section == "breakdown"
    assert (d.par_accent, d.trigger, d.aim) == (PIANO_BREAK["par_accent"], "lead", "sky")


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
@pytest.mark.parametrize("bpm", [170.0, 195.0])
def test_no_more_flicker_than_edm(path, bpm):
    """Hardcore used to be lit as edm: its own faces hit the kick harder, yet chop no more."""
    a, rig = synthetic_analysis(bpm=bpm), load_rig(path)
    base = flicker(Engine(a, _plan(a, rig, STYLES["edm"]), rig), rig, a)
    for style in (STYLES["hardcore"], HAPPY_HARDCORE):
        assert flicker(Engine(a, _plan(a, rig, style), rig), rig, a) <= base


def test_with_the_style_model_the_sound_doubles_not_the_bass():
    from amadeus.audio.analysis import twice_as_fast

    eighths = _kicks(200.0)  # a band's bass in eighths under a 100 BPM song rises like a kick at 200
    bpm, score = strongest_tempo(eighths, FPS)
    assert twice_as_fast(eighths, FPS, bpm, score, {})  # no models: the kick is all there is to go by
    assert not twice_as_fast(eighths, FPS, bpm, score, {"hardcore": 0.02, "hardcore_lead": 0.0})


# "Kind van de Duivel" (Jebroer, Paul Elstak): a hard track whose kick is its low end, loud from its first synth. Its
# kick was heard on a third of the beats in its drops, so two of its three drops played as soft breakdowns.


def _pumping_sub(period: float = 0.387, beats: int = 64, fps: float = FPS):
    """A sub at 40 dB that drops 22 dB right at every beat: the gap a hardcore kick leaves."""
    frames = (np.arange(beats) * period * fps + 10).astype(int)
    sub = np.full(frames[-1] + 40, 40.0)
    for b in frames:
        sub[b - 1 : b + 2] = 18.0
    return sub, frames


def test_a_kick_that_is_the_low_end_is_heard_by_its_gap():
    from amadeus.audio.beats import pumping_kicks

    sub, frames = _pumping_sub()
    t, s = pumping_kicks(sub, frames, frames / FPS)
    assert len(t) == len(frames) - 1 and (s > 0.9).all()  # every beat but the last (no beat after it)
    flat = np.full_like(sub, 40.0)  # a held bass: no gaps, no kicks
    assert len(pumping_kicks(flat, frames, frames / FPS)[0]) == 0
    quiet = sub.copy()
    quiet[: len(sub) // 3] -= 40  # the gaps in a quiet third are no kick (the sub there is under the median)
    t, _ = pumping_kicks(quiet, frames, frames / FPS)
    assert len(t) and t.min() >= len(sub) // 3 / FPS - 0.387  # (a beat counts by the sub after it)


def test_a_hard_grid_runs_through_the_kicks_gaps():
    from amadeus.audio.beats import constant_grid
    from amadeus.audio.features import normalize

    sub, frames = _pumping_sub(beats=200)
    rise = normalize(np.maximum(0, np.diff(sub, prepend=sub[0])))
    true = frames / FPS
    tracked = true[0] + np.arange(len(true)) * 0.388  # the tracker a little slow: a beat off after a minute
    grid = constant_grid(tracked, rise, FPS, agree=0.5, sub=sub)
    assert grid is not None
    assert abs(float(np.median(np.diff(grid))) - 0.387) < 0.0005


def test_a_hard_track_keeps_one_bar_phase():
    from amadeus.audio.beats import downbeats

    n, period = 128, 16
    frames = np.arange(n) * period + 8
    low = np.full(frames[-1] + period, 30.0)
    for start in (17, 49, 81, 113):  # the low end comes in on beat 2 of 4 (index 1) four times
        low[frames[start] : frames[min(start + 8, n - 1)]] = 45.0
    low[frames[64] : frames[66]] = 10.0  # one dropout on another phase
    accent = np.random.default_rng(1).random(len(low))
    idx = downbeats(frames, accent, low, one_phase=True)
    assert set(idx % 4) == {1} and len(idx) == n // 4


def test_hardcore_reads_its_own_form():
    a = synthetic_analysis(bpm=155.0)
    levels = [
        (9, 7, 0.6),
        (37, 35, 0.12),
        (47, 40, 0.69),
        (80, 73, 0.95),
        (43, 35, 0.38),
        (54, 48, 0.4),
        (76, 80, 1.0),
        (70, 70, 1.0),
        (25, 68, 0.75),
    ]  # fmt: skip  (Kind van de Duivel, measured)
    span = a.duration / len(levels)
    a.phrases = [
        replace(a.phrases[0], index=k, start=k * span, end=(k + 1) * span, loudness_pct=lo, low_pct=low,
                kick_ratio=kick, drop_score=0.8 if k in (3, 6) else 0.0, part="", loudness_slope_db=1.0)
        for k, (lo, low, kick) in enumerate(levels)
    ]  # fmt: skip
    plan = direct(a, RuleDirector(style=STYLES["hardcore"]), verbose=False)
    assert [d.section for d in plan] == ["intro", "breakdown", "buildup", "drop", "breakdown", "buildup", "drop",
                                         "drop", "groove"]  # fmt: skip
    assert all(d.intensity == 3 and d.head_light == "strobe" for d in plan if d.section == "drop")  # each one
    between = [d for d in plan if d.section in ("breakdown", "buildup", "groove")]
    assert all(d.intensity >= 2 and d.par_accent == "run" and d.head_light != "breathe" for d in between)


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_a_run_hits_each_light_once_a_lap_in_small_groups(path):
    from amadeus.engine.looks import RUN_STEPS
    from amadeus.engine.timing import MIN_GAP_S

    a, rig = synthetic_analysis(bpm=170.0), load_rig(path)
    plan = [replace(d, par_accent="run", head_light="run", trigger="kick", grouping="unison", layer_split="none")
            for d in _plan(a, rig, STYLES["hardcore"])]  # fmt: skip
    e = Engine(a, plan, rig)
    for kind in ("par", "head"):
        steps = {n for _, n in e._run_units(kind).values()}
        assert steps <= set(range(1, RUN_STEPS + 1))
    ids = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    ts = np.arange(0.05, a.duration - 0.1, 1 / 100)
    for d in plan:
        for eid, kind in [(x["id"], x["kind"]) for x in rig["elements"] if x["id"] in ids][:12]:
            shots = [t for t in ts[(ts >= d.start) & (ts < d.end)] if (e.run(d, float(t), eid, kind) or 0) >= 0.999]
            starts = [t for k, t in enumerate(shots) if k == 0 or t - shots[k - 1] > 0.02]
            assert all(b - x >= MIN_GAP_S - 0.02 for x, b in zip(starts, starts[1:])), (d.section, eid)


def test_a_hard_drop_lands_where_its_bass_comes_in():
    from amadeus.audio.phrases import _bass_entry

    fps, period = 43.0, 0.387
    beats = np.arange(40) * period + 1.0
    sub = np.full(int(beats[-1] * fps) + 40, -25.0)
    bar = 20  # the bar line the phase found; the bass comes in a beat before it
    sub[int(beats[bar - 1] * fps) :] = 40.0
    assert _bass_entry({"sub": sub}, fps, beats, float(beats[bar])) == pytest.approx(beats[bar - 1])
    stutter = sub.copy()  # on and off every other beat first: the entry is where it stays
    for k in (bar - 3, bar - 1):
        stutter[int(beats[k] * fps) : int(beats[k + 1] * fps)] = -25.0
    assert _bass_entry({"sub": stutter}, fps, beats, float(beats[bar])) == pytest.approx(beats[bar])
