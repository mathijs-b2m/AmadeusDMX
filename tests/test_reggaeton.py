"""Reggaeton: told apart by the dembow, the snare's 3+3+2 every two beats."""

from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import dembow, genre
from amadeus.director import RuleDirector, direct
from amadeus.director.style import style_for
from amadeus.engine import Engine
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis
from tests.test_flicker import FPS, fast_cycles


def with_snare(a, sixteenths: list[int], jitter: float = 0.004, seed: int = 1):
    """`a` with its snare on these 16ths of every two beats (0..7), a little loose like a played beat."""
    rng = np.random.default_rng(seed)
    cells = a.beats[::2]
    t = np.sort(np.concatenate([c0 + (c1 - c0) * np.array(sixteenths) / 8 for c0, c1 in zip(cells, cells[1:])]))
    t = t + rng.normal(0, jitter, len(t))
    a.onsets["snare"] = (t, np.full(len(t), 0.8))
    return a


def test_the_dembow_is_reggaeton():
    a = with_snare(synthetic_analysis(bpm=92.0), [3, 6])  # dembow: the 16th before beat 2, and its "and"
    f = genre.facts(a)
    assert f["dembow"] > genre.DEMBOW
    assert genre.from_audio(f) == "reggaeton"
    assert genre.from_audio({**f, "song": True}) == "reggaeton"  # sung and slow: still not hip-hop


def test_a_backbeat_is_not_reggaeton():
    for slots in ([4], [0, 4], [2, 6], [0, 1, 2, 3, 4, 5, 6, 7]):  # backbeat, every beat, offbeats, busy 16ths
        a = with_snare(synthetic_analysis(bpm=92.0), slots)
        assert genre.dembow(a) <= genre.DEMBOW, slots
        assert genre.from_audio(genre.facts(a)) != "reggaeton"


def test_the_dembow_counts_on_either_beat():
    a = with_snare(synthetic_analysis(bpm=92.0), [2, 7])  # the dembow, counted from the other beat
    assert genre.dembow(a) > genre.DEMBOW


def test_a_dembow_at_house_tempo_is_not_reggaeton():
    a = with_snare(synthetic_analysis(bpm=140.0), [3, 6])
    assert genre.from_audio(genre.facts(a)) != "reggaeton"


def test_latin_with_a_dembow_is_reggaeton(monkeypatch):
    monkeypatch.setattr(genre, "overrides", lambda: {})
    monkeypatch.setattr(genre, "tags", lambda path: {})
    monkeypatch.setattr(genre, "from_model", lambda artist, title: ("latin", 0.9))
    assert genre.detect(with_snare(synthetic_analysis(bpm=92.0), [3, 6])).genre == "reggaeton"
    assert genre.detect(with_snare(synthetic_analysis(bpm=92.0), [4])).genre == "latin"  # salsa, cumbia …
    monkeypatch.setattr(genre, "from_model", lambda artist, title: ("pop", 0.9))
    assert genre.detect(with_snare(synthetic_analysis(bpm=92.0), [3, 6])).genre == "pop"  # the model knows


def test_tags():
    assert genre.from_tag({"genre": "Reggaeton"}) == "reggaeton"
    assert genre.from_tag({"genre": "Latin Trap"}) == "reggaeton"
    assert genre.from_tag({"genre": "Música Urbano Latino"}) == "reggaeton"
    assert genre.from_tag({"genre": "Dancehall"}) == "latin"
    assert genre.from_tag({"genre": "Salsa"}) == "latin"
    assert genre.from_tag({"genre": "Trap"}) == "hiphop"


SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))


@pytest.fixture(scope="module")
def dembow_track():
    return with_snare(synthetic_analysis(bpm=92.0), [3, 6])


def test_the_tac_is_the_snare_on_its_pattern():
    a2 = with_snare(synthetic_analysis(bpm=92.0), [3, 6])
    t, s = a2.onsets["snare"]
    ghost = t[::7] + 0.1  # ghost notes and fills between the dembow's hits
    a2.onsets["snare"] = (np.sort(np.concatenate([t, ghost])), np.full(len(t) + len(ghost), 0.8))
    tac_t, _ = dembow.tac(a2)
    assert abs(len(tac_t) - len(t)) <= 0.05 * len(t)  # the dembow's hits, without the ghosts
    assert np.min(np.diff(tac_t)) >= dembow.TAC_GAP_BEATS * 60 / 92 - 0.02


