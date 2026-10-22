"""GDTF and DMXControl DDF converters: driven channels get attributes, the rest stays quiet, lasers stay dark."""

import io
import zipfile

import pytest

from amadeus.engine.state import State
from amadeus.library import ddf, gdtf
from amadeus.library import fixtures as fxlib

HEAD_GDTF = """<?xml version="1.0" encoding="UTF-8"?>
<GDTF DataVersion="1.2">
  <FixtureType Name="Spot 100" LongName="Spot 100 LED" Manufacturer="Acme" FixtureTypeID="X">
    <Wheels>
      <Wheel Name="C1">
        <Slot Name="Open" Color="0.3127,0.3290,100"/>
        <Slot Name="Red" Color="0.64,0.33,21"/>
      </Wheel>
      <Wheel Name="G1"><Slot Name="Open"/><Slot Name="Dots"/><Slot Name="Star"/></Wheel>
    </Wheels>
    <Geometries>
      <Geometry Name="Base"><Axis Name="Yoke"><Axis Name="Head"><Beam Name="Beam" BeamAngle="14"
        LuminousFlux="3000" PowerConsumption="100"/></Axis></Axis></Geometry>
    </Geometries>
    <DMXModes>
      <DMXMode Name="Standard" Geometry="Base">
        <DMXChannels>
          <DMXChannel Offset="1,2" Geometry="Yoke"><LogicalChannel Attribute="Pan">
            <ChannelFunction Attribute="Pan" DMXFrom="0/1" PhysicalFrom="-270" PhysicalTo="270"/>
          </LogicalChannel></DMXChannel>
          <DMXChannel Offset="3" Geometry="Head"><LogicalChannel Attribute="Tilt">
            <ChannelFunction Attribute="Tilt" DMXFrom="0/1" PhysicalFrom="-100" PhysicalTo="100"/>
          </LogicalChannel></DMXChannel>
          <DMXChannel Offset="4" Geometry="Beam"><LogicalChannel Attribute="Shutter1">
            <ChannelFunction Attribute="Shutter1" DMXFrom="0/1">
              <ChannelSet DMXFrom="0/1" Name="Closed"/><ChannelSet DMXFrom="10/1" Name="Open"/>
            </ChannelFunction>
            <ChannelFunction Attribute="Shutter1Strobe" DMXFrom="20/1"/>
          </LogicalChannel></DMXChannel>
          <DMXChannel Offset="5" Geometry="Beam"><LogicalChannel Attribute="Dimmer">
            <ChannelFunction Attribute="Dimmer" DMXFrom="0/1"/>
          </LogicalChannel></DMXChannel>
          <DMXChannel Offset="6" Geometry="Beam"><LogicalChannel Attribute="Color1">
            <ChannelFunction Attribute="Color1" DMXFrom="0/1" Wheel="C1">
              <ChannelSet DMXFrom="0/1" Name="Open" WheelSlotIndex="1"/>
              <ChannelSet DMXFrom="16/1" Name="Red" WheelSlotIndex="2"/>
            </ChannelFunction>
            <ChannelFunction Attribute="Color1WheelSpin" DMXFrom="128/1"/>
          </LogicalChannel></DMXChannel>
          <DMXChannel Offset="7" Geometry="Beam"><LogicalChannel Attribute="Gobo1">
            <ChannelFunction Attribute="Gobo1" DMXFrom="0/1" Wheel="G1">
              <ChannelSet DMXFrom="0/1" Name="Open" WheelSlotIndex="1"/>
              <ChannelSet DMXFrom="20/1" Name="Dots" WheelSlotIndex="2"/>
              <ChannelSet DMXFrom="40/1" Name="Star" WheelSlotIndex="3"/>
            </ChannelFunction>
            <ChannelFunction Attribute="Gobo1SelectShake" DMXFrom="64/1"/>
            <ChannelFunction Attribute="Gobo1WheelSpin" DMXFrom="128/1"/>
          </LogicalChannel></DMXChannel>
          <DMXChannel Offset="8" Geometry="Beam"><LogicalChannel Attribute="Control1">
            <ChannelFunction Attribute="Control1" DMXFrom="0/1">
              <ChannelSet DMXFrom="0/1" Name="No function"/><ChannelSet DMXFrom="200/1" Name="Reset"/>
            </ChannelFunction>
          </LogicalChannel></DMXChannel>
        </DMXChannels>
      </DMXMode>
    </DMXModes>
  </FixtureType>
</GDTF>"""


