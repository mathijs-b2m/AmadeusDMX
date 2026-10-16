"""Disco: told apart from house by its sound (the style model), lit as the mirror ball and the dance floor."""

from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import disco, genre
from amadeus.director import RuleDirector, direct
from amadeus.director.style import MIRROR_BALL, check, style_for
from amadeus.engine import Engine
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis
from tests.test_reggaeton import flicker

# what the style model heard on real tracks (amadeus/audio/disco.py): {"disco", "disco_lead"}
CHEMISE = {"disco": 0.76, "disco_lead": 0.98}  # "She Can't Love You", 1982
DIRTY_TALK = {"disco": 0.69, "disco_lead": 0.74}  # Klein & M.B.O., Italo-Disco
SABATO = {"disco": 0.39, "disco_lead": 0.64}  # I Coccodrilli, nu-disco
KUNGS = {"disco": 0.33, "disco_lead": 0.18}  # house with a disco sample
AFROBEAT = {"disco": 0.44, "disco_lead": 0.14}  # Jungle Fire: funk, not disco
HOUSE = {"disco": 0.12, "disco_lead": 0.0}


def _facts(sound: dict, bpm: float = 120.0, **more) -> dict:
    return {**genre.facts(synthetic_analysis(bpm=bpm)), **sound, **more}


def test_judge_counts_the_disco_family_against_funk_and_house():
    names = [c for fam in disco.FAMILIES.values() for c in fam] + ["Electronic---Techno"]
    styles = np.zeros((4, len(names)))
    styles[:3, names.index("Funk / Soul---Disco")] = 0.6  # three judgements disco …
    styles[3, names.index("Electronic---House")] = 0.7  # … one house
    styles[:, names.index("Electronic---Italo-Disco")] += 0.1
    assert disco.judge(styles, names) == {"disco": 0.55, "disco_lead": 0.75}


@pytest.mark.parametrize("sound", [CHEMISE, DIRTY_TALK, SABATO], ids=["chemise", "dirty-talk", "sabato"])
def test_disco_sounds_like_disco(sound):
    assert genre.from_audio(_facts(sound)) == "disco"
    assert genre.from_audio(_facts(sound, song=True)) == "disco"  # Donna Summer sings: still disco, not pop


@pytest.mark.parametrize("sound", [KUNGS, AFROBEAT, HOUSE, {}], ids=["kungs", "afrobeat", "house", "no-model"])
def test_house_and_funk_are_not_disco(sound):
    assert genre.from_audio(_facts(sound)) != "disco"


def test_disco_has_disco_tempo():
    assert genre.from_audio(_facts(CHEMISE, bpm=80.0)) != "disco"  # (a slow soft-rock song can sound a bit disco)
    assert genre.from_audio(_facts(CHEMISE, bpm=150.0)) != "disco"


def test_a_house_or_funk_call_on_clear_disco_is_disco(monkeypatch):
    monkeypatch.setattr(genre, "overrides", lambda: {})
    monkeypatch.setattr(genre, "tags", lambda path: {})
    a = synthetic_analysis(bpm=120.0)
    calls = [("house", DIRTY_TALK, "disco"), ("funk", CHEMISE, "disco"), ("house", SABATO, "house"),
             ("house", KUNGS, "house"), ("pop", CHEMISE, "pop"), ("disco", HOUSE, "disco")]  # fmt: skip
    for called, sound, out in calls:
        monkeypatch.setattr(genre.disco, "facts", lambda path, s=sound: s)
        monkeypatch.setattr(genre, "from_model", lambda artist, title, g=called: (g, 0.9))
        assert genre.detect(a).genre == out, (called, sound)


def test_no_model_no_disco_facts(monkeypatch, tmp_path):
    from amadeus.audio import instruments

    f = tmp_path / "track.wav"
    f.write_bytes(b"")
    monkeypatch.setattr(instruments, "available", lambda: False)
    assert disco.facts(f) == {} and disco.facts(tmp_path / "missing.wav") == {}


def test_tags():
    assert genre.from_tag({"genre": "Disco"}) == "disco"
    assert genre.from_tag({"genre": "Nu-Disco / Indie Dance"}) == "disco"
    assert genre.from_tag({"genre": "Italo-Disco"}) == "disco"
    assert genre.from_tag({"genre": "Disco House"}) == "house"
    assert genre.from_tag({"genre": "Funk / Disco"}) == "disco"
    assert genre.from_tag({"genre": "Boogie"}) == "funk"
    assert genre.from_tag({"genre": "Funk"}) == "funk"


def test_the_style_sheets_are_sound():
    assert check() == []
    assert "disco" in genre.GENRES and style_for("disco").palettes[0] == "disco"


SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))


@pytest.fixture(scope="module")
def track():
    return synthetic_analysis(bpm=120.0)


def _plan(a, rig, genre_name):
    return direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")), style_for(genre_name)),
                  verbose=False)  # fmt: skip


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_disco_is_the_dance_floor_and_the_mirror_ball(track, path):
    rig = load_rig(path)
    plan = _plan(track, rig, "disco")
    body = [d for d in plan if d.section in ("groove", "verse", "chorus")]
    assert body and all(d.trigger == "kick" for d in body)  # four to the floor leads
    assert all(d.par_base != "off" and d.par_accent not in ("none", "melody") for d in body)  # the floor stays lit
    assert all(d.movement not in ("nod", "bounce", "ballyhoo", "step_on_beat") for d in body)  # round, never hard
    breaks = [d for d in plan if d.section == "breakdown"]
    assert breaks and all(getattr(d, k) == v for d in breaks for k, v in MIRROR_BALL.items())
    assert all(d.palette in style_for("disco").palettes for d in plan)
    # and no more fast on-off cycles than the same track lit as house
    assert flicker(Engine(track, plan, rig), rig, track) <= flicker(Engine(track, _plan(track, rig, "house"), rig),
                                                                    rig, track)  # fmt: skip


def test_the_mirror_ball_is_a_moment():
    """A track the analysis hears as one long break (its kicks too soft) gets the mirror ball two phrases at a
    time, not all the way through."""
    track = synthetic_analysis(bpm=120.0)
    for p in track.phrases:
        p.kick_ratio, p.low_pct, p.loudness_pct, p.drop_score = 0.1, 10, 25, 0.0
    plan = _plan(track, load_rig(SETS[0]), "disco")
    assert sum(d.section == "breakdown" for d in plan) >= 5
    ball = [all(getattr(d, k) == v for k, v in MIRROR_BALL.items()) for d in plan]
    assert any(ball) and not any(all(ball[i : i + 3]) for i in range(len(ball) - 2))


def test_the_mirror_ball_turns(track):
    """In the break the heads keep moving (they never freeze) with their beams lit."""
    rig = load_rig(SETS[0])
    plan = _plan(track, rig, "disco")
    e = Engine(track, plan, rig)
    d = next(d for d in plan if d.section == "breakdown")
    heads = [x["id"] for x in rig["elements"] if x["kind"] == "head"]
    ts = np.linspace(d.start + 1, d.end - 1, 40)
    states = [e.render(float(t))[1] for t in ts]
    pans = np.array([[s[h].pan for h in heads] for s in states])
    assert np.ptp(pans, axis=0).min() > 0.02  # every head circles
    assert np.mean([[s[h].dimmer for h in heads] for s in states]) > 0.2  # and shines
