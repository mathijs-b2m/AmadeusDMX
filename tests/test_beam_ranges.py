"""Gobos, prisms and frost for any fixture: read from its channels' ranges when its file doesn't give the values."""

import json

import pytest

from amadeus.engine.state import State
from amadeus.library import beam_ranges, gobos
from amadeus.library import fixtures as fxlib


def head(attrs: list[str], ranges: list[list], kind: str = "moving_head") -> dict:
    """A fixture made from a chart: its channels' attrs and the chart's ranges per channel."""
    played = {"pan", "tilt", "dimmer", "color_wheel"}
    return {
        "manufacturer": "Test",
        "model": "Head",
        "kind": kind,
        "modes": {"8ch": [{"attr": a} if a in played else {"attr": a, "default": 0} for a in attrs]},
        "made": {"template": "chart", "channels": {"8ch": [{"name": a, "ranges": r} for a, r in zip(attrs, ranges)]}},
    }


CHART = head(
    ["pan", "tilt", "dimmer", "gobo", "prism"],
    [[], [], [],
     [[0, 5, "White"], [6, 80, "Gobos 1 to 14"], [81, 150, "Gobo shake 1-14"],
      [151, 200, "Gobo clockwise fast to slow"], [201, 255, "Gobo counterclockwise slowly to fast"]],
     [[0, 127, "off"], [128, 136, "24 Prism"], [137, 255, "Prism is slow to fast rotate"]]],
)  # fmt: skip


def test_a_charts_gobos_and_prism_are_read_from_its_words():
    d = json.loads(json.dumps(CHART))
    added = beam_ranges.fill(d, lambda d, m: d["made"]["channels"][m])
    fx = d["beam_fx"]
    assert set(added) == {"gobo", "gobo_shake", "gobo_spin", "prism", "prism_spin"}
    assert len(fx["gobo"]["gobo"]) == 14 and all(6 <= v <= 80 for v in fx["gobo"]["gobo"])
    assert len(fx["gobo_shake"]["gobo"]) == 14 and all(81 <= v <= 150 for v in fx["gobo_shake"]["gobo"])
    assert fx["gobo_spin"]["gobo"] == {"range": [200, 151], "reverse": [201, 255]}  # [slow, fast] each way
    assert fx["prism"] == {"prism": 132}
    assert fx["prism_spin"] == {"prism": {"range": [137, 255]}}


def test_a_wheel_under_another_name_and_a_translated_chart_play_too():
    d = head(
        ["pan", "tilt", "dimmer", "pattern_frequency_flash", "pattern_wheel", "prism"],
        [[], [], [[0, 255, "Pattern white light"]], [[0, 0, "No function"], [1, 255, "flash (1Hz~25Hz)"]],
         [[0, 7, "White light"], [8, 63, "Patterns 1 to 7"], [64, 127, "Pattern jitter from slow to fast"],
          [128, 191, "Clockwise automatic switch from fast to slow"],
          [192, 255, "Counterclockwise automatic switch from slow to fast"]],
         [[0, 7, "Close prism"], [8, 127, "Open prism"], [128, 255, "Prism rotates from slow to fast"]]],
    )  # fmt: skip
    beam_ranges.fill(d, lambda d, m: d["made"]["channels"][m])
    fx = d["beam_fx"]
    assert len(fx["gobo"]["pattern_wheel"]) == 7  # not the flash channel, not the dimmer named "Pattern…"
    assert fx["gobo_spin"]["pattern_wheel"] == {"range": [191, 128], "reverse": [192, 255]}
    assert 8 <= fx["prism"]["prism"] <= 127  # "Open prism": the prism in


@pytest.mark.parametrize(
    ("ranges", "inside"),
    [([[0, 19, "Open"], [20, 49, "6-facet linear rotating - indexing"], [50, 75, "6-facet rotation"]], (20, 49)),
     ([[0, 127, "Prism excluded"], [128, 255, "Prism inserted (0%-100%: 0.36 sec)"]], (128, 255)),
     ([[0, 31, "No Prism"], [32, 255, "Prism On"]], (32, 255))],
)  # fmt: skip
def test_the_prism_goes_in_where_the_words_say_not_where_it_is_open(ranges, inside):
    d = head(["pan", "tilt", "dimmer", "prism"], [[], [], [], ranges])
    beam_ranges.fill(d, lambda d, m: d["made"]["channels"][m])
    assert inside[0] <= d["beam_fx"]["prism"]["prism"] <= inside[1]