def _gdtf(xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("description.xml", xml)
    return buf.getvalue()


def _patches(d: dict):
    """Every mode and beam effect patches; an inert fixture only sends its defaults."""
    real = fxlib.get
    fxlib.get = lambda key: d
    try:
        for mode, chans in d["modes"].items():
            fx = {"id": "f", "fixture": "x/y", "mode": mode, "universe": 1, "address": 1, "x": 0.5}
            states = {e["id"]: State(dimmer=1.0, r=1.0, g=0.5, b=0.2, pan=0.3, tilt=0.7) for e in fxlib.expand(fx)}
            for effect in d.get("beam_fx", {"open": {}}):
                for s in states.values():
                    s.fx, s.gobo = effect, 1
                buf = bytearray(512)
                fxlib.patch(buf, fx, states)
                if fxlib.inert(d):
                    assert list(buf[: len(chans)]) == [c.get("default", 0) for c in chans]
    finally:
        fxlib.get = real


def test_gdtf_moving_head():
    d = gdtf.convert(_gdtf(HEAD_GDTF))
    assert (d["manufacturer"], d["model"], d["kind"]) == ("Acme", "Spot 100 LED", "moving_head")
    chans = d["modes"]["Standard"]
    attrs = [c["attr"] for c in chans]
    assert attrs == ["pan", "pan_fine", "tilt", "shutter", "dimmer", "color_wheel", "gobo", "control1"]
    assert chans[3]["default"] == 14  # shutter open (10-19)
    assert chans[7]["default"] == 0  # no function, not reset
    assert d["physical"]["pan_deg"] == 540 and d["physical"]["tilt_deg"] == 200
    assert d["physical"]["beam_deg"] == 14 and d["physical"]["lumens"] == 3000
    red = d["color_wheel"]["slots"][1]
    assert (red["from"], red["to"]) == (16, 127) and red["rgb"][0] == 1.0 and red["rgb"][2] < 0.3
    assert d["beam_fx"]["gobo"] == {"gobo": [29, 51]} and d["gobo_names"] == ["Dots", "Star"]
    assert d["beam_fx"]["gobo_spin"] == {"gobo": {"range": [128, 255]}}
    _patches(d)


def test_gdtf_laser_stays_dark():
    xml = HEAD_GDTF.replace('<Beam Name="Beam"', '<Laser Name="Laser"/><Beam Name="Beam"')
    d = gdtf.convert(_gdtf(xml))
    assert d["kind"] == "laser" and fxlib.inert(d)
    _patches(d)


def test_gdtf_values_in_bytes():
    assert gdtf._dmx("128/1") == 128
    assert gdtf._dmx("32768/2", 2) == 128 and gdtf._dmx("255/1", 2) == 255
    assert gdtf._dmx("65535/2") == 255


TMH = """<device type="DMXDevice" dmxcversion="3.1.0">
  <information><ddf-library-id>1</ddf-library-id><model>TMH Test</model><vendor>Acme</vendor>
    <author>someone</author><mode>14ch</mode></information>
  <functions>
    <position><pan dmxchannel="0" finedmxchannel="1"><range range="540"/></pan>
      <tilt dmxchannel="2"><range range="230"/></tilt></position>
    <ptspeed dmxchannel="3"><range type="linear" mindmx="255" maxdmx="0" minval="0" maxval="100"/></ptspeed>
    <strobe dmxchannel="4"><range type="linear" mindmx="135" maxdmx="239"/></strobe>
    <dimmer dmxchannel="4"><range type="linear" mindmx="8" maxdmx="134"/></dimmer>
    <rgb><r dmxchannel="5"/><g dmxchannel="6"/><b dmxchannel="7"/></rgb>
    <const name="Macro" dmxchannel="8" val="0"/>
    <gobowheel dmxchannel="10">
      <step type="open" mindmx="0" maxdmx="7"/>
      <step type="gobo" caption="Gobo 1" mindmx="8" maxdmx="15">
        <range handler="goboshake" mindmx="80" maxdmx="94"/></step>
    </gobowheel>
    <raw dmxchannel="11" name="Program"><step caption="No function" mindmx="0" maxdmx="9"/>
      <step caption="Auto" mindmx="10" maxdmx="255"/></raw>
  </functions>
</device>"""


def test_ddf_moving_head():
    d = ddf.convert([TMH])
    assert d["kind"] == "moving_head" and d["ddf"]["license"] == "CC-BY-SA-4.0"
    chans = d["modes"]["14ch"]
    assert [c["attr"] for c in chans] == [
        "pan", "pan_fine", "tilt", "pt_speed", "dimmer", "red", "green", "blue", "macro", "unused", "gobo", "program"
    ]  # fmt: skip
    assert chans[3]["default"] == 0  # pan/tilt speed: fastest
    assert chans[4]["range"] == [8, 134]  # the dimmer part of a dimmer + strobe channel
    assert d["physical"]["tilt_deg"] == 230
    assert d["beam_fx"]["gobo"] == {"gobo": [11]} and d["beam_fx"]["gobo_shake"] == {"gobo": [87]}
    _patches(d)


def test_ddf_two_files_are_two_modes():
    d = ddf.convert([TMH, TMH.replace("<mode>14ch</mode>", "<mode>Basic 12 channels</mode>")])
    assert list(d["modes"]) == ["14ch", "Basic12ch"]


@pytest.mark.parametrize(
    "functions",
    [
        '<raw dmxchannel="0" name="X-axis moving"/><colorwheel dmxchannel="1">'
        '<step type="color" val="#ff0000" mindmx="10" maxdmx="20"/></colorwheel>',
        '<colorwheel dmxchannel="0"><step type="color" val="#ff0000" mindmx="10" maxdmx="20"/></colorwheel>'
        '<gobowheel dmxchannel="1"><step type="gobo" mindmx="10" maxdmx="20"/></gobowheel>',
    ],
)
def test_ddf_lasers_and_undimmable_effects_stay_dark(functions):
    xml = TMH.split("<functions>")[0] + f"<functions>{functions}</functions></device>"
    d = ddf.convert([xml.replace("TMH Test", "Effect")])
    assert fxlib.inert(d)
    _patches(d)


def test_ddf_fog_machine_fires_only_its_output():
    xml = TMH.split("<functions>")[0] + (
        '<functions><raw dmxchannel="0" name="Mode"><step caption="DMX" mindmx="0" maxdmx="9"/></raw>'
        '<fog dmxchannel="1"><range type="linear" mindmx="10" maxdmx="255"/></fog>'
        '<raw dmxchannel="2" name="Interval"/></functions></device>'
    )
    d = ddf.convert([xml.replace("TMH Test", "Fogger")])
    assert d["kind"] == "smoke" and not fxlib.inert(d)
    assert [c["attr"] for c in d["modes"]["14ch"]] == ["mode", "fog", "interval"]


def test_ddf_without_known_channels_is_refused():
    xml = TMH.split("<functions>")[0] + '<functions><hsv><hue dmxchannel="0"/></hsv></functions></device>'
    with pytest.raises(ValueError):
        ddf.convert([xml])


@pytest.fixture
def empty_library(monkeypatch, tmp_path):
    monkeypatch.setattr(fxlib, "LIB_DIR", tmp_path)
    monkeypatch.setattr(fxlib, "USER_DIR", None)
    fxlib.library.cache_clear()
    yield tmp_path
    fxlib.library.cache_clear()


def test_importing_a_gdtf_file_through_the_app(empty_library):
    """The apps send the file's bytes; it lands in your fixtures, and a broken file is said, not fatal."""
    import base64

    from amadeus.web import library as web_library

    class Req:
        client = "test"

        def __init__(self, body):
            self._body = body

        def body(self):
            return self._body

    r = web_library.import_gdtf(Req({"name": "spot.gdtf", "data": base64.b64encode(_gdtf(HEAD_GDTF)).decode()}))
    assert r["key"] == "acme/spot-100-led" and r["mode"] == "Standard" and not r["inert"]
    assert fxlib.get(r["key"])["kind"] == "moving_head"
    body, status = web_library.import_gdtf(Req({"name": "notes.txt", "data": base64.b64encode(b"hello").decode()}))
    assert status == 400 and "notes.txt" in body["error"]


def test_a_gdtf_import_never_replaces_a_fixture_from_another_library(empty_library):
    fxlib.save("acme/spot-100-led", {"manufacturer": "Acme", "model": "Spot 100 LED", "kind": "par", "modes": {}})
    assert gdtf.add_file(_gdtf(HEAD_GDTF)) == "acme/spot-100-led-gdtf"
    assert fxlib.get("acme/spot-100-led")["kind"] == "par"
    assert gdtf.add_file(_gdtf(HEAD_GDTF)) == "acme/spot-100-led-gdtf"  # importing again updates its own copy


def test_no_gdtf_content_is_committed():
    """GDTF Share's terms forbid redistribution: a converted .gdtf is the user's own, never in the repo."""
    import json
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    try:
        files = subprocess.run(
            ["git", "-C", str(root), "ls-files", "fixtures"], capture_output=True, text=True, check=True
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    assert not [f for f in files if f.endswith(".gdtf")]
    for f in files:
        if f.endswith(".json"):
            assert "gdtf" not in json.loads((root / f).read_text(encoding="utf-8")), f
