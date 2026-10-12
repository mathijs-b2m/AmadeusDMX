"""Lights never flicker: the kick leads, fast triggers play the kick, nothing strobes with the music, a kick
break holds and builds and the kick's return hits, and moving heads never freeze in quiet parts."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine
from amadeus.engine import looks as L
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
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
def test_no_light_flickers(track, path):
    rig = load_rig(path)
    rig["safety"]["allow_fast_strobe"] = True  # (even when the set would allow it)
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


def _with_kick_break(a, bars: tuple[int, int]):
    """The synthetic track with the kick taken out of some bars of a groove."""
    db = a.beats[a.downbeats]
    kt, ks = a.onsets["kick"]
    keep = (kt < db[bars[0]] - 0.05) | (kt >= db[bars[1]] - 0.05)
    a2 = replace(a, onsets={**a.onsets, "kick": (kt[keep], ks[keep])})
    return a2, float(db[bars[0]]), float(db[bars[1]])


def test_a_kick_break_holds_and_builds_then_the_return_hits(track):
    rig = load_rig(SETS[0])
    plan = direct(track, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    groove = max((d for d in plan if d.section == "groove"), key=lambda d: d.end - d.start)
    first = int(np.searchsorted(track.beats[track.downbeats], groove.start)) + 1
    a, start, end = _with_kick_break(track, (first, first + 3))
    assert end < groove.end
    plan = [replace(d, trigger="kick", par_accent="pulse", head_light="pulse") if d is groove else d for d in plan]
    e = Engine(a, plan, rig)
    assert any(abs(s - start) < 0.01 and abs(t - end) < 0.01 and r for s, t, r in e.kick_breaks)
    accents = set().union(*(e._accent_players(groove, t) for t in np.arange(groove.start, groove.end, 1.0)))
    head = next(h["id"] for h in e.heads if h["id"] not in accents)  # a rhythm light all along
    period = 60 / 128
    ts = np.arange(start + 0.05, end - period, 0.05)
    level = np.array([e.render(float(t))[1][head].dimmer for t in ts])
    assert level.min() > 0.2 and np.all(np.diff(level) >= -1e-6)  # held, building: no pulses, no dark
    assert level[-1] > level[0] + 0.2
    assert e.render(end - 0.1)[1][head].dimmer == 0.0  # a breath of darkness just before…
    hit = e.render(end + 0.02)[1][head]
    assert max(hit.dimmer, hit.white) > 0.9  # …and the return hits


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
