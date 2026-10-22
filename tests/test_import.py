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
from amadeus.rig.importer.draft import Draft
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


# ------------------------------------------------------------------ PDFs (read with AI): recorded answers, no key


class FakeAI:
    """Answers the patch and plan questions with what a model said; counts the requests."""

    def __init__(self, patch: dict, plans: list[dict]):
        self.answers = {"patch": patch, "plot": {"plans": plans}}
        self.asked = []

    @property
    def responses(self):
        return self

    def create(self, model, input, text):
        name = text["format"]["name"]
        self.asked.append(name)
        return type("R", (), {"output_text": json.dumps(self.answers[name])})()


def _pdf(path: Path, pages: list[str | None]) -> Path:
    """A PDF with text pages (str) and empty pages (None: a drawing)."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    w = PdfWriter()
    for text in pages:
        page = w.add_blank_page(595, 842)
        if text:
            lines = "".join(
                f"BT /F1 9 Tf 40 {800 - 12 * i} Td ({ln}) Tj ET\n" for i, ln in enumerate(text.splitlines())
            )
            stream = DecodedStreamObject()
            stream.set_data(lines.encode())
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                }
            )
            page[NameObject("/Resources")] = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): w._add_object(font)})}
            )
            page[NameObject("/Contents")] = w._add_object(stream)
    w.write(path)
    return path


PATCH_TEXT = "\n".join(
    ["universe 1 patch list fixture type description address"]
    + [f"#{100 + i} stage truss Diablo S {1 + 56 * (i - 1)} some words for the page" for i in range(1, 8)]
)
PATCH = {
    "fixtures": [
        {"number": "101", "type": "Diablo S", "manufacturer": "Ayrton", "where": "stage truss", "universe": 2,
         "address": 1, "last_address": None, "per_channel": False, "count": 1, "house_only": False},
        {"number": "102", "type": "Diablo S", "manufacturer": "Ayrton", "where": "stage truss", "universe": 2,
         "address": 57, "last_address": None, "per_channel": False, "count": 1, "house_only": False},
        {"number": "", "type": "PAR 64", "manufacturer": "", "where": "truss stage", "universe": 1, "address": 34,
         "last_address": 37, "per_channel": True, "count": 1, "house_only": False},
        {"number": "701", "type": "Atomic", "manufacturer": "Martin", "where": "stage truss", "universe": 3,
         "address": 301, "last_address": 305, "per_channel": False, "count": 1, "house_only": False},
        {"number": "", "type": "MDG ATMe Hazer", "manufacturer": "MDG", "where": "haze stage", "universe": 1,
         "address": 501, "last_address": 503, "per_channel": False, "count": 1, "house_only": False},
        {"number": "", "type": "4 x rgb led", "manufacturer": "", "where": "interior lights", "universe": 1,
         "address": 434, "last_address": 445, "per_channel": False, "count": 1, "house_only": True},
    ],
    "modes": [{"type": "Diablo S", "mode": "Extended", "channels": 56}],
    "stage": {"width_m": 14.0, "usable_width_m": 9.5, "depth_m": 6.5, "grid_height_m": 7.5, "deck_height_m": 1.5,
              "hall_grid_height_m": 5.5},
}  # fmt: skip
# the stage plan: audience at the bottom, the stage from x 0.1 to 0.9 (14 m), its front edge at y 0.8, 6.5 m deep
PLAN = {
    "title": "stage truss", "area": "stage", "audience": "bottom", "stage_edge": 0.8, "stage_back": 0.5375,
    "stage_end_a": 0.1, "stage_end_b": 0.9, "wall_a": None, "wall_b": None,
    "symbols": [{"label": "101", "x": 0.3, "y": 0.5, "floor": False},
                {"label": "2.57", "x": 0.7, "y": 0.5, "floor": False},
                {"label": "1.34", "x": 0.4, "y": 0.55, "floor": False},
                {"label": "999", "x": 0.5, "y": 0.5, "floor": False}],
    "trusses": [{"label": "upstage", "x1": 0.2, "y1": 0.5, "x2": 0.8, "y2": 0.5}],
}  # fmt: skip


@pytest.fixture
def pdfs(data, monkeypatch):
    from amadeus.rig.importer import pdf as pdfmod

    monkeypatch.setattr(pdfmod, "CACHE", data / "cache")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    return _pdf(data / "patch.pdf", [PATCH_TEXT]), _pdf(data / "plots.pdf", [None])


def test_without_a_key_nothing_is_sent_and_the_report_says_why(data, monkeypatch):
    from amadeus.rig.importer import pdf as pdfmod

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(pdfmod.paths, "load_dotenv", lambda: None)
    ai = FakeAI(PATCH, [PLAN])
    d = importer.read([_pdf(data / "p.pdf", [PATCH_TEXT])], ai)
    assert not ai.asked and not d.items
    assert d.notes[0].level == "missing" and "own OpenAI API key" in d.notes[0].text


def test_a_patch_pdf_and_its_plan_build_the_rig(pdfs):
    ai = FakeAI(PATCH, [PLAN])
    res = importer.build(list(pdfs), "venue", ai)
    assert ai.asked == ["patch", "plot"]  # every page read: the text together, the drawing on its own
    fx = {f["id"]: f for f in res.set_doc["fixtures"]}
    assert fx["diablo101"]["mode"] == "ext" and fx["diablo101"]["universe"] == 2
    assert sorted(f["address"] for f in fx.values() if f["fixture"] == "generic/par-64") == [34, 35, 36, 37]
    assert [f["mode"] for f in fx.values() if f["fixture"] == "martin/atomic-3000"][0] in fxlib.get(
        "martin/atomic-3000"
    )["modes"] and len([f for f in fx.values() if f["fixture"] == "martin/atomic-3000"]) == 1
    assert len([f for f in fx.values() if f["fixture"] == "mdg/atme"]) == 1  # a fixture's range, not 3 lights
    assert any("house lights" in n.text and "rgb" in n.text for n in res.notes)
    assert res.rig_doc["stage"]["width_m"] == 14.0 and res.rig_doc["stage"]["ceiling_m"] == 7.5
    pl = res.rig_doc["placements"]["venue"]
    # 0.8 of the page is 14 m: 101 at x 0.3 is 5.6 m from the stage-left end, 57 is 5.6 m from the other
    W = res.rig_doc["stage"]["width_m"]
    assert pl["diablo101"]["x"] * W == pytest.approx(14 - 0.25 * 14, abs=0.3)  # page left is stage right
    assert pl["diablo102"]["x"] * W == pytest.approx(0.25 * 14, abs=0.3)
    assert pl["diablo101"]["y_m"] == pytest.approx(-0.3 * 842 * 14 / (0.8 * 595), abs=0.5)
    assert any("isn't in the patch" in n.text for n in res.notes)
    assert all(p.get("aim", [0, -90])[1] < 0 for p in pl.values() if "aim" in p)  # fixed lights never at the ceiling


def test_answers_are_cached(pdfs):
    ai = FakeAI(PATCH, [PLAN])
    importer.build(list(pdfs), "venue", ai)
    again = FakeAI(PATCH, [PLAN])
    importer.build(list(pdfs), "venue", again)
    assert again.asked == []


@pytest.mark.parametrize("audience, sym, want", [
    ("bottom", (0.3, 0.5), "right"), ("top", (0.3, 0.5), "left"),
    ("left", (0.5, 0.3), "right"), ("right", (0.5, 0.3), "left"),
])  # fmt: skip
def test_a_plan_turned_any_way_puts_stage_right_where_it_is(audience, sym, want):
    """A symbol on the page's left/top: stage right or left depending on where the audience sits."""
    from amadeus.rig.importer import pdf as pdfmod
    from amadeus.rig.importer.draft import Item

    it = Item(name="x", label="1")
    plan = dict(PLAN, audience=audience, symbols=[{"label": "1", "x": sym[0], "y": sym[1], "floor": False}],
                trusses=[], stage_edge=0.8 if audience in ("bottom", "right") else 0.2,
                stage_back=0.4 if audience in ("bottom", "right") else 0.6)  # fmt: skip
    d = Draft()
    assert pdfmod.place(plan, 595, 595, PATCH["stage"], {"1": it}, d, "plan") == 1
    assert (it.pos[0] > 0) == (want == "right")


