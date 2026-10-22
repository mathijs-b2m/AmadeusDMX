"""Sets (gear) and rigs (venues): the files, the combined view the engine reads, migration and auto-mount."""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from amadeus.library import fixtures as fxlib
from amadeus.rig import automount, manage, store, templates
from amadeus.rig.loader import load_rig_dict

SETS = Path(__file__).parent / "sets"


@pytest.fixture
def config(tmp_path, monkeypatch):
    """An empty config folder (and no examples) for the store."""
    monkeypatch.setattr(store, "SETS_DIR", tmp_path / "sets")
    monkeypatch.setattr(store, "RIGS_DIR", tmp_path / "rigs")
    monkeypatch.setattr(store, "ACTIVE_SET", tmp_path / "active-set")
    monkeypatch.setattr(store, "ACTIVE_RIG", tmp_path / "active-rig")
    monkeypatch.setattr(store, "LEGACY_RIG_FILE", tmp_path / "rig.json")
    monkeypatch.setattr(store, "EXAMPLES", tmp_path / "no-examples")
    monkeypatch.setattr(store, "sets", store._Kind(tmp_path / "sets", tmp_path / "active-set", "set"))
    monkeypatch.setattr(store, "rigs", store._Kind(tmp_path / "rigs", tmp_path / "active-rig", "rig"))
    monkeypatch.setattr(store._prepare, "done", False, raising=False)
    (tmp_path / "sets").mkdir()
    return tmp_path


def old_style(config, name: str) -> dict:
    """Put an old combined set file (as sets were before rigs existed) into the config."""
    doc = json.loads((SETS / f"{name}.json").read_text(encoding="utf-8"))
    shutil.copy(SETS / f"{name}.json", config / "sets" / f"{name}.json")
    return doc


@pytest.mark.parametrize("name", ["showcase", "zones", "laser-zones", "small"])
def test_old_sets_split_into_set_and_rig_and_load_the_same(config, name):
    old = old_style(config, name)
    assert store.sets.names() == [name] and store.rigs.names() == [name]
    set_doc, rig_doc = store.sets.load(name), store.rigs.load(name)
    assert not store.is_combined(set_doc)
    assert "fixtures" not in rig_doc and set(rig_doc["placements"]) == {name}
    show = store.Selection(rig=name, set=name)
    store._onto_tower_faces(old)  # (the one thing that changes: tower fixtures hang off the tower's face now)
    assert load_rig_dict(show.load()) == load_rig_dict(old)


def test_saving_the_combined_view_changes_nothing(config):
    old_style(config, "showcase")
    show = store.Selection(rig="showcase", set="showcase")
    show.save(show.load())  # (once: tower fixtures from before tower faces get theirs)
    before = [p.read_text(encoding="utf-8") for p in show.paths]
    show.save(show.load())
    assert [p.read_text(encoding="utf-8") for p in show.paths] == before


def test_a_set_on_a_new_rig_waits_until_mounted(config):
    old_style(config, "showcase")
    manage.new_rig("club", "club", width=10)
    show = store.Selection(rig="club", set="showcase")
    merged = show.load()
    assert all(f.get(store.UNPLACED) for f in merged["fixtures"])
    assert show.placed() == (0, 30)
    show.save(merged)  # nothing moved: still not mounted
    assert show.placed() == (0, 30)
    merged["fixtures"][0]["x"] = 0.3  # moved by hand: now it has a place
    merged["fixtures"][0].pop(store.UNPLACED)
    show.save(merged)
    assert show.placed() == (1, 30)
    assert store.Selection(rig="showcase", set="showcase").placed() == (30, 30)  # the other rig is untouched


def test_mounting_some_leaves_the_others_waiting(config):
    old_style(config, "showcase")
    manage.new_rig("club", "club", width=10)
    show = store.Selection(rig="club", set="showcase")
    ids = [f["id"] for f in show.load()["fixtures"][:5]]
    assert set(manage.mount(show, ids)) == set(ids)
    assert show.placed() == (5, 30)
    manage.mount(show)
    assert show.placed() == (30, 30)


def test_copying_a_set_copies_where_it_hangs(config):
    old_style(config, "showcase")
    manage.new_set("mine", copy_of="showcase")
    assert store.Selection(rig="showcase", set="mine").placed() == (30, 30)


