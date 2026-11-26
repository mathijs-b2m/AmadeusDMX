"""Dubstep: heard by its sound, read by its own form, the growl found pulse by pulse, the half-time kit, and the rig
in layers: the main group on the growl (an LED pulsing within the flash limit, a lamp holding the notes), the
others on the kick and the snare."""

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import drums, dubstep, genre
from amadeus.audio import growl as growllib
from amadeus.director import RuleDirector, direct
from amadeus.director.style import STYLES, SetGenre
from amadeus.engine import Engine
from amadeus.engine import growl as G
from amadeus.library import fixtures as fxlib
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
FIXTURES = Path(__file__).parent.parent / "fixtures"
DUB = STYLES["dubstep"]
SCARY = {"dubstep": 0.54, "dubstep_share": 0.72}  # measured: Scary Monsters and Nice Sprites
COMPLEXTRO = {"dubstep": 0.22, "dubstep_share": 0.39}  # Kill Everybody
FLUME = {"dubstep": 0.16, "dubstep_share": 0.24}  # the nearest other track: a future-bass remix
FPS = 40


def _facts(sound: dict, bpm: float = 140.0, **more) -> dict:
    return {**genre.facts(synthetic_analysis(bpm=bpm)), **sound, **more}


# ---------------------------------------------------------------- the genre


def test_judge_measures_the_mass_and_its_share():
    names = ["Electronic---Dubstep", "Electronic---House"]
    styles = np.array([[0.6, 0.1], [0.3, 0.5], [0.1, 0.8], [0.0, 0.9]])
    assert dubstep.judge(styles, names) == {"dubstep": 0.25, "dubstep_share": 0.5}


def test_the_sound_calls_dubstep_at_any_tempo_however_loosely_it_grooves():
    for bpm in (110.0, 128.0, 140.0, 145.0):
        assert genre.from_audio(_facts(SCARY, bpm=bpm, groove=0.3)) == "dubstep"  # (not cinematic, not house)
    assert genre.from_audio(_facts(COMPLEXTRO, bpm=127.0)) == "dubstep"
    assert genre.from_audio(_facts(FLUME, bpm=150.0)) != "dubstep"


def test_a_club_call_on_a_dubstep_sound_is_dubstep_and_it_keeps_its_style_in_a_set():
    assert genre._kind_of("house", _facts(SCARY)) == "dubstep"  # (Bangarang, by its tempo)
    assert genre._kind_of("rock", _facts(SCARY)) == "rock"
    assert SetGenre().genre_for("b", "dubstep", "sound") == "dubstep"


def _drops():
    """A dubstep track as the analysis measures it: (loudness, low end, kick ratio) per phrase; the drops' kick
    on a third of their beats (half time)."""
    a = synthetic_analysis(bpm=140.0)
    levels = [(12, 10, 0.5), (48, 72, 0.28), (30, 28, 0.22), (84, 81, 0.38), (74, 62, 0.47), (44, 45, 0.39),
              (26, 29, 0.25), (40, 41, 0.38), (80, 80, 0.38), (14, 23, 0.6)]  # fmt: skip
    span = a.duration / len(levels)
    a.phrases = [
        replace(a.phrases[0], index=k, start=k * span, end=(k + 1) * span, loudness_pct=lo, low_pct=low,
                kick_ratio=kick, drop_score=0.0, part="", loudness_slope_db=-1.0 if k == len(levels) - 1 else 1.0)
        for k, (lo, low, kick) in enumerate(levels)
    ]  # fmt: skip
    return a


def test_the_form_finds_the_half_time_drops_their_builds_and_the_breaks():
    plan = direct(_drops(), RuleDirector(style=DUB), verbose=False)
    sections = [d.section for d in plan]
    assert sections[3:5] == ["drop", "drop"] and sections[8] == "drop"
    assert sections[2] == "buildup" and sections[7] == "buildup" and sections[6] == "breakdown"


def test_the_drops_play_dubstep_and_the_breaks_one_calm_effect():
    plan = direct(_drops(), RuleDirector(style=DUB), verbose=False)
    drops = [d for d in plan if d.section == "drop"]
    assert drops and all(d.trigger == "dubstep" and d.par_base == "off" and d.intensity == 3 for d in drops)
    breaks = [d for d in plan if d.section == "breakdown"]
    assert breaks and all(d.head_light == "steady" and d.par_accent == "none" for d in breaks)


# ---------------------------------------------------------------- the growl

SR = 22050


