"""A fixture's manual read with AI (OpenAI faked: nothing goes out): the mode the fixture is patched in fills the
DMX mapper, and saving it sets the channels, the colour wheel, the gobos, the prism and the strobe."""

import base64
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from amadeus import aikey
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.library import manual, mapper
from amadeus.rig.importer import pdf as pdfmod
from amadeus.web import library as web_library

ROOT = Path(__file__).resolve().parent.parent
PDF = b"%PDF-1.4\n% a manual\n"

# as a library has a cheap head: the right number of channels, the wrong things on them
HEAD = {
    "manufacturer": "Test",
    "model": "Mini Beam",
    "kind": "moving_head",
    "physical": {"beam_deg": 4, "pan_deg": 540, "tilt_deg": 270},
    "modes": {
        "11ch": [{"attr": "pan"}, {"attr": "tilt"}, {"attr": "dimmer"}]
        + [{"attr": f"channel_{n}", "default": 0} for n in range(4, 12)],
        "13ch": [{"attr": "pan"}, {"attr": "tilt"}, {"attr": "dimmer"}]
        + [{"attr": f"channel_{n}", "default": 0} for n in range(4, 14)],
    },
}


def _ch(name, function, value=0, ranges=None, colours=None, cell=0):
    rows = [{"from": lo, "to": hi, "what": what} for lo, hi, what in ranges or [(0, 255, name)]]
    return {"name": name, "function": function, "cell": cell, "value": value, "ranges": rows, "colours": colours or []}


COLOURS = [
    {"name": "white", "from": 0, "to": 9, "r": 1, "g": 1, "b": 1},
    {"name": "red", "from": 10, "to": 19, "r": 1, "g": 0, "b": 0},
    {"name": "green", "from": 20, "to": 29, "r": 0, "g": 1, "b": 0},
    {"name": "blue", "from": 30, "to": 39, "r": 0, "g": 0, "b": 1},
]
WHEEL = _ch(
    "Colour",
    "color_wheel",
    0,
    [(0, 9, "White"), (10, 19, "Red"), (20, 29, "Green"), (30, 39, "Blue"), (140, 255, "Rainbow slow to fast")],
    COLOURS,
)
GOBO = _ch(
    "Gobo",
    "gobo",
    0,
    [(0, 7, "Open"), (8, 15, "Gobo 1"), (16, 23, "Gobo 2"), (24, 31, "Gobo 3"), (64, 127, "Gobo shake 1 to 3"),
     (128, 255, "Gobo wheel rotation slow to fast")],
)  # fmt: skip
SHUTTER = _ch("Strobe", "shutter", 4, [(0, 9, "Open"), (10, 250, "Strobe slow to fast"), (251, 255, "Open")])
PRISM = _ch("Prism", "prism", 0, [(0, 127, "No prism"), (128, 255, "Prism in")])
PRISM_ROT = _ch(
    "Prism rotation", "prism_rotation", 0, [(0, 127, "Prism position"), (128, 255, "Rotation slow to fast")]
)
ELEVEN = [
    _ch("Pan", "pan"), _ch("Pan fine", "pan_fine"), _ch("Tilt", "tilt"), _ch("Tilt fine", "tilt_fine"),
    WHEEL, GOBO, SHUTTER, _ch("Dimmer", "dimmer"), PRISM,
    _ch("XY speed", "pan_tilt_speed", 0, [(0, 255, "Fast to slow")]),
    _ch("Reset", "reset", 0, [(0, 249, "No function"), (250, 255, "Reset")]),
]  # fmt: skip
ANSWER = {
    "manufacturer": "NoName",
    "model": "Mini Beam 150W",
    "type": "beam",
    "modes": [
        {"name": "9 channel", "channels": ELEVEN[:9]},
        {"name": "11 channel", "channels": ELEVEN},
        {"name": "13 channel", "channels": ELEVEN[:9] + [PRISM_ROT, _ch("Focus", "focus", 128)] + ELEVEN[9:]},
    ],
}