def flicker(e: Engine, rig: dict, a) -> int:
    ids = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    ts = np.arange(0.05, a.duration - 0.1, 1 / FPS)
    tr = np.array([[max(st[i].dimmer, st[i].white) for i in ids] for st in (e.render(float(t))[1] for t in ts)])
    return sum(fast_cycles(c) for c in tr.T)


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_reggaeton_plays_boom_tac(dembow_track, path):
    a, rig = dembow_track, load_rig(path)
    plans = {s: direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")), style_for(s)),
                       verbose=False) for s in ("latin", "reggaeton")}  # fmt: skip
    plan = plans["reggaeton"]
    body = [d for d in plan if d.section in ("groove", "verse", "chorus", "drop") and d.par_accent != "none"]
    assert body and all(d.trigger == "dembow" for d in body)
    e = Engine(a, plan, rig)
    # two voices, and still no flicker: no more fast on-off cycles than the same track lit as latin
    assert flicker(Engine(a, plan, rig), rig, a) <= flicker(Engine(a, plans["latin"], rig), rig, a)
    lights = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    if len(lights) < 2:
        return
    voices = {i: e._voice(body[0], i) for i in lights}
    assert set(voices.values()) == {"boom", "tac"}  # both voices play …
    for g in e.groups:  # … by whole groups: a group of heads plays one voice
        assert len({voices[h] for h in g["ids"]}) == 1 or len({g2["cls"] for g2 in e.groups}) == 1
    boom = next(i for i in lights if voices[i] == "boom")
    tac = next(i for i in lights if voices[i] == "tac")
    d = max(body, key=lambda d: d.end - d.start)

    def at(pid, times):  # the light's level just after these hits (once the other voice has let go), in the phrase
        times = times[(times > d.start + 1) & (times < d.end - 1)]
        return np.mean([e.render(float(x) + 0.15)[1][pid].dimmer for x in times])

    kicks = e.boom_t[np.min(np.abs(e.boom_t[:, None] - e.tac_t[None, :]), axis=1) > 0.15]  # kicks alone
    assert at(boom, kicks) > 2 * at(boom, e.tac_t)  # the boom plays the kick …
    assert at(tac, e.tac_t) > 2 * at(tac, kicks)  # … the tac the snare: call and response


def _boom_tac_engine(dembow_track):
    a, rig = dembow_track, load_rig(SETS[0])
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")), style_for("reggaeton")),
                  verbose=False)  # fmt: skip
    e = Engine(a, plan, rig)
    d = max((d for d in plan if d.trigger == "dembow"), key=lambda d: d.end - d.start)
    boom = next(x["id"] for x in rig["elements"] if x["kind"] in ("head", "par") and e._voice(d, x["id"]) == "boom")
    return e, d, boom


def test_a_breather_pauses_and_the_beat_returns_on_every_voice(dembow_track):
    e, d, boom = _boom_tac_engine(dembow_track)
    beats = e.beats[(e.beats > d.start + 4) & (e.beats < d.end - 4)]
    start, end = float(beats[4]), float(beats[6])  # two beats without the beat
    e.boom_t, e.breathers, e._brs = e.boom_t[(e.boom_t < start) | (e.boom_t >= end)], [(start, end)], [start]
    tac_t = e.tac_t
    lit = lambda t: [s.dimmer for k, s in e.render(t)[1].items() if k in e._voices]  # noqa: E731
    assert max(lit(start + 0.3)) < 0.1 and max(lit(end - 0.05)) < 0.1  # the light pauses …
    back = lit(end + 0.05)
    assert min(back) > 0.4  # … and the beat's return hits with every voice, the tac too
    assert not np.any(np.abs(tac_t - end) < 0.05)  # (there's no snare on it)


def test_a_run_of_eighth_kicks_is_played_kick_by_kick(dembow_track):
    e, d, boom = _boom_tac_engine(dembow_track)
    beats = e.beats[(e.beats > d.start + 4) & (e.beats < d.end - 4)]
    run = np.arange(float(beats[4]), float(beats[6]), (beats[1] - beats[0]) / 2)  # four 1/8 kicks
    e.boom_t = np.sort(np.concatenate([e.boom_t[(e.boom_t < run[0] - 0.01) | (e.boom_t > run[-1] + 0.01)], run]))
    e.boom_s = np.full(len(e.boom_t), 0.9, np.float32)
    e.tac_t = e.tac_t[(e.tac_t < run[0] - 0.1) | (e.tac_t > run[-1] + 0.4)]  # (nothing else in the run)
    e.tac_s = np.full(len(e.tac_t), 0.8)
    level = lambda t: e.render(float(t))[1][boom].dimmer  # noqa: E731
    gap = run[1] - run[0]
    for x in run:
        assert level(x + 0.05) > 0.5 and level(x + gap - 0.03) < 0.35  # boom, and let go before the next
