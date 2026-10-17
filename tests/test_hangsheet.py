"""The hang sheet (amadeus/rig/hangsheet.py): every fixture once, labelled by where it goes, in order along its
truss from the stage-left end, on every rig in tests/sets."""

import json
from pathlib import Path

import numpy as np
import pytest

from amadeus.library import fixtures as fxlib
from amadeus.rig import automount, geometry, hangsheet, store, templates
from amadeus.rig import trusses as T

SETS = sorted(Path("tests/sets").glob("*.json"))


def mounted(path: Path) -> dict:
    """A test set, auto-mounted the way the Mac app's Auto-Mount does it."""
    merged = json.loads(path.read_text(encoding="utf-8"))
    places = automount.automount(merged, [f["id"] for f in merged["fixtures"]])
    for f in merged["fixtures"]:
        if f["id"] in places:
            for k in store.PLACEMENT_KEYS:
                f.pop(k, None)
            f.update(places[f["id"]])
    return merged


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_every_fixture_once_with_a_label_that_says_where(path):
    merged = mounted(path)
    lay = hangsheet.layout(merged)
    placed = [r for s in lay["structures"] for r in s["fixtures"]] + lay["floor"]
    assert sorted(r["id"] for r in placed) == sorted(f["id"] for f in merged["fixtures"])
    labels = [r["label"] for r in placed]
    assert len(set(labels)) == len(labels)
    for s in lay["structures"]:
        assert [r["label"] for r in s["fixtures"]] == [f"{s['id']} {n}" for n in range(1, len(s["fixtures"]) + 1)]
        keys = [r["_key"] for r in s["fixtures"]]
        assert keys == sorted(keys)
        if s["kind"] != "tower":
            assert all(-0.01 <= k <= s["truss"]["length_m"] + 0.01 for k in keys)
    assert [(r["universe"], r["address"]) for r in lay["patch"]] == sorted(
        (r["universe"], r["address"]) for r in lay["patch"]
    )
    page = hangsheet.html(merged, path.stem, "test")
    assert page.startswith("<!doctype html>")
    for f in merged["fixtures"]:
        assert f">{f['id']}<" in page