def test_labels_match_however_they_are_written():
    from amadeus.rig.importer.pdf import label_key

    assert label_key("#101") == label_key("101") == "101"
    assert label_key("2.169") == label_key("2. 169") == label_key("02.169") == "2.169"
    assert label_key("1.034") == "1.34"
    assert label_key("6.301 / 6.305") == "6.301"


def test_a_plan_is_kept_under_the_rig_and_two_clicks_line_it_up(pdfs, monkeypatch):
    from amadeus.rig.importer import underlay

    monkeypatch.setattr(underlay, "FOLDER", pdfs[0].parent / "underlays")
    res = importer.build(list(pdfs), "venue", FakeAI(PATCH, [PLAN]))
    (u,) = res.rig_doc["underlays"]
    assert set(u["fixtures"]) >= {"diablo101", "diablo102", "par1"} and u["file"] in res.pages
    # the AI's reference: the stage's ends at x 0.1 and 0.9 of the page, the front edge at y 0.8
    assert u["a"] == pytest.approx([0.9, 0.8], abs=0.01) and u["b"] == pytest.approx([0.1, 0.8], abs=0.01)
    assert underlay.to_rig(u, 0.9, 0.8) == pytest.approx((0.0, 0.0), abs=0.05)  # stage left at the front edge
    places = res.rig_doc["placements"]["venue"]
    before = places["diablo101"]["x"] * 14, places["diablo101"]["y_m"]
    # lined up again: the stage really runs from x 0.3 to 0.7 of the page: everything is twice as far apart
    underlay.align(res.rig_doc, u["id"], [0.7, 0.8], [0.3, 0.8], 14.0)
    after = places["diablo101"]["x"] * 14, places["diablo101"]["y_m"]
    assert after[1] == pytest.approx(before[1] * 2, rel=0.05)  # upstage twice as far
    assert after[0] - 7 == pytest.approx((before[0] - 7) * 2, abs=0.3)
    truss = next(t for t in res.rig_doc["trusses"] if t["id"] == places["diablo101"]["truss"])
    assert truss["y_m"] == pytest.approx(after[1] + 0.0, abs=0.6)  # the truss went with them
    underlay.save_page(res.pages[u["file"]])
    assert underlay.page_bytes(u["file"]).startswith(b"%PDF")
    with pytest.raises(FileNotFoundError):
        underlay.page_bytes("../../secret.pdf")


