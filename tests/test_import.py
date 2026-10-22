"""Building a set and a rig from a venue's documents: an MVR scene (a rig written out and read back), patch
sheets in CSV and Excel, fixture matching, and the checks the report makes."""

import io
import json
import math
import zipfile
from pathlib import Path

import pytest

from amadeus.library import fixtures as fxlib
from amadeus.rig import importer, store
from amadeus.rig.importer import mvr, resolve, sheet
from tests.mvr_tool import gdtf_bytes, mvr_bytes

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def data(monkeypatch, tmp_path):
    """Fixtures the import makes (from a template) go to a throwaway library."""
    user = tmp_path / "fixtures"
    user.mkdir()
    monkeypatch.setattr(fxlib, "USER_DIR", user)
    fxlib.library.cache_clear()
    yield tmp_path
    fxlib.library.cache_clear()


def _melkweg():
    return (json.loads((ROOT / f"examples/{k}/melkweg-max.json").read_text()) for k in ("sets", "rigs"))


def test_an_mvr_scene_comes_back_as_the_rig_it_was(data):
    s, r = _melkweg()
    path = data / "venue.mvr"
    path.write_bytes(mvr_bytes(s, r, "melkweg-max"))
    res = importer.build([path], "venue")
    assert len(res.set_doc["fixtures"]) == len(s["fixtures"])
    assert not [n for n in res.notes if n.level == "missing"]
    assert {n.text.split(",")[0] for n in res.notes if n.level == "ok"} >= {
        "30 × Ayrton Diablo-S",
        "40 × Martin MAC Aura",
    }
    old = store.compose(s, r, "melkweg-max")
    new = store.compose(res.set_doc, res.rig_doc, "venue")
    by_patch = {(f["universe"], f["address"]): f for f in new["fixtures"]}
    W0, W1 = old["stage"]["width_m"], new["stage"]["width_m"]
    errors = []
    for f in old["fixtures"]:
        g = by_patch[(f["universe"], f["address"])]
        assert (g["fixture"], g["mode"]) == (f["fixture"], f["mode"])
        dx = (g["x"] - 0.5) * W1 - (f["x"] - 0.5) * W0
        errors.append(math.dist((dx, g["y_m"], g["z_m"]), (0, f["y_m"], f["z_m"])))
    assert max(errors) < 0.6 and sum(errors) / len(errors) < 0.1  # every light where it was drawn
    trusses = {t["id"] for t in res.rig_doc["trusses"]}
    assert {"upL", "upR", "downL", "downR", "sideSL", "sideSR", "front", "hall1", "balconySL"} <= trusses
    assert next(t for t in res.rig_doc["trusses"] if t["id"] == "sideSL").get("rot_deg") == 90
    json.dumps(res.set_doc), json.dumps(res.rig_doc)  # plain JSON (no numpy numbers)


def test_fixed_lights_keep_where_they_point_and_the_check_finds_a_wall(data):
    s, r = _melkweg()
    path = data / "venue.mvr"
    path.write_bytes(mvr_bytes(s, r, "melkweg-max"))
    res = importer.build([path], "venue")
    assert not [n for n in res.notes if "wall" in n.text or "ceiling" in n.text]
    turned = json.loads(json.dumps(r))
    for f in ("par30", "par31", "par32", "par33"):  # the mistake the example once had: the stage-left side at the wall
        turned["placements"]["melkweg-max"][f]["aim"] = [0.0, -55.0]
    notes = importer.checks(store.compose(s, turned, "melkweg-max"))
    wall = next(n for n in notes if "wall" in n.text)
    assert set(wall.ids) == {"par30", "par31", "par32", "par33"}


def test_an_embedded_gdtf_names_the_fixture_and_its_mode(data):
    set_doc = {
        "fixtures": [
            {"id": f"h{i}", "fixture": "martin/mac-aura", "mode": "Extended", "universe": 2, "address": 1 + 25 * i}
            for i in range(4)
        ]
    }
    rig_doc = {
        "stage": {"width_m": 8},
        "trusses": [],
        "placements": {
            "s": {f"h{i}": {"x": 0.2 + 0.2 * i, "y_m": -1.0, "z_m": 4.5, "mount": "hang"} for i in range(4)}
        },
    }
    spec = "Martin@MAC Aura"
    path = data / "aura.mvr"
    path.write_bytes(
        mvr_bytes(
            set_doc, rig_doc, "s", gdtf={spec: gdtf_bytes("Martin", "MAC Aura", {"Standard": 14, "Extended": 25})}
        )
    )
    d = mvr.read(path)
    assert {(it.name, it.mode, it.channels, it.universe) for it in d.items} == {("Martin MAC Aura", "Extended", 25, 2)}
    res = importer.build([path], "aura")
    assert len(res.rig_doc["trusses"]) == 1 and res.rig_doc["trusses"][0]["length_m"] >= 5
    assert {f["mode"] for f in res.set_doc["fixtures"]} == {"Extended"}