def test_counted_from_stage_left_and_measured_from_that_end():
    """x = 0 is stage left: the fixture nearest it is number 1, at its distance from that end."""
    rig = templates.rig("booth", width=8.0)
    t = rig["trusses"][0]
    rig["fixtures"] = []
    for k, u in enumerate((1.5, -2.0, 0.0)):
        f = {"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1, "address": 1 + 20 * k}
        rig["fixtures"].append(T.place(f, t, u, 8.0))
    st = hangsheet.layout(rig)["structures"][0]
    assert st["ends"] == ("SL end", "SR end")
    assert [r["id"] for r in st["fixtures"]] == ["h1", "h2", "h0"]
    assert st["fixtures"][0]["where"].startswith(f"{t['length_m'] / 2 - 2.0:.2f} m from the SL end, hanging under")
    assert st["fixtures"][0]["facing"] == "base front towards the audience"


def test_a_truss_turned_round_is_still_counted_from_stage_left():
    t = {"id": "t", "type": "quatro", "length_m": 4.0, "x_m": 4.0, "y_m": -1.0, "z_m": 4.0, "rot_deg": 180}
    rig = {"stage": {"width_m": 8.0}, "trusses": [t], "fixtures": []}
    for k, u in enumerate((1.5, -1.5)):  # +u runs towards stage left on a truss turned round
        rig["fixtures"].append(
            T.place({"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1, "address": 1}, t, u, 8.0)
        )
    st = hangsheet.layout(rig)["structures"][0]
    assert [r["id"] for r in st["fixtures"]] == ["h0", "h1"]
    assert st["fixtures"][0]["where"].startswith("0.50 m from the SL end")


def test_a_side_truss_is_measured_from_upstage_and_a_tower_from_its_base():
    side = {"id": "side", "type": "quatro", "length_m": 4.0, "x_m": 0.5, "y_m": -2.0, "z_m": 4.0, "rot_deg": 90}
    tower = {"id": "tw", "type": "quatro", "length_m": 3.0, "x_m": 7.5, "y_m": -1.0, "z_m": 1.5, "vertical": True}
    rig = {"stage": {"width_m": 8.0}, "trusses": [side, tower], "fixtures": []}
    rig["fixtures"].append(
        T.place({"id": "a", "fixture": "claypaky/sharpy", "universe": 1, "address": 1}, side, 1.0, 8.0)
    )
    rig["fixtures"].append(T.place({"id": "b", "fixture": "claypaky/sharpy", "universe": 1, "address": 21},
                                   tower, 2.0, 8.0, "left"))  # fmt: skip
    by = {s["id"]: s for s in hangsheet.layout(rig)["structures"]}
    assert by["side"]["ends"] == ("upstage end", "downstage end")
    assert by["side"]["fixtures"][0]["where"].startswith("3.00 m from the upstage end")
    b = by["tw"]["fixtures"][0]
    assert b["where"] == "2.00 m up from the base, on the face towards stage left"
    assert b["facing"] == "base on the truss, head out towards stage left"


def test_crew_directions():
    assert hangsheet.toward(0, 1) == "the audience"
    assert hangsheet.toward(1, 0) == "stage right"
    assert hangsheet.toward(-1, 0) == "stage left"
    assert hangsheet.toward(0, -1) == "upstage"
    assert hangsheet.toward(-1, 1) == "the audience, SL"


def test_a_fixture_not_placed_yet_is_named_not_drawn():
    merged = mounted(Path("tests/sets/small.json"))
    merged["fixtures"][0]["_unplaced"] = {"x": 0.5}
    lay = hangsheet.layout(merged)
    assert [r["id"] for r in lay["waiting"]] == [merged["fixtures"][0]["id"]]
    assert "aren't placed on this rig yet" in hangsheet.html(merged)


def test_the_setup_api_serves_it_for_a_saved_rig_and_for_an_editors_layout():
    import urllib.request

    from amadeus.web.server import serve

    serve(18797, store.Selection(file=Path("tests/sets/small.json")), "127.0.0.1")
    r = urllib.request.urlopen("http://127.0.0.1:18797/api/hangsheet", timeout=10)
    assert r.headers["Content-Type"].startswith("text/html")
    assert b"Hang sheet" in r.read()
    body = json.dumps({"rig": mounted(Path("tests/sets/ring.json")), "names": ["my-set", "my-rig"]}).encode()
    req = urllib.request.Request("http://127.0.0.1:18797/api/hangsheet", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})  # fmt: skip
    page = urllib.request.urlopen(req, timeout=10).read().decode()
    assert "Hang sheet: my-set on my-rig" in page and "ring 1" in page


# ---- the check after hanging -----------------------------------------------------------------------------------


def _heads(merged: dict):
    for f in merged["fixtures"]:
        defn = hangsheet._defn(f)
        if fxlib.is_moving(defn) and not f.get("mount_roll_deg"):
            yield {**f, "mode": hangsheet._mode(f, defn)}, defn


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_the_check_goes_in_the_sheets_order_and_says_what_to_see(path):
    merged = mounted(path)
    steps = hangsheet.check_steps(merged)
    lay = hangsheet.layout(merged)
    assert [s["label"] for s in steps] == [r["label"] for st in lay["structures"] for r in st["fixtures"]] + [
        r["label"] for r in lay["floor"]
    ]
    for s in steps:
        assert bool(s["expect"]) == (s["moving"] and not s["dark"])


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_a_head_hung_wrong_shows_at_the_check_and_its_fix_puts_it_right(path):
    """A real head turned round or mirrored (its pan the other way): its check beam lands in another quarter, the
    fix the crew picks for what they see makes the app's aim land where it should, at the check and in the show."""
    targets = [
        np.array(v, dtype=float) / np.linalg.norm(v) for v in ((0.3, 1, -0.6), (-1, 0.2, -0.3), (0.5, -0.5, -0.7))
    ]
    checked = 0
    merged = mounted(path)
    for fx, defn in _heads(merged):
        want = hangsheet.check_dir(fx)
        aim = hangsheet.check_aim(fx, defn)
        if float(geometry.fk(fx, defn, *aim) @ want) < 0.97:  # out of this head's reach: not a fair check
            continue
        checked += 1
        step = next(s for s in hangsheet.check_steps(merged) if s["id"] == fx["id"])
        P = defn["physical"].get("pan_deg", 0) or 0
        for fault in step["faults"]:  # what the crew sees when it is hung wrong, and the fix they pick for it
            real = hangsheet._hung_wrong(fx, fault["fix"])
            assert hangsheet.beam_words(geometry.fk(real, defn, *aim)) == fault["seen"]
            model = {**fx, **hangsheet.fix(fx, defn, fault["fix"])}  # the app, put right
            for d in [want, *targets] if P else [want]:
                dmx = geometry.to_dmx(model, defn, *geometry.ik(model, defn, d, None))
                assert float(geometry.fk(real, defn, *dmx) @ geometry.fk(model, defn, *dmx)) > 0.999, (fx["id"], fault)
            assert (
                float(
                    geometry.fk(real, defn, *geometry.to_dmx(model, defn, *geometry.ik(model, defn, want, None))) @ want
                )
                > 0.97
            )
        assert {x["fix"] for x in step["faults"]} == ({"mirrored", "turned", "both"} if P else {"turned"})
    if path.stem != "small":
        assert checked


def test_the_setup_api_lights_a_head_the_checks_way():
    from amadeus.web import rig as web

    merged = mounted(Path("tests/sets/ring.json"))
    head = next(f for f in merged["fixtures"] if fxlib.is_moving(hangsheet._defn(f)))
    head.setdefault("mode", fxlib.default_mode(hangsheet._defn(head)))
    steps = [s for s in hangsheet.check_steps(merged) if s["id"] == head["id"]]
    assert steps and steps[0]["expect"].startswith("Its beam points down towards ") and steps[0]["faults"]
    buf = bytearray(512)
    fxlib.test_light(buf, head, aim=hangsheet.check_aim(head, hangsheet._defn(head)))
    centred = bytearray(512)
    fxlib.test_light(centred, head)
    assert buf != centred
    assert web.POST["/api/hangcheck"] and web.POST["/api/hangcheck/fix"]
