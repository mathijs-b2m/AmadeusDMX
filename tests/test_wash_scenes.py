"""Colour scenes from a designer's scene reel: LED strobes with colour that wash with the pars (white flashes on
top), the pars split in colour down the middle, and a drop with a steady colour wash under white beams."""

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
    return Engine(a, plan, load_rig(f"tests/sets/{rig_name}.json"), real_output=False), plan[k]


def _times(d, n=40):
    return np.linspace(d.start + 0.3 * (d.end - d.start), d.end - 0.5, n)  # clear of the moments at the edges


def _strobes(e):
    ids = [x["id"] for x in e.rig["elements"] if x["kind"] == "strobe"]
    if not ids:
        pytest.skip("no strobes")
    return ids


def test_colour_strobes_wash_with_the_pars(track):
    e, d = _engine(track, "showcase", "groove", par_base="full", par_accent="none", dynamics="steady")
    ids = _strobes(e)
    e._strobe_states(d, d.start, {}, 0.0)  # (builds the lists)
    assert set(ids) <= e._strobe_rgb, "the Atomic 3000 LED mixes colour"
    for t in _times(d, 10):
        out = {}
        e._strobe_states(d, float(t), out, 0.0, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
        for s in ids:
            st = out[s]
            assert st.dimmer > 0.3 and st.strobe_hz == 0.0, "a steady wash, no strobing"
            assert (st.r, st.g, st.b) == (0.0, 0.0, 1.0), "in the pars' base colour"


@pytest.mark.parametrize("par_base", ["off"])
def test_colour_strobes_dark_when_the_pars_wait(track, par_base):
    e, d = _engine(track, "showcase", "groove", par_base=par_base, par_accent="pulse", dynamics="steady")
    ids = _strobes(e)
    lit = max(e.render(float(t))[1][s].dimmer for t in _times(d) for s in ids)
    assert lit == 0.0


def test_white_strobes_never_wash(track):
    e, d = _engine(track, "showcase", "groove", par_base="full", par_accent="none", dynamics="steady")
    ids = _strobes(e)
    e._strobe_states(d, d.start, {}, 0.0)  # (builds the lists)
    e._strobe_rgb = set()  # as if they were white-only strobes
    lit = max(e.render(float(t))[1][s].dimmer for t in _times(d) for s in ids)
    assert lit == 0.0, "a white strobe is never a steady light"


def test_the_build_up_flashes_stay_white(track):
    e, d = _engine(track, "showcase", "buildup", par_base="full", dynamics="rise")
    ids = _strobes(e)
    nxt = e.plan[d.phrase + 1] if d.phrase + 1 < len(e.plan) else None
    if nxt is None or nxt.section != "drop":
        pytest.skip("no drop after the build-up")
    out = {}
    e._strobe_states(d, d.end - 0.3, out, 0.0, (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))
    for s in ids:
        assert (out[s].r, out[s].g, out[s].b) == (1.0, 1.0, 1.0)


@pytest.mark.parametrize("rig_name", RIGS)
def test_pars_split_down_the_middle(track, rig_name):
    e, d = _engine(track, rig_name, "groove", par_base="sides", par_accent="none", dynamics="steady")
    t = float(_times(d, 3)[1])
    taken = e._accent_players(d, t)  # the synth's accents play their own notes
    left = [p["id"] for p in e.pars if float(p.get("x", 0.5)) < 0.45 and p["id"] not in taken]
    right = [p["id"] for p in e.pars if float(p.get("x", 0.5)) > 0.55 and p["id"] not in taken]
    if not left or not right:
        pytest.skip("pars on one side only")
    out = e._scene(d, t)
    rgb = lambda p: np.round([out[p].r, out[p].g, out[p].b], 3)  # noqa: E731
    assert all((rgb(p) == rgb(left[0])).all() for p in left)
    assert all((rgb(p) == rgb(right[0])).all() for p in right)
    assert not (rgb(left[0]) == rgb(right[0])).all(), "left and right in different colours"
    assert min(out[p].dimmer for p in left + right) > 0.15, "both sides glow"


def test_a_drop_look_washes_under_white_beams():
    assert any(look[:2] == ("full", "none") and look[7] == "white" for look in RULE_LOOKS["drop"])


@pytest.mark.parametrize("rig_name", RIGS)
def test_the_wash_holds_steady_in_a_drop(track, rig_name):
    e, d = _engine(track, rig_name, "drop", par_base="full", par_accent="none", head_light="pulse",
                   head_color="white", dynamics="impact")  # fmt: skip
    if not e.pars:
        pytest.skip("no pars")
    seen: dict[str, list[float]] = {}
    for t in _times(d):
        out, taken = e._scene(d, float(t)), e._accent_players(d, float(t))  # (the synth's accents play notes)
        for p in e.pars:
            if p["id"] not in taken:
                assert out[p["id"]].white == 0.0, "no white flashes on the wash"
                seen.setdefault(p["id"], []).append(out[p["id"]].dimmer)
    assert seen
    assert min(min(v) for v in seen.values()) > 0.3, "the wash glows"
    assert max(max(v) - min(v) for v in seen.values()) < 0.05, "a steady wash"
