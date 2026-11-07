"""A fixture with a strobe channel strobes on it, its dimmer open; the others flash on their dimmer."""

import copy
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine, State
from amadeus.library import fixtures as fxlib
from amadeus.library import generic, mapper, strobe
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from amadeus.show.mixer import Mixer
from tests.synthetic import synthetic_analysis

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
HEAD = {"fixture": "t/head", "mode": "m", "address": 1, "id": "h"}
DIM, SHUTTER = 0, 1


@pytest.fixture(scope="module")
def track():
    return synthetic_analysis()


def _defn(*chans):
    return {"kind": "moving_head", "modes": {"m": list(chans)}, "physical": {}, "key": "t/head"}


def _patch(monkeypatch, defn, states, limit=1.0):
    monkeypatch.setattr(fxlib, "get", lambda key: defn)
    monkeypatch.setattr(fxlib, "expand", lambda fx, *_: [{"id": k, "head": n} for n, k in enumerate(states)])
    buf = bytearray(512)
    fxlib.patch(buf, HEAD, states, limit)
    return buf


CHAN = {"attr": "shutter", "default": 40, "strobe_range": [64, 95]}


@pytest.mark.parametrize(
    "ranges, want",
    [
        ([(0, 31, "closed"), (64, 95, "Strobe, slow to fast"), (192, 223, "Strobe random, slow to fast")],
         {"strobe_range": [64, 95]}),
        ([(4, 103, "Strobe (slow 1 flash/sec to fast 12 flashes/sec)")],
         {"strobe_range": [4, 103], "strobe_hz": [1.0, 12.0]}),
        ([(10, 200, "strobe fast to slow")], {"strobe_range": [200, 10]}),
        ([(10, 200, "strobe", 20, 2)], {"strobe_range": [200, 10], "strobe_hz": [2.0, 20.0]}),
        ([(10, 19, "strobe 1 Hz", 1), (20, 29, "strobe 2 Hz", 2), (30, 39, "strobe 3 Hz", 3)],
         {"strobe_range": [10, 39], "strobe_hz": [1.0, 3.0]}),
        ([(30, 119, "Strobe (from 3,27 s to 30 ms)")], {"strobe_range": [30, 119], "strobe_hz": [0.31, 33.33]}),
        ([(0, 9, "no strobe"), (10, 255, "pulse strobe"), (5, 7, "strobe")], {}),
    ],
)  # fmt: skip
def test_the_steady_strobe_is_found_in_a_channels_words(ranges, want):
    assert strobe.pick(ranges) == want


def test_the_quiet_value_is_no_strobe():
    for default, want in ((0, [1, 255]), (255, [0, 254])):
        spec = strobe.mark({"attr": "strobe", "default": default}, [(0, 255, "strobe slow to fast")])
        assert spec["strobe_range"] == want


def test_a_rate_is_never_faster_than_asked():
    known = {"strobe_range": [4, 103], "strobe_hz": [1.0, 12.0]}
    for hz in (1.0, 2.13, 4.0, 10.0):
        assert (strobe.value(known, hz) - 4) / 99 * 11 + 1 <= hz + 1e-6
    assert strobe.value(known, 40.0) == 103
    assert strobe.value({"strobe_range": [200, 10], "strobe_hz": [1.0, 20.0]}, 20.0) == 10
    assert strobe.value({"strobe_range": [10, 200], "strobe_hz": [8.0, 20.0]}, 4.0) is None  # can't go that slowly
    assert 64 <= strobe.value({"strobe_range": [64, 95]}, 2.0) < 70  # unknown speeds: on the slow side


def test_the_strobe_channel_flashes_and_the_dimmer_stays_open(monkeypatch):
    defn = _defn({"attr": "dimmer"}, CHAN)
    for gate in (1.0, 0.0):
        buf = _patch(monkeypatch, defn, {"h": State(dimmer=0.8, strobe_hz=4.0, gate=gate)})
        assert buf[DIM] == round(0.8 * 255) and 64 <= buf[SHUTTER] <= 95
    assert _patch(monkeypatch, defn, {"h": State(dimmer=0.8)})[SHUTTER] == 40  # not strobing: back to quiet


def test_a_dark_light_does_not_strobe(monkeypatch):
    buf = _patch(monkeypatch, _defn({"attr": "dimmer"}, CHAN), {"h": State(dimmer=0.0, strobe_hz=4.0)})
    assert (buf[DIM], buf[SHUTTER]) == (0, 40)  # (the eye-band and high-risk guards darken `dimmer`)


def test_the_limiter_holds_a_strobing_light(monkeypatch):
    buf = _patch(monkeypatch, _defn({"attr": "dimmer"}, CHAN), {"h": State(dimmer=1.0, strobe_hz=4.0)}, limit=0.5)
    assert buf[DIM] == round(0.5 * 255)


def test_without_a_strobe_channel_it_flashes_on_the_dimmer(monkeypatch):
    defn = _defn({"attr": "dimmer"}, {"attr": "shutter", "default": 40})
    assert _patch(monkeypatch, defn, {"h": State(dimmer=0.8, strobe_hz=4.0, gate=0.0)})[DIM] == 0
    assert _patch(monkeypatch, defn, {"h": State(dimmer=0.8, strobe_hz=4.0, gate=1.0)})[DIM] == round(0.8 * 255)


