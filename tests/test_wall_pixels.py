"""The LED wall's pixels: they set its shape (the apps draw it, auto-mount keeps clear of it), the hello sends them
and the hang sheet tells the crew."""

import json

import pytest

from amadeus.rig import automount, hangsheet, templates
from amadeus.rig import trusses as T
from amadeus.show import feed as feedlib
from tests.synthetic import synthetic_analysis

W = 16.0


def festival(pixels=None, panel=None, height=9.0):
    rig = templates.rig("festival", width=W, height=height, screen=True)
    if pixels:
        rig["screen"]["pixels"] = pixels
    if panel:
        rig["screen"]["panel_px"] = panel
    return rig


def test_without_pixels_the_wall_is_16_by_9_as_before():
    rig = festival()
    assert T.screen_pixels(rig) is None and T.screen_aspect(rig) == pytest.approx(16 / 9)
    half, bottom, top = T.screen_rect(rig)
    assert (top - bottom) == pytest.approx(2 * half * 9 / 16)
    assert T.screen_pixels({"screen": True}) is None  # an LED wall given as true
    assert T.screen_pixels({"screen": {"pixels": [0, 384]}}) is None
    assert T.screen_pixels({"screen": {"pixels": "768x384"}}) is None


def test_a_long_wall_is_lower_as_wide():
    half16, b16, top16 = T.screen_rect(festival())
    half, bottom, top = T.screen_rect(festival([1536, 384]))  # 4:1
    assert half == pytest.approx(half16) and bottom == b16
    assert top - bottom == pytest.approx(2 * half / 4)


def test_a_tall_wall_stays_under_the_ceiling():
    rig = festival([384, 768], height=6.0)  # 1:2 under a low roof
    rig["stage"]["outdoor"] = False  # (outdoors there is no roof to stay under)
    half, bottom, top = T.screen_rect(rig)
    assert top <= rig["stage"]["ceiling_m"] - 0.3 + 1e-6
    assert (2 * half) / (top - bottom) == pytest.approx(0.5)  # narrower, the shape kept
    rig["stage"]["outdoor"] = True
    half, bottom, top = T.screen_rect(rig)
    assert top - bottom == pytest.approx(4 * half)  # in the open: as tall as its width makes it


def test_auto_mount_keeps_clear_of_a_wall_of_any_shape():
    for px in ([768, 384], [384, 768], [2048, 256]):
        rig = festival(px)
        rig["fixtures"] = [{"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1, "address": 1 + 20 * k}
                           for k in range(16)]  # fmt: skip
        half, bottom, top = T.screen_rect(rig)
        for s in automount.automount(rig).values():
            if s.get("truss") == "wall":
                assert not (abs(s["truss_pos_m"]) < half and bottom - 0.2 < s["z_m"] < top + 0.2), (px, s)


def test_the_hello_sends_the_pixels():
    from amadeus.director import RuleDirector, direct
    from amadeus.rig.groups import head_groups, laser_list
    from amadeus.rig.loader import load_rig_dict

    rig = festival([768, 384])
    rig["fixtures"] = [{"id": "h0", "fixture": "claypaky/sharpy", "universe": 1, "address": 1}]
    for fid, spot in automount.automount(rig).items():
        next(f for f in rig["fixtures"] if f["id"] == fid).update(spot)
    loaded = load_rig_dict(rig)
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(head_groups(loaded), laser_list(loaded), True), verbose=False)
    hello = json.loads(feedlib.hello(a, plan, loaded, None, title="t", director="rules"))
    assert hello["screen"] is True and hello["screen_px"] == [768, 384]
    loaded["screen"] = True
    assert json.loads(feedlib.hello(a, plan, loaded, None, title="t", director="rules"))["screen_px"] is None


def test_the_hang_sheet_tells_the_crew_the_pixels_and_panels():
    assert hangsheet.screen_text({}) is None
    text = hangsheet.screen_text(festival([768, 384], panel=128))
    assert "768 × 384 pixels" in text and "6 × 3 panels of 128 px" in text and "on the front of wall" in text
    assert "aren't in the rig" in hangsheet.screen_text({"screen": True, "trusses": []})
    assert "behind the DJ" in hangsheet.screen_text({"screen": True, "trusses": []})


def test_the_feed_says_when_the_lights_strobe():
    from amadeus.engine.realism import Realism
    from amadeus.engine.state import State
    from amadeus.rig.loader import load_rig_dict

    rig = festival()
    rig["fixtures"] = [
        {"id": f"h{k}", "fixture": "claypaky/sharpy", "universe": 1, "address": 1 + 20 * k} for k in range(4)
    ]
    for fid, spot in automount.automount(rig).items():
        next(f for f in rig["fixtures"] if f["id"] == fid).update(spot)
    loaded = load_rig_dict(rig)
    feed = feedlib.Feed(loaded, Realism(loaded), 0.025)
    ids = feed.ids
    assert "strobe" not in feed.fixture_fields({e: State(dimmer=1.0) for e in ids})  # steady light: no word of it
    half = {e: State(dimmer=1.0, strobe_hz=4.0 if k % 2 == 0 else 0.0, gate=0.0) for k, e in enumerate(ids)}
    assert feed.fixture_fields(half)["strobe"] == [0.5, 0.0]  # half the rig strobes, dark this moment
    lit = {e: State(dimmer=1.0, strobe_hz=4.0, gate=1.0) for e in ids}
    assert feed.fixture_fields(lit)["strobe"] == [1.0, 1.0]
    assert "strobe" not in feed.fixture_fields(
        {e: State(dimmer=0.0, strobe_hz=4.0) for e in ids}
    )  # dark lights don't count
