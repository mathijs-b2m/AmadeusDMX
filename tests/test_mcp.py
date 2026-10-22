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
