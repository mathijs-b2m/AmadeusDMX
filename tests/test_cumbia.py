"""Cumbia: heard by its sound, danced as two voices on the beat and its "and", in all the fiesta's colours, the heads
dancing the basic step."""

from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import cumbia, genre
from amadeus.director import RuleDirector, direct
from amadeus.director.style import STYLES, SetGenre, style_for
from amadeus.director.vocabulary import PALETTES
from amadeus.engine import Engine
from amadeus.engine.motion import SWAY_SPOTS
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis
from tests.test_flicker import FPS, fast_cycles

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
COLEGIALA = {"cumbia": 1.01, "cumbia_lead": 0.6}  # measured: Rodolfo Aicardi's classic
VILLERA = {"cumbia": 0.25, "cumbia_lead": 0.36}  # Yerba Brava, the faintest cumbia measured
TROPICAL_POP = {"cumbia": 0.17, "cumbia_lead": 0.11}  # Max Pizzolante, the nearest miss
REGGAETON = {"cumbia": 0.01, "cumbia_lead": 0.0}


def _facts(sound: dict, bpm: float = 95.0, **more) -> dict:
    return {**genre.facts(synthetic_analysis(bpm=bpm)), **sound, **more}


def test_judge_counts_the_family_against_its_rivals():
    names = [*cumbia.FAMILY, *cumbia.RIVALS]
    styles = np.zeros((4, len(names)))
    styles[:3, names.index("Latin---Cumbia")] = 0.8
    styles[3, names.index("Latin---Vallenato")] = 0.8
    assert cumbia.judge(styles, names) == {"cumbia": 0.6, "cumbia_lead": 0.75}


def test_the_sound_calls_cumbia_sung_or_not():
    assert genre.from_audio(_facts(COLEGIALA, song=True)) == "cumbia"  # (the form made it pop)
    assert genre.from_audio(_facts(VILLERA)) == "cumbia"  # (its tempo made it hip-hop)
    assert genre.from_audio(_facts(VILLERA, bpm=174.0)) == "cumbia"  # (its 8ths counted as the beat)
    assert genre.from_audio(_facts(TROPICAL_POP)) != "cumbia"
    assert genre.from_audio(_facts(REGGAETON)) != "cumbia"
    assert genre.from_audio(_facts(COLEGIALA, bpm=60.0)) != "cumbia"  # (no cumbia is this slow)


def test_a_latin_call_that_sounds_a_little_like_cumbia_is_cumbia():
    assert genre._kind_of("latin", _facts({"cumbia": 0.14, "cumbia_lead": 0.25})) == "cumbia"
    assert genre._kind_of("latin", _facts(TROPICAL_POP)) == "latin"
    assert genre._kind_of("pop", _facts(COLEGIALA)) == "pop"  # (not a Latin word: the model knows better)


def test_tags_and_the_models_choices():
    assert genre.from_tag({"genre": "Cumbia"}) == "cumbia"
    assert genre.from_tag({"genre": "Cumbia Sonidera"}) == "cumbia"
    assert genre.from_tag({"genre": "Salsa"}) == "latin"
    assert "cumbia" in genre.GENRES and "cumbia" not in genre.GENRES["latin"]


def test_a_track_heard_as_cumbia_keeps_its_style_in_a_set():
    s = SetGenre()
    assert s.genre_for("a", "techno", "audio") == "techno"
    assert s.genre_for("b", "cumbia", "sound") == "cumbia"


def test_the_fiesta_has_its_colours():
    style = STYLES["cumbia"]
    assert style.palettes[0] == "fiesta" and len(PALETTES["fiesta"][1]) >= 6
    assert style.beat == "cumbia"


def _track():
    """A cumbia: 95 BPM, the bass on the beat, the güiro on every 8th, the llamador's hits on half of the "ands"
    (the detector misses the rest)."""
    a = synthetic_analysis(bpm=95.0)
    beat = 60 / 95.0
    ands = a.beats + beat / 2
    heard = ands[::2]
    a.onsets["hat"] = (heard, np.full(len(heard), 0.8, np.float32))
    a.onsets["snare"] = (np.zeros(0), np.zeros(0, np.float32))
    a.style = "cumbia"
    return a


@pytest.fixture(scope="module")
def track():
    return _track()


def test_the_swing_plays_every_beat_and_every_and(track):
    a = track
    bt, _, ct, _ = cumbia.voices(a)
    body = a.phrases[1]  # a groove
    beats = a.beats[(a.beats >= body.start) & (a.beats < body.end - 1)]
    near = lambda x, ts: np.min(np.abs(ts - x)) < 0.02  # noqa: E731
    assert all(near(x, bt) for x in beats)  # the boom on every beat …
    assert all(near(x + 0.5 * 60 / 95.0, ct) for x in beats)  # … the cha on every "and", heard or not


