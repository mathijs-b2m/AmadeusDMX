"""The fixture twin (tools/twin.py): its motors, its DMX decoding, and that it tells range and speed apart."""

import copy
import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

from amadeus.rig.loader import load_rig

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("twin", ROOT / "tools" / "twin.py")
twin = importlib.util.module_from_spec(_spec)
sys.modules["twin"] = twin  # (dataclasses look their module up)
_spec.loader.exec_module(twin)

RIG = ROOT / "tests" / "sets" / "fuze24.json"


def test_motor_moves_like_a_motor():
    """90° with 400°/s² both ways never reaches 200°/s: a triangle, 2·√(d/a) = 0.95 s, after the delay."""
    axis = twin.Axis(range_deg=180, vmax_dps=200, accel_dps2=400, decel_dps2=400, latency_ms=50)
    t = twin.Twin({"pan": axis, "tilt": copy.copy(axis)})
    t.feed(0.0, 0.0, 0.0)
    t.advance(0.1)
    t.feed(0.1, 0.5, 0.0)  # 0 → 90°
    arrived = None
    for k in range(1, 2000):
        t.advance(0.1 + k / 1000)
        if arrived is None and abs(t.deg("pan") - 90) < 0.01:
            arrived = k / 1000
    assert arrived == pytest.approx(0.05 + 2 * math.sqrt(90 / 400), abs=0.03)
    assert t.deg("pan") == pytest.approx(90, abs=0.01)  # and stays there, no overshoot left
    assert t.deg("tilt") == 0


def test_decodes_what_the_library_patches():
    rig = load_rig(RIG)
    head = twin.Head(rig, "top1")
    pan, tilt, speed = head.decode(bytes(head.universe_with(0.3, 0.7, 1.0)))
    assert pan == pytest.approx(0.3, abs=1e-4) and tilt == pytest.approx(0.7, abs=1e-4)
    assert speed == 0  # the engine always asks for the fastest


@pytest.fixture(scope="module")
def show():
    rig = load_rig(RIG)
    head = twin.Head(rig, "top1")
    r, fps = twin.render(rig, head)
    return head, r, fps


def _run(show, **changes):
    head, r, fps = show
    profile = twin.default_profile(head.defn)
    for key, value in changes.items():
        axis, field = key.split("__")
        setattr(profile[axis], field, value)
    return twin.measure(head, profile, r, twin.drive(r, profile), fps)


def test_a_twin_with_the_engines_numbers_matches_the_visualiser(show):
    """The engine's prediction is consistent with the DMX it sends: any gap on a real head is its numbers."""
    for axis, c in _run(show).items():
        assert c["rms_aligned"] < 2.5, axis  # the lag is checked on its own: a fast motor makes it cost degrees
        assert c["range"] == pytest.approx(1.0, abs=0.03), axis
        assert abs(c["lag_ms"]) < 40, axis
        assert "matches" in twin.verdict(axis, c)


def test_a_smaller_range_is_a_range_not_a_delay(show):
    c = _run(show, tilt__range_deg=180)["tilt"]
    assert c["range"] == pytest.approx(180 / show[0].engine_range["tilt"], abs=0.03)
    assert abs(c["lag_ms"]) < 40
    assert "range" in twin.verdict("tilt", c)


def test_a_slow_motor_is_late_not_a_smaller_range(show):
    c = _run(show, pan__vmax_dps=90, pan__accel_dps2=200, pan__decel_dps2=200)["pan"]
    assert c["lag_ms"] >= 60
    assert c["range"] is None or c["range"] == pytest.approx(1.0, abs=0.05)
    assert "later" in twin.verdict("pan", c)


def test_a_quicker_fixture_runs_ahead(show):
    """Less delay than the engine's lead: the real head arrives before the visualiser's."""
    c = _run(show, tilt__latency_ms=40)["tilt"]
    assert c["lag_ms"] == pytest.approx(-80, abs=30)


def test_apply_writes_the_range_and_keeps_home_on_the_same_dmx_value(tmp_path, monkeypatch):
    from amadeus.rig.store import Selection

    lib = tmp_path / "fixtures"
    (lib / "beamz").mkdir(parents=True)
    (lib / "beamz" / "fuze75b-beam.json").write_text(
        (ROOT / "fixtures/beamz/fuze75b-beam.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(twin.fxlib, "LIB_DIR", lib)
    rig_file = tmp_path / "rig.json"
    rig_file.write_text(RIG.read_text(encoding="utf-8"), encoding="utf-8")
    doc = json.loads(rig_file.read_text(encoding="utf-8"))
    doc["fixtures"][0]["pan_home_deg"] = 360  # like a set whose front is at 2/3 of the pan range
    rig_file.write_text(json.dumps(doc), encoding="utf-8")

    head = twin.Head(load_rig(rig_file), doc["fixtures"][0]["id"])
    head.defn = copy.deepcopy(head.defn)  # the library's cache stays untouched
    profile = twin.default_profile(head.defn)
    profile["pan"].range_deg = 600
    profile["tilt"].vmax_dps = 120
    notes = twin.apply_to_engine(head, profile, Selection(file=rig_file))

    saved = json.loads((lib / "beamz" / "fuze75b-beam.json").read_text(encoding="utf-8"))
    tilt_deg = json.loads((ROOT / "fixtures/beamz/fuze75b-beam.json").read_text(encoding="utf-8"))["physical"][
        "tilt_deg"
    ]
    assert saved["physical"]["pan_deg"] == 600 and saved["physical"]["tilt_deg"] == tilt_deg
    assert saved["motion"]["tilt_speed_dps"] == 120
    fx = json.loads(rig_file.read_text(encoding="utf-8"))["fixtures"][0]
    assert fx["pan_home_deg"] == 400  # 360 of 540 is the same DMX value as 400 of 600
    assert any("pan range" in n for n in notes)
