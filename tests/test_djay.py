"""djay: the playhead from a whole-second label that is late by up to LATE_S, never early."""

import random

from amadeus.show.sources.djay import LATE_S, Playhead, clock, percent


def test_labels():
    assert clock("01:07") == 67 and clock("-01:23") == 83 and clock("1:02:03") == 3723 and clock("x") is None
    assert abs(percent("0.9%") - 0.009) < 1e-12 and percent("100%") == 1.0


def run(head, start, until, speed=1.0, t0=0.0, seed=1, late=LATE_S - 0.05):
    """Play from `start` at time t0: every whole second crossed shows up 0..late later."""
    rnd, k = random.Random(seed), int(start) + 1
    while (t0 + (k - start) / speed) < until:
        cross = t0 + (k - start) / speed
        head.seen(k, cross + rnd.uniform(0, late))
        k += 1


def test_ticks_give_the_playhead_within_some_milliseconds():
    head = Playhead()
    head.seen(10, 0.0)  # paused at 10.x: the first label
    head.set_play(True, 0.0)
    head.frozen = head.coarse[1]
    true_start = 10.3
    head.ticks.clear()
    head.coarse = (0.0, true_start)
    run(head, true_start, 12.0)
    err = head.at(12.0) - (true_start + 12.0)
    assert -0.06 < err <= 0.001  # never ahead; the least late of 8 ticks is close


def test_a_tempo_change_keeps_the_position():
    head = Playhead()
    head.seen(0, 0.0)
    head.set_play(True, 0.0)
    head.coarse = (0.0, 0.0)
    run(head, 0.0, 6.0)
    before = head.at(6.0)
    head.set_speed(1.05, 6.0)
    assert abs(head.at(6.0) - before) < 1e-9 and abs(head.at(7.0) - before - 1.05) < 1e-9


def test_a_seek_starts_over_coarse_then_ticks_again():
    head = Playhead()
    head.seen(0, 0.0)
    head.set_play(True, 0.0)
    head.coarse = (0.0, 0.0)
    run(head, 0.0, 5.0)
    assert head.seen(40, 5.0) == "jump" and not head.ticks and head.coarse == (5.0, 40.5)
    # the real position was 40.2: the next tick (41) comes 0.8 s later and puts it right
    assert head.seen(41, 5.8 + 0.03) == "tick"
    assert abs(head.at(6.0) - (40.2 + 1.0)) < 0.05


def test_pause_holds_the_position():
    head = Playhead()
    head.seen(0, 0.0)
    head.set_play(True, 0.0)
    head.coarse = (0.0, 0.0)
    run(head, 0.0, 3.5)
    head.set_play(False, 3.5)
    assert abs(head.at(10.0) - head.at(3.5)) < 1e-9 and abs(head.at(3.5) - 3.5) < 0.06


class FakeWindow:
    def __init__(self, labels: dict):
        self.labels = labels

    def value(self, label):
        return self.labels.get(label)

    def decks(self):
        return [1]

    def bpm(self, n):
        return 0.0


def test_a_streamed_track_is_fetched_as_soon_as_it_is_loaded(capsys):
    """djay records a Spotify track in its library only once it plays: loaded and paused, it is looked for by
    artist and title (length from the deck's clocks); once djay knows it, its copy is checked and kept."""
    import threading

    from amadeus.show.sources import djay
    from amadeus.show.sources.base import DeckBook
    from amadeus.show.sources.streamed import Stream

    class Library:
        def find(self, title, artist):
            return ""  # djay's library: no file of it

    class Resolver:
        ready = threading.Event()

        def find(self, path, artist, title):
            return ""  # not on this computer

    class Streams:
        known = {}

        def find(self, title, artist):
            return self.known.get((title, artist))

    class Fetcher:
        asked = []

        def file(self, s):
            self.asked.append(s)
            return "/cache/streamed/copy.m4a" if len(self.asked) > 1 else ""

        def status(self, s):
            return "done" if len(self.asked) > 1 else "waiting"

    d = djay.Djay.__new__(djay.Djay)
    d.window = FakeWindow({"Title, Deck 1": "Toxic", "Artist, Deck 1": "Britney Spears", "Elapsed time, Deck 1":
                           "00:00", "Remaining time, Deck 1": "-03:20", "Play / Pause, Deck 1": None})  # fmt: skip
    d.library, d.resolver, d.streams, d.fetcher = Library(), Resolver(), Streams(), Fetcher()
    d.streamed, d.info, d.heads, d.xfader, d.link = True, {}, {}, 0.5, None
    d.book, d.latency, d.packets = DeckBook(), 0.0, 0
    d.resolver.ready.set()
    d._slow(0.0)
    guess = d.fetcher.asked[0]
    assert guess.guess and (guess.title, guess.artist, guess.length) == ("Toxic", "Britney Spears", 200.0)
    d._slow(0.2)  # the copy is in: the deck has its file while still paused
    d._reading(0.2)
    deck = d.decks[1]
    assert deck.file == "/cache/streamed/copy.m4a" and not deck.play and deck.length == 200.0
    real = Stream("spotify", "6I9", "Toxic", "Britney Spears", "US1", 198.8)
    Streams.known[("Toxic", "Britney Spears")] = real
    d._slow(0.4)  # played: djay's library knows it now
    assert d.fetcher.asked[-1] is real and d.info[1]["stream"] is real and d.info[1]["length"] == 198.8
    assert "looking for a copy by artist and title" in capsys.readouterr().out


def test_streamed_tracks_switched_on_in_settings_get_their_fetcher(monkeypatch):
    """Settings ▸ Integrations ▸ Streamed tracks is enough: not only --streamed fetches copies of Spotify tracks."""
    from amadeus.show.sources import djay

    made = []
    monkeypatch.setattr(djay, "enabled", lambda: True)
    monkeypatch.setattr(djay, "Fetcher", lambda: made.append(1) or "fetcher")
    from unittest.mock import MagicMock

    for name in ("open_window", "DjayStreams", "Resolver", "Library"):  # no djay here: its window and library
        monkeypatch.setattr(djay, name, MagicMock())
    d = djay.Djay(link=0, streamed=0)
    assert d.streamed and d.fetcher == "fetcher" and made == [1]
    monkeypatch.setattr(djay, "enabled", lambda: False)
    assert djay.Djay(link=0, streamed=0).fetcher is None
