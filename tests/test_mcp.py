"""`amadeus mcp`: the protocol on stdio, and the tools working on sets and rigs (checked, undoable)."""

import io
import json
import sys

import pytest

from amadeus import mcp
from amadeus.rig import store


@pytest.fixture
def config(tmp_path, monkeypatch):
    """An empty config folder (and no examples) for the store, and the undo copies next to it."""
    monkeypatch.setattr(store, "SETS_DIR", tmp_path / "sets")
    monkeypatch.setattr(store, "RIGS_DIR", tmp_path / "rigs")
    monkeypatch.setattr(store, "ACTIVE_SET", tmp_path / "active-set")
    monkeypatch.setattr(store, "ACTIVE_RIG", tmp_path / "active-rig")
    monkeypatch.setattr(store, "LEGACY_RIG_FILE", tmp_path / "rig.json")
    monkeypatch.setattr(store, "EXAMPLES", tmp_path / "no-examples")
    monkeypatch.setattr(store, "sets", store._Kind(tmp_path / "sets", tmp_path / "active-set", "set"))
    monkeypatch.setattr(store, "rigs", store._Kind(tmp_path / "rigs", tmp_path / "active-rig", "rig"))
    monkeypatch.setattr(store._prepare, "done", False, raising=False)
    monkeypatch.setattr(mcp, "UNDO_DIR", tmp_path / "undo")
    (tmp_path / "sets").mkdir()
    return tmp_path


def tool(_tool: str, **args):
    r = mcp.call(_tool, args)
    text = r["content"][0]["text"]
    if r.get("isError"):
        raise AssertionError(f"{_tool}: {text}")
    return json.loads(text)


def converse(*messages) -> list[dict]:
    out = io.BytesIO()
    stdin = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
    old = sys.stdout
    try:
        mcp.serve(stdin, out)
    finally:
        sys.stdout = old
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_handshake_lists_the_tools_and_answers_only_requests():
    replies = converse(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
    )  # fmt: skip
    assert [r["id"] for r in replies] == [1, 2, 3, 4]
    init = replies[0]["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    assert "stage left" in init["instructions"]
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"get_show", "save_show", "add_fixtures", "check_show", "undo_last_change"} <= names
    for t in replies[1]["result"]["tools"]:
        assert t["inputSchema"]["type"] == "object" and t["description"]
    assert replies[2]["error"]["code"] == -32601 and replies[3]["error"]["code"] == -32602


