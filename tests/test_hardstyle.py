"""Hardstyle: heard by its sound, read by its own form, a climax that hammers, a break with one effect alone, and
the twister that turns on any rig."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from amadeus.audio import genre, hardstyle
from amadeus.director import RuleDirector, direct
from amadeus.director.style import STYLES, SetGenre
from amadeus.engine import Engine
from amadeus.rig.groups import head_groups, laser_list
from amadeus.rig.loader import load_rig
from tests.synthetic import synthetic_analysis

SETS = sorted((Path(__file__).parent / "sets").glob("*.json"))
HARD = STYLES["hardstyle"]
DESTINY = {"hardstyle": 0.65, "hardstyle_lead": 0.78}  # measured
NEAR_MISS = {"hardstyle": 0.48, "hardstyle_lead": 0.18}  # a festival track with hardcore in its name


def _facts(sound: dict, bpm: float = 150.0, **more) -> dict:
    return {**genre.facts(synthetic_analysis(bpm=bpm)), **sound, **more}


def test_judge_counts_the_family_against_its_rivals():
    names = [*hardstyle.FAMILY, *hardstyle.RIVALS]
    styles = np.zeros((4, len(names)))
    styles[:3, names.index("Electronic---Hardstyle")] = 0.8
    styles[3, names.index("Electronic---Happy Hardcore")] = 0.8
    assert hardstyle.judge(styles, names) == {"hardstyle": 0.6, "hardstyle_lead": 0.75}


def test_the_sound_calls_hardstyle_sung_or_not():
    assert genre.from_audio(_facts(DESTINY)) == "hardstyle"  # (150 BPM: psytrance by its tempo)
    assert genre.from_audio(_facts(DESTINY, song=True)) == "hardstyle"
    assert genre.from_audio(_facts(NEAR_MISS)) != "hardstyle"
    assert genre.from_audio(_facts(DESTINY, bpm=100.0)) != "hardstyle"


def test_a_club_call_on_a_hardstyle_sound_is_hardstyle():
    assert genre._kind_of("edm", _facts(DESTINY)) == "hardstyle"
    assert genre._kind_of("pop", _facts(DESTINY)) == "pop"  # (not a club word: the model knows better)


def test_a_track_heard_as_hardstyle_keeps_its_style_in_a_set():
    s = SetGenre()
    assert s.genre_for("a", "hiphop", "audio") == "hiphop"
    assert s.genre_for("b", "hardstyle", "sound") == "hardstyle"


def _destiny():
    """Headhunterz' "Destiny" as the analysis measured it: (loudness, low end, kick ratio) per phrase."""
    a = synthetic_analysis(bpm=150.0)
    levels = [(20, 32, 0.06), (52, 57, 0.19), (33, 29, 0.3), (18, 9, 0.84), (40, 31, 0.75), (77, 85, 0.73),
              (16, 32, 0.62), (30, 31, 0.66), (60, 58, 0.48), (75, 82, 0.58), (2, 18, 0.56)]  # fmt: skip
    span = a.duration / len(levels)
    a.phrases = [
        replace(a.phrases[0], index=k, start=k * span, end=(k + 1) * span, loudness_pct=lo, low_pct=low,
                kick_ratio=kick,
                drop_score=0.0, part="", loudness_slope_db=-1.0 if k == len(levels) - 1 else 1.0)
        for k, (lo, low, kick) in enumerate(levels)
    ]  # fmt: skip
    return a


def test_the_form_finds_the_climaxes_their_builds_and_the_breaks():
    plan = direct(_destiny(), RuleDirector(style=HARD), verbose=False)
    assert [d.section for d in plan[1:10]] == ["breakdown", "breakdown", "breakdown", "buildup", "drop", "breakdown",
                                               "breakdown", "buildup", "drop"]  # fmt: skip


def test_every_climax_hammers_and_every_break_plays_one_effect_alone():
    plan = direct(_destiny(), RuleDirector(style=HARD), verbose=False)
    drops = [d for d in plan if d.section == "drop"]
    assert all(d.head_light == "hammer" and d.intensity == 3 and d.palette in HARD.palettes for d in drops)
    assert all(
        d.par_base == "off" and d.par_accent == "pulse" and d.trigger == "kick" for d in drops
    )  # (the first too)
    breaks = [d for d in plan if d.section == "breakdown"]
    assert all(d.par_base == "off" and d.par_accent == "none" and d.head_light == "steady" for d in breaks)
    assert sum(d.movement == "twister" for d in plan) >= len(plan) // 2


def test_the_hammer_takes_turns_punching_and_strobing():
    rig = load_rig(SETS[0])
    a = _destiny()
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), False, HARD), verbose=False)
    e = Engine(a, plan, rig)
    d = next(x for x in plan if x.section == "drop")
    bars = 4 * e._beat_s()
    assert not e._hammering(d, d.start + bars) and e._hammering(d, d.start + 5 * bars)
    assert not e._hammering(d, d.start + 9 * bars)


