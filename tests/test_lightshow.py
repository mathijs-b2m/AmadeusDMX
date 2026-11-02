"""The lightshow program: switched on by hand, it builds up layer by layer, every voice keeps its own section,
it is brighter than the cinematic program, and the no-flicker rules still hold."""

from pathlib import Path

import numpy as np
import pytest

from amadeus.director import direct
from amadeus.director import lightshow as D
from amadeus.director.cinematic import CinematicDirector
from amadeus.director.lightshow import LightshowDirector
from amadeus.engine import Engine
from amadeus.engine import cinematic as C
from amadeus.engine.engine import program_of
from amadeus.rig.loader import load_rig
from amadeus.show.arc import ShowArc
from tests.test_cinematic import cinematic_analysis
from tests.test_flicker import FPS, fast_cycles

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))


def rock(seed: int = 3):
    """The synthetic track with hits, but not a film score: only the switch makes it a lightshow."""
    a = cinematic_analysis(seed)
    a.genre = "rock"
    return a


@pytest.fixture(scope="module")
def show():
    a = rock()
    rig = load_rig("tests/sets/showcase.json")
    return a, rig, Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)


def test_only_the_lightshow_director_makes_a_lightshow():
    a = rock()
    assert program_of(a, direct(a, LightshowDirector(), verbose=False)) == "lightshow"
    assert program_of(a, direct(a, CinematicDirector(), verbose=False)) == ""  # a rock track: no program by genre
    a.hits = None
    assert program_of(a, direct(a, LightshowDirector(), verbose=False)) == ""  # (no hits: nothing to play)


def test_the_layers_build_up_one_by_one():
    a = rock()
    n = 6
    got = D.layers(a, n)
    assert got[0] == 1  # one section starts alone
    # one new section at a time (after a breakdown the ones that played before come back at once)
    assert all(got[k] <= max(got[:k]) + 1 for k in range(1, len(got)))
    assert max(got) > 1
    r = D.ranks(a)
    for k, rank in zip(got, r):
        assert k <= max(1, 1 + round(rank * (n - 1))) or rank >= D.CLIMAX  # a quiet part thins out


def test_the_build_reaches_everything_at_a_long_climax():
    a = rock()
    loud = [10, 20, 40, 60, 70, 80, 90, 95, 99, 99, 99, 99]
    a.phrases = [a.phrases[0].__class__(**{**a.phrases[0].__dict__, "loudness_pct": v}) for v in loud]
    got = D.layers(a, 5)
    assert got[-1] == 5 and got[0] == 1


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_every_rig_plays_it(path):
    a = rock()
    rig = load_rig(path)
    e = Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)
    assert e.program == "lightshow"
    lit = [sum(s.dimmer > 0.05 for s in e.render(float(t))[1].values()) for t in np.arange(0, a.duration, 0.5)]
    assert max(lit) > 0


def test_every_voice_keeps_its_section_once_it_has_joined(show):
    _, _, e = show
    for role, seat in e.ls_seats.items():
        for sc in e.cine_score:
            if seat in sc["active"]:
                assert sc["parts"][role][0] == seat


def test_only_sections_that_have_joined_play(show):
    a, _, e = show
    first = e.cine_score[0]["active"]
    assert len(first) == 1
    playing = {eid for u in e.cine_sections[first[0]]["units"] for eid in u}
    end = e.plan[0].end
    for eid, (_, items) in e.cine_events.items():
        early = [it for it in items if it[0] < end and not it[5]]
        if early:
            assert eid in playing


def test_no_fixture_is_hit_faster_than_about_three_times_a_second(show):
    a, _, e = show
    impacts = set(a.hits.t[a.hits.impact].round(6))
    for _, items in e.cine_events.values():
        played = [t0 for t0, *_ in items if round(t0, 6) not in impacts]
        assert all(b - x >= C.RETRIGGER_S - 1e-6 for x, b in zip(played, played[1:]))


def test_strobes_stay_within_max_flash_hz(show):
    _, rig, e = show
    max_hz = rig["safety"]["max_flash_hz"]
    for eid in e.cine_strobes:
        if eid in e.cine_events:
            assert np.all(np.diff(e.cine_events[eid][0]) >= 1 / max_hz - 1e-6)


