import json
import socket
import time

import numpy as np
import soundfile as sf

from amadeus.show import probe
from amadeus.show.sources import open_source, parse_opts
from amadeus.show.sources.base import FROZEN_S, Deck, DeckBook, Source
from amadeus.show.sources.resolve import Resolver
from amadeus.show.vdj import Listener


def deck(pos, t, play=True, file="a.mp3", n=1, vol=1.0, bpm=128.0):
    return Deck(n, file, pos, 300.0, play, bpm, 128.0, vol, t)


def kinds(book):
    return [e.kind for e in book.events]


def test_events_follow_the_playhead():
    book = DeckBook()
    book.update([deck(10.0, 0.0)], 0.0)
    book.update([deck(10.1, 0.1)], 0.1)  # plays on: no event
    assert kinds(book) == ["track_loaded", "playback_started"]
    book.update([deck(40.0, 0.2)], 0.2)  # jumped
    assert kinds(book)[-1] == "seek"
    book.update([deck(40.0, 0.3, play=False)], 0.3)
    assert kinds(book)[-1] == "playback_stopped"
    book.update([deck(0.0, 0.4, file="b.mp3")], 0.4)
    assert kinds(book)[-2:] == ["track_loaded", "playback_started"]


def test_a_loop_is_two_jumps_back_to_the_same_place():
    book, t, pos = DeckBook(), 0.0, 20.0
    book.update([deck(pos, t)], t)
    for _ in range(3):  # 20.0 → 22.0, back to 20.0
        for _ in range(20):
            t, pos = t + 0.1, pos + 0.1
            book.update([deck(pos, t)], t)
        t, pos = t + 0.1, 20.0
        book.update([deck(pos, t)], t)
    assert kinds(book).count("loop") == 2
    loop = [e for e in book.events if e.kind == "loop"][-1]
    assert abs(loop.data["length"] - 2.1) < 0.05


def test_playing_with_a_frozen_position_counts_as_stopped():
    book = DeckBook()
    book.update([deck(5.0, 0.0)], 0.0)
    book.update([deck(5.0, FROZEN_S + 0.1)], FROZEN_S + 0.1)
    assert not book.decks[1].play


def test_a_deck_repeated_from_its_last_reading_is_not_frozen():
    """Sources that report on change send a deck's last playhead again when another deck has news."""
    book = DeckBook()
    book.update([deck(5.0, 0.0)], 0.0)
    book.update([deck(5.0, 0.0)], FROZEN_S + 0.1)  # same reading (received 0.0), later
    assert book.decks[1].play


def test_mirrored_decks_are_dropped_only_when_asked():
    two = [deck(5.0, 0.0, n=1), deck(5.0, 0.0, n=3)]
    assert len(DeckBook().update(list(two), 0.0)) == 2
    assert list(DeckBook(dedupe_mirrors=True).update(list(two), 0.0)) == [1]


def test_master_is_the_loudest_playing_deck():
    s = Source()
    s.received([deck(1.0, 0.0, n=1, vol=0.3), deck(1.0, 0.0, n=2, vol=0.9, file="b")], now=time.monotonic())
    assert s.master == 2 and s.alive()


