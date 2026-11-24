"""The lightshow program: switched on by hand, it plays the band (every kick and snare of the drummer, the
guitar's notes), it builds up with light from the first note, the groups take turns and the whole rig is kept for
the climaxes, every voice keeps its own section, it is brighter than the cinematic program, and the flash limits
still hold."""

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
    assert got[0] == 3  # half of the rig starts: a build-up with light
    # a third of the rig at a time (after a breakdown the ones that played before come back at once)
    assert all(got[k] <= max(got[:k]) + 2 for k in range(1, len(got)))
    assert max(got) > got[0]
    r = D.ranks(a)
    for k, rank in zip(got, r):
        assert k >= 3  # a quiet part thins out, never under half
        assert k < n or rank >= D.CLIMAX  # the whole rig is kept for the climaxes
    assert D.layers(a, 1) == [1] * len(a.phrases) and min(D.layers(a, 2)) == 2


def test_the_build_reaches_everything_at_a_long_climax():
    a = rock()
    loud = [10, 20, 40, 60, 70, 80, 90, 95, 99, 99, 99, 99]
    a.phrases = [a.phrases[0].__class__(**{**a.phrases[0].__dict__, "loudness_pct": v}) for v in loud]
    got = D.layers(a, 5)
    assert got[-1] == 5 and got[0] == 3
    b = D.builds(a)
    assert b[0] < 0.2 and b[-1] == 1 and np.all(np.diff(b) >= 0)  # how far the song has built: it never falls


def test_a_phrase_starts_with_half_and_adds_layers():
    assert D.passages(6, 4, climax=False, opens=False) == [3, 4, 5, 6]
    assert D.passages(1, 3, climax=False, opens=False) == [1, 1, 1]
    assert D.passages(5, 1, climax=False, opens=False) == [3]
    assert D.passages(6, 1, climax=True, opens=False) == [6]
    assert D.passages(6, 4, climax=True, opens=True) == [6, 5, 5, 6]  # a drop hits with everything, then thins out
    assert D.passages(6, 4, climax=True, opens=False) == [4, 5, 5, 6]  # a climax keeps most of it


def varied(a, rig):
    return Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_the_groups_take_turns(path):
    a = rock()
    e = varied(a, load_rig(path))
    if len(e.cine_sections) < 2:
        pytest.skip("nothing to vary")
    lineups = [frozenset(s["active"]) for s in e.ls_scores]
    if e.ls_all_in:  # a handful of lights: nobody sits out, the families swap instruments instead
        assert len(set(lineups)) == 1
        assert len({(tuple(s["kick"]), tuple(s["snare"])) for s in e.ls_scores if not s["climax"]}) >= 2
        return
    assert len(set(lineups)) >= 3
    ts = np.arange(0, a.duration, 0.25)
    full = np.mean([e._score_at(float(t), e.decision_at(float(t))[0])["full"] for t in ts])
    assert 0 < full < 0.5  # the whole rig at the climaxes only


def test_a_layer_adds_to_the_line_up_and_a_turn_keeps_some_of_it(show):
    _, _, e = show
    scores = e.ls_scores
    layered = turned = 0
    for x, y in zip(scores, scores[1:]):
        a_, b_ = set(x["active"]), set(y["active"])
        if len(b_) > len(a_) and x["build"] == y["build"]:
            assert a_ < b_  # (within a phrase) nobody leaves when a layer joins
            layered += 1
        elif a_ != b_ and len(a_) > 1 and len(b_) > 1:
            assert a_ & b_  # some stay, the others take over
            turned += 1
    assert layered and turned


def test_who_is_not_in_the_line_up_stays_dark(show):
    a, _, e = show
    impacts = a.hits.t[a.hits.impact]
    for q, score in enumerate(e.ls_scores[:-1]):
        if score["full"]:
            continue
        t = e.ls_times[q + 1] - 0.1  # (the glow of the line-up before has long gone)
        if e.ls_times[q + 1] - e.ls_times[q] < 3 or (len(impacts) and np.min(np.abs(impacts - t)) < 1.5):
            continue
        states = e.render(float(t))[1]
        for si, sec in enumerate(e.cine_sections):
            if si not in score["active"]:
                assert all(states[eid].dimmer < 0.05 for u in sec["units"] for eid in u), sec["name"]


def test_a_rig_of_one_model_gets_groups_to_vary():
    rig = load_rig("tests/sets/concert60.json")
    e = varied(rock(), rig)
    assert len(e.cine_sections) == 3
    ids = [eid for s in e.cine_sections for u in s["units"] for eid in u]
    assert len(ids) == len(set(ids)) == sum(el["kind"] == "head" for el in rig["elements"])  # every light, once
    spans = [
        [el["x"] for el in rig["elements"] if el["id"] in {i for u in s["units"] for i in u}] for s in e.cine_sections
    ]
    assert all(np.ptp(x) > 0.5 * np.ptp(sum(spans, [])) for x in spans)  # each group across the whole rig


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_every_rig_plays_it(path):
    a = rock()
    rig = load_rig(path)
    e = Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)
    assert e.program == "lightshow"
    lit = [sum(s.dimmer > 0.05 for s in e.render(float(t))[1].values()) for t in np.arange(0, a.duration, 0.5)]
    assert max(lit) > 0