def test_an_older_client_gets_its_own_protocol_version():
    (r,) = converse({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
    assert r["result"]["protocolVersion"] == "2024-11-05"


def test_what_the_engine_prints_never_reaches_the_conversation(config, monkeypatch):
    monkeypatch.setattr(mcp, "list_sets_and_rigs", lambda a: print("chatter") or {"ok": True})
    monkeypatch.setitem(mcp.TOOLS, "list_sets_and_rigs", (mcp.list_sets_and_rigs, *mcp.TOOLS["list_sets_and_rigs"][1:]))
    (r,) = converse({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "list_sets_and_rigs"}})
    assert json.loads(r["result"]["content"][0]["text"]) == {"ok": True}


def test_a_venue_from_scratch_then_undo_step_by_step(config):
    tool("create_rig", name="Club X", template="club", width_m=10)
    tool("create_set", name="My Gear")
    assert tool("list_sets_and_rigs")["active"] == {"set": "my-gear", "rig": "club-x"}

    added = tool("add_fixtures", key="claypaky/sharpy", mode="Vector", count=4)
    assert [f["address"] for f in added["added"]] == [1, 21, 41, 61]
    assert sorted(added["mounted"]) == sorted(f["id"] for f in added["added"])
    check = tool("check_show")
    assert not check["problems"] and not check["overlaps"] and not check["not_mounted"]

    show = tool("get_show")["show"]
    assert all(f.get("truss") for f in show["fixtures"])
    show["fixtures"][0]["address"] = 510  # 20 channels from 510: past the end of the universe
    refused = tool("save_show", show=show)
    assert refused["saved"] is False and refused["problems"]
    assert tool("undo_last_change")["undone"].startswith("add_fixtures")  # the refused save left no copy
    assert store.sets.load("my-gear")["fixtures"] == []
    tool("undo_last_change")
    assert "my-gear" not in store.sets.names() and "club-x" in store.rigs.names()
    tool("undo_last_change")
    assert store.rigs.names() == []
    with pytest.raises(AssertionError, match="Nothing to undo"):
        tool("undo_last_change")


def test_a_failed_change_says_why_and_keeps_no_copy(config):
    tool("create_set", name="gear")
    r = mcp.call("create_set", {"name": "gear"})
    assert r["isError"] and "already exists" in r["content"][0]["text"]
    r = mcp.call("add_fixtures", {"key": "claypaky/sharpy", "mode": "Nope"})
    assert r["isError"] and "no mode" in r["content"][0]["text"]
    assert len(list((config / "undo").iterdir())) == 1


def test_a_set_placed_on_a_second_rig_keeps_its_places_on_the_first(config):
    tool("create_rig", name="home", template="booth")
    tool("create_set", name="gear")
    tool("add_fixtures", key="claypaky/sharpy", mode="Vector", count=2)
    first = store.rigs.load("home")["placements"]["gear"]
    tool("create_rig", name="festival", template="stage", width_m=14, make_active=False)
    placed = tool("place_set_on_rig", set="gear", rig="festival")
    assert placed["mounted"] == placed["fixtures"] == 2
    assert store.rigs.load("home")["placements"]["gear"] == first
    assert tool("check_show", rig="festival")["not_mounted"] == []


def test_the_command_never_watches_stdin_for_a_stop(monkeypatch, capsys):
    """Its stdin is the conversation: the stop-on-EOF watch (amadeus/shutdown.py) would read the messages away."""
    import threading

    from amadeus import cli

    monkeypatch.setenv("AMADEUS_STOP_ON_EOF", "1")
    cli.main(["mcp", "--guide"])
    assert "stage left" in capsys.readouterr().out
    assert not any(t.name == "stop-on-eof" for t in threading.enumerate())


def test_claude_desktop_gets_our_server_and_keeps_its_own(tmp_path):
    from amadeus.mcp import claude_desktop as cd

    folder = tmp_path / "Claude"
    folder.mkdir()
    config = folder / cd.FILE
    mine = {"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}
    config.write_text(json.dumps(mine), encoding="utf-8")
    env = {"PYTHONNOUSERSITE": "1"}

    assert cd.status(env, [folder]) == {"installed": True, "on": False, "current": False, "config": str(config),
                                        "problem": ""}  # fmt: skip
    on = cd.switch(True, env, [folder])
    assert on["on"] and on["current"]
    doc = json.loads(config.read_text(encoding="utf-8"))
    assert doc["theme"] == "dark" and doc["mcpServers"]["other"] == {"command": "x"}
    server = doc["mcpServers"][cd.NAME]
    assert server["command"] == sys.executable and server["args"] == ["-m", "amadeus", "mcp"]
    assert server["env"]["PYTHONNOUSERSITE"] == "1" and server["env"]["AMADEUS_DATA"]
    assert json.loads((folder / (cd.FILE + ".before-amadeus")).read_text(encoding="utf-8")) == mine

    server["command"] = "/an/app/that/moved/python3"  # the app moved: out of date until written again
    config.write_text(json.dumps(doc), encoding="utf-8")
    assert cd.status(env, [folder])["current"] is False
    assert cd.switch(True, env, [folder])["current"] is True

    assert cd.switch(False, env, [folder]) == {**on, "on": False, "current": False}
    assert json.loads(config.read_text(encoding="utf-8")) == mine


def test_a_claude_config_that_isnt_json_is_left_alone(tmp_path):
    from amadeus.mcp import claude_desktop as cd

    (tmp_path / cd.FILE).write_text("{ not json", encoding="utf-8")
    assert cd.status({}, [tmp_path])["problem"]
    with pytest.raises(ValueError):
        cd.switch(True, {}, [tmp_path])
    assert (tmp_path / cd.FILE).read_text(encoding="utf-8") == "{ not json"


def test_windows_finds_the_store_apps_config_too(tmp_path):
    from amadeus.mcp import claude_desktop as cd

    env = {"APPDATA": str(tmp_path / "Roaming"), "LOCALAPPDATA": str(tmp_path / "Local")}
    assert cd.folders(env, tmp_path, windows=True) == [tmp_path / "Roaming" / "Claude"]  # not installed: where it goes
    store = tmp_path / "Local" / "Packages" / "Claude_pzs8sxrjxfjjc" / "LocalCache" / "Roaming" / "Claude"
    store.mkdir(parents=True)
    assert cd.folders(env, tmp_path, windows=True) == [store]


@pytest.fixture
def fixtures_dir(config, tmp_path, monkeypatch):
    """Your fixtures in a folder of their own (the shipped library stays as it is)."""
    from amadeus.library import fixtures as fxlib

    monkeypatch.setattr(fxlib, "USER_DIR", tmp_path / "fixtures")
    fxlib.library.cache_clear()
    yield tmp_path / "fixtures"
    fxlib.library.cache_clear()


# a 15-channel beam/wash moving head as a maker's DMX chart lists it (made up for the test)
CHART = [
    {"name": "Pan", "role": "pan"}, {"name": "Pan fine", "role": "pan_fine"},
    {"name": "Tilt", "role": "tilt"}, {"name": "Tilt fine", "role": "tilt_fine"},
    {"name": "Pan/tilt speed", "role": "hold", "value": 0, "ranges": [[0, 255, "fast to slow"]]},
    {"name": "Dimmer", "role": "dimmer"}, {"name": "Dimmer fine", "role": "dimmer_fine"},
    {"name": "Shutter", "role": "hold", "value": 255, "ranges": [[0, 3, "closed"], [4, 7, "open"], [8, 255, "strobe"]]},
    {"name": "Red", "role": "red"}, {"name": "Green", "role": "green"}, {"name": "Blue", "role": "blue"},
    {"name": "White", "role": "white"}, {"name": "Zoom", "role": "hold", "value": 128},
    {"name": "Auto programs", "role": "hold", "value": 0}, {"name": "Control", "role": "hold", "value": 0},
]  # fmt: skip


def test_a_fixture_the_library_lacks_is_made_from_its_chart_then_patched(fixtures_dir):
    tool("create_rig", name="venue", template="club")
    tool("create_set", name="gear")
    made = tool("create_fixture", manufacturer="Test Maker", model="Beamwash 15", type="wash", mode="15CH",
                channels=CHART, physical={"watts": 300, "beam_deg": 4, "pan_deg": 540, "tilt_deg": 270},
                source="the user manual, page 12")  # fmt: skip
    assert made["key"] == "test-maker/beamwash-15" and made["mode"] == "15CH" and made["checked"] is False
    assert made["details"]["kind"] == "moving_head" and len(made["details"]["modes"]["15CH"]) == 15

    from amadeus.library import fixtures as fxlib

    defn = fxlib.get(made["key"])
    chans = defn["modes"]["15CH"]
    assert chans[7] == {"attr": "shutter", "default": 255}  # held open: the light shows
    assert chans[12] == {"attr": "zoom", "default": 128}
    assert [c["attr"] for c in chans if "default" not in c] == [
        "pan", "pan_fine", "tilt", "tilt_fine", "dimmer", "dimmer_fine", "red", "green", "blue", "white"]  # fmt: skip
    assert defn["made"]["checked"] is False and "page 12" in defn["source"]
    assert defn["made"]["channels"]["15CH"][7]["ranges"][1] == [4, 7, "open"]
    assert defn["physical"]["pan_deg"] == 540 and defn["physical"]["watts"] == 300

    added = tool("add_fixtures", key=made["key"], mode="15CH", count=2)
    assert [f["address"] for f in added["added"]] == [1, 21] and len(added["mounted"]) == 2
    tool("undo_last_change")  # the patch
    tool("undo_last_change")  # the fixture
    assert not (fixtures_dir / "test-maker" / "beamwash-15.json").exists()


def test_a_chart_that_cant_light_or_has_an_unknown_role_makes_nothing(fixtures_dir):
    r = mcp.call("create_fixture", {"manufacturer": "X", "model": "Dark", "type": "par", "source": "x",
                                    "channels": [{"name": "Macro", "role": "hold", "value": 0}]})  # fmt: skip
    assert r["isError"] and "No channel lights it" in r["content"][0]["text"]
    r = mcp.call("create_fixture", {"manufacturer": "X", "model": "Odd", "type": "par", "source": "x",
                                    "channels": [{"name": "Gobo", "role": "gobo"}]})  # fmt: skip
    assert r["isError"] and "unknown role" in r["content"][0]["text"]
    assert not list(fixtures_dir.glob("*/*.json"))
    assert not (fixtures_dir.parent / "undo").exists() or not list((fixtures_dir.parent / "undo").iterdir())


QXF = """<?xml version="1.0" encoding="UTF-8"?>
<FixtureDefinition xmlns="http://www.qlcplus.org/FixtureDefinition">
 <Manufacturer>Test Maker</Manufacturer>
 <Model>Par Four</Model>
 <Type>Color Changer</Type>
 <Channel Name="Dimmer" Preset="IntensityMasterDimmer"/>
 <Channel Name="Red" Preset="IntensityRed"/>
 <Channel Name="Green" Preset="IntensityGreen"/>
 <Channel Name="Blue" Preset="IntensityBlue"/>
 <Mode Name="4 Channel">
  <Channel Number="0">Dimmer</Channel>
  <Channel Number="1">Red</Channel>
  <Channel Number="2">Green</Channel>
  <Channel Number="3">Blue</Channel>
 </Mode>
</FixtureDefinition>
"""


def test_a_fixture_file_of_your_own_is_imported_and_never_replaces_one(fixtures_dir, tmp_path):
    f = tmp_path / "Test-Maker-Par-Four.qxf"
    f.write_text(QXF, encoding="utf-8")
    first = tool("import_fixture_file", path=str(f))
    assert first["key"] == "testmaker/par-four" and list(first["details"]["modes"]) == ["4ch"]
    assert tool("import_fixture_file", path=str(f))["key"] == "testmaker/par-four-2"
    tool("undo_last_change")
    assert not (fixtures_dir / "testmaker" / "par-four-2.json").exists()
    assert (fixtures_dir / "testmaker" / "par-four.json").exists()
    r = mcp.call("import_fixture_file", {"path": str(tmp_path / "nope.qxf")})
    assert r["isError"] and "No file" in r["content"][0]["text"]
    (tmp_path / "x.d4").write_text("x", encoding="utf-8")
    assert "a .gdtf or .qxf" in mcp.call("import_fixture_file", {"path": str(tmp_path / "x.d4")})["content"][0]["text"]
