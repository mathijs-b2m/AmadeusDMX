"""Streamed tracks: djay's records read, the right YouTube result picked, and YouTube asked gently."""

import sqlite3
import struct
import sys
import time
import types

import pytest

from amadeus.show.sources import streamed
from amadeus.show.sources.streamed import Fetcher, Stream, _fields, djay_streams, score


def s8(text: str) -> bytes:
    return b"\x08" + text.encode() + b"\x00"


def f32(data: bytes, value: float) -> bytes:
    """A float as djay writes it: 0x13, zero padding to a 4-byte boundary, the float."""
    data += b"\x13"
    data += b"\x00" * (-len(data) % 4)
    return data + struct.pack("<f", value)


def location(title, artist, uri, isrc, length) -> bytes:
    d = b"TSAF\x03\x00\x03\x00" + s8("ADCMediaItemLocation") + s8("ab12") + s8("uuid") + b"\x05\x02"
    d += s8(title) + s8("title") + s8(artist) + s8("artist")
    d = f32(d, length) + s8("duration")
    return d + s8(isrc) + s8("isrc") + s8(uri) + s8("sourceURIs")


def test_a_record():
    f = _fields(location("Toxic", "Britney Spears", "spotify:track:6I9VzX", "USJI10301102", 198.8))
    assert f["title"] == "Toxic" and f["artist"] == "Britney Spears" and f["isrc"] == "USJI10301102"
    assert abs(f["duration"] - 198.8) < 1e-3 and f["uris"] == ["spotify:track:6I9VzX"]


def test_a_missing_artist_is_not_a_key():
    d = s8("Zebra") + s8("title") + s8("artist") + s8("spotify:track:x") + s8("sourceURIs")
    assert "artist" not in _fields(d)


def test_djay_library(tmp_path):
    db = tmp_path / "MediaLibrary.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE database2 (rowid INTEGER PRIMARY KEY, collection, key, data, metadata)")
        rows = [
            ("globalMediaItemLocations", "a", location("Toxic", "Britney Spears", "spotify:track:6I9", "US1", 198.8)),
            ("globalMediaItemLocations", "b", s8("file:///x.mp3") + s8("Local") + s8("title")),  # not streamed
            ("mediaItemAnalyzedData", "a", f32(s8("Toxic") + s8("title"), 143.0) + s8("bpm")),
        ]
        con.executemany("INSERT INTO database2 (collection, key, data) VALUES (?, ?, ?)", rows)
    found = djay_streams(db)
    assert list(found) == [("Toxic", "Britney Spears")]
    s = found[("Toxic", "Britney Spears")]
    assert (s.service, s.id, s.isrc, round(s.length, 1), s.bpm) == ("spotify", "6I9", "US1", 198.8, 143.0)


TOXIC = Stream("spotify", "6I9", "Toxic", "Britney Spears", "US1", 198.8)


def test_scores():
    topic = {"id": "a", "title": "Toxic", "channel": "Britney Spears - Topic", "duration": 199}
    video = {
        "id": "b",
        "title": "Britney Spears - Toxic (Official HD Video)",
        "channel": "Britney Spears",
        "duration": 211,
    }
    live = {"id": "c", "title": "Toxic (Live)", "channel": "Fan", "duration": 199}
    other = {"id": "d", "title": "Womanizer", "channel": "Britney Spears - Topic", "duration": 199}
    assert score(TOXIC, topic) > 1.5
    assert score(TOXIC, video) is None  # an intro: 12 s longer
    assert score(TOXIC, live) is None and score(TOXIC, other) is None


@pytest.fixture
def fetcher(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "yt_dlp", types.ModuleType("yt_dlp"))
    monkeypatch.setattr(streamed, "GAP_S", 0.0)
    return Fetcher(tmp_path)


def fake(fetcher, lengths: dict, calls: list):
    """YouTube: every search finds these ids; a download writes a file of the given length."""

    def search(s):
        calls.append(("search", s.id))
        return [{"id": k, "channel": "x"} for k in lengths]

    def download(s, hit):
        calls.append(("download", hit["id"]))
        f = fetcher.folder / f"{fetcher._stem(s)}.{hit['id']}.webm"
        f.write_bytes(b"x")
        return f, lengths[hit["id"]]

    fetcher._search, fetcher._download = search, download


