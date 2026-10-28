"""Zoom as part of the look (amadeus/engine/zoom.py): beams tight when the music is big, washes wide and gathering
at the peaks, sized to the rig, set per phrase and never pumping with the beat."""

from dataclasses import replace

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.engine import zoom as Z
from amadeus.engine.looks import XFADE
from amadeus.engine.realism import Realism
from amadeus.library import fixtures as fxlib
from amadeus.rig import automount, templates
from amadeus.rig.groups import head_groups
from amadeus.rig.loader import load_rig_dict
from tests.synthetic import synthetic_analysis

MODELS = {"d": ("ayrton/diablo-s", "ext", 1), "a": ("martin/mac-aura", "Extended", 2),
          "c": ("high-end-systems/color-command", "5ch", 3)}  # fmt: skip


def club_rig() -> dict:
    """Two trusses over a 10 m stage: four beam heads (Diablo-S), four wash heads (MAC Aura) and four fixed
    washes with a zoom (Color Command)."""
    rig = templates.rig("club", width=10.0)
    rig["fixtures"] = []
    for p, (key, mode, uni) in MODELS.items():
        size = len(fxlib.channels(fxlib.get(key), mode))
        rig["fixtures"] += [{"id": f"{p}{k}", "fixture": key, "mode": mode, "universe": uni, "address": 1 + size * k}
                            for k in range(4)]  # fmt: skip
    for fid, spot in automount.automount(rig).items():
        next(f for f in rig["fixtures"] if f["id"] == fid).update(spot)
    return load_rig_dict(rig)


@pytest.fixture(scope="module")
def show():
    a = synthetic_analysis()
    rig = club_rig()
    plan = direct(a, RuleDirector(head_groups(rig)), verbose=False)
    return a, plan, Engine(a, plan, rig)


def _role(mv="still"):
    return {"movement": mv}


def test_each_light_with_a_zoom_is_a_beam_a_wash_or_a_fixed_wash_with_one_wide_per_model(show):
    _, _, eng = show
    kinds = {eid[0]: k for eid, k in eng.zoom_kind.items()}
    assert kinds == {"d": "beam", "a": "wash", "c": "fixed"}
    for p in "dac":
        wides = {w for eid, w in eng.zoom_wide.items() if eid.startswith(p)}
        assert len(wides) == 1 and Z.WASH_WIDE_MIN <= wides.pop() <= 1.0  # an operator's preset: even over a row


def test_wide_is_what_the_rig_needs():
    """Washes close together, high up: less than fully open (no hot spots); one on its own: fully open."""
    rig = club_rig()
    eng = Z.ZoomMixin()
    eng._init_zoom(rig, {f["id"]: f for f in rig["fixtures"]})
    assert eng.zoom_wide["a0"] < 1.0
    alone = {**rig, "elements": [e for e in rig["elements"] if e["id"] == "a0"]}
    eng._init_zoom(alone, {f["id"]: f for f in rig["fixtures"]})
    assert eng.zoom_wide["a0"] == 1.0


def test_beams_tight_when_big_or_flying_soft_when_calm(show):
    _, plan, eng = show
    d = replace(plan[0], section="groove", dynamics="steady", beam_fx="open", aim="crowd", intensity=0)
    z = lambda dd, mv="still": eng._head_zoom(dd, "d0", _role(mv), None, None, 0.5)  # noqa: E731
    assert z(d) == Z.BEAM_OPEN_ZOOM[0] > 0.3  # calm, resting on the crowd: soft pools
    assert z(replace(d, section="drop", intensity=3)) == 0.0
    assert z(replace(d, dynamics="impact")) == 0.0
    assert z(replace(d, aim="sky")) == 0.0  # shafts in the haze
    assert z(d, "ballyhoo") == 0.0
    assert z(d, "sweep") == Z.BEAM_FLOWING_ZOOM
    assert z(replace(d, beam_fx="prism")) == Z.BEAM_FLOWING_ZOOM
    assert z(replace(d, beam_fx="gobo")) == 0.45  # a gobo's pattern reads on the floor
    assert z(replace(d, beam_fx="frost")) == 1.0


def test_washes_wide_and_gathering_at_the_peaks(show):
    _, plan, eng = show
    wide = eng.zoom_wide["a0"]
    d = replace(plan[0], section="groove", dynamics="steady", beam_fx="open", intensity=2)
    z = lambda dd: eng._head_zoom(dd, "a0", _role(), None, None, 0.5)  # noqa: E731
    assert z(replace(d, intensity=1)) == wide
    assert z(replace(d, section="breakdown")) == wide
    assert z(d) == pytest.approx(Z.WASH_GROOVE * wide)
    assert z(replace(d, section="drop", intensity=3)) == Z.WASH_PEAK_ZOOM
    f = lambda dd: eng._fixed_zoom(dd, "c0", 0.5)  # noqa: E731
    cw = eng.zoom_wide["c0"]
    assert f(replace(d, intensity=0)) == cw
    assert f(replace(d, section="drop", intensity=3)) == pytest.approx(Z.FIXED_PEAK * cw)  # the stage stays covered
    assert cw > f(d) > Z.FIXED_PEAK * cw
    assert eng._fixed_zoom(d, "nope", 0.5) is None