def test_probe_emits_what_the_vdj_listener_reads():
    """Any source, passed on with --emit, arrives as the plugin's packets (here: straight into live mode's
    VirtualDJ listener; on a DJ laptop: into the Amadeus Link app)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    listener = Listener(port)
    src = Source()
    now = time.monotonic()
    src.received([deck(61.42, now, vol=0.83, bpm=130.0)], now=now)
    out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    out.sendto(json.dumps(probe.plugin_packet(src, now, now - 1)).encode(), ("127.0.0.1", port))
    for _ in range(100):
        if listener.decks:
            break
        time.sleep(0.01)
    d = listener.decks[1]
    assert d.file == "a.mp3" and abs(d.pos - 61.42) < 1e-3 and d.vol == 0.83 and abs(d.speed - 130 / 128) < 1e-9
    listener.close()


def test_replay_plays_a_recording(tmp_path):
    lines = [
        {
            "t": i * 0.02,
            "master": 1,
            "decks": [
                {
                    "deck": 1,
                    "file": "x.wav",
                    "pos": 3 + i * 0.02,
                    "len": 9.0,
                    "play": 1,
                    "bpm": 120,
                    "bpm0": 120,
                    "vol": 1,
                    "title": "X",
                }
            ],
        }
        for i in range(10)
    ]
    f = tmp_path / "cap.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    src = open_source("replay", file=str(f))
    assert src.done.wait(2)
    assert src.packets == 10 and src.decks[1].title == "X" and abs(src.decks[1].pos - 3.18) < 1e-9


def test_resolver_finds_a_track_by_artist_and_title(tmp_path):
    for name, secs in [("Artist A - Song One (Club Mix).wav", 2.0), ("Other - Song One.wav", 3.0)]:
        sf.write(tmp_path / name, np.zeros(int(secs * 8000)), 8000)
    r = Resolver([tmp_path])
    assert r.find(artist="Artist A, Artist B", title="Song One (Club Mix)", wait=5).endswith(
        "Artist A - Song One (Club Mix).wav"
    )
    assert r.find(title="Song One", length=3.0, wait=5).endswith("Other - Song One.wav")  # the length decides
    assert r.find(path="C:\\Music\\Other - Song One.wav", wait=5).endswith("Other - Song One.wav")  # same name
    assert r.find(title="Missing", wait=5) == ""


def test_a_reported_rate_beats_the_tempo_ratio():
    d = Deck(1, "a", 10.0, 300.0, True, 0.0, 0.0, 1.0, 0.0, rate=0.92)  # no beatgrid: no tempo
    assert abs(d.now(1.0) - 10.92) < 1e-9


def test_latency_moves_positions_later(tmp_path):
    f = tmp_path / "cap.jsonl"
    f.write_text(json.dumps({"t": 0, "decks": [{"deck": 1, "pos": 10.0, "play": 1}]}), encoding="utf-8")
    src = open_source("replay", file=str(f), latency="20")
    assert src.done.wait(2)
    d = src.decks[1]
    assert abs(d.now(d.received - 0.02) - 10.0 + 0.02) < 1e-9 and abs(src.latency - 0.02) < 1e-12


def test_parse_opts():
    assert parse_opts(["port=50002", "host=10.0.0.5"]) == {"port": 50002, "host": "10.0.0.5"}


def test_snap_moves_to_the_nearest_point_at_that_phase():
    from amadeus.show.sources.base import snap

    beats = np.arange(0, 100) * 0.5  # 120 BPM
    assert abs(snap(10.1, beats, 0.0) - 10.0) < 1e-9
    assert abs(snap(10.4, beats, 0.0) - 10.5) < 1e-9  # the next beat is nearer
    assert abs(snap(10.1, beats, 0.5) - 10.25) < 1e-9


def test_phase_lock_learns_a_fixed_offset_near_half_a_beat():
    """The DJ software's position runs 0.2 s (0.4 beat) ahead of what Link says is heard, with ±50 ms noise:
    the lock still picks the right beat every time, and ends exactly on Link's phase."""
    from amadeus.show.sources.base import PhaseLock

    beats, rnd, lock = np.arange(0, 400) * 0.5, np.random.default_rng(3), PhaseLock()
    for k in range(200):
        t = k * 0.05
        heard = 30.0 + t  # the truth
        d = Deck(1, "a", heard + 0.2 + rnd.uniform(-0.05, 0.05), 300.0, True, 120.0, 120.0, 1.0, t)
        d.phase = (heard / 0.5) % 1.0
        got = lock.at(d, t, beats, "a")
        if k > 10:
            assert abs(got - heard) < 1e-6, (k, got, heard)
    assert abs(sorted(lock.moves)[len(lock.moves) // 2] + 0.2) < 0.03


def test_the_phase_travels_with_emit():
    src = Source()
    now = time.monotonic()
    d = deck(5.0, now, bpm=120.0)
    d.phase = 0.25
    src.received([d], now=now)
    packet = probe.plugin_packet(src, now + 0.125, now)  # a quarter beat later at 120 BPM
    assert abs(packet["decks"][0]["phase"] - 0.5) < 1e-3


def test_resolver_learns_more_folders(tmp_path):
    (tmp_path / "music").mkdir()
    (tmp_path / "elsewhere" / "sub").mkdir(parents=True)
    sf.write(tmp_path / "elsewhere" / "sub" / "Artist - Far Away.wav", np.zeros(800), 8000)
    r = Resolver([tmp_path / "music"])
    assert r.find(title="Far Away", wait=5) == ""
    r.add([str(tmp_path / "elsewhere"), str(tmp_path / "elsewhere" / "sub"), str(tmp_path / "music")])
    assert r.folders == [tmp_path / "music", tmp_path / "elsewhere"]  # nothing indexed twice
    for _ in range(200):
        if r.find(title="Far Away"):
            break
        time.sleep(0.01)
    assert r.find(title="Far Away").endswith("Artist - Far Away.wav")
