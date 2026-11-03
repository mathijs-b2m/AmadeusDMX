"""A house style per genre, and a live set's genre."""

from amadeus.director import direct
from amadeus.director.prompt import QUESTIONS, build_prompt, questions_for
from amadeus.director.rules import RuleDirector
from amadeus.director.style import STYLES, SetGenre, check, style_for
from amadeus.director.vocabulary import DEFAULT_PALETTES
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
        assert {d.palette for d in plan} <= set(style.palettes)  # the genre's colours all through
        grooves = [d for d in plan if d.section == "groove"]
        misfits = sum(not style.allows(layer, getattr(d, layer)) for d in grooves for layer in style.avoid)
        assert misfits <= max(1, len(grooves) // 4)  # its looks in the grooves (the arc may still insist)


def test_the_other_parts_follow_their_own_music():
    a = synthetic_analysis()
    plain = direct(a, RuleDirector(), verbose=False)
    jazz = direct(a, RuleDirector(style=STYLES["jazz"]), verbose=False)
    for p, j in zip(plain, jazz):
        if p.section in ("drop", "buildup") and j.section == p.section:
            assert (p.movement, p.head_light) == (j.movement, j.head_light)  # a drop stays a drop, also in jazz


def test_two_genres_look_different():
    a = synthetic_analysis()
    techno = direct(a, RuleDirector(style=STYLES["techno"]), verbose=False)
    rock = direct(a, RuleDirector(style=STYLES["rock"]), verbose=False)
    assert {d.palette for d in techno} != {d.palette for d in rock}
    assert [d.look() for d in techno] != [d.look() for d in rock]


def test_the_models_get_the_colours_and_the_style_as_a_lean():
    style = STYLES["techno"]
    qs = {q["name"]: q for q in questions_for(None, style=style)}
    assert [c["value"] for c in qs["palette"]["choices"]] == list(style.palettes)
    plain = {q["name"]: q for q in questions_for(None)}
    assert all(qs[n] == plain[n] for n in qs if n != "palette")  # every move and light still open
    prompt = build_prompt(synthetic_analysis(), 2, [], style=style)
    assert "STYLE: this part of the set is techno" in prompt and "LEAN, not a rule" in prompt


def test_the_set_keeps_its_genre_until_a_new_one_lasts():
    s = SetGenre()
    assert s.genre_for("a.mp3", "house", "audio") == "house"
    assert s.genre_for("b.mp3", "house", "audio") == "house"
    assert s.genre_for("c.mp3", "pop", "audio") == "house"  # one pop guess in a house set: played as house
    assert s.genre_for("c.mp3", "pop", "audio") == "house"  # (decided once per track)
    assert s.genre_for("d.mp3", "house", "audio") == "house"
    assert s.genre_for("e.mp3", "techno", "audio") == "house"
    assert s.genre_for("f.mp3", "techno", "audio") == "techno"  # two in a row: the set has moved on
    assert s.genre_for("g.mp3", "rock", source="you") == "rock"  # your own choice counts for its track
    assert s.genre_for("h.mp3", "pop", source="ai") == "pop"  # so does a genre known from artist and title
    assert s.genre_for("i.mp3", "cinematic") == "cinematic"  # a program of its own…
    assert s.genre_for("j.mp3", "pop", "audio") == "pop"  # …and leaves the set alone: pop twice, the set is pop


def test_prydz_tomorrow_red_pars_white_heads_strobing_drops():
    from amadeus.director.style import NAMED, named_shows

    style = NAMED["prydz-tomorrow"]
    assert style_for("prydz-tomorrow") is style and style.of == "techno"
    assert {"key": "prydz-tomorrow", "title": "Prydz Tomorrow", "genre": "techno"} in named_shows()
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(style=style), verbose=False)
    assert all(d.head_color == "white" and d.beam_fx == "open" for d in plan)  # open white beams all night
    body = [d for d in plan if d.section in ("groove", "drop", "buildup")]
    assert body and all(d.palette == "prydz" for d in body)  # red washes, the blue and green only in the breaks
    assert all(d.par_base == "full" for d in body)
    drops = [d for d in plan if d.section == "drop"]
    assert drops and sum(d.head_light == "strobe" for d in drops) >= len(drops) // 2  # (the arc tames an early one)
    assert all(d.movement in ("swing", "ballyhoo", "sweep", "step_on_beat") for d in drops)


def test_a_named_show_is_the_whole_set_and_not_a_lean():
    from amadeus.director.style import NAMED

    a = synthetic_analysis()
    prompt = build_prompt(a, 0, [], style=NAMED["prydz-tomorrow"])
    assert "named show 'Prydz Tomorrow'" in prompt and "LEAN" not in prompt
