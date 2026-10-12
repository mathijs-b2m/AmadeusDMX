"""Genre and the cinematic program: the genre call, and the program's timing and safety rules."""

import json
from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import genre
from amadeus.audio.hits import Hits
from amadeus.director import direct
from amadeus.director.cinematic import CinematicDirector
from amadeus.engine import Engine
from amadeus.engine import cinematic as C
from amadeus.rig.loader import load_rig, load_rig_dict
from tests.synthetic import synthetic_analysis


def test_a_groove_is_not_cinematic():
    f = genre.facts(synthetic_analysis())
    assert f["groove"] > genre.CINEMATIC_GROOVE
    assert genre.from_audio(f) != "cinematic"


def test_no_groove_and_tonal_is_cinematic():
    f = {"groove": 0.1, "pump_db": 8.0, "bpm": 120.0, "tonal": 0.85, "hat_density": 0.9, "dynamics_db": 14.0}
    assert genre.from_audio(f) == "cinematic"


def test_the_model_may_not_call_a_grooving_track_cinematic(monkeypatch):
    a = synthetic_analysis()
    monkeypatch.setattr(genre, "overrides", lambda: {})
    monkeypatch.setattr(genre, "from_model", lambda artist, title: ("cinematic", 0.99))
    assert genre.detect(a).genre != "cinematic"
    monkeypatch.setattr(genre, "from_model", lambda artist, title: ("techno", 0.95))
    assert genre.detect(a).genre == "techno"


def cinematic_analysis(seed: int = 3):
    """The synthetic track, as a film score: hits at irregular times in eight voices, a few impacts."""
    a = synthetic_analysis()
    rng = np.random.default_rng(seed)
    t = np.sort(rng.uniform(0.5, a.duration - 1, 600))
    t = t[np.r_[True, np.diff(t) > 0.07]]
    n = len(t)
    impact = np.zeros(n, bool)
    impact[rng.choice(n, 12, replace=False)] = True
    a.genre, a.genre_source = "cinematic", "you"
    low = rng.uniform(0, 1, len(a.rms_db)).astype(np.float32)
    a.hits = Hits(t, rng.uniform(0.3, 1.0, n), rng.uniform(0.06, 1.2, n), rng.integers(0, 8, n), impact,
                  rng.uniform(0, 1, n), low, a.fps)  # fmt: skip
    return a


@pytest.fixture(scope="module")
def show():
    a = cinematic_analysis()
    rig = load_rig("tests/sets/concert60.json")  # 60 heads and 10 lasers
    plan = direct(a, CinematicDirector(), verbose=False)
    return a, rig, Engine(a, plan, rig, real_output=False)


def test_the_cinematic_program_runs(show):
    a, rig, e = show
    assert e.program == "cinematic"
    lit = [sum(s.dimmer > 0.3 for s in e.render(float(t))[1].values()) for t in np.arange(0, a.duration, 0.25)]
    assert max(lit) > 0 and np.median(lit) < len(rig["elements"])  # hits light some fixtures, not all


def test_no_fixture_is_hit_faster_than_about_three_times_a_second(show):
    a, _, e = show
    impacts = set(a.hits.t[a.hits.impact].round(6))
    for _, items in e.cine_events.values():
        played = [t0 for t0, *_ in items if round(t0, 6) not in impacts]  # impacts: the whole rig, rate-limited apart
        assert all(b - a_ >= C.RETRIGGER_S - 1e-6 for a_, b in zip(played, played[1:]))


def test_strobes_stay_within_max_flash_hz(show):
    _, rig, e = show
    max_hz = rig["safety"]["max_flash_hz"]
    for eid in e.cine_strobes:
        if eid in e.cine_events:
            times = e.cine_events[eid][0]
            assert np.all(np.diff(times) >= 1 / max_hz - 1e-6)