@pytest.mark.parametrize("template", list(templates.TEMPLATES))
@pytest.mark.parametrize("set_name", ["showcase", "laser-zones"])
def test_automount_hangs_everything_sensibly(config, template, set_name):
    old_style(config, set_name)
    manage.new_rig("venue", template, width=10, height=5)
    show = store.Selection(rig="venue", set=set_name)
    manage.mount(show)
    merged = show.load()
    fixtures = merged["fixtures"]
    assert show.placed() == (len(fixtures), len(fixtures))
    trusses = {t["id"]: t for t in merged.get("trusses", [])}
    on_side: dict = {}
    for f in fixtures:
        kind = fxlib.get(f["fixture"])["kind"]
        if f.get("truss"):
            t = trusses[f["truss"]]
            u = f["truss_pos_m"]
            assert (0 <= u <= t["length_m"]) if t.get("vertical") else abs(u) <= t["length_m"] / 2 + 1e-6
            on_side.setdefault((f["truss"], f.get("truss_side")), []).append((u, f["fixture"]))
        if kind == "laser":
            assert f["z_m"] >= automount.LASER_MIN_M, f"laser {f['id']} too low"
        if kind in ("moving_head", "moving_bar") and f.get("truss"):
            assert f["z_m"] > 0.5, f"head {f['id']} on the floor"
    for (tid, side), spots in on_side.items():
        us = sorted(u for u, _ in spots)
        assert all(b - a >= 0.39 for a, b in zip(us, us[1:])), f"crowded on {tid}/{side}: {us}"
        if not trusses[tid].get("vertical"):  # every model mirrored around the middle (up to an odd one out)
            for model in {m for _, m in spots}:
                pos = sorted(round(u, 2) for u, m in spots if m == model)
                mirrored = sorted(round(-u, 2) for u in pos)
                assert len(set(pos) ^ set(mirrored)) <= 2, f"{model} not symmetric on {tid}: {pos}"


def test_automount_leaves_mounted_fixtures_and_their_room_alone(config):
    old_style(config, "showcase")
    manage.new_rig("club", "club", width=10)
    show = store.Selection(rig="club", set="showcase")
    merged = show.load()
    first = merged["fixtures"][0]
    truss = merged["trusses"][0]
    first.pop(store.UNPLACED)
    from amadeus.rig.trusses import place

    place(first, truss, 0.0, merged["stage"]["width_m"], "under")
    show.save(merged)
    manage.mount(show)
    after = {f["id"]: f for f in show.load()["fixtures"]}
    assert after[first["id"]]["truss_pos_m"] == 0.0
    clash = [f for f in after.values() if f["id"] != first["id"] and f.get("truss") == truss["id"]
             and f.get("truss_side") == "under" and abs(f["truss_pos_m"]) < 0.4]  # fmt: skip
    assert not clash


def test_a_tower_has_four_faces_and_a_top():
    from amadeus.rig import geometry
    from amadeus.rig import trusses as T

    tower = {"id": "tw", "vertical": True, "x_m": 0.0, "y_m": -1.5, "z_m": 1.5, "length_m": 3.0}
    out = {"front": (0, 1, 0), "back": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0)}
    for side, n in out.items():
        f = T.place({"id": "h", "mount": "stand"}, tower, 2.0, 8.0, side)
        assert f["mount"] == "hang" and f["z_m"] == 2.0  # hanging off the face…
        assert np.allclose(geometry.mount_up(f), n, atol=1e-6)  # …the head pointing out of it
    top = T.place({"id": "h"}, tower, 2.0, 8.0, "top")
    assert top["mount"] == "stand" and top["z_m"] > 3.0  # only on top it stands


def test_a_fixture_standing_on_a_tower_from_before_hangs_off_its_front():
    from amadeus.rig.store import compose

    rig = {"trusses": [{"id": "tw", "vertical": True, "x_m": 0.0, "y_m": -1.5, "z_m": 1.5, "length_m": 3.0}],
           "placements": {"s": {"h": {"truss": "tw", "truss_pos_m": 2.0, "mount": "stand", "x": 0.0, "y_m": -1.18,
                                      "z_m": 2.0}}}}  # fmt: skip
    out = compose({"fixtures": [{"id": "h", "fixture": "x"}]}, rig, "s")
    f = out["fixtures"][0]
    assert f["mount"] == "hang" and f["truss_side"] == "front" and f["mount_roll_deg"] == 90


