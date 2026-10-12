"""DMX devices apart from sets: a set maps its universes onto them."""

import pytest

from amadeus.dmx import devices, outputs

DEVICES = [
    {"id": "pocket", "name": "Pocket", "type": "artnet", "ip": "127.0.0.1", "first_universe": 0, "outputs": 2},
    {"id": "foh", "name": "FOH", "type": "sacn", "ip": "127.0.0.1", "priority": 120},
]


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(devices, "path", lambda: tmp_path / "devices.json")
    assert devices.save(DEVICES) == []
    return tmp_path


def test_a_set_maps_its_universes_onto_devices(library):
    rig = {"dmx": {"1": {"device": "pocket", "output": 1}, "2": {"device": "pocket", "output": 2},
                   "3": {"device": "foh", "output": 4}}}  # fmt: skip
    specs = {s["type"]: s for s in devices.resolve(rig)}
    assert specs["artnet"]["universes"] == [1, 2] and specs["artnet"]["universe_map"] == {1: 0, 2: 1}
    assert specs["sacn"]["universe_map"] == {3: 4} and specs["sacn"]["priority"] == 120
    assert "Pocket (universe 1, 2)" in devices.describe(rig)


def test_the_engine_sends_each_universe_to_its_device_and_output(library):
    out = outputs.open_output({"dmx": {"1": {"device": "pocket", "output": 2}}}, owner=True)
    sent = []
    out.sender.send = lambda u: sent.append(sorted(u))
    out.send({1: bytes(512), 2: bytes(512)})
    assert sent == [[1]]  # set universe 1 → the node's second output (Art-Net universe 1); universe 2 not mapped here


def test_mapping_problems_are_found(library):
    assert devices.check_mapping({"dmx": {"1": {"device": "nope"}}})
    clash = {"dmx": {"1": {"device": "pocket", "output": 1}, "2": {"device": "pocket", "output": 1}}}
    assert any("both go to" in p for p in devices.check_mapping(clash))
    assert outputs.validate({"dmx": {"1": {"device": "pocket", "output": 1}}}) == []


def test_devices_are_validated(library):
    assert devices.save([{"id": "bad id", "type": "artnet", "ip": "1.2.3.4"}])
    assert devices.save([{"id": "a", "type": "artnet"}])  # an Art-Net node needs its IP
    assert devices.load() == DEVICES  # nothing saved


def test_a_set_without_a_mapping_works_as_before():
    assert outputs.describe({"artnet": {"ip": "2.0.0.10"}}) == "Art-Net → 2.0.0.10"
