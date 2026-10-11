"""Themes from a track's title, and the starfield."""

from dataclasses import replace

import numpy as np

from decisive.director import RuleDirector, direct
from decisive.director.prompt import questions_for
from decisive.director.themes import theme_of
from decisive.engine import Engine
from decisive.rig.loader import load_rig
from tests.synthetic import synthetic_analysis


def test_a_title_about_stars_has_the_stars_theme():
    assert theme_of("Coldplay - A Sky Full of Stars.mp3") == "stars"
    assert theme_of("Starlight.mp3") == "stars" and theme_of("Galaxy.wav") == "stars"
    assert theme_of("Ringo Starr - Photograph.mp3") is None  # the artist doesn't count
    assert theme_of("Rockstar.mp3") is None and theme_of("Purple Noise.mp3") is None


def test_only_a_themed_track_gets_the_special_question():
    assert not any(q["name"] == "special" for q in questions_for(None))
    q = next(q for q in questions_for(None, theme="stars") if q["name"] == "special")
    assert [c["value"] for c in q["choices"]] == ["off", "stars"]


def test_the_rules_play_stars_at_key_moments_only():
    plan = direct(synthetic_analysis(), RuleDirector(theme="stars"), verbose=False)
    stars = [d.special == "stars" for d in plan]
    assert any(stars) and not all(stars)
    assert not any(a and b and c for a, b, c in zip(stars, stars[1:], stars[2:]))  # two in a row at most
    assert all(d.special == "off" for d in direct(synthetic_analysis(), RuleDirector(), verbose=False))


def test_stars_are_subtle_accents_on_a_few_lights_each_on_its_own():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(), verbose=False)
    k = next(i for i, d in enumerate(plan) if d.section == "groove")
    rig = load_rig("tests/sets/showcase.json")
    plain = Engine(a, plan, rig, real_output=False)
    starry = list(plan)
    starry[k] = replace(plan[k], special="stars")
    e = Engine(a, starry, rig, real_output=False)
    d = plan[k]
    ts = np.arange(d.start + 1, d.end - 1, 1 / 40)
    stars = set(e._star_lights())
    changed, moments = set(), []
    prev = None
    for t in ts:
        got, base = e.render(float(t))[1], plain.render(float(t))[1]
        diff = {
            eid for eid in got if abs(got[eid].dimmer - base[eid].dimmer) > 1e-6 or abs(got[eid].b - base[eid].b) > 1e-6
        }
        changed |= diff
        if prev is not None:  # how many star lights start a twinkle on the same frame
            moments.append(
                sum(1 for eid in stars if got[eid].dimmer > prev[eid] + 0.05 and got[eid].dimmer > base[eid].dimmer)
            )
        prev = {eid: got[eid].b for eid in got}
    assert changed and changed <= stars  # only the star lights; the heads and the rest play on
    assert len(stars) < len(rig["elements"]) / 2
    assert max(moments) <= 3  # each star at its own moment, not the rig stepping at once