def test_too_fast_a_strobe_channel_leaves_it_to_the_dimmer(monkeypatch):
    defn = _defn({"attr": "dimmer"}, {**CHAN, "strobe_hz": [8.0, 25.0]})
    buf = _patch(monkeypatch, defn, {"h": State(dimmer=0.8, strobe_hz=4.0, gate=0.0)})
    assert (buf[DIM], buf[SHUTTER]) == (0, 40)


def test_a_shared_channel_waits_for_all_its_cells(monkeypatch):
    defn = _defn({"attr": "dimmer", "head": 0}, {"attr": "dimmer", "head": 1}, CHAN)
    both = {"a": State(dimmer=1.0, strobe_hz=4.0, gate=0.0), "b": State(dimmer=1.0, strobe_hz=4.0, gate=0.0)}
    assert 64 <= _patch(monkeypatch, defn, both)[2] <= 95
    one = {"a": State(dimmer=1.0, strobe_hz=4.0, gate=0.0), "b": State(dimmer=1.0)}
    buf = _patch(monkeypatch, defn, one)
    assert (buf[0], buf[1], buf[2]) == (0, 255, 40)  # the steady cell stays steady, the other flashes on its dimmer


def test_a_library_copy_from_before_gets_its_ranges_from_the_catalogue(monkeypatch):
    fresh = {"modes": {"m": [{"attr": "dimmer"}, {"attr": "shutter", "default": 9, **{"strobe_range": [10, 90]}}]}}
    monkeypatch.setattr(fxlib.shadow, "get", lambda key: copy.deepcopy(fresh))
    old = {
        "qlc": {"key": "a/b.qxf", "converter": 9},
        "modes": {"m": [{"attr": "dimmer"}, {"attr": "shutter", "default": 40}]},
    }
    fxlib._strobes_from_catalogue(old)
    assert old["modes"]["m"][1] == {"attr": "shutter", "default": 40, "strobe_range": [10, 90]}  # its default stays


def test_a_template_and_a_chart_know_their_strobe(tmp_path, monkeypatch):
    monkeypatch.setattr(fxlib, "LIB_DIR", tmp_path)
    monkeypatch.setattr(fxlib, "USER_DIR", None)
    fxlib.library.cache_clear()
    try:
        made = generic.create("T", "Spot", "spot-9", 9)
        chans = fxlib.get(made["key"])["modes"][made["mode"]]
        assert next(c for c in chans if c["attr"] == "strobe")["strobe_range"] == [10, 255]
        chart = [
            {"name": "Dimmer", "role": "dimmer"},
            {"name": "Strobe", "role": mapper.HOLD, "value": 0,
             "ranges": [[0, 9, "off"], [10, 255, "strobe slow to fast"]]},
        ]  # fmt: skip
        made = generic.from_chart("T", "Par", "par", chart)
        assert fxlib.get(made["key"])["modes"][made["mode"]][1]["strobe_range"] == [10, 255]
    finally:
        fxlib.library.cache_clear()


def _strobing_show(track, path, **safety):
    rig = load_rig(path)
    rig["safety"].update(safety)
    plan = direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    drop = next(d for d in plan if d.section == "drop")
    plan = [replace(d, head_light="strobe", grouping="unison", layer_split="none") if d is drop else d for d in plan]
    return Engine(track, plan, rig), rig, drop


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_every_strobe_channel_plays_within_the_flash_limit(track, path):
    e, rig, drop = _strobing_show(track, path)
    limit = e._head_strobe_hz()  # (allow_fast_strobe: faster)
    rate = e.head_strobe_rate(drop)
    assert 0 < rate <= limit
    for t in np.arange(drop.start + 1.0, min(drop.end - 1.0, drop.start + 3.0), 1 / 40):
        states = e.render(float(t))[1]
        for s in states.values():
            assert s.strobe_hz <= limit + 1e-6
        for fx in rig["fixtures"]:
            if not fxlib.patched(fx) or fxlib.inert(fxlib.get(fx["fixture"])):
                continue
            buf = bytearray(512)
            fxlib.patch(buf, fx, states, 1.0)
            for off, c in enumerate(fxlib.channels(fxlib.get(fx["fixture"]), fx["mode"])):
                if "strobe_range" in c and buf[fx["address"] - 1 + off] != c.get("default"):
                    a, b = sorted(c["strobe_range"])
                    assert a <= buf[fx["address"] - 1 + off] <= b


def test_two_decks_keep_one_flash():
    rig = load_rig(SETS[0])
    head = next(e["id"] for e in rig["elements"] if e["kind"] == "head")
    others = {e["id"]: State() for e in rig["elements"]}
    mine = {**others, head: State(dimmer=1.0, strobe_hz=4.0, gate=0.0)}
    deck = type("Deck", (), {"deck": 0})
    other = type("Deck", (), {"deck": 1})
    states, _ = Mixer(rig).mix([(1.0, mine, deck, None, 0.0, 0), (0.0, others, other, None, 0.0, 0)])
    assert states[head].dimmer == pytest.approx(1.0) and states[head].lit == 0.0 and states[head].strobe_hz == 4.0
