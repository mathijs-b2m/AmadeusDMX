"""The shadow catalogue (fixtures/catalog/): every converted QLC+, Open Fixture Library and DMXControl DDF fixture
is safe to add and patch, and adding one works offline."""

import pytest

from amadeus.engine.state import State
from amadeus.library import catalog, ddf, ofl, qlc, shadow
from amadeus.library import fixtures as fxlib

KINDS = {"moving_head", "moving_bar", "par", "par_bar", "strobe", "blinder", "laser", "smoke"}


def entries():
    for source in shadow.FILES:
        for key, f in shadow.load(source)["fixtures"].items():
            yield key, f["index"], f["defn"]


def test_built_with_the_current_converters():
    """A converter changed: run `python tools/build_catalog.py` so every fixture gets the change."""
    assert shadow.load("qlc")["converter"] == qlc.CONVERTER_VERSION
    assert shadow.load("ofl")["converter"] == ofl.CONVERTER_VERSION
    assert shadow.load("ddf")["converter"] == ddf.CONVERTER_VERSION
    assert len(shadow.load("qlc")["fixtures"]) > 1500 and len(shadow.load("ofl")["fixtures"]) > 500
    assert len(shadow.load("ddf")["fixtures"]) > 500


def test_lasers_stay_dark_and_smoke_machines_only_fire_their_output():
    """A converted laser is never driven. A smoke machine is either inert (no output channel found) or plays
    only its output and its fan (engine/fog.py); everything else on it (timers, programs, LEDs) stays off."""
    seen = {"laser": 0, "smoke": 0, "driven smoke": 0}
    for key, idx, d in entries():
        cats = set(idx.get("categories", [])) | {idx.get("type", ""), idx.get("kind", "")}  # DDF: no categories
        if cats & {"laser", "Laser"}:
            assert d["kind"] == "laser" and fxlib.inert(d), key
            seen["laser"] += 1
        elif cats & {"smoke", "Smoke", "Hazer"}:
            assert d["kind"] == "smoke", key
            seen["smoke"] += 1
            if fxlib.inert(d):
                continue
            seen["driven smoke"] += 1
            assert d["physical"]["fog"]["type"] in ("fog", "haze"), key
            for chans in d["modes"].values():
                assert all(c["attr"] in ("fog", "fog_fan") or "default" in c for c in chans), key
    assert seen["laser"] > 50 and seen["smoke"] > 50 and seen["driven smoke"] > 60


def test_every_fixture_patches(monkeypatch):
    """Every mode of every fixture patches without errors; an inert one only ever sends its off values."""
    current = {}
    monkeypatch.setattr(fxlib, "get", lambda key: current["defn"])
    for key, _, d in entries():
        assert d["kind"] in KINDS, key
        assert d["modes"] and all(d["modes"].values()), key
        if d["kind"] in fxlib.MOVING:
            assert "tilt_deg" in d["physical"] and "motion" in d, key
        for c in (c for chans in d["modes"].values() for c in chans):
            assert all(0 <= v <= 255 for k, v in c.items() if k != "head" and type(v) is int), (key, c)
        current["defn"] = d
        for mode, chans in d["modes"].items():
            fx = {"id": "f", "fixture": key, "mode": mode, "universe": 1, "address": 1, "x": 0.5}
            states = {e["id"]: State(dimmer=1.0, r=1.0, g=0.5, b=0.2, pan=0.3, tilt=0.7) for e in fxlib.expand(fx)}
            for effect in d.get("beam_fx", {"open": {}}):  # every beam effect (gobos, prisms…) too
                for s in states.values():
                    s.fx, s.gobo = effect, 3
                buf = bytearray(512)
                fxlib.patch(buf, fx, states)
                if fxlib.inert(d):
                    assert list(buf[: len(chans)]) == [c.get("default", 0) for c in chans], key


def test_adding_works_offline(monkeypatch, tmp_path):
    def offline(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(qlc, "ensure_downloaded", offline)
    monkeypatch.setattr(ofl, "ensure_downloaded", offline)
    monkeypatch.setattr(qlc, "FIXTURES_DIR", tmp_path / "no-qlc")
    monkeypatch.setattr(ofl, "OFL_DIR", tmp_path / "no-ofl")
    monkeypatch.setattr(fxlib, "LIB_DIR", tmp_path / "fixtures")
    catalog._candidates_cached.cache_clear()
    fxlib.library.cache_clear()
    try:
        hits = catalog.search("stairville mh x50")
        assert hits and hits[0]["source"] in ("qlc", "ofl")
        key = catalog.add(hits[0]["key"])
        assert (tmp_path / "fixtures" / f"{key}.json").exists()
        assert fxlib.get(key)["kind"] == "moving_head"
        laser = catalog.details("qlc:beamZ/beamZ-LS-3DRG.qxf")
        assert laser["inert"] and "switch" in laser["warning"]
    finally:
        catalog._candidates_cached.cache_clear()
        fxlib.library.cache_clear()


@pytest.mark.parametrize("key", ["qlc:beamZ/beamZ-LS-3DRG.qxf"])
def test_a_laser_dmx_cant_keep_off_says_so(key):
    assert "power it from a switch" in shadow.get(key)["warning"]


def test_a_ddf_fixture_keeps_its_licence_and_authors(monkeypatch, tmp_path):
    """CC BY-SA 4.0: a DDF fixture copied into your library still says where it came from, by whom, under what."""
    monkeypatch.setattr(fxlib, "LIB_DIR", tmp_path)
    monkeypatch.setattr(fxlib, "USER_DIR", None)
    catalog._candidates_cached.cache_clear()
    fxlib.library.cache_clear()
    try:
        hits = [c for c in catalog.search("eurolite", 200) if c["source"] == "ddf"]
        assert hits, "the DDF library fills in Eurolite"
        key = catalog.add(hits[0]["key"])
        d = fxlib.get(key)
        assert d["ddf"]["license"] == "CC-BY-SA-4.0" and d["ddf"]["ids"] and "CC BY-SA 4.0" in d["source"]
    finally:
        catalog._candidates_cached.cache_clear()
        fxlib.library.cache_clear()
