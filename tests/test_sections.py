"""Sections: one model in one place, left and right mirrored. The show's parts go by sections, or by mirrored pairs."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import looks as L
from amadeus.engine.engine import Engine
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig, load_rig_dict
from amadeus.rig.sections import parts, rig_sections, share_out
from tests.synthetic import synthetic_analysis

BEAM, SPOT, PAR = "beamz/fuze75b-beam", "beamz/fuze75s-spot", "generic/par-64"
WIDTH = 6.0


def light(fid, model, x, y=-1.5, z=2.6, mount="hang", address=1):
    return {"id": fid, "fixture": model, "x": x, "y_m": y, "z_m": z, "mount": mount, "universe": 1, "address": address}


def mixed_rig(camera=False):
    """Beams and spots side by side on a truss, the same beams on the floor, pars down both walls."""
    spots = [
        ("beamL", BEAM, 0.1), ("spotL", SPOT, 0.25), ("spotL2", SPOT, 0.4),
        ("spotR2", SPOT, 0.6), ("spotR", SPOT, 0.75), ("beamR", BEAM, 0.9),
    ]  # fmt: skip
    fixtures = [light(i, m, x) for i, m, x in spots]
    fixtures += [light("floorL", BEAM, 0.2, -1.5, 0.3, "floor"), light("floorR", BEAM, 0.8, -1.5, 0.3, "floor")]
    for k, y in enumerate((1.5, 3.5, 5.5, 7.5)):
        fixtures += [light(f"parL{k}", PAR, 0.03, y, 0.3, "floor"), light(f"parR{k}", PAR, 0.97, y, 0.3, "floor")]
    for k, f in enumerate(fixtures):
        f["address"] = 1 + 20 * k
    stage = {"width_m": WIDTH, "ceiling_m": 4.0, "eye_safety": False}
    if camera:
        stage |= {"camera_x_m": 3.0, "camera_y_m": 8.0, "camera_z_m": 1.6}
    return load_rig_dict({"fixtures": fixtures, "stage": stage, "safety": {"master": 1, "max_flash_hz": 3}})


def section_of(rig):
    return {i: k for k, s in enumerate(rig_sections(rig)) for i in s["ids"]}


MIRRORS = [("beamL", "beamR"), ("spotL", "spotR"), ("spotL2", "spotR2"), ("floorL", "floorR")] + [
    (f"parL{k}", f"parR{k}") for k in range(4)
]


def test_a_section_is_one_model_in_one_place():
    secs = {frozenset(s["ids"]) for s in rig_sections(mixed_rig())}
    assert frozenset({"beamL", "beamR"}) in secs
    assert frozenset({"floorL", "floorR"}) in secs  # the same model somewhere else: a section of its own
    assert frozenset({"spotL", "spotL2", "spotR2", "spotR"}) in secs
    assert frozenset(f"par{s}{k}" for s in "LR" for k in range(4)) in secs
    assert len(secs) == 4


def test_every_fixture_pairs_with_its_mirror_image():
    pairs = {frozenset(p) for s in rig_sections(mixed_rig()) for p in s["pairs"]}
    assert pairs == {frozenset(p) for p in MIRRORS}


def test_a_fixture_without_a_mirror_image_stays_alone():
    rig = load_rig_dict(
        {
            "fixtures": [light("a", BEAM, 0.2), light("b", BEAM, 0.5, address=21), light("c", BEAM, 0.55, address=41)],
            "stage": {"width_m": WIDTH},
            "safety": {"master": 1, "max_flash_hz": 3},
        }
    )
    assert sorted(map(sorted, rig_sections(rig)[0]["pairs"])) == [["a"], ["b"], ["c"]]


def test_parts_go_by_sections_else_by_pairs():
    secs = rig_sections(mixed_rig())
    assert len(parts(secs, 3)) == 4
    assert len(parts(secs, 5)) == len(MIRRORS)
    assert sorted(len(s) for s in share_out(parts(secs, 3), 3)) == [4, 4, 8]


def test_the_camera_never_splits_a_pair():
    heads = Engine(*_show(mixed_rig(camera=True)))
    ids = [e["id"] for e in heads.heads]
    pulled = {ids[j] for j in heads.camera_heads}
    assert 0 < len(pulled) < len(ids)
    for a, b in MIRRORS[:4]:
        assert (a in pulled) == (b in pulled)


def _show(rig):
    a = synthetic_analysis()
    return a, direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False), rig


@pytest.fixture(scope="module")
def show():
    a, plan, rig = _show(mixed_rig())
    return a, plan, rig


@pytest.mark.parametrize("par_accent", ["pulse", "alternate", "sparkle", "color_pop"])
@pytest.mark.parametrize("head_light", ["pulse", "alternate", "beat", "steady"])
@pytest.mark.parametrize("layers", ["none", "alternate"])
def test_mirrored_lights_play_alike(show, par_accent, head_light, layers):
    a, plan, rig = show
    plan = [
        replace(d, par_accent=par_accent, head_light=head_light, layer_split=layers, grouping="per_group",
                formation="mirror", head_color="cycle")
        for d in plan
    ]  # fmt: skip
    e = Engine(a, plan, rig)
    for t in np.arange(1.0, a.duration - 1, 0.37):
        i, s = e.render(float(t))
        was = max(i - 1, 0) if t - plan[i].start < L.XFADE else i  # (fading out of the phrase before)
        if "sides" in (e._kick_pattern(plan[i], float(t)), e._kick_pattern(plan[was], float(t))):
            continue  # (left against right on purpose)
        for left, right in MIRRORS:
            assert s[left].lit == pytest.approx(s[right].lit, abs=0.02), (left, right, t)
            assert (s[left].r, s[left].g, s[left].b) == pytest.approx((s[right].r, s[right].g, s[right].b), abs=0.02)


def test_sides_still_plays_left_against_right():
    assert L.kick_turn("sides", 0, 8, 0) != L.kick_turn("sides", 7, 8, 0)


def test_a_section_takes_the_accents_as_one(show):
    a, plan, rig = show
    e = Engine(a, plan, rig)
    of = section_of(rig)
    played = [d for d in plan if e._accent_players(d, d.start + 1)]
    for d in played:
        players = e._accent_players(d, d.start + 1)
        for s in {of[i] for i in players}:
            assert {i for i, k in of.items() if k == s} <= players


@pytest.mark.parametrize("name", ["concert60", "encore60", "fuze24", "ring", "showcase", "small", "zones"])
def test_every_rig_gets_sections(name):
    rig = load_rig(f"tests/sets/{name}.json")
    secs = rig_sections(rig)
    ids = [i for s in secs for i in s["ids"]]
    assert len(ids) == len(set(ids))
    assert {i for s in secs for p in s["pairs"] for i in p} == set(ids)
    assert set(ids) == {e["id"] for e in rig["elements"] if e["kind"] in ("head", "par")}
