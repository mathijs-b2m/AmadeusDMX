"""Lights never flicker: the kick leads, fast triggers play the kick, the strobe is rare and at a fixed rate,
and moving heads never freeze in quiet parts."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from decisive.director import RuleDirector, direct
from decisive.engine import Engine, timing
from decisive.engine import looks as L
from decisive.rig.groups import head_groups, laser_list
from decisive.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
FPS = 40


def fast_cycles(x: np.ndarray, hyst: float = 0.25, fastest_s: float = 0.3) -> int:
    """Off-on cycles (down and up again by at least `hyst`) quicker than `fastest_s`, timed from each switch-on."""
    ons, falling, low, high = [], False, x[0], x[0]
    for k, v in enumerate(x):
        if not falling:
            high = max(high, v)
            if high - v >= hyst:
                falling, low = True, v
        else:
            low = min(low, v)
            if v - low >= hyst:
                ons.append(k)
                falling, high = False, v
    return int((np.diff(ons) < fastest_s * FPS).sum()) if len(ons) > 1 else 0


@pytest.fixture(scope="module")
def track():
    return synthetic_analysis()


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_no_light_flickers_without_a_strobe(track, path):
    rig = load_rig(path)
    rig["safety"]["allow_fast_strobe"] = False  # (the deliberate strobe is the only fast thing allowed)
    plan = direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    plan = [
        replace(d, trigger="sixteenths", head_light="stutter", par_accent="stutter") if d.section == "groove" else d
        for d in plan
    ]  # fmt: skip  (the fastest choices there are)
    e = Engine(track, plan, rig)
    ids = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    ts = np.arange(0.05, track.duration - 0.1, 1 / FPS)
    tr = np.array([[max(st[i].dimmer, st[i].white) for i in ids] for st in (e.render(float(t))[1] for t in ts)])
    assert sum(fast_cycles(c) for c in tr.T) == 0


def test_the_strobe_is_rare_and_at_a_fixed_rate(track):
    rig = load_rig(SETS[0])
    rig["safety"]["allow_fast_strobe"] = True
    e = Engine(track, direct(track, RuleDirector(), verbose=False), rig)
    e.chop[:] = 1.0  # the synths stutter all the time
    bars = e._strobe_bars()
    assert 0 < bars.mean() <= 1 / (timing.STROBE_REST_BARS + 1) + 0.02  # one bar in seventeen at most
    e.strobe_bars = bars
    t0 = np.flatnonzero(bars)[0] / track.fps
    seq = [e._strobe(t0 + k / 1000) for k in range(1000)]
    assert set(seq) == {0.0, 1.0}
    flips = np.flatnonzero(np.diff(seq))
    assert np.allclose(np.diff(flips[::2]), 1000 / timing.STROBE_HZ, atol=2)  # a fixed rate, not the music


def test_a_group_plays_the_kicks_in_parts():
    n = 6
    for pattern in ("alternate", "sides", "rotate"):
        lit = [[L.kick_turn(pattern, k, n, hit) for k in range(n)] for hit in range(4)]
        assert all(0 < sum(row) < n for row in lit)  # each kick some of the group, not all
        assert all(any(row[k] for row in lit) for k in range(n))  # and every light gets its turns
    assert all(L.kick_turn("all", k, n, 3) for k in range(n))


def test_the_engine_varies_how_the_group_plays(track):
    e = Engine(track, direct(track, RuleDirector(), verbose=False), load_rig(SETS[0]))
    assert len({e._kick_pattern(replace(d, phrase=i, section="groove")) for i, d in enumerate(e.plan * 4)}) >= 3


def test_still_heads_drift_and_upward_aims_fit_under_a_low_ceiling(track):
    rig = load_rig(SETS[0])
    rig["stage"].update(ceiling_m=2.6, room_depth_m=4)
    e = Engine(track, direct(track, RuleDirector(), verbose=False), rig)
    for movement, aim in (("still", "crowd"), ("nod", "sky")):
        d = replace(e.plan[0], movement=movement, aim=aim, intensity=0)
        ts = np.linspace(d.start, d.start + 20, 80)
        out = e._head_dir_v(d, ts, 0)
        travel = np.degrees(np.arccos(np.clip(out @ out.T, -1, 1))).max()
        assert travel > 5, f"{movement}/{aim} frozen"
