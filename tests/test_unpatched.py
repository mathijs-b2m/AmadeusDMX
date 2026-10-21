"""Fixtures without a start address (added in the apps: you give the address set on the fixture): they play in the
visualiser only, never on the wire; overlaps are a warning while you patch, not a reason to refuse a save."""

from types import SimpleNamespace

from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.rig.loader import load_rig_dict
from amadeus.web import rig as webrig

KATANA = {"fixture": "dts/katana", "mode": "Extended", "universe": 1, "x": 0.5}


def test_without_an_address_nothing_is_written():
    fx = {"id": "katana1", **KATANA}
    buf = bytearray(512)
    fxlib.patch(buf, fx, {e["id"]: State(dimmer=1.0, r=1, g=1, b=1) for e in fxlib.expand(fx)})
    fxlib.test_light(buf, fx)
    fxlib.test_raw(buf, fx, [255] * fxlib.footprint(fx))
    assert buf == bytearray(512)
    assert not fxlib.patched(fx) and fxlib.patched({**fx, "address": 1})


def test_a_set_with_fixtures_waiting_for_an_address_loads():
    rig = load_rig_dict({"fixtures": [{"id": "katana1", **KATANA}, {"id": "katana2", **KATANA, "address": 1}]})
    assert {e["fixture"] for e in rig["elements"]} == {"katana1", "katana2"}  # both in the visualiser
    assert fxlib.validate(rig) == [] and fxlib.overlaps(rig) == []


def test_overlaps_are_a_warning_out_of_range_is_refused():
    n = fxlib.footprint(KATANA)
    both = {"fixtures": [{"id": "a", **KATANA, "address": 1}, {"id": "b", **KATANA, "address": n // 2}]}
    assert fxlib.validate(both) == []
    assert fxlib.overlaps(both) == [f"b overlaps a at universe 1 channel {n // 2}"]
    past = {"fixtures": [{"id": "a", **KATANA, "address": 512}]}
    assert fxlib.validate(past)


def test_autopatch_can_leave_the_addresses_to_you():
    req = SimpleNamespace(body=lambda: {"fixtures": [dict(KATANA), dict(KATANA)], "addresses": False})
    out = webrig.autopatch(req)["fixtures"]
    assert [f["id"] for f in out] == ["katana1", "katana2"] and all("address" not in f for f in out)
    req = SimpleNamespace(body=lambda: {"fixtures": [dict(KATANA), dict(KATANA)]})
    assert [f["address"] for f in webrig.autopatch(req)["fixtures"]] == [1, 1 + fxlib.footprint(KATANA)]
