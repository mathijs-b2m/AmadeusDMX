"""The show arc: the night's stages are found from the music (at any length), and the knobs shape the frame."""

from types import SimpleNamespace

import pytest

from amadeus.engine import State
from amadeus.rig.loader import load_rig
from amadeus.show.arc import STAGE_KEYS, ShowArc, fold_tempo

RIG = "tests/sets/showcase.json"

# how a typical night runs, as shares of its length: (until, intensity, section, bpm)
NIGHT = [
    (0.2, 1, "groove", 120),
    (0.4, 2, "groove", 124),
    (0.6, 3, "drop", 128),
    (0.8, 1, "breakdown", 124),
    (0.95, 3, "drop", 130),
    (1.0, 0, "outro", 122),
]


def run_night(arc: ShowArc, hours: float, night=NIGHT, step: float = 10.0) -> list[tuple[float, str]]:
    """Play a night of this length through the arc; (share, stage) every time the stage changes."""
    length = hours * 3600
    arc.control({"length_s": length}, now=0.0)
    seen, t = [], 0.0
    while t < length:
        share = t / length
        _, intensity, section, bpm = next(p for p in night if share < p[0])
        arc.observe(t, SimpleNamespace(intensity=intensity, section=section), bpm)
        stage = STAGE_KEYS[arc.stage]
        if not seen or seen[-1][1] != stage:
            seen.append((share, stage))
        t += step
    return seen


@pytest.mark.parametrize("hours", [1, 5, 10])
def test_the_same_night_at_any_length(tmp_path, hours):
    """The classic wave is found at the same places in a one-hour set as in a ten-hour one (a little after the
    music changes: the music has to say so for a while)."""
    arc = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=0.0)
    seen = run_night(arc, hours, NIGHT)
    assert [s for _, s in seen] == STAGE_KEYS
    for (share, _), changed in zip(seen[1:], (0.2, 0.4, 0.6, 0.8, 0.95)):
        assert changed < share <= changed + 0.06, (hours, seen)


def test_the_dj_picks_the_path(tmp_path):
    """No fixed order: a DJ who goes straight for the peak, dips, and peaks again gets exactly that."""
    path = [
        (0.1, 1, "groove", 122),
        (0.3, 3, "drop", 128),
        (0.45, 1, "breakdown", 122),
        (0.7, 3, "drop", 128),
        (1.0, 2, "groove", 124),
    ]
    arc = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=0.0)
    seen = run_night(arc, 4, path)
    moods = [s for _, s in seen if s != "build"]  # (rising into a peak passes through building the floor)
    assert moods[:4] == ["warmup", "peak", "deep", "peak"]
    assert next(share for share, s in seen if s == "peak") < 0.25  # long before the classic wave's peak
    assert "finale" not in moods  # this DJ never went for a finale: none is made up


def test_events_have_their_own_character(tmp_path):
    """A wedding: dinner first and for longer, its own names, fewer specials and less smoke than a club."""
    arc = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=0.0)
    arc.control({"event": "wedding", "stage": "deep"}, now=0.0)
    snap = arc.snapshot(0.0)
    assert snap["event"] == "wedding" and dict(snap["stages"])["deep"] == "Slow Dances"
    assert arc._targets(0.6, 0.0)["specials"] == 0.0
    arc.control({"event": "club"}, now=0.0)
    club = arc._targets(0.6, 0.0)
    arc.control({"event": "wedding"}, now=0.0)
    assert arc._targets(0.6, 0.0)["smoke"] < club["smoke"] and club["specials"] == 0.5  # big moments only
    # a warm-up mood a quarter into the night: still dinner at a wedding, no longer a warm-up at a club
    assert "warmup" in arc.scores(0.25)
    arc.control({"event": "club"}, now=0.0)
    assert "warmup" in arc.scores(0.25) and "warmup" not in arc.scores(0.4)


def test_half_and_double_time_are_not_hotter():
    assert fold_tempo(190, 95) == pytest.approx(1.0)  # a salsa after a reggaeton
    assert fold_tempo(128, 124) == pytest.approx(128 / 124)


def test_operator_takes_over_and_gives_back(tmp_path):
    arc = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=0.0)
    arc.observe(0.0, SimpleNamespace(intensity=1, section="groove"), 120)
    arc.control({"knob": {"intensity": 0.2}, "stage": "peak", "lock": True}, now=1.0)
    assert arc.values["intensity"] == 0.2 and STAGE_KEYS[arc.stage] == "peak" and arc.locked
    arc.save(1.0)
    again = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=2.0)  # remembered over an engine restart
    assert again.manual == {"intensity": 0.2} and STAGE_KEYS[again.stage] == "peak"
    again.control({"auto": "all"}, now=3.0)
    assert not again.manual