def test_heads_move_in_the_dark_before_an_impact(show):
    _, _, e = show
    move = float(e.cine_moves[len(e.cine_moves) // 2])
    _, states = e.render(move - C.PRE_IMPACT_S / 2)
    assert all(states[h].dimmer == 0 for h in e.cine_heads)


@pytest.fixture(scope="module")
def mixed():
    """A rig with a few very powerful lights (strobes, halogen sunstrips) among small ones."""
    a = cinematic_analysis(seed=5)
    rig = load_rig("tests/sets/showcase.json")
    plan = direct(a, CinematicDirector(), verbose=False)
    return a, rig, Engine(a, plan, rig, real_output=False)


def test_the_powerful_lights_are_found(mixed):
    _, _, e = mixed
    assert e.cine_power["strobe1"] == 1.0 and e.cine_power["sunstrip1.1"] > C.SMALL
    assert e.cine_power["pixbar1.1"] < C.SMALL and e.cine_power["sharpy1"] < C.SMALL


def test_the_powerful_lights_leave_the_small_hits_to_the_small_ones(mixed):
    a, _, e = mixed
    weak = {round(float(t), 6) for t, s in zip(a.hits.t, a.hits.strength) if s < C.BIG_HIT}
    for eid, (_, items) in e.cine_events.items():
        if e.cine_power.get(eid, 0) >= C.SMALL:
            assert not any(round(t0, 6) in weak and not imp for t0, *_, imp in items)


def test_the_powerful_lights_step_down_for_accents(mixed):
    _, _, e = mixed
    big = next(eid for eid, p in e.cine_power.items() if p >= C.SMALL and e.cine_power[eid] < 1.0)
    down, up = int(np.argmax(e.cine_room)), int(np.argmin(e.cine_room))
    assert e.cine_room[down] == 1.0 and e.cine_room[up] == 0.0
    held = (1.0, 1.0, 1.0)
    for k, want in ((up, 1.0), (down, 1 - C.DUCK_DEPTH * e.cine_power[big])):
        t = k / C.GRID_HZ
        e.cine_events[big] = (np.array([t - 0.3]), [(t - 0.3, 1.0, 10.0, 0.0, held, False)])
        assert e.render(t)[1][big].dimmer == pytest.approx(want, abs=0.02)  # a step down, never to black


def test_a_hit_is_held_and_let_go_gently(show):
    _, _, e = show
    for eid, (_, items) in e.cine_events.items():
        if eid in e.cine_floor:
            continue  # (the floor glows under the low end too)

        def at(t, eid=eid):
            return e.render(t)[1][eid].dimmer

        for k, (t0, level, hold, release, _, impact) in enumerate(items[:-1]):
            end = t0 + hold + release
            if impact or items[k + 1][0] < end + 0.05 or at(t0 + 0.01) == 0 or e._fill_at(end) > 0:
                continue
            assert level in C.LEVELS and hold >= min(C.HOLD_S.values()) and release > 0
            assert at(t0 + 0.01) == at(t0 + hold - 0.01)  # hit at once and held, not decaying
            mid = at(t0 + hold + release / 2)
            assert 0.3 * at(t0 + 0.01) < mid < 0.7 * at(t0 + 0.01)  # let go gently…
            assert at(end + 0.02) < 0.05  # …all the way
            return
    pytest.fail("no hit to look at")


def test_the_score_gives_each_voice_its_sections(mixed):
    _, _, e = mixed
    loud = max(e.cine_score, key=lambda sc: sc["rank"])
    leads = {loud["parts"][r][0] for r in C.ROLES}
    assert len(leads) >= 3  # different sections play different voices
    assert any(loud["parts"][r][1] is not None for r in C.ROLES)  # and the big moments get answers
    quiet = min(e.cine_score, key=lambda sc: sc["rank"])
    assert all(quiet["parts"][r][1] is None for r in ("mid", "tick"))  # chamber music
    assert len({tuple(sc["parts"]["cymbal"][:2]) for sc in e.cine_score}) > 1  # parts move round


def test_a_loud_passage_without_hits_plays_the_melody():
    a = cinematic_analysis(seed=7)
    keep = (a.hits.t < 10) | (a.hits.t > 20)  # ten seconds of sustained music, no hits
    h = a.hits
    a.hits = Hits(
        h.t[keep], h.strength[keep], h.decay[keep], h.voice[keep], h.impact[keep], h.pitch[keep], h.low, h.fps
    )
    for x in a.bands_db.values():  # loud all through
        x[int(10 * a.fps) : int(20 * a.fps)] = x.max()
    notes = np.arange(10.0, 20.0, 0.25)
    a.synth_notes = (notes, np.full(len(notes), 0.8), (np.sin(notes) + 1) / 2)
    e = Engine(
        a, direct(a, CinematicDirector(), verbose=False), load_rig("tests/sets/showcase.json"), real_output=False
    )
    assert e._fill_at(15.0) == 1.0
    i, _ = e.decision_at(15.0)
    sec = e.cine_sections[e.cine_score[i]["melody"]]
    ids = [eid for u in sec["units"] for eid in u]
    frames = [e.render(float(t))[1] for t in np.arange(13.0, 17.0, 0.1)]
    lit = [frozenset(eid for eid in ids if s[eid].dimmer > 0.2) for s in frames]
    assert np.mean([bool(x) for x in lit]) > 0.8  # (heads go dark a moment to move to a new picture)
    assert len(set(lit)) > 3  # the melody steps over its section


@pytest.mark.parametrize("name", ["concert60", "fuze24", "small", "showcase"])
def test_any_rig_gets_an_orchestra(name):
    """Nothing is made for one rig: uniform rigs are split by position, tiny ones still play every voice."""
    a = cinematic_analysis(seed=11)
    e = Engine(a, direct(a, CinematicDirector(), verbose=False), load_rig(f"tests/sets/{name}.json"), real_output=False)
    assert len(e.cine_sections) >= 2
    assert all(sc["parts"][r][0] is not None for sc in e.cine_score for r in C.ROLES)
    lit = [sum(s.dimmer > 0.2 for s in e.render(float(t))[1].values()) for t in np.arange(0, a.duration, 0.5)]
    assert max(lit) > 0


def test_a_rig_of_only_lasers_still_plays_the_impacts():
    rig = json.loads(Path("tests/sets/fuze24.json").read_text())
    rig["fixtures"] = [f for f in rig["fixtures"] if "laser" in f["fixture"]]
    a = cinematic_analysis(seed=11)
    e = Engine(a, direct(a, CinematicDirector(), verbose=False), load_rig_dict(rig), real_output=False)
    t = float(a.hits.t[a.hits.impact][0])
    assert any(s.fx == "fan" for s in e.render(t + 0.05)[1].values())