def test_every_family_plays_an_instrument_and_keeps_it(show):
    _, _, e = show
    seated = sorted(s for fams in e.ls_seats.values() for s in fams)
    assert seated == list(range(len(e.cine_sections)))  # every family has an instrument, one each
    for role, fams in e.ls_seats.items():
        for sc in e.cine_score:
            joined = [s for s in fams if s in sc["active"]]
            if joined:
                assert [s for s, _ in sc["parts"][role]] == joined


def test_a_family_is_every_fixture_of_a_model(show):
    _, rig, e = show
    models = {
        f["fixture"]
        for f in rig["fixtures"]
        if any(
            el["fixture"] == f["id"] and el["kind"] not in ("laser", "strobe", "smoke", "inert")
            for el in rig["elements"]
        )
    }
    assert len(e.cine_sections) == len(models)
    assert all(len(s["units"]) <= 8 for s in e.cine_sections)


def test_only_sections_that_have_joined_play(show):
    a, _, e = show
    first = e.cine_score[0]["active"]
    assert 2 <= len(first) < len(e.cine_sections)  # half of the rig starts
    playing = {eid for si in first for u in e.cine_sections[si]["units"] for eid in u}
    end = e.plan[0].end
    for eid, (_, items) in e.cine_events.items():
        early = [it for it in items if it[0] < end and not it[5]]
        if early:
            assert eid in playing


def test_no_fixture_is_hit_faster_than_the_flash_limit(show):
    a, rig, e = show
    impacts = set(a.hits.t[a.hits.impact].round(6))
    gap = min(C.RETRIGGER_S, 1 / rig["safety"]["max_flash_hz"])  # (the Lightshow hits as often as the set allows)
    for _, items in e.cine_events.values():
        played = [t0 for t0, *_ in items if round(t0, 6) not in impacts]
        assert all(b - x >= gap - 1e-6 for x, b in zip(played, played[1:]))


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
    fastest = 1 / rig["safety"]["max_flash_hz"] - 0.01  # it flashes on purpose, as often as the set allows …
    for eid in frames[0]:  # … but no light chops along with the music
        x = np.array([f[eid].dimmer for f in frames])
        assert fast_cycles(x, fastest_s=fastest) <= 0.03 * a.duration, eid


@pytest.mark.parametrize("name", ["showcase", "concert60"])
def test_no_fixture_flashes_faster_than_the_set_allows(name):
    a = rock()
    rig = load_rig(f"tests/sets/{name}.json")
    e = Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)
    gap = 1 / rig["safety"]["max_flash_hz"] - 1e-6
    for eid, (_, items) in e.cine_events.items():
        played = sorted({round(float(t0), 6) for t0, *_ in items})
        assert all(b - x >= gap for x, b in zip(played, played[1:])), eid


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
    assert arc.plan_shape() == (2, 1, True, False, 2)  # the plan as the director made it (at the default level)
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


def test_switching_the_lightshow_off_goes_back_to_the_rules_at_once(monkeypatch):
    from amadeus import pipeline
    from amadeus.show import tracks

    calls = []

    def plan(file, director, redo, **kw):
        calls.append(director)
        if director == "openai":
            raise RuntimeError("no key")  # the model fails: the rules' show must already play
        return "a", [director]

    monkeypatch.setattr(pipeline, "get_plan", plan)
    shows = tracks.TrackShows(load_rig("tests/sets/small.json"), "openai", Path("."))
    monkeypatch.setattr(shows, "_install", lambda f, a, p, d: shows.shows.__setitem__(f, (a, p, None, d)))
    shows.shows[__file__] = ("a", ["lightshow"], None, "lightshow")
    shows._build(__file__, first=False)
    assert calls[0] == "rules" and shows.shows[__file__][3] == "rules"


def test_hits_land_on_the_analysis_onsets():
    from amadeus.audio import hits

    t = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    n = len(t)
    h = hits.Hits(
        t - 0.07,
        np.ones(n),
        np.full(n, 0.2),
        np.zeros(n, int),
        np.zeros(n, bool),
        np.zeros(n),
        np.zeros(10, np.float32),
        46.875,
    )  # fmt: skip  (found 70 ms early, as a sharp kick is)
    onsets = {"kick": (t[:-1], np.ones(n - 1))}  # the last one has no onset of its own
    got = hits.aligned(h, onsets).t
    assert np.allclose(got[:-1], t[:-1])  # on the onset
    assert abs(got[-1] - t[-1]) < 1e-6  # moved by the others' offset


def test_strobe_free_keeps_the_strobes_dark(show):
    a = rock()
    rig = load_rig("tests/sets/showcase.json")
    rig["safety"]["strobe_free"] = True
    e = Engine(a, direct(a, LightshowDirector(), verbose=False), rig, real_output=False)
    assert e.cine_strobes
    for t in np.arange(0, a.duration, 0.05):
        states = e.render(float(t))[1]
        assert all(states[s].dimmer == 0 for s in e.cine_strobes)