def _plan(a, rig, style):
    director = RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")), style_for(style))
    return direct(a, director, verbose=False)


def _trace(e, rig, a, t0, t1):
    ids = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    frames = [e.render(float(t))[1] for t in np.arange(t0, t1, 1 / FPS)]
    return ids, frames


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_cumbia_dances_two_voices_in_many_colours(track, path):
    a, rig = track, load_rig(path)
    plans = {s: _plan(a, rig, s) for s in ("latin", "cumbia")}
    plan = plans["cumbia"]
    body = [d for d in plan if d.section in ("groove", "verse", "chorus", "drop") and d.par_accent != "none"]
    assert body and all(d.trigger == "cumbia" for d in body)
    engines = {s: Engine(a, p, rig) for s, p in plans.items()}
    traces = {s: _trace(e, rig, a, 0.1, a.duration - 0.1) for s, e in engines.items()}

    def flicker(s):
        ids, frames = traces[s]
        tr = np.array([[max(st[i].dimmer, st[i].white) for i in ids] for st in frames])
        return sum(fast_cycles(c) for c in tr.T)

    def colours(s):  # the colours lit at once, on average
        ids, frames = traces[s]
        return np.mean([len({(round(st[i].r, 1), round(st[i].g, 1), round(st[i].b, 1)) for i in ids
                             if st[i].dimmer > 0.4}) for st in frames])  # fmt: skip

    assert flicker("cumbia") <= flicker("latin")  # dancing on every 8th, and still no flicker
    lights = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    if len(lights) < 4:
        return
    assert colours("cumbia") > colours("latin")  # the fiesta: more colours at once
    e = engines["cumbia"]
    d = max(body, key=lambda d: d.end - d.start)
    voices = {i: e._voice(d, i) for i in lights}
    assert set(voices.values()) == {"boom", "tac"}
    boom = [i for i in lights if voices[i] == "boom"]
    cha = [i for i in lights if voices[i] == "tac"]
    bt, ct = e.dance_boom[0], e.dance_cha[0]
    bt, ct = bt[(bt > d.start + 1) & (bt < d.end - 1)], ct[(ct > d.start + 1) & (ct < d.end - 1)]

    def at(ids, times):  # the lights' level just after these hits
        return np.mean([np.mean([e.render(float(x) + 0.1)[1][i].dimmer for i in ids]) for x in times[:24]])

    assert at(boom, bt) > 2 * at(boom, ct)  # the boom lights dance on the beat …
    assert at(cha, ct) > 2 * at(cha, bt)  # … the cha lights on its "and": call and response


def test_a_light_changes_colour_as_it_hits_never_while_it_glows(track):
    a, rig = track, load_rig(SETS[0])
    e = Engine(a, _plan(a, rig, "cumbia"), rig)
    d = max((d for d in e.plan if d.trigger == "cumbia"), key=lambda d: d.end - d.start)
    ids, frames = _trace(e, rig, a, d.start + 0.5, d.end - 0.5)
    hits = np.sort(np.concatenate([e.dance_boom[0], e.dance_cha[0]]))
    ts = np.arange(d.start + 0.5, d.end - 0.5, 1 / FPS)[: len(frames)]
    changes = 0
    for k in range(1, len(frames)):
        for i in ids:
            p, s = frames[k - 1][i], frames[k][i]
            if s.dimmer > 0.3 and abs(p.r - s.r) + abs(p.g - s.g) + abs(p.b - s.b) > 0.3:  # lit in a new colour
                changes += 1
                assert np.min(np.abs(hits - ts[k])) < 0.06, (i, ts[k])  # … as it hits
                assert p.dimmer < s.dimmer, (i, ts[k])  # (never while it glows or lets go)
    assert changes  # (and the colours do change)


def test_the_sway_dances_the_basic_step_landing_on_the_beat(track):
    a, rig = track, load_rig(SETS[0])
    e = Engine(a, _plan(a, rig, "cumbia"), rig)
    e._reach_uv, e.move_beats[0], e.move_travel[0] = (1.0, 1.0), (1, 1), (0.5, 0.5)
    spots = [e._shape("sway", k + 0.4, 0) for k in range(5)]  # just after each landing: held there
    want = [(0.75 * u, 0.5 * v) for u, v in SWAY_SPOTS]
    assert np.allclose(spots[:4], want) and np.allclose(spots[4], want[0])
    assert e._shape("sway", 0.4, 0)[1] < 0 < e._shape("sway", 1.4, 0)[1]  # down on the step, up in the middle