def test_groups_specials_and_off(tmp_path):
    rig = load_rig(RIG)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    lit = lambda: {e["id"]: State(dimmer=1.0, white=1.0) for e in rig["elements"]}  # noqa: E731
    arc.control({"knob": {"groups": 0.1, "specials": 0.0, "intensity": 1.0, "response": 1.0}}, now=0.0)
    states = lit()
    for _ in range(400):  # ten seconds: every fade done
        states = lit()
        arc.apply(states, None, 0.0, 0.025)
    playing = [g for g in arc.groups if states[g[0]].dimmer > 0]
    assert len(playing) == 1 and playing[0] == arc.groups[0]
    assert all(states[e].dimmer == 0 for e in arc.specials)

    arc.control({"enabled": False}, now=1.0)
    states = lit()
    arc.apply(states, None, 0.0, 0.025)
    assert all(s.dimmer == 1.0 for s in states.values())  # off: the show as the engine plays it


def test_smoke_goes_out_in_a_share_of_the_bursts(tmp_path):
    rig = load_rig(RIG)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    arc.foggers, arc.hazers = {"fog"}, set()
    arc.fog_credit, arc.fog_open, arc.fog_was = {"fog": 0.0}, {"fog": False}, {"fog": 0.0}
    arc.control({"knob": {"smoke": 0.5}}, now=0.0)
    out = []
    for _ in range(8):
        for v in (0.6, 0.6, 0.0):
            states = {"fog": State(dimmer=v)}
            arc._smoke(states)
            if v:
                out.append(states["fog"].dimmer)
    fired = sum(1 for k in range(0, len(out), 2) if out[k] > 0)
    assert fired == 4 and all(out[k] == out[k + 1] for k in range(0, len(out), 2))  # whole bursts, half of them


def test_outdoor_opens_the_sky():
    """Outdoors: no ceiling guard, a higher sky aim, and the rules director aims at the sky far more often."""
    from amadeus.director.plan import direct
    from amadeus.director.rules import RuleDirector
    from amadeus.rig import geometry
    from tests.synthetic import synthetic_analysis

    assert geometry.ceiling_top_deg([0, 0, 2.0], {"ceiling_m": 4.0}) is not None
    assert geometry.ceiling_top_deg([0, 0, 2.0], {"ceiling_m": 4.0, "outdoor": True}) is None
    a = synthetic_analysis()
    indoor = direct(a, RuleDirector(), verbose=False)
    outdoor = direct(a, RuleDirector(outdoor=True), verbose=False)
    sky = lambda plan: sum(d.aim == "sky" for d in plan) / len(plan)  # noqa: E731
    assert sky(outdoor) > sky(indoor) and sky(outdoor) >= 0.6


def test_movement_calms_the_plan():
    """Calm: no beat-locked jumps, flicks, prisms or flash accents, slow tempo; moderate: no wild paths."""
    from amadeus.director.plan import direct
    from amadeus.director.rules import RuleDirector
    from amadeus.show.arc import CALM_PATH, calm_plan
    from tests.synthetic import synthetic_analysis

    plan = direct(synthetic_analysis(), RuleDirector(), verbose=False)
    assert calm_plan(plan, 2) is plan
    calm = calm_plan(plan, 0)
    assert all(d.movement not in CALM_PATH and d.intensity <= 1 and d.dynamics != "impact" for d in calm)
    assert all(d.head_light not in ("flick", "beat", "pulse") and "prism" not in d.beam_fx for d in calm)
    assert all(d.movement not in ("ballyhoo", "bounce", "swing") for d in calm_plan(plan, 1))
    assert [d.start for d in calm] == [d.start for d in plan]


def test_knobs_go_all_the_way_down(tmp_path):
    rig = load_rig(RIG)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    arc.control({"knob": {"groups": 0.0, "intensity": 0.0, "movement": 0.0}}, now=0.0)
    for _ in range(400):
        states = {e["id"]: State(dimmer=1.0) for e in rig["elements"]}
        arc.apply(states, None, 0.0, 0.025)
    assert all(states[e].dimmer == 0 for e in arc.lights)
    assert arc.movement_level() == 0
    arc.control({"knob": {"movement": 0.42}}, now=1.0)
    assert arc.movement_level() == 0  # just past the edge: stays (no rebuild for a gliding knob)
    arc.control({"knob": {"movement": 0.6}}, now=2.0)
    assert arc.movement_level() == 1


