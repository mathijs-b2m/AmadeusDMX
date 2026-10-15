"""The song's form: a song's choruses are no drops, its real drops stay, club tracks are left alone."""

from dataclasses import replace

from amadeus.audio import form
from amadeus.audio.genre import GenreCall, from_audio
from amadeus.audio.model import DROP_THRESHOLD
from amadeus.director import RuleDirector, direct
from amadeus.director.arc import song_arc
from tests.synthetic import synthetic_analysis

# (loudness %, low %, kick ratio, drop score, vocal share) per 8-bar phrase: a rock song whose choruses come in
# like drops (the energy and the low end jump, the kick runs), sung all the way
ROCK = [
    (15, 15, 0.4, 0.0, 0.05),  # intro: the band, no voice yet
    (35, 35, 0.6, 0.0, 0.7),  # verse
    (85, 85, 0.9, 0.8, 0.75),  # chorus, scored like a drop
    (35, 35, 0.6, 0.0, 0.7),  # verse
    (88, 88, 0.9, 0.8, 0.75),  # chorus, scored like a drop
    (20, 10, 0.5, 0.0, 0.6),  # a quiet bridge
    (95, 95, 0.9, 0.9, 0.8),  # the last chorus
    (20, 20, 0.5, 0.0, 0.0),  # outro
]


def _song(shape=ROCK):
    a = synthetic_analysis()
    a.phrases = a.phrases[: len(shape)]
    for p, (loud, low, kick, drop, vocal) in zip(a.phrases, shape):
        p.loudness_pct, p.low_pct, p.kick_ratio, p.drop_score, p.vocal = loud, low, kick, drop, vocal
    a.roll, a.pauses = None, None
    return a


def test_a_rock_songs_choruses_are_not_drops():
    a = _song()
    form.apply(a, GenreCall("rock", "ai"), {"song": True})
    assert a.form == "song"
    assert not any(p.drop_score >= DROP_THRESHOLD for p in a.phrases)
    assert [p.part for p in a.phrases] == ["intro", "verse", "chorus", "verse", "chorus", "verse", "chorus", "outro"]
    assert a.phrases[2].lift == 0.8  # how big its entrance was is kept


def test_a_real_drop_inside_a_song_stays_a_drop():
    # Coldplay-style: the voice steps back and the synths take over after the chorus
    shape = [*ROCK[:6], (95, 95, 0.95, 0.9, 0.05), ROCK[7]]
    shape[5] = (40, 30, 0.2, 0.0, 0.7)  # the build before it, still sung
    a = _song(shape)
    form.apply(a, GenreCall("pop", "ai"), {"song": True})
    assert a.phrases[6].drop_score >= DROP_THRESHOLD and a.phrases[6].part == "drop"
    assert a.phrases[2].drop_score == 0.0  # the sung choruses before it are still choruses


def test_a_club_track_is_left_exactly_as_it_was():
    a = synthetic_analysis()
    before = [replace(p) for p in a.phrases]
    form.apply(a, GenreCall("techno", "ai"), {"song": True})  # a known club genre outweighs the audio
    assert a.form == "club"
    assert [(p.drop_score, p.part) for p in a.phrases] == [(p.drop_score, "") for p in before]


def test_the_audio_decides_when_the_genre_is_a_guess():
    assert form.decide(GenreCall("house", "audio"), {"song": True}) == "song"
    assert form.decide(GenreCall("house", "audio"), {"song": False}) == "club"
    assert form.decide(GenreCall("house", "audio"), {"song": None}) == ""


def test_a_song_gets_a_song_genre_never_a_tempo_family():
    f = {"groove": 0.08, "pump_db": 9.0, "bpm": 144.0, "tonal": 0.8, "hat_density": 1.6, "dynamics_db": 18.0}
    assert from_audio(f) == "cinematic"  # a loose groove alone still reads as a score…
    assert from_audio({**f, "song": True, "guitar_led": 0.8}) == "rock"  # …but a sung, guitar-led song is rock
    assert from_audio({**f, "song": True, "guitar_led": 0.2}) == "pop"  # (144 BPM: not psytrance)
    assert from_audio({**f, "bpm": 92.0, "song": True, "guitar_led": 0.2}) == "hiphop"


def test_the_rule_director_lights_verses_and_choruses_and_saves_the_last_chorus():
    a = _song()
    form.apply(a, GenreCall("rock", "ai"), {"song": True})
    plan = direct(a, RuleDirector(), verbose=False)
    sections = [d.section for d in plan]
    assert "drop" not in sections
    assert sections[1:7] == ["verse", "chorus", "verse", "chorus", "verse", "chorus"]
    assert song_arc(a)[6]["role"] == "main_chorus"
    assert plan[6].intensity == 3 and plan[2].intensity < 3  # the last chorus is the biggest
