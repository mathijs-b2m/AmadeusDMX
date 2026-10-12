"""The Mixxx mapping's script (run in Node with a stand-in for Mixxx) against our decoder and source."""

import json
import shutil
import sqlite3
import subprocess

import pytest

from amadeus import paths
from amadeus.show.sources import mixxx

HARNESS = """
const fs = require("fs");
const values = %s;
const sent = [];
global.engine = {
  getValue: (g, k) => (values[g] || {})[k] || 0,
  makeConnection: () => ({disconnect() {}}),
  beginTimer: () => 1, stopTimer: () => {},
};
global.midi = {sendSysexMsg: (m, n) => sent.push(m.slice(0, n))};
eval(fs.readFileSync(%s, "utf8") + "; global.AmadeusDMX = AmadeusDMX;");
AmadeusDMX.init();
AmadeusDMX.tick();
console.log(JSON.stringify(sent));
"""


def script_output(values: dict) -> list[list[int]]:
    js = paths.ROOT / "mixxx" / "Amadeus-DMX-scripts.js"
    out = subprocess.run(
        ["node", "-e", HARNESS % (json.dumps(values), json.dumps(str(js)))], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js to run the Mixxx script")
def test_script_sysex_decodes():
    ch2 = {"track_loaded": 1, "play": 1, "loop_enabled": 1, "orientation": 2, "playposition": 0.25, "duration": 200.5,
           "track_samples": 2 * 44100 * 200.5, "track_samplerate": 44100, "rate_ratio": 1.08, "bpm": 138.24,
           "volume": 0.5}  # fmt: skip
    sent = script_output({"[App]": {"num_decks": 2}, "[Channel2]": ch2, "[Master]": {"crossfader": -0.5}})
    assert all(0 <= b < 128 for m in sent for b in m[1:-1])  # SysEx data bytes are 7-bit
    msgs = [mixxx.decode(m) for m in sent]
    deck = next(m for m in msgs if m and "deck" in m)
    assert deck["deck"] == 2 and deck["play"] and deck["loop"] and deck["orientation"] == 2
    assert abs(deck["pos"] - 50.125) < 0.001 and deck["samples"] == 2 * 44100 * 200.5 and deck["rate"] == 44100
    assert abs(deck["ratio"] - 1.08) < 1e-6 and abs(deck["bpm"] - 138.24) < 1e-3 and abs(deck["vol"] - 0.5) < 1e-3
    assert not any(m and m.get("deck") == 1 for m in msgs)  # nothing loaded on deck 1
    assert abs(next(m for m in msgs if m and "xfader" in m)["xfader"] + 0.5) < 1e-3


def test_crossfader_gain():
    assert mixxx.xfade_gain(-1.0, 0) == 1.0 and mixxx.xfade_gain(1.0, 0) == 0.0
    assert mixxx.xfade_gain(0.5, 2) == 1.0 and mixxx.xfade_gain(-0.5, 2) == 0.5 and mixxx.xfade_gain(1.0, 1) == 1.0


def test_library_finds_the_track_by_its_length(tmp_path):
    db = tmp_path / "mixxxdb.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("CREATE TABLE track_locations (id INTEGER PRIMARY KEY, location TEXT)")
        c.execute("CREATE TABLE library (id INTEGER PRIMARY KEY, location INTEGER, artist TEXT, title TEXT, "
                  "duration REAL, samplerate INTEGER, bpm REAL, mixxx_deleted INTEGER)")  # fmt: skip
        c.executemany("INSERT INTO track_locations VALUES (?, ?)", [(1, "/m/a.mp3"), (2, "/m/b.mp3")])
        c.executemany(
            "INSERT INTO library VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            [(1, 1, "A", "Song A", 200.5, 44100, 128.0), (2, 2, "B", "Song B", 201.5, 44100, 128.0)],
        )
    lib = mixxx.Library(db)
    assert lib.find(int(2 * 44100 * 200.5), 44100, 128.0) == ("/m/a.mp3", "A", "Song A")
    assert lib.find(int(2 * 48000 * 200.5), 48000, 128.0) == ("", "", "")


def _u7(v, n):
    return [(int(v) >> (7 * i)) & 127 for i in reversed(range(n))]


def test_an_existing_midi_port_is_used_as_it_is(tmp_path):
    """Like the IAC bus: a port that is already there (here: a stand-in made by the test) is opened, not created."""
    rtmidi = pytest.importorskip("rtmidi")
    import time

    bus = rtmidi.MidiOut()
    bus.open_virtual_port("DL Test Bus")
    src = mixxx.Mixxx(port="DL Test Bus", library=str(tmp_path / "none.sqlite"))
    try:
        assert src.out is None and "MIDI port" in src.name
        body = [0x01, 1, 1, *_u7(2**30 + 12345, 5), *_u7(2 * 44100 * 60, 5), *_u7(44100, 3)]
        body += [*_u7(2**27 + 10**6, 4), *_u7(128000, 4), *_u7(16383, 2), *_u7(1, 2)]
        bus.send_message([*mixxx.HEADER, *body, 0xF7])
        for _ in range(100):
            if src.state:
                break
            time.sleep(0.01)
        assert src.state[1]["pos"] == 12.345 and src.state[1]["bpm"] == 128.0
    finally:
        src.close()
        bus.close_port()