class FakeOpenAI:
    """Answers every request with one manual's chart, and keeps what it was sent."""

    def __init__(self, answer=ANSWER):
        self.answer, self.sent = answer, []
        self.responses = self

    def create(self, model, input, text):
        self.sent.append(input)
        assert text["format"]["strict"] and text["format"]["name"] == "manual"
        return SimpleNamespace(output_text=json.dumps(self.answer))


@pytest.fixture
def library(monkeypatch, tmp_path):
    lib = tmp_path / "fixtures"
    shutil.copytree(ROOT / "fixtures", lib)
    (lib / "test").mkdir()
    (lib / "test" / "mini-beam.json").write_text(json.dumps(HEAD), encoding="utf-8")
    monkeypatch.setattr(fxlib, "LIB_DIR", lib)
    monkeypatch.setattr(fxlib, "USER_DIR", None)
    monkeypatch.setattr(pdfmod, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(aikey, "_problem", None)
    fxlib.library.cache_clear()
    yield lib
    fxlib.library.cache_clear()


def _save(shown: dict) -> list[str]:
    """Save a mapping as the apps do: the channels as shown, the wheel, and the manual's chart."""
    chans = [{k: c[k] for k in ("role", "cell", "value", "attr")} for c in shown["channels"]]
    chart = [{"name": c["name"], "ranges": c["ranges"]} for c in shown["channels"]]
    return mapper.apply(shown["key"], shown["mode"], shown["kind"], chans, shown["wheel"],
                        manual={"file": shown["manual"]["file"], "channels": chart})  # fmt: skip


def test_the_manual_is_sent_whole_and_fills_the_mapper(library):
    client = FakeOpenAI()
    answer = manual.read(PDF, "mini beam.pdf", client)
    sent = client.sent[0][0]["content"]
    assert sent[1]["type"] == "input_file" and base64.b64decode(sent[1]["file_data"].split(",", 1)[1]) == PDF
    shown = manual.mapping("test/mini-beam", "11ch", answer, "mini beam.pdf")
    assert shown["manual"]["mode"] == "11 channel" and shown["manual"]["file"] == "mini beam.pdf"
    assert [m["channels"] for m in shown["manual"]["modes"]] == [9, 11, 13]
    assert [c["role"] for c in shown["channels"]] == [
        "pan", "pan_fine", "tilt", "tilt_fine", "color_wheel", "hold", "hold", "dimmer", "hold", "hold", "hold",
    ]  # fmt: skip
    assert [c["attr"] for c in shown["channels"]][5:] == [
        "gobo",
        "shutter",
        "dimmer",
        "prism",
        "pan_tilt_speed",
        "reset",
    ]
    assert shown["channels"][6]["value"] == 4 and shown["channels"][5]["ranges"][1] == [8, 15, "Gobo 1"]
    assert [s["name"] for s in shown["wheel"]] == ["white", "red", "green", "blue"]
    assert shown["kind"] == "moving_head" and shown["plays"]
    assert fxlib.get("test/mini-beam")["modes"] == HEAD["modes"]  # nothing saved by reading


def test_saving_it_sets_colours_gobos_prism_and_strobe(library):
    shown = manual.mapping("test/mini-beam", "11ch", ANSWER, "mini.pdf")
    assert _save(shown) == []
    defn = fxlib.get("test/mini-beam")
    chans = defn["modes"]["11ch"]
    assert [c["attr"] for c in chans][:5] == ["pan", "pan_fine", "tilt", "tilt_fine", "color_wheel"]
    assert chans[6]["default"] == 4 and chans[6]["strobe_range"] == [10, 250]
    assert [s["from"] for s in defn["color_wheel"]["slots"]] == [0, 10, 20, 30]
    fx = defn["beam_fx"]
    assert fx["gobo"] == {"gobo": [12, 20, 28]} and len(fx["gobo_shake"]["gobo"]) == 3
    assert fx["gobo_spin"] == {"gobo": {"range": [128, 255]}} and fx["prism"] == {"prism": 191}
    assert "_filled" not in fx
    assert defn["manual"]["file"] == "mini.pdf" and defn["modes"]["13ch"] == HEAD["modes"]["13ch"]
    # the mapper shows the manual's names from then on, and the show plays them
    again = mapper.describe("test/mini-beam", "11ch")
    assert again["channels"][5]["name"] == "Gobo" and again["channels"][5]["ranges"][0] == [0, 7, "Open"]
    rig_fx = {"id": "h", "fixture": "test/mini-beam", "mode": "11ch", "universe": 1, "address": 1, "x": 0.5}
    buf = bytearray(512)
    s = State(dimmer=1.0, r=0.0, g=0.0, b=1.0, pan=0.5, tilt=0.5)
    s.fx, s.gobo = "prism", 0
    fxlib.patch(buf, rig_fx, {"h": s})
    assert buf[4] == 34 and buf[7] == 255 and buf[8] == 191 and buf[5] == 0 and buf[6] == 4


def test_a_manual_with_several_modes_gives_the_one_the_fixture_runs_in(library):
    shown = manual.mapping("test/mini-beam", "13ch", ANSWER, "mini.pdf")
    assert shown["manual"]["mode"] == "13 channel" and len(shown["channels"]) == 13
    assert [c["attr"] for c in shown["channels"]][8:11] == ["prism", "prism_rotation", "focus"]
    assert _save(shown) == []
    fx = fxlib.get("test/mini-beam")["beam_fx"]
    assert fx["prism_spin"] == {"prism": 191, "prism_rotation": {"range": [128, 255]}}
    # two modes of one size: the one named like ours
    two = {**ANSWER, "modes": [{"name": "Basic", "channels": ELEVEN[::-1]}, {"name": "11CH mode", "channels": ELEVEN}]}
    assert manual.pick_mode(two, 11, "11ch")[0]["name"] == "11CH mode"
    # none of that size: said, with the sizes it has
    none = manual.mapping("test/mini-beam", "13ch", {**ANSWER, "modes": ANSWER["modes"][:2]})
    assert "13 channels" in none["error"] and "9, 11" in none["error"]
    assert "No DMX chart" in manual.mapping("test/mini-beam", "13ch", {**ANSWER, "modes": []})["error"]


def test_a_new_fixture_is_made_from_the_manual(library):
    made = manual.create(ANSWER, 13, "mini.pdf")
    assert made["mode"] == "13ch" and made["manual"]["mode"] == "13 channel"
    defn = fxlib.get(made["key"])
    assert defn["manufacturer"] == "NoName" and defn["kind"] == "moving_head" and not defn["made"]["checked"]
    assert defn["beam_fx"]["gobo"] == {"gobo": [12, 20, 28]} and defn["beam_fx"]["prism"] == {"prism": 191}
    assert mapper.describe(made["key"], "13ch")["channels"][4]["name"] == "Colour"
    assert manual.create(ANSWER, 7)["problems"]


def test_a_pasted_picture_of_the_chart_is_read_like_the_pdf(library):
    client = FakeOpenAI()
    png, jpg = b"\x89PNG\r\n\x1a\n chart", b"\xff\xd8\xff\xe0 more of it"
    answer = manual.read([("Pasted picture.png", png), ("page 2.jpg", jpg)], client=client)
    sent = client.sent[0][0]["content"]
    assert [c["type"] for c in sent] == ["input_text", "input_image", "input_image"]
    assert sent[1]["image_url"].startswith("data:image/png;base64,") and sent[2]["image_url"].startswith(
        "data:image/jpeg"
    )
    assert base64.b64decode(sent[1]["image_url"].split(",", 1)[1]) == png
    assert manual.mapping("test/mini-beam", "11ch", answer, "Pasted picture.png")["manual"]["mode"] == "11 channel"
    with pytest.raises(ValueError, match="PDF or a picture"):
        manual.read(b"BM a bitmap", "chart.bmp", client)
    with pytest.raises(ValueError, match="No manual"):
        manual.read([], client=client)
    assert len(client.sent) == 1  # nothing sent for those


class Req:
    client = "test"

    def __init__(self, body):
        self._body = body

    def body(self):
        return self._body


def _upload(**more):
    return Req({"name": "mini.pdf", "data": base64.b64encode(PDF).decode(), **more})


def test_the_endpoint_needs_a_key_and_a_pdf(library, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(pdfmod.paths, "load_dotenv", lambda: None)
    r, status = web_library.read_manual(_upload(key="test/mini-beam", mode="11ch"))
    assert status == 400 and "OpenAI API key" in r["error"]
    r, status = web_library.read_manual(Req({"name": "x.txt", "data": base64.b64encode(b"hello").decode()}))
    assert status == 400 and "PDF" in r["error"]


def test_the_endpoint_takes_a_pasted_picture(library, monkeypatch):
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    fake = FakeOpenAI()
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: fake)
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n chart").decode()
    r = web_library.read_manual(
        Req({"name": "Pasted picture.png", "data": png, "key": "test/mini-beam", "mode": "13ch"})
    )
    assert r["manual"] == {**r["manual"], "file": "Pasted picture.png", "mode": "13 channel"}
    assert fake.sent[0][0]["content"][1]["type"] == "input_image"


def test_the_add_fixtures_sheet_makes_a_new_fixture_from_a_pasted_chart(library, monkeypatch):
    """No fixture key sent (the apps' Add Fixtures › From Manual): a new fixture in its largest mode, chosen next."""
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: FakeOpenAI())
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n chart").decode()
    r = web_library.read_manual(Req({"name": "Pasted picture.png", "data": png}))
    assert r["mode"] == "13ch" and r["manual"]["file"] == "Pasted picture.png"
    assert fxlib.get(r["key"])["made"]["checked"] is False


