"""The brightness limiter: a ceiling, not a scale. At 70 % a light at 50 % stays at 50 %, one at 100 % plays at 70 %;
colours keep their hue; smoke isn't light."""

from amadeus.dmx import limiter
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib


def dmx(fx: dict, state: State, limit: float | None = None) -> bytearray:
    buf = bytearray(512)
    fxlib.patch(buf, fx, {e["id"]: state for e in fxlib.expand(fx)}, limit=limit)
    return buf


def at(fx: dict, attr: str, buf: bytearray) -> int:
    chans = fxlib.channels(fxlib.get(fx["fixture"]), fx["mode"])
    return buf[fx["address"] - 1 + next(i for i, c in enumerate(chans) if c["attr"] == attr)]


HEAD = {"id": "fuze1", "fixture": "beamz/fuze75b-beam", "mode": "12ch", "universe": 1, "address": 1, "x": 0.5}
PAR = {"id": "par1", "fixture": "ayra/compar-kit-2", "mode": "3ch", "universe": 1, "address": 1, "x": 0.5}
BAR = {"id": "bar1", "fixture": "ayra/compar-kit-2", "mode": "16ch", "universe": 1, "address": 1, "x": 0.5}


def test_a_dimmer_is_limited_not_scaled():
    full, half = State(dimmer=1.0, r=1, g=1, b=1), State(dimmer=0.5, r=1, g=1, b=1)
    assert at(HEAD, "dimmer", dmx(HEAD, full, 0.7)) == round(0.7 * 255)
    assert at(HEAD, "dimmer", dmx(HEAD, half, 0.7)) == at(HEAD, "dimmer", dmx(HEAD, half, 1.0)) == round(0.5 * 255)


def test_rgb_without_a_dimmer_keeps_its_hue():
    orange = State(dimmer=1.0, r=1.0, g=0.5, b=0.0)
    buf = dmx(PAR, orange, 0.6)
    assert (buf[0], buf[1], buf[2]) == (round(0.6 * 255), round(0.3 * 255), 0)
    dim = State(dimmer=0.4, r=1.0, g=0.5, b=0.0)  # under the ceiling: untouched
    assert dmx(PAR, dim, 0.6)[:3] == dmx(PAR, dim, 1.0)[:3]


def test_a_bar_with_one_dimmer_limits_each_cell():
    buf = dmx(BAR, State(dimmer=1.0, r=1, g=1, b=1), 0.5)
    assert max(buf[:12]) == round(0.5 * 255)
    assert at(BAR, "dimmer", buf) == 255  # the cells carry the level


def test_off_is_bit_for_bit_the_show():
    s = State(dimmer=0.83, r=0.2, g=0.9, b=0.4, white=0.1, pan=0.3, tilt=0.7)
    for fx in (HEAD, PAR, BAR):
        assert dmx(fx, s, 1.0) == dmx(fx, s, None)  # nothing saved: off


def test_the_saved_level_reaches_every_patch(tmp_path):
    old = limiter.FILE
    try:
        limiter.use(tmp_path / "limiter.json")
        assert limiter.level() == 1.0
        assert limiter.save(0.4) == 0.4
        assert at(HEAD, "dimmer", dmx(HEAD, State(dimmer=1.0))) == round(0.4 * 255)
        assert limiter.save(0) == limiter.MIN_LEVEL  # never fully dark
        assert limiter.save(7) == 1.0
    finally:
        limiter.use(old)