@pytest.mark.parametrize(
    ("ranges", "value"),
    [([[0, 179, "Frost from 0-100"], [180, 189, "Frost 100%"], [190, 211, "Pulse closing"]], 184),
     ([[0, 255, "Frost insertion (excluded to inserted)"]], 255),
     ([[0, 127, "No function"], [128, 191, "Frost"], [192, 255, "Rainbow"]], 159)],
)  # fmt: skip
def test_the_frost_goes_all_the_way_in(ranges, value):
    d = head(["pan", "tilt", "dimmer", "frost"], [[], [], [], ranges])
    beam_ranges.fill(d, lambda d, m: d["made"]["channels"][m])
    assert d["beam_fx"]["frost"] == {"frost": value}


def test_what_a_file_gives_is_kept_and_a_bar_has_no_gobos():
    d = json.loads(json.dumps(CHART))
    d["beam_fx"] = {"open": {}, "gobo": {"gobo": [10, 20]}}
    beam_ranges.fill(d, lambda d, m: d["made"]["channels"][m])
    assert d["beam_fx"]["gobo"] == {"gobo": [10, 20]} and "gobo_shake" not in d["beam_fx"]
    assert "prism" in d["beam_fx"]  # what it lacked
    bar = head(["dimmer", "pattern"], [[], [[0, 255, "patterns"]]], kind="par_bar")
    assert beam_ranges.fill(bar, lambda d, m: d["made"]["channels"][m]) == []


def test_a_held_wheel_without_ranges_gets_the_usual_layout_but_a_librarys_fixture_is_never_guessed():
    d = head(["pan", "tilt", "dimmer", "gobo", "prism"], [[]] * 5)
    beam_ranges.fill(d, lambda d, m: d["made"]["channels"][m])
    assert d["beam_fx"]["gobo"] == {"gobo": beam_ranges.GUESS_GOBOS} and d["beam_fx"]["prism"]
    converted = head(["pan", "tilt", "dimmer", "gobo"], [[]] * 4)
    assert beam_ranges.fill(converted, lambda d, m: None, guess=False) == []


@pytest.fixture
def library(monkeypatch, tmp_path):
    (tmp_path / "test").mkdir()
    (tmp_path / "test" / "chart.json").write_text(json.dumps(CHART), encoding="utf-8")
    monkeypatch.setattr(fxlib, "LIB_DIR", tmp_path)
    monkeypatch.setattr(fxlib, "USER_DIR", None)
    fxlib.library.cache_clear()
    yield tmp_path
    fxlib.library.cache_clear()


def test_the_library_plays_a_charts_gobos_and_keeps_its_file_as_it_was(library):
    defn = fxlib.get("test/chart")
    fx = {"id": "h", "fixture": "test/chart", "mode": "8ch", "universe": 1, "address": 1, "x": 0.5}
    buf = bytearray(512)
    fxlib.patch(buf, fx, {"h": State(dimmer=1.0, fx="gobo", gobo=2)})
    assert buf[3] == defn["beam_fx"]["gobo"]["gobo"][2] and buf[4] == 0  # gobo 3 in, prism out
    fxlib.patch(buf, fx, {"h": State(dimmer=1.0, fx="prism_spin", fx_speed=1.0)})
    assert buf[3] == 0 and buf[4] == 255
    assert len(gobos.usable(defn)) == 14  # the show picks among its gobos
    fxlib.save("test/chart", dict(defn))
    assert "beam_fx" not in json.loads((library / "test" / "chart.json").read_text())  # read again on load


def test_a_qlc_fixture_added_before_reads_its_prism_and_frost_from_the_catalogue():
    sharpy = fxlib.get("claypaky/sharpy")  # converter 10: its file has no prism or frost values
    assert sharpy["qlc"]["converter"] < 11
    assert sharpy["beam_fx"]["prism"] == {"prism": 191} and sharpy["beam_fx"]["frost"] == {"frost": 255}