def test_auto_mount_reads_the_structure_of_a_rig_without_trusses():
    from amadeus.rig import automount as am

    merged = json.loads(
        Path("tests/sets/concert60.json").read_text(encoding="utf-8")
    )  # fixtures at fixed positions, no trusses
    merged.pop("trusses", None)
    for f in merged["fixtures"]:
        f[store.UNPLACED] = True
    places = am.automount(merged, [f["id"] for f in merged["fixtures"]])
    kinds = sorted((t.get("vertical", False), t["length_m"]) for t in merged["trusses"])
    assert sum(v for v, _ in kinds) == 2 and len(kinds) == 4  # two towers, two overhead trusses
    assert all(p.get("truss") for p in places.values() if p.get("mount") == "hang")
    assert not any(p.get("mount") == "stand" and not p.get("truss") for p in places.values())  # no field of stands


def test_auto_mount_in_an_empty_room_builds_a_structure_first():
    from amadeus.rig import automount as am

    merged = json.loads(Path("tests/sets/showcase.json").read_text(encoding="utf-8"))
    merged.pop("trusses", None)
    for f in merged["fixtures"]:
        f.update(mount="floor", z_m=0.25, y_m=-0.3)
        f.pop("truss", None)
        f[store.UNPLACED] = True
    places = am.automount(merged, [f["id"] for f in merged["fixtures"]])
    assert merged["trusses"]  # a standard structure
    heads = [p for f, p in places.items() if p.get("truss")]
    assert len(heads) >= 10


def test_renaming_a_fixture_keeps_where_it_hangs(config):
    from types import SimpleNamespace

    from amadeus.web import rig as api

    old_style(config, "showcase")
    store.sets.load("showcase")  # (split into set and rig)
    req = SimpleNamespace(body=lambda: {"set": "showcase", "from": "sharpy1", "to": "beam-left"}, client="test")
    assert api.rename_fixture(req) == {"ok": True}
    assert "beam-left" in {f["id"] for f in store.sets.load("showcase")["fixtures"]}
    places = store.rigs.load("showcase")["placements"]["showcase"]
    assert "beam-left" in places and "sharpy1" not in places
    clash = SimpleNamespace(body=lambda: {"set": "showcase", "from": "sharpy2", "to": "beam-left"}, client="test")
    assert api.rename_fixture(clash)[1] == 400  # names stay unique


def test_mounting_new_fixtures_leaves_a_small_room_as_it_is():
    """Two new heads in a living room with two heads on stands: on stands beside them, no trusses invented."""
    from amadeus.rig import automount as am

    def fx(fid, x, y, z, mount, waiting=False):
        f = {"id": fid, "fixture": "beamz/fuze75b-beam", "x": x, "y_m": y, "z_m": z, "mount": mount}
        return {**f, "_unplaced": {}} if waiting else f

    merged = {
        "stage": {"width_m": 1.7, "ceiling_m": 2.6},
        "fixtures": [fx("a", 0.1, -1.2, 1.8, "stand"), fx("b", 0.9, -1.2, 1.8, "stand"),
                     fx("n1", 0.3, -0.3, 0.25, "floor", True), fx("n2", 0.6, -0.3, 0.25, "floor", True)],
    }  # fmt: skip
    places = am.automount(merged, ["n1", "n2"])
    assert merged["trusses"] == []  # nothing invented (and nothing through the 2.6 m ceiling)
    assert set(places) == {"n1", "n2"}  # the others stay where they are
    xs = sorted(p["x"] for p in places.values())
    assert all(min(abs(x - 0.1), abs(x - 0.9)) > 0.15 for x in xs)  # not on top of the ones already there
    assert all(p["mount"] == "stand" for p in places.values())


def test_an_example_added_later_comes_in_once(config, monkeypatch):
    examples = config / "examples"
    for folder in ("sets", "rigs"):
        (examples / folder).mkdir(parents=True)
        (examples / folder / "showcase.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(store, "EXAMPLES", examples)
    (config / "sets" / "mine.json").write_text("{}", encoding="utf-8")  # a folder from before .examples
    assert store.sets.names() == ["mine"]  # showcase shipped then: this folder had it and deleted it
    assert store.rigs.names() == ["showcase"]  # a first run

    (examples / "sets" / "venue.json").write_text("{}", encoding="utf-8")  # a later version adds an example
    (examples / "rigs" / "venue.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(store._prepare, "done", False)
    assert store.sets.names() == ["mine", "venue"] and store.rigs.names() == ["showcase", "venue"]

    (config / "sets" / "venue.json").unlink()  # deleted stays deleted
    monkeypatch.setattr(store._prepare, "done", False)
    assert store.sets.names() == ["mine"]