def wait(fetcher, s, until=2.0):
    t = time.monotonic() + until
    while fetcher.state.get(s.id) in ("waiting", "running") and time.monotonic() < t:
        time.sleep(0.01)


def test_the_same_length_is_taken_and_kept(fetcher):
    calls = []
    fake(fetcher, {"near": 198.5, "same": 198.82, "third": 198.8}, calls)
    assert fetcher.file(TOXIC) == ""  # queued
    wait(fetcher, TOXIC)
    f = fetcher.file(TOXIC)
    assert f.endswith("Britney Spears - Toxic [spotify-6I9].webm")
    assert [c for c in calls if c[0] == "download"] == [("download", "near"), ("download", "same")]  # at most 2
    assert sorted(p.name for p in fetcher.folder.iterdir()) == [
        "Britney Spears - Toxic [spotify-6I9].json", "Britney Spears - Toxic [spotify-6I9].webm",
    ]  # fmt: skip


def test_another_version_is_not_taken(fetcher):
    fake(fetcher, {"edit": 185.0, "extended": 260.0}, [])
    fetcher.file(TOXIC)
    wait(fetcher, TOXIC)
    assert fetcher.state[TOXIC.id] == "failed" and fetcher.file(TOXIC) == ""
    assert not list(fetcher.folder.iterdir())


def test_a_track_no_longer_on_a_deck_is_skipped(fetcher):
    calls, gate = [], []
    fake(fetcher, {"same": 198.8}, calls)
    search = fetcher._search

    def slow(s):  # the first fetch takes a while: meanwhile the DJ loads two more and unloads one
        while not gate:
            time.sleep(0.01)
        return search(s)

    fetcher._search = slow
    a, b = Stream("spotify", "a", "A", "x", "", 198.8), Stream("spotify", "b", "B", "x", "", 198.8)
    fetcher.file(TOXIC)
    fetcher.file(a)
    fetcher.file(b)
    fetcher.asked["a"] = time.monotonic() - streamed.WANTED_S - 1  # deck 2 moved on from it
    gate.append(1)
    wait(fetcher, TOXIC)
    wait(fetcher, b)
    assert [c for c in calls if c[0] == "search"] == [("search", "6I9"), ("search", "b")]  # one by one, not "a"
    assert "a" not in fetcher.state  # asked for again later, it is queued again


def test_saved_settings_and_the_command_line(tmp_path):
    from amadeus.show.sources import settings

    f = tmp_path / "integrations.json"
    assert settings("djay", f) == {}  # no file: everything at its default (streamed tracks off)
    f.write_text('{"djay": {"streamed": true, "poll": 100}, "mixxx": {"port": "IAC"}}')
    assert settings("djay", f) == {"streamed": 1, "poll": 100}
    f.write_text("not json")
    assert settings("djay", f) == {}


def test_streamed_tracks_are_off_by_default():
    import inspect

    from amadeus.show.sources.djay import Djay

    assert inspect.signature(Djay).parameters["streamed"].default == 0


def test_offline_is_tried_again_later(fetcher, monkeypatch):
    def search(s):
        raise OSError("<urlopen error [Errno 8] nodename nor servname provided, or not known>")

    fetcher._search = search
    fetcher.file(TOXIC)
    wait(fetcher, TOXIC)
    assert fetcher.state[TOXIC.id] == "failed" and TOXIC.id in fetcher.offline_at
    fetcher.file(TOXIC)
    assert fetcher.state[TOXIC.id] == "failed"  # not at once
    fetcher.offline_at[TOXIC.id] -= streamed.OFFLINE_RETRY_S + 1
    fake(fetcher, {"same": 198.8}, [])  # back online
    fetcher.file(TOXIC)
    wait(fetcher, TOXIC)
    assert fetcher.file(TOXIC).endswith("[spotify-6I9].webm")
