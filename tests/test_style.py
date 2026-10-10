"""A house style per genre, and a live set's genre."""

from decisive.director import direct
from decisive.director.prompt import QUESTIONS, build_prompt, questions_for
from decisive.director.rules import RuleDirector
from decisive.director.style import STYLES, SetGenre, check, style_for
from decisive.director.vocabulary import DEFAULT_PALETTES
from tests.synthetic import synthetic_analysis


def test_the_style_sheets_only_use_known_options():
    assert check() == []


def test_without_a_genre_nothing_changes():
    assert style_for("") is None and style_for("cinematic") is None
    assert questions_for(None) == QUESTIONS
    palette = next(q for q in QUESTIONS if q["name"] == "palette")
    assert [c["value"] for c in palette["choices"]] == DEFAULT_PALETTES  # the style-only palettes stay out


def test_the_rule_director_keeps_to_the_style():
    a = synthetic_analysis()
    for genre in ("techno", "rock", "ambient"):
        style = STYLES[genre]
        plan = direct(a, RuleDirector(style=style), verbose=False)
        assert {d.palette for d in plan} <= set(style.palettes)
        misfits = sum(not style.allows(layer, getattr(d, layer)) for d in plan for layer in style.avoid)
        assert misfits <= len(plan) // 4  # (the song's arc and the drops may still insist now and then)


def test_two_genres_look_different():
    a = synthetic_analysis()
    techno = direct(a, RuleDirector(style=STYLES["techno"]), verbose=False)
    rock = direct(a, RuleDirector(style=STYLES["rock"]), verbose=False)
    assert {d.palette for d in techno} != {d.palette for d in rock}
    assert [d.look() for d in techno] != [d.look() for d in rock]


def test_the_models_get_the_style_and_only_options_that_fit():
    style = STYLES["techno"]
    qs = {q["name"]: q for q in questions_for(None, style=style)}
    assert [c["value"] for c in qs["palette"]["choices"]] == list(style.palettes)
    for layer, bad in style.avoid.items():
        if layer in qs:
            assert not bad & {c["value"] for c in qs[layer]["choices"]}
    prompt = build_prompt(synthetic_analysis(), 2, [], style=style)
    assert "STYLE: this part of the set is techno" in prompt


def test_the_set_keeps_its_genre_until_a_new_one_lasts():
    s = SetGenre()
    assert s.genre_for("a.mp3", "house") == "house"
    assert s.genre_for("b.mp3", "house") == "house"
    assert s.genre_for("c.mp3", "pop") == "house"  # one pop track in a house set: played as house
    assert s.genre_for("c.mp3", "pop") == "house"  # (decided once per track)
    assert s.genre_for("d.mp3", "house") == "house"
    assert s.genre_for("e.mp3", "techno") == "house"
    assert s.genre_for("f.mp3", "techno") == "techno"  # two in a row: the set has moved on
    assert s.genre_for("g.mp3", "rock", source="you") == "rock"  # your own choice counts for its track
    assert s.genre_for("h.mp3", "cinematic") == "cinematic"  # a program of its own…
    assert s.genre_for("i.mp3", "pop") == "techno"  # …and the set's genre stays