def test_fewer_look_changes_keep_the_drops():
    """A look held for several phrases, but a drop always gets its own, exactly on its phrase."""
    from amadeus.director.plan import direct
    from amadeus.director.rules import RuleDirector
    from amadeus.show.arc import hold_looks
    from tests.synthetic import synthetic_analysis

    plan = direct(synthetic_analysis(), RuleDirector(), verbose=False)
    held = hold_looks(plan, 8)
    looks = lambda p: sum(1 for k in range(1, len(p)) if p[k].look() != p[k - 1].look())  # noqa: E731
    assert looks(held) < looks(plan)
    assert [(d.start, d.section, d.dynamics, d.drop_score) for d in held] == [
        (d.start, d.section, d.dynamics, d.drop_score) for d in plan
    ]
    for k, d in enumerate(plan):
        if d.section == "drop" and (k == 0 or plan[k - 1].section != "drop"):
            assert held[k].look() == d.look()  # the drop's own look


def test_plan_shape_follows_the_knobs(tmp_path):
    arc = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=0.0)
    arc.control({"knob": {"movement": 0.1, "changes": 0.1}}, now=0.0)
    assert arc.plan_shape()[:2] == (0, 8)
    arc.control({"knob": {"movement": 1.0, "changes": 1.0}}, now=0.0)
    assert arc.plan_shape()[:2] == (2, 1)
    arc.control({"enabled": False}, now=0.0)
    assert arc.plan_shape()[:2] == (2, 1)


def test_drop_size():
    """Full: the approved drop (dark the last half beat, then the hit). Small: no darkness and no flash, a lift."""
    from amadeus.director.plan import direct
    from amadeus.director.rules import RuleDirector
    from amadeus.engine import Engine
    from tests.synthetic import synthetic_analysis

    a = synthetic_analysis()
    rig = load_rig(RIG)
    e = Engine(a, direct(a, RuleDirector(), verbose=False), rig)
    drop = e.drops[0]
    _, _, period = e.beat_info(drop)
    before, after = drop - period * 0.25, drop + 0.02
    lit = lambda t: sum(s.dimmer for s in e.render(t)[1].values())  # noqa: E731
    white = lambda t: sum(s.white for s in e.render(t)[1].values())  # noqa: E731
    full = (lit(before), white(after))
    e.drop_strength = 1.0
    assert (lit(before), white(after)) == full and full[0] == 0  # the knob at full: exactly as approved
    e.drop_strength = 0.0
    own = white(after)  # the drop's own look (its flash accents are the "flashes" knob's)
    e.drop_strength = 0.1
    assert lit(before) > 0 and white(after) - own < (full[1] - own) * 0.2


