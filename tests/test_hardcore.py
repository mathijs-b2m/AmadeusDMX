"""Hardcore: its tempo, its sound, and its two faces (Thunderdome's red and white, happy hardcore's rave colours)."""

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