def test_mvr_addresses_absolute_or_universe_dot_address():
    assert mvr.address("45") == (1, 45)
    assert mvr.address("513") == (2, 1)
    assert mvr.address("3.301") == (3, 301)


CSV = """Venue patch;;;;;
#;Fixture type;Mode;Patch;Position;Qty
101;Ayrton Diablo S;;1.141;stage truss;
102;Ayrton Diablo S;;1.197;stage truss;
103;Ayrton Diablo S;;1.253;stage truss;
201;Martin Mac Aura;Extended;3.001;stage truss;4
;PAR 64;;1.034 > 1.049;truss stage;
;Unknown Brand Wash 3000;;2.001;floor;2
"""


def test_a_patch_sheet_builds_a_set_and_auto_mounts_it(data):
    path = data / "patch.csv"
    path.write_text(CSV, encoding="utf-8")
    d = sheet.read(path)
    assert [(it.name, it.universe, it.address, it.count) for it in d.items][:3] == [
        ("Ayrton Diablo S", 1, 141, 1),
        ("Ayrton Diablo S", 1, 197, 1),
        ("Ayrton Diablo S", 1, 253, 1),
    ]
    par = next(it for it in d.items if it.name == "PAR 64")
    assert (par.count, par.channels, par.address) == (16, 1, 34)  # a dimmer range: one light per channel
    res = importer.build([path], "venue")
    fx = {f["id"]: f for f in res.set_doc["fixtures"]}
    assert len(fx) == 3 + 4 + 16 + 2
    assert fx["diablo101"]["mode"] == "ext"  # 56 channels apart: the 56-channel mode
    assert [fx[f"aura{n}"]["address"] for n in (201, 202, 203, 204)] == [1, 26, 51, 76]
    unknown = next(n for n in res.notes if "Unknown Brand" in n.text)
    assert unknown.level == "check" and "template" in unknown.text
    assert any("no position" in n.text for n in res.notes)
    merged = store.compose(res.set_doc, res.rig_doc, "venue")
    assert not [f for f in merged["fixtures"] if f.get("_unplaced")] and merged["trusses"]


def test_an_excel_sheet_reads_like_the_csv(data):
    rows = [["Fixture", "Universe", "Address"], ["Martin MAC Aura", "3", "1"], ["Martin MAC Aura", "3", "26"]]
    shared = sorted({c for r in rows for c in r if not c.isdigit()})
    cells = "".join(
        f'<row r="{i}">'
        + "".join(
            f'<c r="{"ABC"[j]}{i}"><v>{v}</v></c>'
            if v.isdigit()
            else f'<c r="{"ABC"[j]}{i}" t="s"><v>{shared.index(v)}</v></c>'
            for j, v in enumerate(r)
        )
        + "</row>"
        for i, r in enumerate(rows, 1)
    )
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("xl/sharedStrings.xml", f"<sst {ns}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{cells}</sheetData></worksheet>")
    path = data / "patch.xlsx"
    path.write_bytes(out.getvalue())
    d = sheet.read(path)
    assert [(it.name, it.universe, it.address) for it in d.items] == [
        ("Martin MAC Aura", 3, 1),
        ("Martin MAC Aura", 3, 26),
    ]


@pytest.mark.parametrize(
    "name, channels, key",
    [
        ("Mac Aura", 25, "martin/mac-aura"),
        ("Clay Paky Sharpy", 0, "claypaky/sharpy"),
        ("Ayrton Diablo-S", 56, "ayrton/diablo-s"),
    ],
)
def test_a_name_finds_its_fixture(name, channels, key):
    c = resolve.match(name, channels, "")
    assert c.key == key and c.sure


def test_another_model_number_is_never_sure():
    c = resolve.match("GLP Impression X4 Bar 20", 0, "")
    assert c is None or not c.sure


@pytest.mark.parametrize(
    "cell, want",
    [
        ("1.141", (1, 141, 141)),
        ("2/45", (2, 45, 45)),
        ("U3 301", (3, 301, 301)),
        ("141", (0, 141, 141)),
        ("1.013 > 1.019", (1, 13, 19)),
        ("", (0, 0, 0)),
    ],
)
def test_patch_cells(cell, want):
    assert sheet.patch(cell) == want