def test_the_corners_turn_with_the_drawing():
    from amadeus.rig.importer import underlay

    u = {"w": 100, "h": 100, "a": [0.0, 1.0], "b": [1.0, 1.0], "a_m": [0.0, 0.0], "b_m": [10.0, 0.0]}
    # stage left at the page's left, stage right at its right: the performer faces up the page, so the
    # audience is at its top (and a plan drawn the usual way, audience at the bottom, has stage left on the right)
    tl, tr, br, bl = underlay.corners(u)
    assert bl == pytest.approx((0.0, 0.0)) and br == pytest.approx((10.0, 0.0))
    assert tl == pytest.approx((0.0, 10.0)) and tr == pytest.approx((10.0, 10.0))
    u.update(a=[1.0, 0.0], b=[0.0, 0.0])  # the usual way: stage left at the top right, the audience below
    tl, tr, br, bl = underlay.corners(u)
    assert tr == pytest.approx((0.0, 0.0)) and tl == pytest.approx((10.0, 0.0)) and bl[1] == pytest.approx(10.0)


def test_an_import_can_be_cancelled_and_saves_nothing(data, monkeypatch):
    from amadeus.rig import store as st
    from amadeus.web import importer as web

    path = data / "patch.csv"
    path.write_text(CSV, encoding="utf-8")
    monkeypatch.setattr(st.sets, "save", lambda *a: pytest.fail("saved"))
    web.JOBS["j"] = {"state": "running", "step": "", "notes": [], "name": "venue", "cancel": True}
    web._run("j", [path], "venue", data / "uploads")
    assert web.JOBS["j"]["state"] == "cancelled"
