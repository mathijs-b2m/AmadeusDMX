"""The DMX trace: with the flag file there, every value that really goes out is written as it changes, with its
fixture and channel; without it, nothing is written."""

import pytest

from amadeus.dmx import outputs, trace
from amadeus.library import fixtures as fxlib


@pytest.fixture
def tr(tmp_path, monkeypatch):
    monkeypatch.setattr(trace, "FLAG", tmp_path / "dmx-trace")
    monkeypatch.setattr(trace, "LOG", tmp_path / "dmx-trace.log")
    monkeypatch.setattr(trace, "CHECK_S", -1.0)  # look at the flag every frame
    t = trace.Trace()
    monkeypatch.setattr(trace, "TRACE", t)
    return t


class Quiet(outputs.Output):
    def __init__(self, **kw):
        super().__init__(owner=True, **kw)
        self.sent = []

    def _send(self, universes):
        self.sent.append(universes)


def rig():
    key = next(k for k, d in fxlib.library().items() if len(fxlib.channels(d, fxlib.default_mode(d))) >= 3)
    defn = fxlib.get(key)
    mode = fxlib.default_mode(defn)
    fx = {"id": "fx1", "fixture": key, "mode": mode, "universe": 1, "address": 17}
    return {"fixtures": [fx]}, fxlib.channels(defn, mode)


def lines():
    trace.flush()
    return trace.LOG.read_text(encoding="utf-8").splitlines() if trace.LOG.exists() else []


def test_off_writes_nothing(tr):
    out = Quiet()
    out.send({1: bytes([9] * 512)})
    assert out.sent and lines() == []


def test_changes_are_named_and_only_changes_are_written(tr):
    r, chans = rig()
    trace.describe(r, "test")
    trace.FLAG.write_text("")
    out = Quiet()
    buf = bytearray(512)
    buf[16], buf[400] = 131, 7  # the fixture's first channel, and a channel nobody is patched on
    out.send({1: buf})
    first = lines()
    assert first[0].startswith("# ") and "trace on" in first[0]
    assert len(first) == 3  # only what isn't 0
    assert "U1.017" in first[1] and "fx1" in first[1] and chans[0]["attr"] in first[1] and first[1].endswith("· → 131")
    assert "U1.401" in first[2] and " -  " in first[2]

    out.send({1: buf})  # held still: nothing
    assert lines() == first
    buf[18] = 255
    out.send({1: buf})
    new = lines()[len(first) :]
    assert len(new) == 1 and "U1.019" in new[0] and new[0].endswith("0 → 255")

    out.blackout([1])  # the show's last word is in the trace too
    assert sum("→   0" in line for line in lines()) == 3

    trace.FLAG.unlink()
    buf[20] = 1
    out.send({1: buf})
    assert len(lines()) == len(first) + 1 + 3


def test_only_the_outputs_own_universes(tr):
    trace.FLAG.write_text("")
    out = outputs.MultiOutput([Quiet(universes=[1]), Quiet(universes=[2])])
    out.send({1: bytes([1]) + bytes(511), 2: bytes([2]) + bytes(511), 3: bytes([3]) + bytes(511)})
    got = [line for line in lines() if not line.startswith("#")]
    assert [line.split()[1] for line in got] == ["U1.001", "U2.001"]


def test_starts_over_when_full(tr, monkeypatch):
    monkeypatch.setattr(trace, "MAX_BYTES", 200)
    trace.FLAG.write_text("")
    out = Quiet()
    for v in range(1, 30):
        out.send({1: bytes([v]) * 4})
        trace.flush()
    assert trace.LOG.stat().st_size < 600 and trace.LOG.with_name("dmx-trace.log.1").exists()
