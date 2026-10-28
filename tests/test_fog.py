"""Smoke machines: the director's haze level per phrase, played by engine/fog.py to fit the machine and the room."""

import json

import numpy as np
import pytest

from amadeus.director import RuleDirector, direct
from amadeus.engine import Engine, fog, motion
from amadeus.library import fixtures as fxlib
from amadeus.rig.groups import has_smoke, head_groups, laser_list
from amadeus.rig.loader import load_rig_dict
from tests.synthetic import SHAPE, synthetic_analysis

BPM = 128
BEAT = 60 / BPM
LEVELS = ["none", "light", "medium", "burst", "heavy", "light", "medium", "burst", "none"]
PHRASE = 32 * BEAT
PHRASES = [(0.5 + i * PHRASE, 0.5 + (i + 1) * PHRASE, lv) for i, lv in enumerate(LEVELS)]
BEATS = np.arange(len(LEVELS) * 32) * BEAT + 0.5
DURATION = PHRASES[-1][1] + 2
FOGGER = fog.Machine("f", m3_min=450, haze=False, max_burst_s=25, rest_s=25)  # a 1500 W fogger


def run(m: fog.Machine, volume: float, **kw):
    out, haze = fog.plan(PHRASES, BEATS, DURATION, [m], volume, **kw)
    return out[0], haze


def bursts(out: np.ndarray) -> list[tuple[float, float]]:
    on = np.concatenate([[0], (out > 0).astype(int), [0]])
    edges = np.flatnonzero(np.diff(on))
    return [(a / fog.FOG_FPS, b / fog.FOG_FPS) for a, b in zip(edges[::2], edges[1::2])]


def test_a_big_machine_in_a_small_room_fogs_briefly_a_small_one_in_a_hall_long():
    small_room, _ = run(FOGGER, 60)
    club, _ = run(FOGGER, 600)
    hall, _ = run(fog.Machine("s", 120, False, 25, 25), 4000)
    seconds = [float((o > 0).sum()) / fog.FOG_FPS for o in (small_room, club, hall)]
    assert seconds[0] < seconds[1] < seconds[2]
    assert seconds[0] < 5 and seconds[2] > 40
    assert small_room[small_room > 0].mean() < hall[hall > 0].mean()  # and softer


def test_never_hazier_than_the_cap_and_never_longer_than_the_machine_can():
    for volume in (60, 600, 4000):
        out, haze = run(FOGGER, volume, max_fog=0.5)
        assert haze.max() <= 0.5 + 0.12  # a burst may overshoot a little, never run away
        for a, b in bursts(out):
            assert b - a <= FOGGER.max_burst_s + 1e-6
        gaps = [b2[0] - b1[1] for b1, b2 in zip(bursts(out), bursts(out)[1:])]
        assert all(g >= fog.MIN_GAP_S - 1e-6 for g in gaps)


def test_bursts_start_on_the_beat_and_the_drop_blast_on_its_downbeat():
    out, _ = run(FOGGER, 600)
    starts = [a for a, _ in bursts(out)]
    assert starts
    for s in starts:
        assert np.min(np.abs(BEATS - s)) <= 1 / fog.FOG_FPS + 1e-6, s
    for start, _, level in PHRASES:
        if level == "burst":
            assert any(abs(s - start) <= 1 / fog.FOG_FPS + 1e-6 for s in starts), start


def test_quiet_at_the_edges():
    out, _ = run(FOGGER, 600)
    first = int((PHRASES[0][1] - fog.SPREAD_S - 1) * fog.FOG_FPS)
    assert not out[:first].any()  # the intro stays clear
    assert not out[int((PHRASES[-1][0] + 1) * fog.FOG_FPS) :].any()  # and the outro lets it clear


def test_a_hazer_runs_steadily():
    out, haze = run(fog.Machine("h", 60, True, 600, 0), 600)
    on = out > 0
    assert on.sum() / fog.FOG_FPS > 60  # most of the time…
    assert len(bursts(out)) <= 3  # … in long stretches, not bursts
    assert haze.max() <= fog.DEFAULT_MAX_FOG + 0.05


def test_room_volume_from_the_stage():
    assert fog.room_volume({"room_volume_m3": 900}) == 900
    assert fog.room_volume({"width_m": 6, "room_depth_m": 6, "ceiling_m": 4.5}) == pytest.approx(10 * 9 * 4.5)
    # the hall's width when the rig gives it (never narrower than the stage)
    assert fog.room_volume({"width_m": 4, "room_width_m": 20, "room_depth_m": 6, "ceiling_m": 4}) == pytest.approx(20 * 9 * 4)
    assert fog.room_volume({"width_m": 6, "room_width_m": 3, "room_depth_m": 6, "ceiling_m": 4}) == pytest.approx(6 * 9 * 4)


def test_the_rules_director_fogs_in_arcs():
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(fog=True), verbose=False)
    levels = [d.fog for d in plan]
    assert levels[0] == "none" and levels[-1] == "none"
    assert levels.count("burst") >= 1 and all(d.section == "drop" for d in plan if d.fog == "burst")
    assert all(d.fog == "none" for d in direct(a, RuleDirector(), verbose=False))  # no machine, no fog


SMOKE = {
    "manufacturer": "Test",
    "model": "Fogger 1500",
    "kind": "smoke",
    "physical": {"watts": 1500, "fog": {"type": "fog"}},
    "modes": {
        "3ch": [{"attr": "fog", "on_from": 128}, {"attr": "fog_fan", "default": 0}, {"attr": "timer", "default": 0}]
    },
}


def test_a_smoke_machine_in_a_show(monkeypatch, tmp_path):
    lib = tmp_path / "fixtures"
    lib.mkdir()
    for p in fxlib.LIB_DIR.glob("*/*.json"):
        (lib / p.parent.name).mkdir(exist_ok=True)
        (lib / p.parent.name / p.name).write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    (lib / "test").mkdir()
    (lib / "test" / "fogger.json").write_text(json.dumps(SMOKE), encoding="utf-8")
    monkeypatch.setattr(fxlib, "LIB_DIR", lib)
    monkeypatch.setattr(motion, "TRAJ_CACHE", tmp_path / "traj")
    fxlib.library.cache_clear()
    try:
        rig = json.loads((fxlib.paths.ROOT / "tests" / "sets" / "small.json").read_text(encoding="utf-8"))
        used = max(f["address"] + fxlib.footprint(f) for f in rig["fixtures"])
        rig["fixtures"].append(
            {"id": "fog1", "fixture": "test/fogger", "mode": "3ch", "universe": 1, "address": used, "x": 0.95}
        )
        rig = load_rig_dict(rig)
        assert has_smoke(rig)
        a = synthetic_analysis()
        plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), fog=True), verbose=False)
        eng = Engine(a, plan, rig)
        values = []
        for k in range(int(a.duration * 10)):
            _, states = eng.render(k / 10)
            buf = eng.dmx(states)[1]
            values.append((buf[used - 1], buf[used + 1]))
        out = np.array(values)
        assert out[:, 1].max() == 0  # its timer is never touched
        fired = out[:, 0][out[:, 0] > 0]
        assert len(fired) and fired.min() >= 128  # fires above where the pump starts
        intro = int((a.phrases[0].end - fog.SPREAD_S - 1) * 10)
        assert not out[:intro, 0].any()
        assert SHAPE[0][0] == "intro"
    finally:
        fxlib.library.cache_clear()