def test_a_buildup_focuses_into_its_drop(show):
    _, plan, eng = show
    d = replace(plan[0], section="buildup", dynamics="rise", beam_fx="open", intensity=2)
    beam = [eng._head_zoom(d, "d0", _role("sweep"), None, None, p) for p in (0.0, 0.5, 1.0)]
    wash = [eng._head_zoom(d, "a0", _role(), None, None, p) for p in (0.0, 0.5, 1.0)]
    fixed = [eng._fixed_zoom(d, "c0", p) for p in (0.0, 0.5, 1.0)]
    assert beam[0] == Z.BEAM_OPEN_ZOOM[0] and beam[-1] == 0.0 and beam[0] > beam[1] > beam[2]
    assert wash[0] == eng.zoom_wide["a0"] and wash[-1] == pytest.approx(Z.WASH_PEAK_ZOOM)
    assert fixed[0] > fixed[1] > fixed[2]


def test_accents_and_featured_groups_tighter_than_the_carpet(show):
    _, plan, eng = show
    d = replace(plan[0], section="groove", dynamics="steady", beam_fx="open", aim="crowd", intensity=1)
    plain = eng._head_zoom(d, "a0", _role(), None, None, 0.5)
    assert eng._head_zoom(d, "a0", _role(), "accent", None, 0.5) < plain
    assert eng._head_zoom(d, "a0", _role(), None, True, 0.5) < plain
    assert eng._head_zoom(d, "a0", _role(), None, False, 0.5) == plain
    assert eng._head_zoom(replace(d, intensity=3), "d0", _role(), "base", None, 0.5) == Z.BEAM_BASE_ZOOM


def test_the_cinematic_program_keeps_beams_tight_and_washes_wide_for_a_pad(show):
    _, _, eng = show
    assert eng._cine_zoom("d0", set(), 0.9) == 0.0
    assert eng._cine_zoom("a0", {"a0"}, 0.9) == eng.zoom_wide["a0"]
    assert eng._cine_zoom("a0", set(), 0.2) == eng.zoom_wide["a0"]
    assert eng._cine_zoom("a0", set(), 0.9) == Z.WASH_PEAK_ZOOM


def test_zoom_never_pumps_with_the_beat(show):
    """Through the whole show, every light's zoom only goes one way within a phrase (set per phrase; a buildup's
    focus, the drop's zoom taken in the dark, a pickup's look coming in early)."""
    a, plan, eng = show
    ts = np.arange(0.0, a.duration - 0.1, 1 / 40)
    zoom = {eid: [] for eid in eng.zoom_kind}
    for t in ts:
        _, states = eng.render(float(t))
        for eid in zoom:
            zoom[eid].append(states[eid].zoom)
    moved = False
    for i, d in enumerate(plan):
        inside = (ts >= d.start + XFADE) & (ts < d.end)
        for eid, z in zoom.items():
            steps = np.diff(np.asarray(z)[inside])
            steps = steps[np.abs(steps) > 1e-6]
            moved |= np.ptp(np.asarray(z)) > 0.1
            assert len(steps) == 0 or np.all(steps > 0) or np.all(steps < 0), (eid, i, d.section)
    assert moved  # the zoom does play: it changes from phrase to phrase


def test_the_dmx_and_the_visualiser_get_the_washes_zoom(show):
    _, plan, eng = show
    i = next(k for k, d in enumerate(plan) if d.intensity <= 1 and d.section != "buildup")
    _, states = eng.render((plan[i].start + plan[i].end) / 2)
    aura = next(f for f in eng.rig["fixtures"] if f["id"] == "a0")
    chans = fxlib.channels(fxlib.get(aura["fixture"]), aura["mode"])
    zc = next(k for k, c in enumerate(chans) if c["attr"] == "zoom")
    buf = bytearray(512)
    fxlib.patch(buf, aura, states, limit=1.0)
    c = chans[zc]
    want = round(c["tight"] + (c["wide"] - c["tight"]) * fxlib.zoom_of(states["a0"]))
    assert buf[aura["address"] - 1 + zc] == want and states["a0"].zoom > 0.2  # calm: opened up, not tight
    real = Realism(eng.rig)
    beams = real.beams(states, 1.0)
    assert beams["c0"][:2] == (None, None) and beams["c0"][2] == pytest.approx(states["c0"].zoom)  # a fixed wash too


def test_a_head_is_drawn_with_its_light_and_field():
    from amadeus.engine.realism import beam_info

    b = beam_info(6000, 2.0, 2.0, True)
    assert b["beam_deg"] == 2.0 and b["field"] == 1.8 and b["flux"] == 2.0  # four times the reference light: twice as bright
    assert beam_info(None, 14.0, 14.0, True)["flux"] == 1.0  # no lumens: the reference
    assert beam_info(10, 14.0, 14.0, True)["flux"] == 0.25  # never fainter than this
    assert beam_info(1500, 10.0, 30.0, True, field_deg=13)["field"] == 1.3  # the fixture's own field angle