class FakeEngine:
    """Just what the arc asks an engine: phrases of 8 s, bars of 2 s, a drop at phrase 5."""

    drop_idx = {5}

    def decision_at(self, t):
        return int(t // 8), None

    def bar_info(self, t):
        return int(t // 2)

    def in_drop_moment(self, t):
        return 40 <= t < 42

    def big_moment(self, t):
        return 40 <= t < 48


def test_surprises_stay_in_the_box_until_a_moment(tmp_path):
    """More groups are wanted at 10 s: the ones already shown tonight come back on the next phrase line, a group
    new tonight waits for the drop (40 s) and comes in at once there. Specials at "moments": the drop only."""
    rig = load_rig(RIG)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    n = len(arc.groups)
    arc.control({"knob": {"groups": 1.5 / n, "specials": 0.5, "flashes": 1.0, "intensity": 1.0, "drops": 1.0}}, now=0.0)
    e, dt = FakeEngine(), 0.025
    lit = {}
    for k in range(int(50 / dt)):
        t = k * dt
        if abs(t - 10) < dt / 2:
            arc.manual.pop("groups")  # the arc wants all of them now
            arc.values["groups"] = 1.0
        states = {x["id"]: State(dimmer=1.0) for x in rig["elements"]}
        arc.apply(states, e, t, dt)
        lit[round(t, 3)] = (arc.playing_groups, max(states[x].dimmer for x in arc.specials) if arc.specials else 0)
    assert lit[20.0][0] == lit[5.0][0] < n  # nothing new before the drop (a phrase passed at 16 s)
    assert lit[40.5][0] == n  # the drop reveals them all
    assert lit[39.0][1] == 0 and lit[41.0][1] > 0.9  # specials out on the drop only


def test_a_stage_you_pick_applies_at_once_and_small_drops_reveal_nothing(tmp_path):
    rig = load_rig(RIG)
    arc = ShowArc(rig, tmp_path / "arc.json", now=0.0)
    arc.control({"event": "wedding", "stage": "peak"}, now=0.0)
    arc.control({"stage": "warmup"}, now=1.0)
    assert arc.values == pytest.approx(arc._targets(arc.heat(), 1.0))  # no minutes-long crossfade from the peak
    n = len(arc.groups)
    arc.control({"knob": {"groups": 1.5 / n}}, now=1.0)
    e, dt = FakeEngine(), 0.025
    for k in range(int(10 / dt)):  # the warm-up's groups are out
        arc.apply({x["id"]: State(dimmer=1.0) for x in rig["elements"]}, e, k * dt, dt)
    arc.manual.pop("groups")
    arc.values["groups"] = 1.0
    for k in range(int(10 / dt), int(41 / dt)):
        arc.apply({x["id"]: State(dimmer=1.0) for x in rig["elements"]}, e, k * dt, dt)
    assert arc.playing_groups < n  # a warm-up's small drop at 40 s is no moment for the surprises


@pytest.mark.parametrize("event", ["club", "latin", "wedding", "party"])
def test_intensity_is_full_but_in_calm_stages(tmp_path, event):
    """A night runs at full intensity (a quiet stage plays fewer lights); only the calm stages (a wedding's
    dinner) are dimmed, whatever the music does."""
    arc = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=0.0)
    arc.control({"event": event}, now=0.0)
    for stage in STAGE_KEYS:
        arc.control({"stage": stage, "lock": True}, now=1.0)
        for heat in (0.0, 1.0):
            target = arc._targets(heat, now=1.0)["intensity"]
            calm = {"wedding": {"warmup", "deep", "outro"}, "party": {"warmup", "outro"}}.get(event, set())
            if stage in calm:
                assert target < 1.0 or heat > 0.5  # (hot music lifts a calm stage, up to full)
            else:
                assert target == 1.0, (stage, heat)


def test_calm_heads_keep_their_brightness():
    """Calmer heads lower a plan's intensity (slower paths, fewer effects), not its brightness."""
    from amadeus.director.plan import direct
    from amadeus.director.rules import RuleDirector
    from amadeus.show.arc import calm_plan
    from tests.synthetic import synthetic_analysis

    plan = direct(synthetic_analysis(), RuleDirector(), verbose=False)
    for level in (0, 1):
        assert [d.brightness for d in calm_plan(plan, level)] == [d.intensity for d in plan]
        assert [d.brightness for d in calm_plan(calm_plan(plan, level), 0)] == [d.intensity for d in plan]


def test_warmup_ambience(tmp_path):
    """The warm-up with calm heads: a static cozy wash, very slow heads projecting gobos onto the floor."""
    from amadeus.director.plan import direct
    from amadeus.director.rules import RuleDirector
    from amadeus.show.arc import AMBIENT_PALETTES, shape_plan
    from tests.synthetic import synthetic_analysis

    arc = ShowArc(load_rig(RIG), tmp_path / "arc.json", now=0.0)
    arc.control({"event": "wedding", "stage": "warmup", "lock": True, "knob": {"movement": 0.1}}, now=0.0)
    assert arc.plan_shape()[3]
    arc.control({"knob": {"movement": 0.6}}, now=1.0)
    assert not arc.plan_shape()[3]  # livelier heads: the director's looks
    arc.control({"stage": "build", "knob": {"movement": 0.1}}, now=2.0)
    assert not arc.plan_shape()[3]

    plan = direct(synthetic_analysis(), RuleDirector(), verbose=False)
    ambient = shape_plan(plan, (0, 4, False, True))
    assert all(d.palette in AMBIENT_PALETTES and d.par_accent == "none" and d.par_base == "full" for d in ambient)
    assert all(d.beam_fx in ("gobo", "gobo_rotate") and d.aim == "crowd" and d.intensity == 0 for d in ambient)
    assert all(d.movement in ("still", "sweep", "circle") for d in ambient)
    assert [d.brightness for d in ambient] == [d.intensity for d in plan]  # each phrase its own energy
