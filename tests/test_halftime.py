"""Half time (amadeus/audio/halftime.py), the chill genre and its calm drops, and the genre question's title."""

from types import SimpleNamespace

import numpy as np

from amadeus.audio import genre, halftime
from amadeus.director.style import STYLES

BEATS = np.arange(256) * 0.4  # 150 BPM


def _hits(every: int, offset: int = 0):
    t = BEATS[offset::every]
    return t, np.ones(len(t))


def test_snare_on_every_fourth_beat_with_a_sparse_kick_is_half_time():
    snare, kick = _hits(4, 2), _hits(4, 0)
    second, kicks = halftime.measure(BEATS, *kick, *snare)
    assert second < halftime.SNARE_SECOND and kicks < halftime.KICK_MAX


def test_a_backbeat_is_not_half_time():
    second, _ = halftime.measure(BEATS, *_hits(1), *_hits(2, 1))
    assert second >= halftime.SNARE_SECOND


def test_four_on_the_floor_with_a_clap_on_three_is_not_half_time():
    second, kicks = halftime.measure(BEATS, *_hits(1), *_hits(4, 2))  # (SOFI TUKKER's "Manhattan")
    assert second < halftime.SNARE_SECOND and kicks >= halftime.KICK_MAX


def test_too_few_snares_says_nothing():
    assert halftime.measure(BEATS, *_hits(1), np.zeros(0), np.zeros(0)) is None


def test_only_separated_drums_count(monkeypatch):
    from amadeus.audio import drums

    t, s = _hits(4, 2)
    mix = drums.Kit(*_hits(4), t, s, np.zeros(len(t)), source="mix")
    monkeypatch.setattr(drums, "kit", lambda a: mix)
    a = SimpleNamespace(bpm=150.0, beats=BEATS)
    assert not halftime.heard(a)
    monkeypatch.setattr(drums, "kit", lambda a: drums.Kit(*_hits(4), t, s, np.zeros(len(t)), source="stem"))
    assert halftime.heard(a)
    assert not halftime.heard(SimpleNamespace(bpm=100.0, beats=BEATS))  # counted slow: halving goes too far


def test_a_streamed_copys_id_is_no_part_of_the_title():
    a = SimpleNamespace(path="/c/Disclosure, Flume - You & Me - Flume Remix [spotify-3W2ZcrRsInZbjWylOi6KhZ].00962f6f.decoded.wav")
    assert genre.artist_title(a, {}) == ("Disclosure, Flume", "You & Me - Flume Remix")
    a = SimpleNamespace(path="/c/Skrillex - Make It Bun Dem [streamed-3119f992faf0].d3ec939b.decoded.wav")
    assert genre.artist_title(a, {})[1] == "Make It Bun Dem"


def test_future_bass_is_chill():
    assert genre.from_tag({"genre": "Future Bass"}) == "chill"
    assert genre.from_tag({"genre": "Chillstep"}) == "chill"
    assert genre.from_tag({"genre": "Chill-out"}) == "ambient"


def test_chill_stays_calm_where_it_drops():
    style = STYLES["chill"]
    d = SimpleNamespace(section="drop", phrase=3, palette="warm", trigger="kick", movement="ballyhoo",
                        head_light="strobe", par_base="off", par_accent="chase", beam_fx="prism_spin")  # fmt: skip
    style.adjust(d, 0)
    assert style.allows("movement", d.movement) and style.allows("head_light", d.head_light)
    assert style.allows("par_accent", d.par_accent) and style.allows("beam_fx", d.beam_fx)
    assert style.allows("par_base", d.par_base)
    house = STYLES["house"]  # (other genres: a drop's own music decides, as before)
    d2 = SimpleNamespace(section="drop", phrase=3, palette="warm", trigger="kick", movement="ballyhoo")
    house.adjust(d2, 0)
    assert d2.movement == "ballyhoo"