@pytest.mark.parametrize("name", ["showcase", "small", "concert60"])
def test_no_light_flickers(name):
    a = rock()
    rig = load_rig(f"tests/sets/{name}.json")
    e = Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)
    ts = np.arange(0, a.duration, 1 / FPS)
    frames = [e.render(float(t))[1] for t in ts]
    for eid in frames[0]:
        x = np.array([f[eid].dimmer for f in frames])
        assert fast_cycles(x) <= 2, eid


def test_brighter_than_the_cinematic_program():
    a = rock()
    rig = load_rig("tests/sets/showcase.json")
    ls = Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)
    b = rock()
    b.genre = "cinematic"
    cine = Engine(b, direct(b, CinematicDirector(), verbose=False), rig, real_output=False)
    assert cine.program == "cinematic"
    ts = np.arange(a.duration / 2, a.duration, 0.1)  # once it has built up

    def mean(e):
        return np.mean([np.mean([s.dimmer for s in e.render(float(t))[1].values()]) for t in ts])

    assert mean(ls) > 1.1 * mean(cine)


def test_heads_change_pictures_more_often_as_it_builds(show):
    _, _, e = show
    moves = np.asarray(e.cine_moves)
    builds = [sc["build"] for sc in e.cine_score]
    early = [i for i, b in enumerate(builds) if b < 0.5]
    late = [i for i, b in enumerate(builds) if b >= 0.5]
    assert early and late

    def per_s(idx):
        n = sum(((moves >= e.plan[i].start) & (moves < e.plan[i].end)).sum() for i in idx)
        return n / sum(e.plan[i].end - e.plan[i].start for i in idx)

    assert per_s(late) > per_s(early)


def test_the_glow_between_hits_is_dark_in_silence(show):
    a, _, e = show
    quiet = np.flatnonzero(e.breath < 0.05)
    if not len(quiet):
        pytest.skip("no silence in the synthetic track")
    t = float(quiet[len(quiet) // 2] / a.fps)
    for bed in e.ls_beds:
        assert e._at(bed, t) < 0.05


def test_the_switch_on_the_show_arc(tmp_path):
    rig = load_rig("tests/sets/showcase.json")
    arc = ShowArc(rig, path=tmp_path / "arc.json", now=1000.0)
    assert not arc.lightshow and not arc.snapshot(1000.0)["lightshow"]
    arc.control({"type": "arc", "lightshow": True}, now=1000.0)
    assert arc.snapshot(1000.0)["lightshow"]
    assert arc.plan_shape() == (2, 1, True, False)  # the plan as the director made it
    arc.started, arc.seen = 1000.0, 1000.0
    arc.save(1000.0)
    assert ShowArc(rig, path=tmp_path / "arc.json", now=1100.0).lightshow  # an engine restart keeps it…
    assert not ShowArc(rig, path=tmp_path / "arc.json", now=1000.0 + 3 * 3600).lightshow  # …not a new night
    arc.control({"type": "arc", "lightshow": False}, now=1000.0)
    assert not arc.lightshow


def test_the_arc_leaves_a_lightshow_as_it_plays(tmp_path):
    from amadeus.engine import State

    rig = load_rig("tests/sets/showcase.json")
    arc = ShowArc(rig, path=tmp_path / "arc.json", now=1000.0)
    arc.control({"type": "arc", "lightshow": True, "stage": "warmup"}, now=1000.0)
    states = {e["id"]: State(dimmer=0.8, white=0.5) for e in rig["elements"]}
    arc.apply(states, None, 0.0, 0.025)
    assert all(states[eid].dimmer == pytest.approx(0.8) for eid in arc.lights)
    arc.control({"type": "arc", "knob": {"intensity": 0.5}}, now=1000.0)
    arc.apply(states, None, 0.0, 0.025)
    assert all(states[eid].dimmer == pytest.approx(0.4) for eid in arc.lights)


def test_track_shows_switch_to_the_lightshow(monkeypatch):
    from amadeus.show import tracks

    built = []
    shows = tracks.TrackShows(load_rig("tests/sets/small.json"), "rules", Path("."))
    monkeypatch.setattr(shows.pool, "submit", lambda fn, *args: built.append(args))
    shows.shows["x.mp3"] = ("a", [], None, "rules")
    assert shows.wanted() == "rules"
    shows.set_lightshow(True)
    assert shows.wanted() == "lightshow" and built == [("x.mp3", False)]
    shows.set_lightshow(True)  # (no change: nothing rebuilt)
    assert len(built) == 1
    shows.pending.clear()
    shows.set_lightshow(False)
    assert shows.wanted() == "rules" and len(built) == 2