def test_the_endpoint_fills_the_mapper_and_a_refused_key_is_the_warning(library, monkeypatch):
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    fake = FakeOpenAI()
    monkeypatch.setattr(openai, "OpenAI", lambda *a, **k: fake)
    r = web_library.read_manual(_upload(key="test/mini-beam", mode="11ch"))
    assert r["manual"]["mode"] == "11 channel" and r["channels"][4]["role"] == "color_wheel"
    web_library.read_manual(_upload(key="test/mini-beam", mode="13ch"))
    assert len(fake.sent) == 1  # the same manual again: from the cache
    saved = web_library.save_mapping(
        Req({"key": r["key"], "mode": r["mode"], "kind": r["kind"], "wheel": r["wheel"],
             "channels": [{k: c[k] for k in ("role", "cell", "value", "attr")} for c in r["channels"]],
             "manual": {"file": "mini.pdf", "channels": [{"name": c["name"], "ranges": c["ranges"]}
                                                         for c in r["channels"]]}})
    )  # fmt: skip
    assert saved == {"saved": True, "problems": []}
    assert fxlib.get("test/mini-beam")["beam_fx"]["gobo"] == {"gobo": [12, 20, 28]}

    class Refused(Exception):
        status_code = 401

    def refuse(*a, **k):
        raise Refused("bad key")

    fake.create = refuse
    monkeypatch.setattr(pdfmod, "CACHE", library.parent / "cache2")
    r, status = web_library.read_manual(_upload(key="test/mini-beam", mode="11ch"))
    assert status == 502 and r["error"] == aikey.REJECTED and aikey.problem() == aikey.REJECTED


def test_a_gobo_or_prism_held_in_the_beam_is_saved_out_of_it(library):
    """The check asks for a held channel's value "where the light is on": a gobo or a prism put in there would
    sit in every look. Saved, it rests out of the beam; the show still puts it in when a look asks."""
    shown = manual.mapping("test/mini-beam", "11ch", ANSWER, "mini.pdf")
    shown["channels"][5]["value"] = 20  # gobo 2
    shown["channels"][8]["value"] = 200  # prism in
    assert _save(shown) == []
    chans = fxlib.get("test/mini-beam")["modes"]["11ch"]
    assert chans[5]["default"] == 0 and chans[8]["default"] == 0
    rig_fx = {"id": "h", "fixture": "test/mini-beam", "mode": "11ch", "universe": 1, "address": 1, "x": 0.5}
    buf = bytearray(512)
    fxlib.patch(buf, rig_fx, {"h": State(dimmer=1.0, r=1.0, g=1.0, b=1.0, pan=0.5, tilt=0.5)})
    assert buf[5] == 0 and buf[8] == 0  # an open beam