def played_at(e, t: float, tol: float = 1e-6) -> list[tuple]:
    """The events on the show's lights at this time."""
    out = []
    for eid, (times, items) in e.cine_events.items():
        if eid in e.cine_strobes or eid in e.cine_lasers:
            continue
        k = int(np.searchsorted(times, t - tol))
        if k < len(times) and abs(times[k] - t) <= tol:
            out.append((eid, *items[k]))
    return out


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_the_drummer_leads(path):
    """Every kick and snare is a hit of whole families at full level, wherever the song is."""
    a = rock()
    e = varied(a, load_rig(path))
    if not e.cine_sections:
        pytest.skip("no lights to play them")
    kit = e.ls_kit
    assert len(kit.kick_t) > 20 and len(kit.snare_t) > 20
    for name, ts in (("kick", kit.kick_t), ("snare", kit.snare_t)):
        got = [played_at(e, float(t)) for t in ts]
        assert np.mean([bool(g) for g in got]) >= 0.95, name
        for t, g in zip(ts, got):
            if not g or any(ev[-1] for ev in g):
                continue  # (an impact took it)
            score = e._score_at(float(t), e.decision_at(float(t))[0])
            side = {eid for si in score[name] for u in e.cine_sections[si]["units"] for eid in u}
            assert len({ev[0] for ev in g} & side) >= 0.5 * len(side), (name, t)  # its side of the line-up
            assert max(ev[2] for ev in g) >= 0.85


def test_the_guitar_runs_over_the_rig():
    """The separated melodic part's notes are played one by one, by the families that play the guitar."""
    a = rock()
    t = np.arange(4.0, 30.0, 0.115)  # a riff of sixteenths
    a.synth_notes = (t, np.full(len(t), 0.4), (np.arange(len(t)) % 7) / 6)
    e = varied(a, load_rig("tests/sets/showcase.json"))
    drums = np.sort(np.concatenate([e.ls_kit.kick_t, e.ls_kit.snare_t, a.hits.t[a.hits.impact]]))
    alone = [x for x in t if np.min(np.abs(drums - x)) > 0.06]
    got = [played_at(e, float(x)) for x in alone]
    assert np.mean([bool(g) for g in got]) >= 0.9
    lights = [frozenset(ev[0] for ev in g) for g in got if g]
    assert len(set(lights)) >= 6  # a run: block by block, not one light


def test_a_hit_has_let_go_before_the_next_one(show):
    _, _, e = show
    for eid, (times, items) in e.cine_events.items():
        if eid in e.cine_strobes or eid in e.cine_lasers:
            continue
        for (t0, _, hold, fade, *_), t1 in zip(items, times[1:]):
            assert t0 + hold + fade <= t1 - 0.05 or t1 - t0 < 0.2, eid


def test_a_small_rig_plays_with_all_of_it_from_the_first_note():
    a = rock()
    e = varied(a, load_rig("tests/sets/small.json"))
    assert e.ls_all_in
    n = len(e.cine_sections)
    assert all(len(s["active"]) == n for s in e.ls_scores)
    big = varied(a, load_rig("tests/sets/showcase.json"))
    mid = varied(a, load_rig("tests/sets/fuze24.json"))
    assert e.ls_share == 1.0 > mid.ls_share > big.ls_share == 0.4  # the bigger the rig, the more can sit out
    assert not big.ls_all_in
    lights = sum(len(s["units"]) for s in big.cine_sections)
    for sc in big.ls_scores:
        assert sum(len(big.cine_sections[si]["units"]) for si in sc["active"]) >= 0.4 * lights
    showing = {eid for s in e.cine_sections for u in s["units"] for eid in u}
    end = e.plan[0].end
    early = {eid for eid, (times, _) in e.cine_events.items() if np.any(times < end)}
    assert showing <= early


def test_a_climax_arrives_on_an_impact(show):
    a, _, e = show
    r = e.ls_ranks
    opens = [d.start for i, d in enumerate(e.plan) if r[i] >= D.CLIMAX and i and r[i - 1] < D.CLIMAX]
    assert opens
    for t in opens:
        near = [ev for eid, (times, items) in e.cine_events.items() for ev in items if abs(ev[0] - t) <= 0.5 and ev[5]]
        assert near, t


def test_the_heads_change_pictures_on_the_kick(show):
    a, _, e = show
    kicks = np.asarray(e.ls_kit.kick_t, float)
    off = np.array([np.min(np.abs(kicks - m)) for m in e.cine_moves])
    assert np.mean(off < 0.02) > 0.5


def test_the_heads_sway_faster_and_wider_as_it_gets_louder(show):
    _, _, e = show
    r = e.ls_ranks
    quiet, loud = int(np.argmin(r)), int(np.argmax(r))

    def mid(i):
        return int((e.plan[i].start + e.plan[i].end) / 2 * C.GRID_HZ)

    assert e.ls_sway_amp[mid(loud)] > e.ls_sway_amp[mid(quiet)]
    rate = np.diff(e.ls_sway_turns)
    assert rate[mid(loud)] > rate[mid(quiet)]