def test_the_kick_plays_the_grid_in_the_climax_where_the_low_end_is():
    a = _destiny()
    a.style = "hardstyle"
    plan = direct(a, RuleDirector(style=HARD), verbose=False)
    d = next(x for x in plan if x.section == "drop")
    gone = (a.onsets["kick"][0] >= d.start) & (a.onsets["kick"][0] < d.end)
    a.onsets["kick"] = tuple(np.asarray(x)[~gone] for x in a.onsets["kick"])  # the onsets lost them all
    times, strengths = hardstyle.grid_kicks(a, plan, HARD.kick_grid)
    beats = a.beats[(a.beats >= d.start) & (a.beats < d.end)]
    found = times[(times >= d.start) & (times < d.end)]
    assert len(found) >= 0.8 * len(beats) and len(times) == len(strengths)
    assert (np.diff(times) >= 0).all()


def _twister(path, formation="sync", aim="sky", intensity=1):
    rig = load_rig(path)
    a = synthetic_analysis(bpm=150.0)
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), False), verbose=False)
    plan = [replace(d, movement="twister", formation=formation, aim=aim, intensity=intensity, grouping="unison",
                    dynamics="steady") for d in plan]  # fmt: skip
    return Engine(a, plan, rig), plan


@pytest.mark.parametrize("path", SETS, ids=lambda p: p.stem)
@pytest.mark.parametrize("aim", ["sky", "crowd"])
def test_the_twister_turns_on_every_rig(path, aim):
    e, plan = _twister(path, aim=aim)
    if not e.heads:
        return
    d = plan[len(plan) // 2]
    ts = np.linspace(d.start + 1.0, d.end - 0.2, 120)
    dirs = np.stack([e._head_dir_v(d, ts, j) for j in range(len(e.heads))])  # (heads, times, 3)
    mean = dirs.mean(axis=1, keepdims=True)
    mean = mean / np.linalg.norm(mean, axis=2, keepdims=True)
    swing = np.degrees(np.arccos(np.clip((dirs * mean).sum(axis=2), -1, 1))).max(axis=1)
    assert swing.min() > 8  # nobody freezes, not even under a low ceiling or against a limit


def test_the_heads_of_a_twister_are_a_step_apart_and_mirror_turns_the_other_way():
    path = next(p for p in SETS if p.stem == "fuze24")
    e, plan = _twister(path)
    d = plan[len(plan) // 2]
    t = np.array([d.start + 2.0])
    now = np.stack([e._twister_v(d, t, e._role(d, j), j)[0] for j in range(len(e.heads))])
    assert len({tuple(np.round(x, 2)) for x in now}) == len(e.heads)  # every beam its own place
    e, plan = _twister(path, formation="mirror")
    d = plan[len(plan) // 2]
    sides = [e._role(d, j)["side"] for j in range(len(e.heads))]
    left, right = int(np.argmin(sides)), int(np.argmax(sides))  # the outer heads of the row: each other's mirror image
    x = [e._twister_v(d, np.linspace(8.0, 16.0, 9), e._role(d, j), j)[:, 0] for j in (left, right)]
    assert np.allclose(x[0], -x[1], atol=0.25)  # (the two hang at different heights)


def test_a_head_on_camera_duty_turns_round_the_lens_at_full_size():
    rig = load_rig(next(p for p in SETS if p.stem == "fuze24"))
    rig["stage"].update(camera_x_m=6.0, camera_y_m=8.0, camera_z_m=1.7)
    a = synthetic_analysis(bpm=150.0)
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), False), verbose=False)
    plan = [replace(d, movement="twister", formation="sync", aim="crowd", intensity=1, grouping="unison",
                    dynamics="steady") for d in plan]  # fmt: skip
    e = Engine(a, plan, rig)
    assert e.camera_heads
    d = plan[len(plan) // 2]
    ts = np.linspace(d.start + 1.0, d.end - 0.2, 120)
    for j in e.camera_heads:
        dirs = e._head_dir_v(d, ts, j)
        mean = dirs.mean(axis=0) / np.linalg.norm(dirs.mean(axis=0))
        assert np.degrees(np.arccos(np.clip(dirs @ mean, -1, 1))).max() > 15
        to_lens = (e.camera - e.head_pos[j]) / np.linalg.norm(e.camera - e.head_pos[j])
        assert mean @ to_lens > 0.9  # …and it does play towards the camera


def test_a_turn_never_outruns_the_slowest_head():
    e, _ = _twister(SETS[0])
    for _, defn in e.head_fx:
        defn["motion"] = {"pan_speed_dps": 40, "tilt_speed_dps": 40, "accel_dps2": 50}
    assert e._twist_beats(3) > 4  # slower, never smaller