def _wobble(bpm=140.0, beats=32, per_beat=(2, 3), seconds_each=8):
    """A distorted bass at 1/8 then in triplets: noise through an LFO, its sound (a high or a low band) swapped
    with the rate. Returns (signal, pulse onsets)."""
    rng = np.random.default_rng(3)
    beat = 60.0 / bpm
    out, onsets, t0 = [], [], 0.0
    for k, n in enumerate(per_beat):
        dur = beats * beat
        t = np.arange(int(dur * SR)) / SR
        lfo = ((t / beat * n) % 1.0 < 0.55).astype(np.float32)  # on 55% of each pulse
        noise = rng.standard_normal(len(t)).astype(np.float32)
        f = np.fft.rfft(noise)
        freqs = np.fft.rfftfreq(len(noise), 1 / SR)
        band = (300, 1200) if k % 2 == 0 else (2000, 6000)
        f[(freqs < band[0]) | (freqs > band[1])] = 0
        x = np.fft.irfft(f, len(noise)).astype(np.float32)
        out.append(0.3 * x * lfo)
        onsets += [t0 + q * beat / n for q in range(beats * n)]
        t0 += dur
    return np.concatenate(out), np.array(onsets)


def test_the_growl_is_found_pulse_by_pulse_and_a_new_sound_is_a_new_patch():
    x, truth = _wobble()
    bite, prof, fps = growllib.bands(x, SR)
    g = growllib.pulses(bite, prof, fps, t0=0.5 * growllib.NFFT / SR)
    assert abs(len(g) - len(truth)) <= 2
    near = np.abs(g.on[:, None] - truth[None, :]).min(1)
    assert np.median(near) < 0.015
    assert np.all(g.off > g.on)
    half = float(truth[len(truth) // 2 - 32 * 1])  # (the second sound starts after 32 beats of 1/8)
    assert len(set(g.patch[g.on < half - 0.1])) == 1
    assert g.patch[-1] > g.patch[0]  # (the triplets are another sound)


def test_led_pulses_keep_the_flash_limit_and_lamps_hold_the_notes():
    x, _ = _wobble(per_beat=(3,))  # 7 a second
    bite, prof, fps = growllib.bands(x, SR)
    g = growllib.pulses(bite, prof, fps)
    on, off, _, _ = G._thinned(g, 1 / 4.0)
    assert np.diff(on).min() >= 0.25 - 1e-6 and len(on) >= 0.5 * len(g)
    assert np.all(off[:-1] < on[1:])
    held = G._held(g, G.LAMP_GAP_S)
    assert len(held[0]) == 1  # (one long growl: one note)


# ---------------------------------------------------------------- the half-time kit


def test_the_half_time_kit_finds_the_kick_on_the_one_and_the_snare_on_the_three():
    rng = np.random.default_rng(5)
    beat, bars = 60.0 / 140, 16
    x = np.zeros(int(bars * 4 * beat * SR) + SR, np.float32)
    t = np.arange(int(0.2 * SR)) / SR
    kick = (np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.08)).astype(np.float32)
    snare = rng.standard_normal(len(t)).astype(np.float32)
    f = np.fft.rfft(snare)
    fr = np.fft.rfftfreq(len(snare), 1 / SR)
    f[(fr < 800) | (fr > 3500)] = 0
    snare = (np.fft.irfft(f, len(t)) * np.exp(-t / 0.05)).astype(np.float32)
    snare *= np.abs(kick).max() / np.abs(snare).max()
    for b in range(bars):
        k0, s0 = int((0.5 + b * 4 * beat) * SR), int((0.5 + (b * 4 + 2) * beat) * SR)
        x[k0 : k0 + len(t)] += kick
        x[s0 : s0 + len(t)] += snare
    k = drums.detect_half_time(x, SR)
    assert len(k.kick_t) == bars and len(k.snare_t) == bars
    assert np.all(np.abs(((k.snare_t - k.kick_t) / beat) - 2.0) < 0.1)


# ---------------------------------------------------------------- lamps and LEDs


@pytest.mark.parametrize(
    "key, lamp",
    [("claypaky/sharpy", True), ("robe/pointe", True), ("generic/par-64", True), ("showtec/sunstrip-active", True),
     ("martin/mac-aura", False), ("beamz/fuze75b-beam", False), ("dts/katana", False), ("cameo/flat-pro-18", False)],
)  # fmt: skip
def test_a_lamp_is_told_from_an_led(key, lamp):
    defn = json.loads((FIXTURES / f"{key}.json").read_text(encoding="utf-8"))
    assert bool(fxlib.lamp(defn)) is lamp


def test_a_fixture_can_say_its_source_outright():
    assert fxlib.lamp({"physical": {"lamp": "MSD Platinum 5R"}, "modes": {}}) == "MSD Platinum 5R"
    assert fxlib.lamp({"model": "Pointe", "physical": {"lamp": "LED"}, "modes": {}}) == ""


# ---------------------------------------------------------------- the rig in layers


def _growl_track(a):
    """A growl in 1/16 (about 9 a second at 140 BPM) over every drop, a new sound each bar; a half-time kit."""
    beat = 60.0 / a.bpm
    on = np.arange(0.0, a.duration - 1, beat / 4)
    g = growllib.Growl(on, on + 0.6 * beat / 4, np.ones(len(on), np.float32), (on // (4 * beat)).astype(int))
    bars = np.arange(0.0, a.duration - 1, 4 * beat)
    k = drums.Kit(bars, np.ones(len(bars)), bars + 2 * beat, np.ones(len(bars)), np.full(len(bars), 0.3), "stem")
    return g, k


def _render(rig, a, monkeypatch, seconds=6.0):
    """The engine on the track, and each drop's first seconds as rendered: [(ids × frames) per drop]."""
    g, k = _growl_track(a)
    monkeypatch.setattr(growllib, "growl", lambda _a: g)
    monkeypatch.setattr(drums, "half_time", lambda _a: k)
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen")), DUB), verbose=False)
    e = Engine(a, plan, rig)
    drops = [d for d in plan if d.section == "drop"]
    ids = [x["id"] for x in rig["elements"] if x["kind"] in ("head", "par")]
    # (from after the drop's own moment to before the next one's: the dark breath before a drop is its own)
    windows = [np.arange(d.start + 1.0, min(d.end - 1.5, d.start + 1.0 + seconds), 1 / FPS) for d in drops]
    return (
        e,
        ids,
        [np.array([[e.render(float(t))[1][i].dimmer for i in ids] for t in ts]) for ts in windows],
        [(d, ts) for d, ts in zip(drops, windows)],
    )


def _switch_ons(x: np.ndarray) -> np.ndarray:
    return np.flatnonzero((x[1:] > 0.4) & (x[:-1] <= 0.4)) / FPS


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
def test_the_main_group_plays_the_growl_and_the_others_the_drums(path, monkeypatch):
    rig = load_rig(path)
    if not [x for x in rig["elements"] if x["kind"] in ("head", "par")]:
        pytest.skip("no heads or pars")
    a = _drops()
    e, ids, windows, drops = _render(rig, a, monkeypatch)
    voices = {i: e._dub_voice(i) for i in ids}
    assert "growl" in voices.values()
    limit = e._head_strobe_hz()
    for tr, (d, ts) in zip(windows, drops):
        for k, i in enumerate(ids):
            ons = _switch_ons(tr[:, k])
            if voices[i] == "growl":  # the growl's own voice (the eye-band blackout comes on top: a safety gate)
                voice = np.array([(e.growl_at(d, float(t), i) or (0.0, 0))[0] for t in ts])
                gaps = np.diff(_switch_ons(voice))
                if i in e.lamp_lights:  # a lamp holds the growl's notes
                    assert not len(gaps) or gaps.min() >= G.LAMP_GAP_S - 1.5 / FPS
                else:  # an LED pulses, many hits a second, within the flash limit
                    assert len(ons) >= 0.3 * limit * len(tr) / FPS
                    assert not len(gaps) or gaps.min() >= 1.0 / limit - 1.5 / FPS
            else:  # the drums: never faster than a note (no flicker)
                gaps = np.diff(ons)
                assert not len(gaps) or gaps.min() >= 0.3 - 1.5 / FPS


def test_a_lamp_in_the_main_group_holds_while_an_led_pulses(monkeypatch):
    rig = load_rig(SETS[0])
    a = _drops()
    g, _ = _growl_track(a)
    monkeypatch.setattr(growllib, "growl", lambda _a: g)
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), False, DUB), verbose=False)
    e = Engine(a, plan, rig)
    d = next(x for x in plan if x.section == "drop")
    led = next(i for i, v in ((h["id"], e._dub_voice(h["id"])) for h in e.heads) if v == "growl")
    e.lamp_lights = {led}
    ts = np.arange(d.start + 0.5, d.end - 0.5, 1 / FPS)
    lamp_x = np.array([e.growl_at(d, float(t), led)[0] for t in ts])
    e.lamp_lights = set()
    led_x = np.array([e.growl_at(d, float(t), led)[0] for t in ts])
    assert len(_switch_ons(led_x)) > 3 * max(1, len(_switch_ons(lamp_x)))


def test_strobe_free_plays_the_growl_as_held_notes(monkeypatch):
    rig = load_rig(SETS[0])
    rig["safety"]["strobe_free"] = True
    a = _drops()
    e, ids, windows, _ = _render(rig, a, monkeypatch)
    for tr in windows:
        for k in range(len(ids)):
            gaps = np.diff(_switch_ons(tr[:, k]))
            assert not len(gaps) or gaps.min() >= 0.3 - 1.5 / FPS
