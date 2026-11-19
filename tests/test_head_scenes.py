"""Scenes for the moving heads, from a designer's scene reel: a build-up the pars carry alone (the beams come in at
the drop), a real solo (one pair of beams in a dark room, on any rig) and the rig split in colour down the middle."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.director.rules import RULE_LOOKS
from amadeus.engine import Engine
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

RIGS = sorted(p.stem for p in Path("tests/sets").glob("*.json"))


@pytest.fixture(scope="module")
def track():
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(), verbose=False)


def _engine(track, rig_name, section, **look):
    a, plan = track
    plan = list(plan)
    k = next((i for i, d in enumerate(plan) if d.section == section), None)
    if k is None:
        pytest.skip(f"no {section} in the synthetic track")
    plan[k] = replace(plan[k], **look)
    e = Engine(a, plan, load_rig(f"tests/sets/{rig_name}.json"), real_output=False)
    if not e.heads:
        pytest.skip("no moving heads")
    return e, plan[k]


def _times(d, n=40):
    return np.linspace(d.start + 0.3 * (d.end - d.start), d.end - 0.5, n)  # clear of the moments at the edges


def test_a_buildup_look_leaves_the_heads_dark():
    assert any(look[3] == "off" for look in RULE_LOOKS["buildup"])


@pytest.mark.parametrize("rig_name", RIGS)
def test_heads_off_dark_when_pars_carry_the_look(track, rig_name):
    e, d = _engine(track, rig_name, "buildup", head_light="off", dynamics="rise")
    lit = max(e.render(float(t))[1][h["id"]].dimmer for t in _times(d) for h in e.heads)
    if e.pars:
        assert lit == 0.0, "the heads wait dark while the pars build"
    else:
        assert lit > 0.1, "nothing else to carry the look: the heads keep playing"


@pytest.mark.parametrize("rig_name", RIGS)
def test_solo_one_lit_the_rest_dark(track, rig_name):
    e, d = _engine(track, rig_name, "breakdown", grouping="solo", featured=None, head_light="steady")
    if not e.multi and len(e.head_pairs) < 2:
        pytest.skip("a single pair plays as one")
    if e.multi:  # the first group leads
        d = replace(d, featured=e.groups[0]["name"])
        e.plan[d.phrase] = d
    feat = {h["id"] for j, h in enumerate(e.heads) if e._featured(d, j)}
    assert feat and len(feat) < len(e.heads)
    for t in _times(d, 20):
        states = e.render(float(t))[1]
        others = [states[h["id"]].dimmer for h in e.heads if h["id"] not in feat]
        assert max(others) == 0.0, "the others wait dark"
    lit = max(e.render(float(t))[1][h].dimmer for t in _times(d, 20) for h in feat)
    assert lit > 0.1


def test_single_group_rigs_get_solos_in_calm_parts():
    a = synthetic_analysis()
    one = [{"name": "all", "cls": "all", "ids": ["h1", "h2", "h3", "h4"]}]
    plan = direct(a, RuleDirector(groups=one), verbose=False)
    calm = [d for d in plan if d.section in ("intro", "breakdown", "bridge")]
    if not calm:
        pytest.skip("no calm parts in the synthetic track")
    assert any(d.grouping == "solo" for d in calm)
    assert all(d.grouping != "solo" for d in plan if d.section not in ("intro", "breakdown", "bridge"))


@pytest.mark.parametrize("rig_name", RIGS)
def test_sides_split_the_colour_down_the_middle(track, rig_name):
    e, d = _engine(track, rig_name, "groove", head_color="sides", head_light="steady", grouping="unison")
    mid = e.stage["width_m"] / 2
    left = [h["id"] for j, h in enumerate(e.heads) if e.head_pos[j][0] < mid - 0.2]
    right = [h["id"] for j, h in enumerate(e.heads) if e.head_pos[j][0] > mid + 0.2]
    if not left or not right:
        pytest.skip("heads on one side only")
    accents = set().union(*(e._accent_players(d, float(t)) for t in _times(d, 10)))
    left, right = [h for h in left if h not in accents], [h for h in right if h not in accents]
    if not left or not right:
        pytest.skip("the synth's accents take one side")
    t = float(_times(d, 3)[1])
    states = e._scene(d, t)  # the look itself (a colour wheel may snap two near colours to one slot)
    rgb = lambda h: np.round([states[h].r, states[h].g, states[h].b], 3)  # noqa: E731
    assert all((rgb(h) == rgb(left[0])).all() for h in left)
    assert all((rgb(h) == rgb(right[0])).all() for h in right)
    assert not (rgb(left[0]) == rgb(right[0])).all(), "left and right in different colours"
