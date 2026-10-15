"""The show arc: a whole night (a DJ set, a wedding, a birthday, a Latin night; one hour or ten) as one
curve, with the operator's knobs on it.

A night moves through moods, the stages: a warm-up while the room fills, building the floor, peaks, deeper
breathers in between against fatigue, a finale and an outro. Their order is the DJ's: one goes up and down in
waves, another peaks early and twice, a wedding has dinner first and slow dances in between. So the stages
are detected from the music, not read off a timetable: how hot the mix runs (the tracks' energy per phrase,
and the tempo against the night's own warm-up tempo, half and double time folded together, so a salsa after a
reggaeton is not "twice as hot") is followed quickly and slowly, and each stage is scored by how well the
music fits it (its heat, and whether it is rising or falling). The clock only nudges: a warm-up belongs to the
start, a finale and an outro to the end; in between any stage may come in any order. The event type sets those
nudges, the stages' names and the knobs' character (a wedding has fewer lasers and less smoke than a club).
Every time constant is a share of the show's length, so a one-hour set has the same shape as a ten-hour one.

Each stage shapes the knobs (all 0..1): how many light groups play, special effects (lasers, strobes,
blinders), responsiveness, head movement, look changes, smoke, colour variety, intensity, flashes and the LED
wall. The music on top lifts or lowers intensity and responsiveness a little. The operator can take over any
knob at any moment (and give it back to the arc), force a stage, hold it, pick the event type and change the
show's length.

The knobs work on the mixed frame after the engines (`apply`), except colour variety, which the engines read
themselves (engine/looks.py), head movement and look changes, which reshape each track's plan (`shape_plan`,
the track is rebuilt in the background: head paths are worked out ahead), and the LED wall, which the
visualisers draw. The drop moment is never touched: it keeps its full response.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from amadeus import paths
from amadeus.engine.fog import machine
from amadeus.library import fixtures as fxlib
from amadeus.rig.groups import head_groups

FILE = "show-arc.json"
DEFAULT_LENGTH_S = 4 * 3600.0
MIN_LENGTH_S, MAX_LENGTH_S = 30 * 60.0, 12 * 3600.0
NEW_NIGHT_AFTER_S = 2 * 3600.0  # no music for this long (the engine stopped, the next day): a new night

KNOBS = (
    "groups", "specials", "screen", "smoke",  # in play
    "movement", "changes", "colour",  # character
    "response", "drops", "flashes",  # reaction
    "intensity",  # level
)  # fmt: skip
STAGE_KEYS = ["warmup", "build", "peak", "deep", "finale", "outro"]

# Each stage's knobs as it begins → as it ends (a peak ends in a breather, the finale climbs to the climax).
# Special effects and intensity come from the event (EVENTS[...]["specials"], ["calm"]), the other knobs from here:
# a night runs at full intensity (a quiet stage plays fewer lights, not dimmer ones), only the event's calm stages
# (a wedding's dinner) are dimmed.
# fmt: off
PROFILES = {  # per stage, per knob: (as the stage begins, as it ends)
    #         groups       response     movement    smoke        colour      flashes     LED wall     changes      drops  # noqa: E501
    "warmup": ((0.4, 0.55), (0.3, 0.45), (0.2, 0.3), (0.2, 0.35), (0.2, 0.3), (0.0, 0.1), (0.0, 0.2),  (0.15, 0.3), (0.2, 0.3)),  # noqa: E501
    "build":  ((0.5, 0.75), (0.5, 0.7),  (0.5, 0.7), (0.4, 0.55), (0.4, 0.55), (0.2, 0.5), (0.35, 0.6), (0.4, 0.6), (0.5, 0.7)),  # noqa: E501
    "peak":   ((1.0, 0.9),  (0.95, 0.8), (1.0, 0.9), (0.75, 0.65), (0.8, 0.6),  (1.0, 0.7), (1.0, 0.9),  (0.9, 0.8), (1.0, 0.9)),  # noqa: E501
    "deep":   ((0.6, 0.6),  (0.5, 0.55), (0.5, 0.5), (0.7, 0.7),  (0.3, 0.35), (0.2, 0.3), (0.4, 0.45), (0.35, 0.4), (0.5, 0.5)),  # noqa: E501
    "finale": ((0.85, 1.0), (0.85, 1.0), (0.85, 1.0), (0.7, 0.9), (0.7, 0.9),  (0.7, 1.0), (0.85, 1.0), (0.8, 1.0), (0.9, 1.0)),  # noqa: E501
    "outro":  ((0.5, 0.35), (0.3, 0.2),  (0.3, 0.2), (0.6, 0.4),  (0.2, 0.2),  (0.0, 0.0), (0.3, 0.1),  (0.2, 0.1), (0.2, 0.1)),  # noqa: E501
}
PROFILE_KNOBS = ("groups", "response", "movement", "smoke", "colour", "flashes", "screen", "changes", "drops")
# fmt: on
# The LED wall is drawn by the visualisers (the app, web/js/screen.js): they read the "screen" knob from the feed,
# dim the wall by it, and below SCREEN_CALM show only calm colour (no characters, words or psychedelics).
SCREEN_CALM = 0.5

# Movement: the heads' paths are worked out per track ahead of time, so the knob works in three levels, each a
# calmer version of the director's plan (the track is planned again in the background when the level changes).
MOVE_LEVELS = (0.4, 0.75)  # below the first: calm; below the second: moderate; above: as the director planned
LEVEL_HYSTERESIS = 0.05  # a level changes only this far past its edge (a gliding knob doesn't rebuild twice)
# Look changes: how many phrases one look is held for (a warm-up song gets a few looks, not one per part). Like
# movement, in levels: below 0.25 eight phrases, below 0.5 four, below 0.75 two, above that every phrase.
CHANGE_LEVELS = (0.25, 0.5, 0.75)
HOLD_PHRASES = (8, 4, 2, 1)
# What a held phrase keeps of its own: when it is, its section and energy (a buildup still rises, a drop still
# lands exactly), smoke (long arcs anyway) and the director's notes. Everything else is the held look.
OWN_FIELDS = (
    "phrase",
    "start",
    "end",
    "section",
    "dynamics",
    "intensity",
    "drop_score",
    "fog",
    "source",
    "confidence",
    "probabilities",
    "prompt",
    "brightness",
)
CALM_PATH = {  # per-beat and wild paths → smooth ones
    "step_on_beat": "sweep",
    "bounce": "nod",
    "swing": "sweep",
    "ballyhoo": "circle",
    "tilt_wave": "sweep",
    "follow_lead": "sweep",
}
MODERATE_PATH = {"ballyhoo": "circle", "bounce": "nod", "swing": "sweep"}
CALM_LIGHT = {"flick": "steady", "beat": "breathe", "alternate": "breathe", "random": "breathe", "pulse": "breathe"}
# The groups playing are the show arc's (Light Groups): calmer plans don't feature one group over the others
# (it may be resting), nor light one group per beat.
CALM_GROUPING = {"chase": "unison", "solo": "unison", "split": "unison"}
MODERATE_GROUPING = {"chase": "per_group", "solo": "per_group"}
CALM_BEAM = {"prism": "open", "prism_spin": "open", "gobo_shake": "gobo", "gobo_spin": "gobo"}
# The warm-up with calm heads (dinner and drinks, an empty floor): a static wash of cozy colour as the base, the
# heads very slow, projecting gobos onto the floor (on an empty floor people actually look at them).
AMBIENT_PALETTES = ("warm", "gold")  # cozy; any other palette becomes the first
AMBIENT_PATH = {"nod": "sweep", "figure8": "circle"}  # (after CALM_PATH) the slowest, longest paths

# How each stage sounds: (its heat, the trend it likes: +1 rising, -1 falling, 0 either)
MOODS = {
    "warmup": (0.45, 0),
    "build": (0.63, 1),
    "peak": (0.82, 0),
    "deep": (0.55, -1),
    "finale": (0.82, 1),
    "outro": (0.55, -1),
}
HEAT_WIDTH = 0.1  # a stage fits the heat within about this much
TREND_WEIGHT = 15.0  # a rising or falling mix counts this much (the trend is a few hundredths)
STICK = 0.6  # the stage the night is in counts this much extra: no flapping between two close ones
PULL = 1.0  # a stage in its own part of the night (the warm-up early, the finale late) counts this much extra

# The event types: the stages' names, where in the night a stage may come (share from, to) and where it is
# pulled to, which stages have special effects, which are calm (intensity as the stage begins, as it ends;
# the others run at full), and the character of the knobs (smoke and flashes scaled,
# colour variety and responsiveness lifted). The tempo counts for less where the genres change tempo a lot.
_ANYWHERE = (0.04, 9.0)
EVENTS = {
    "club": {
        "title": "DJ Set / Club Night",
        "names": ("Warm-Up", "Building the Floor", "Peak", "Deep Middle", "Grand Finale", "Outro"),
        "allowed": {"warmup": (0, 0.35), "finale": (0.7, 9), "outro": (0.92, 9)},
        "pull": {"warmup": (0, 0.15), "finale": (0.8, 9), "outro": (0.96, 9)},
        "specials": {"peak": 0.5, "deep": 0.5, "finale": 1.0, "outro": 0.5},
        "calm": {},
        "smoke": 1.0,
        "flashes": 1.0,
        "colour": 0.0,
        "response": 0.0,
        "bpm": 0.3,
    },
    "wedding": {
        "title": "Wedding",
        "names": ("Dinner & Drinks", "Opening the Floor", "Party", "Slow Dances", "Last Dances", "Goodnight"),
        "allowed": {"warmup": (0, 0.45), "finale": (0.75, 9), "outro": (0.93, 9)},
        "pull": {"warmup": (0, 0.3), "finale": (0.85, 9), "outro": (0.97, 9)},
        "specials": {"peak": 0.5, "finale": 0.5},
        "calm": {"warmup": (0.65, 0.75), "deep": (0.85, 0.85), "outro": (0.8, 0.65)},
        "smoke": 0.5,
        "flashes": 0.6,
        "colour": 0.0,
        "response": 0.0,
        "bpm": 0.2,
    },
    "party": {
        "title": "Birthday / House Party",
        "names": ("Arrivals", "Getting Going", "Party Peak", "Breather", "Last Rounds", "Wind-Down"),
        "allowed": {"warmup": (0, 0.25), "finale": (0.7, 9), "outro": (0.92, 9)},
        "pull": {"warmup": (0, 0.1), "finale": (0.8, 9), "outro": (0.96, 9)},
        "specials": {"peak": 0.5, "finale": 1.0},
        "calm": {"warmup": (0.8, 0.9), "outro": (0.9, 0.8)},
        "smoke": 0.6,
        "flashes": 0.8,
        "colour": 0.1,
        "response": 0.0,
        "bpm": 0.2,
    },
    "latin": {
        "title": "Latin (Salsa, Reggaeton, Bachata…)",
        "names": ("Warm-Up", "Heating Up", "Fuego", "Romantic Break", "Grand Finale", "Outro"),
        "allowed": {"warmup": (0, 0.2), "finale": (0.7, 9), "outro": (0.93, 9)},
        "pull": {"warmup": (0, 0.08), "finale": (0.8, 9), "outro": (0.97, 9)},
        "specials": {"peak": 0.5, "finale": 1.0},
        "calm": {},
        "smoke": 0.6,
        "flashes": 0.7,
        "colour": 0.2,
        "response": 0.05,
        "bpm": 0.1,
    },
}
DEFAULT_EVENT = "club"

LIFT = 0.3  # intensity (calm stages) and responsiveness follow the music's heat this much (against the stage) …
LIFT_MAX = 0.12  # … at most this far
SECTION_HEAT = {"drop": 1.0, "buildup": 0.8, "groove": 0.65, "breakdown": 0.3, "intro": 0.3, "outro": 0.3}
SPECIALS_MOMENTS, SPECIALS_FREE = 0.25, 0.75  # specials knob: in the box below, big moments only, free above
REVEAL_WAIT_PHRASES = 4  # a group new tonight waits for a drop to be revealed, but at most this many phrases
GLIDE_S = 8.0  # the knobs follow a stage the music brings this quickly (1/e)
DROP_FLASH = 0.6  # flashes turned down: a big drop still flashes at least this much
BIG_DROP = 0.5  # drops at least this big keep their full response and flash (the moment the lights hit)
DROPS_OWN_LOOK = 0.25  # drops at least this big bring their own look, also when looks are held


def calm_plan(plan: list, level: int, ambient: bool = False) -> list:
    """The director's plan at a movement level: 2 as it is, 1 without the wildest paths and at most "high"
    intensity, 0 smooth slow paths, beams that stay on (no flicks or kick on/off), no prism, no flash accents.
    The lights keep the director's brightness (only the intensity knob dims). `ambient` (at level 0): the
    warm-up's look (`ambient_look`)."""
    from dataclasses import replace

    if level >= 2:
        return plan
    out = []
    for d in plan:
        bright = d.intensity if d.brightness < 0 else d.brightness
        if level == 1:
            out.append(
                replace(
                    d,
                    movement=MODERATE_PATH.get(d.movement, d.movement),
                    movement2=MODERATE_PATH.get(d.movement2, d.movement2),
                    grouping=MODERATE_GROUPING.get(d.grouping, d.grouping),
                    intensity=min(d.intensity, 2),
                    brightness=bright,
                )
            )
        else:
            d = replace(
                d,
                movement=CALM_PATH.get(d.movement, d.movement),
                movement2=CALM_PATH.get(d.movement2, d.movement2),
                head_light=CALM_LIGHT.get(d.head_light, d.head_light),
                beam_fx=CALM_BEAM.get(d.beam_fx, d.beam_fx),
                dynamics="steady" if d.dynamics == "impact" else d.dynamics,
                grouping=CALM_GROUPING.get(d.grouping, d.grouping),
                layer_split="none",  # (an accent layer plays the hits: on, off, on)
                intensity=min(d.intensity, 1),
                brightness=bright,
            )
            out.append(ambient_look(d) if ambient else d)
    return out


def ambient_look(d):
    """The warm-up's look: the pars a static wash in a cozy palette (no hits), the heads steady beams in its
    colour, very slow (the calmest pace, the longest paths), a gobo (turning, where the director turned one)
    projected onto the floor."""
    from dataclasses import replace

    return replace(
        d,
        palette=d.palette if d.palette in AMBIENT_PALETTES else AMBIENT_PALETTES[0],
        par_base="full",
        par_accent="none",
        head_light="steady" if d.head_light != "off" else "off",
        head_color="base" if d.head_color in ("white", "cycle") else d.head_color,
        movement=AMBIENT_PATH.get(d.movement, d.movement),
        movement2=AMBIENT_PATH.get(d.movement2, d.movement2),
        aim="crowd",
        beam_fx="gobo_rotate" if d.beam_fx == "gobo_rotate" else "gobo",
        dynamics="steady",
        intensity=0,  # the slowest paths, the slowest gobo turn, no accents
    )


def hold_looks(plan: list, hold: int, at_drops: bool = True) -> list:
    """Fewer look changes: one look held for `hold` phrases, but (`at_drops`) always a new one where a drop
    starts or ends (the drop lands with its own look). Each phrase keeps its own section and energy."""
    from dataclasses import fields, replace

    from amadeus.audio.model import DROP_THRESHOLD

    if hold <= 1:
        return plan
    look = [f.name for f in fields(plan[0]) if f.name not in OWN_FIELDS] if plan else []
    out, anchor = [], None
    for k, d in enumerate(plan):
        drop = d.drop_score >= DROP_THRESHOLD or d.section == "drop"
        was = k > 0 and (plan[k - 1].drop_score >= DROP_THRESHOLD or plan[k - 1].section == "drop")
        if anchor is None or k - anchor >= hold or (at_drops and drop != was):
            anchor = k
            out.append(d)
            continue
        out.append(replace(d, **{n: getattr(plan[anchor], n) for n in look}))
    return out


def shape_plan(plan: list, shape: tuple) -> list:
    """The director's plan in the show arc's shape: (movement level, phrases a look is held, new look at drops,
    the warm-up's ambient look)."""
    return hold_looks(calm_plan(plan, shape[0], len(shape) > 3 and shape[3]), shape[1], shape[2])


def _ramp(share: float, lo: float, hi: float) -> float:
    return min(max(share, lo), hi)


def fold_tempo(bpm: float, base: float) -> float:
    """The tempo against the base, half and double time folded together: 0.75..1.5."""
    r = bpm / base
    while r >= 1.5:
        r /= 2
    while r < 0.75:
        r *= 2
    return r


class ShowArc:
    """The night's clock, its detected stage and the knobs. `observe` once per frame with what plays (cheap),
    `apply` to the mixed states, `control` with the operator's messages, `snapshot` for the feed."""

    def __init__(self, rig: dict, path: Path | None = None, now: float | None = None):
        self.path = path or paths.CONFIG / FILE
        self.enabled = True
        self.event = DEFAULT_EVENT
        self.length = DEFAULT_LENGTH_S
        self.started: float | None = None  # wall clock (time.time) when the music first played tonight
        self.seen = 0.0  # wall clock of the last music heard (a new night after a long silence)
        self.stage = 0
        self.stage_since = 0.0  # night time the stage began
        self.locked = False  # the operator holds the stage
        self.manual: dict[str, float] = {}
        self.fast = self.slow = None  # heat, followed quickly and slowly
        self.bpm_fast = self.bpm_slow = None
        self.bpm_base: float | None = None  # the warm-up's tempo
        self.candidate, self.evidence = 0, 0.0  # the stage the music says, and for how long it has said so
        self.values = self._targets(0.5)
        self._revealed_saved: list[int] = []  # the groups tonight has already shown (_load)
        self._load(now if now is not None else time.time())
        self._last_obs: float | None = None
        self._last_save = 0.0
        self._dirty = False
        self._levels: dict[str, int] = {}
        self._init_rig(rig)

    # ------------------------------------------------------------ the rig: groups, specials, smoke

    def _init_rig(self, rig: dict):
        els = rig["elements"]
        by_fixture = {f["id"]: f for f in rig["fixtures"]}
        groups: list[list[str]] = []
        washes: dict[str, list[str]] = {}
        for e in els:  # pars, bars and other washes: per the rig's group, else per kind of fixture
            if e["kind"] not in ("head", "laser", "strobe", "blinder", "smoke", "inert"):
                fx = by_fixture[e["fixture"]]
                washes.setdefault(fx.get("group") or fx["fixture"], []).append(e["id"])
        groups += sorted(washes.values(), key=len, reverse=True)  # the washes light the room first
        heads = [g["ids"] for g in head_groups(rig)]
        groups += sorted(heads, key=len)  # the biggest group of heads last: the night's reveal
        self.groups = [g for g in groups if g]
        self.member_of = {eid: k for k, g in enumerate(self.groups) for eid in g}
        self.cumulative = [sum(len(g) for g in self.groups[: k + 1]) for k in range(len(self.groups))]
        self.gain = [1.0] * len(self.groups)
        self.playing_groups = len(self.groups)
        self.bar, self.phrase_at, self.waited, self.reveal_now = -1, None, 0, False
        self.revealed: set[int] = set(self._revealed_saved) if self.started is not None else set()
        self.specials = {e["id"] for e in els if e["kind"] in ("laser", "strobe", "blinder")}
        self.strobes = {e["id"] for e in els if e["kind"] == "strobe"}
        self.special_gain = 1.0
        self.heads = {e["id"] for e in els if e["kind"] == "head"}
        self.lights = [e["id"] for e in els if e["kind"] not in ("smoke", "inert")]
        self.hazers, self.foggers = set(), set()
        for e in els:
            if e["kind"] == "smoke":
                m = machine(e["id"], fxlib.get(by_fixture[e["fixture"]]["fixture"]))
                (self.hazers if m.haze else self.foggers).add(e["id"])
        self.fog_credit = {eid: 0.0 for eid in self.foggers}
        self.fog_open = {eid: False for eid in self.foggers}
        self.fog_was = {eid: 0.0 for eid in self.foggers}
        self.smooth: dict[str, list[float]] = {}

    # ------------------------------------------------------------ the night's clock

    def elapsed(self, now: float) -> float:
        return 0.0 if self.started is None else max(0.0, now - self.started)

    def share(self, now: float) -> float:
        return self.elapsed(now) / self.length

    def _scaled(self, share: float, lo: float, hi: float) -> float:
        """A time constant: this share of the night, within lo..hi seconds."""
        return _ramp(self.length * share, lo, hi)

    # ------------------------------------------------------------ listening

    def observe(self, now: float, decision=None, bpm: float | None = None):
        """What plays now: the dominant deck's phrase (its intensity and section) and tempo; None: silence."""
        dt = 0.0 if self._last_obs is None else min(now - self._last_obs, 5.0)
        self._last_obs = now
        if decision is not None:
            if self.started is None or now - self.seen > NEW_NIGHT_AFTER_S:
                self._new_night(now)
            self.seen = now
            heat = 0.6 * max(0, min(3, decision.intensity)) / 3 + 0.4 * SECTION_HEAT.get(decision.section, 0.6)
            self._listen(heat, bpm, dt)
            self._detect(now, dt)
        self.values = self._glide(self._targets(self.heat(), now), dt)
        if now - self._last_save > (2 if self._dirty else 60):  # the operator's changes soon, the rest now and then
            self.save(now)

    def _listen(self, heat: float, bpm: float | None, dt: float):
        tf = self._scaled(0.012, 45, 600)  # the mix's heat over a few minutes …
        ts = self._scaled(0.07, 240, 2400)  # … and over a longer stretch: the trend is the difference
        kf, ks = 1 - math.exp(-dt / tf), 1 - math.exp(-dt / ts)
        self.fast = heat if self.fast is None else self.fast + (heat - self.fast) * kf
        self.slow = heat if self.slow is None else self.slow + (heat - self.slow) * ks
        if bpm and 40 < bpm < 250:
            self.bpm_fast = bpm if self.bpm_fast is None else self.bpm_fast + (bpm - self.bpm_fast) * kf
            self.bpm_slow = bpm if self.bpm_slow is None else self.bpm_slow + (bpm - self.bpm_slow) * ks
            if STAGE_KEYS[self.stage] == "warmup" or self.bpm_base is None:
                self.bpm_base = self.bpm_slow  # the warm-up's tempo: what "faster" means tonight

    def heat(self) -> float:
        """How hot the mix runs, 0..1: the tracks' energy, and the tempo against the warm-up's."""
        if self.fast is None:
            return MOODS[STAGE_KEYS[self.stage]][0]
        rel = 0.0
        if self.bpm_fast and self.bpm_base:
            rel = min(max((fold_tempo(self.bpm_fast, self.bpm_base) - 1.0) * 12.0, -0.5), 1.0)  # +8%: hot
        w = EVENTS[self.event]["bpm"]
        return min(max((1 - w) * self.fast + w * (0.5 + 0.5 * rel), 0.0), 1.0)

    def trend(self) -> float:
        return 0.0 if self.fast is None or self.slow is None else self.fast - self.slow

    def scores(self, share: float) -> dict[str, float]:
        """How well each stage fits the music now (higher is better), with the event's nudges from the clock."""
        ev = EVENTS[self.event]
        h, tr = self.heat(), self.trend()
        out = {}
        for k, key in enumerate(STAGE_KEYS):
            lo, hi = ev["allowed"].get(key, _ANYWHERE)
            if not lo <= share < hi:
                continue
            centre, likes = MOODS[key]
            v = -(((h - centre) / HEAT_WIDTH) ** 2) + TREND_WEIGHT * tr * likes
            plo, phi = ev["pull"].get(key, (9.0, 9.0))
            v += PULL if plo <= share < phi else 0.0
            v += STICK if k == self.stage else 0.0
            out[key] = v
        return out

    def _detect(self, now: float, dt: float):
        """The stage the music fits best, once it has fitted best for a while (any order: the DJ's path)."""
        if self.locked:
            return
        sc = self.scores(self.share(now))
        if not sc:
            return
        best = STAGE_KEYS.index(max(sc, key=sc.get))
        if best == self.stage:
            self.candidate, self.evidence = best, 0.0
            return
        if best != self.candidate:
            self.candidate, self.evidence = best, 0.0
        self.evidence += dt
        if self.evidence >= self._scaled(0.015, 45, 480) or STAGE_KEYS[self.stage] not in sc:
            self._enter(best, now)  # (or at once: the night has passed the stage's place, e.g. the warm-up)

    def title(self, stage: int | None = None) -> str:
        return EVENTS[self.event]["names"][self.stage if stage is None else stage]

    def _enter(self, stage: int, now: float):
        self.stage, self.stage_since = stage, self.elapsed(now)
        self.candidate, self.evidence = stage, 0.0
        print(f"  ☾ show arc: {self.title()} ({_hm(self.elapsed(now))} of {_hm(self.length)})", flush=True)
        self.save(now)

    def _new_night(self, now: float):
        self.started, self.stage, self.stage_since, self.candidate, self.evidence = now, 0, 0.0, 0, 0.0
        self.fast = self.slow = self.bpm_fast = self.bpm_slow = self.bpm_base = None
        self.revealed = set()  # every surprise back in the box
        print(f"  ☾ show arc: a new night ({EVENTS[self.event]['title']}, {_hm(self.length)}) starts", flush=True)

    # ------------------------------------------------------------ the knobs

    def stage_progress(self, now: float) -> float:
        """How far into its stage the night is, 0..1: a stage runs its course over a fifth of the night (the
        outro over the last few percent)."""
        span = (0.05 if STAGE_KEYS[self.stage] == "outro" else 0.2) * self.length
        return min(max((self.elapsed(now) - self.stage_since) / span, 0.0), 1.0)

    def _targets(self, heat: float, now: float | None = None) -> dict[str, float]:
        key, ev = STAGE_KEYS[self.stage], EVENTS[self.event]
        q = self.stage_progress(now if now is not None else time.time())
        out = {k: a + (b - a) * q for k, (a, b) in zip(PROFILE_KNOBS, PROFILES[key])}
        out["specials"] = ev["specials"].get(key, 0.0)
        calm = ev["calm"].get(key)
        out["intensity"] = 1.0 if calm is None else calm[0] + (calm[1] - calm[0]) * q
        out["smoke"] *= ev["smoke"]
        out["flashes"] *= ev["flashes"]
        out["colour"] += ev["colour"]
        lift = min(max(LIFT * (heat - MOODS[key][0]), -LIFT_MAX), LIFT_MAX)
        if calm is not None:  # (a stage at full intensity stays at full)
            out["intensity"] += lift
        out["response"] += lift + ev["response"]
        return {k: min(max(v, 0.0), 1.0) for k, v in out.items()}

    def _glide(self, target: dict[str, float], dt: float, snap: bool = False) -> dict[str, float]:
        """The arc's values follow the stage within seconds (a stage the music brings: a crossfade, not a jump);
        a stage, event or knob the operator picks applies at once (`snap`)."""
        k = 1.0 if snap else 1 - math.exp(-dt / GLIDE_S) if dt else 0.0
        out = {}
        for name in KNOBS:
            if name in self.manual:
                out[name] = self.manual[name]
            else:
                cur = self.values.get(name, target[name])
                out[name] = cur + (target[name] - cur) * k
        return out

    def value(self, name: str) -> float:
        return 1.0 if not self.enabled else self.values[name]

    def _level(self, name: str, edges: tuple[float, ...]) -> int:
        """A knob in levels (0 .. len(edges)), with hysteresis: a gliding knob doesn't flip back and forth."""
        v = self.values[name]
        cur = self._levels.get(name, len(edges))
        want = sum(v >= e for e in edges)
        if want != cur:
            edge = edges[min(want, cur)]
            if abs(v - edge) >= LEVEL_HYSTERESIS or abs(want - cur) > 1:
                cur = want
        self._levels[name] = cur
        return cur

    def movement_level(self) -> int:
        """The heads' movement level for the plans: 0 calm, 1 moderate, 2 as directed."""
        return self._level("movement", MOVE_LEVELS) if self.enabled else 2

    def hold(self) -> int:
        """How many phrases a look is held for (1: every phrase as directed)."""
        return HOLD_PHRASES[self._level("changes", CHANGE_LEVELS)] if self.enabled else 1

    def plan_shape(self) -> tuple[int, int, bool, bool]:
        """What the plans are shaped to (show/tracks.py rebuilds a track's engine when it changes): the movement
        level, how many phrases a look is held, whether a drop still brings its own look (not for small drops),
        and the warm-up's ambient look (in the warm-up while the heads are calm)."""
        move = self.movement_level()
        ambient = self.enabled and move == 0 and STAGE_KEYS[self.stage] == "warmup"
        return move, self.hold(), self._level("drops", (DROPS_OWN_LOOK,)) == 1, ambient

    def drop_strength(self) -> float | None:
        """For the engines (looks.py, the drop moment): None lands drops in full."""
        return self.values["drops"] if self.enabled else None

    def colour_variety(self) -> float | None:
        """For the engines (looks.py): None leaves the colours as designed."""
        return self.values["colour"] if self.enabled else None

    # ------------------------------------------------------------ the frame

    def apply(self, states: dict, engine, t: float, dt: float):
        """Shape the mixed frame (in place): responsiveness, the groups that play, specials, intensity, flashes
        and smoke. `engine`: the dominant deck's (its bars and drops), `t` its position."""
        if not self.enabled:
            return
        self._respond(states, engine, t, dt)
        self._group_gains(engine, t, dt)
        sp = self.value("specials")  # in the box, out for the big moments only, or free (as directed)
        moment = engine is not None and engine.big_moment(t)
        on = sp >= SPECIALS_FREE or (sp >= SPECIALS_MOMENTS and moment)
        self.special_gain = _towards(self.special_gain, 1.0 if on else 0.0, dt, 0.25 if on and moment else 1.5)
        level = self.value("intensity")
        flashes = self.value("flashes")
        if engine is not None and self.value("drops") >= BIG_DROP and engine.in_drop_moment(t):
            flashes = max(flashes, DROP_FLASH)  # the drop's white hit stays (softer when flashes are down)
        for eid in self.lights:
            s = states.get(eid)
            if s is None:
                continue
            g = self.gain[self.member_of[eid]] if eid in self.member_of else 1.0
            if eid in self.specials:
                g = self.special_gain if self.special_gain > 0.02 else 0.0  # (a laser off is off)
                if eid in self.strobes:
                    g *= flashes
            s.dimmer *= g * level
            s.white *= g * level * flashes
        self._smoke(states)

    def _respond(self, states: dict, engine, t: float, dt: float):
        """Low responsiveness: the lights follow the music's hits less and glow more (a slow follower, mixed in);
        full responsiveness: as the engine plays it. The drop moment always gets its full response."""
        r = self.value("response")
        drop = engine is not None and self.value("drops") >= BIG_DROP and engine.in_drop_moment(t)
        tau = 0.35 + 1.2 * (1.0 - r)
        k = 1 - math.exp(-dt / tau) if dt else 1.0
        for eid in self.lights:
            s = states.get(eid)
            if s is None or eid in self.specials:
                continue
            fields = ("dimmer", "white") if eid in self.heads else ("dimmer", "white", "r", "g", "b")
            raw = [getattr(s, f) for f in fields]
            sm = self.smooth.get(eid)
            if sm is None or drop or r >= 0.999:
                self.smooth[eid] = raw
                continue
            sm = [a + (b - a) * k for a, b in zip(sm, raw)]
            self.smooth[eid] = sm
            for f, a, b in zip(fields, sm, raw):
                setattr(s, f, a + (b - a) * r)

    def _group_gains(self, engine, t: float, dt: float):
        """How many groups play: the first ones in the list (washes, then heads, the smaller groups first: the big
        ones are kept for later). The arc changes them on a phrase line; a group that hasn't played yet tonight is
        a surprise kept in the box until a drop reveals it (or a few phrases at most). When the operator holds the
        knob, the change comes on the next bar. Groups fade in over two seconds (at once on a drop), out over four."""
        n = len(self.groups)
        if not n:
            return
        v = self.value("groups")  # the share of the rig's lights, in whole groups
        want = (
            0
            if v < 0.05
            else next((k + 1 for k, c in enumerate(self.cumulative) if c >= v * self.cumulative[-1] - 0.5), n)
        )
        if engine is None:
            self.playing_groups, self.bar, self.phrase_at = min(self.playing_groups, want), -1, None
        else:
            bar, phrase = engine.bar_info(t), (id(engine), engine.decision_at(t)[0])
            new_bar, new_phrase = bar != self.bar, phrase != self.phrase_at
            drop = new_phrase and phrase[1] in engine.drop_idx
            if want <= self.playing_groups:
                self.waited = 0  # (counts the phrases more lights have been wanted)
            elif new_phrase:
                self.waited += 1
            if self.phrase_at is None:  # music (again): the night's groups at once, but no surprise out of the box
                shown = next((k for k in range(n) if k not in self.revealed), n)
                self.playing_groups = want if not self.revealed else min(want, shown)
            elif want < self.playing_groups and (new_phrase or ("groups" in self.manual and new_bar)):
                self.playing_groups = want
            elif want > self.playing_groups:
                ready = new_phrase or ("groups" in self.manual and new_bar)
                surprise = self.playing_groups not in self.revealed
                big = drop and self.value("drops") >= BIG_DROP  # a big drop: the moment a surprise comes out
                if ready and (not surprise or big or self.waited >= REVEAL_WAIT_PHRASES or "groups" in self.manual):
                    self.playing_groups = want if big or not surprise else self.playing_groups + 1
                    self.waited = 0
                    self.reveal_now = big  # at once on a big drop; otherwise a gentle fade on the phrase line
            self.bar, self.phrase_at = bar, phrase
        for k in range(n):
            on = k < self.playing_groups
            if on and engine is not None:
                self.revealed.add(k)
            fade = 0.05 if on and self.reveal_now else 3.0 if on else 4.0
            self.gain[k] = _towards(self.gain[k], 1.0 if on else 0.0, dt, fade)

    def _smoke(self, states: dict):
        """Hazers: their output scaled. Foggers fire in bursts: a share of the bursts goes out (every other one
        at half), never a cut-off burst."""
        amount = self.value("smoke")
        for eid in self.hazers:
            s = states.get(eid)
            if s is not None:
                v = s.dimmer * amount
                s.dimmer = v if v >= 0.05 else 0.0
        for eid in self.foggers:
            s = states.get(eid)
            if s is None:
                continue
            if s.dimmer > 0 and self.fog_was[eid] <= 0:  # a burst begins: does this one go out?
                self.fog_credit[eid] += amount
                self.fog_open[eid] = self.fog_credit[eid] >= 1.0 - 1e-6
                if self.fog_open[eid]:
                    self.fog_credit[eid] -= 1.0
            self.fog_was[eid] = s.dimmer
            if not self.fog_open[eid] or amount <= 0.0:
                s.dimmer = 0.0

    # ------------------------------------------------------------ the operator

    def control(self, msg: dict, now: float | None = None):
        """A message from the app: {"type": "arc", …} with any of
        knob: {name: value} (the operator takes it over), auto: name | "all" (back to the arc),
        stage: key (force it), lock: bool, length_s: seconds, event: type, reset: true (a new night), enabled: bool."""
        now = time.time() if now is None else now
        for name, v in (msg.get("knob") or {}).items():
            if name in KNOBS:
                self.manual[name] = min(max(float(v), 0.0), 1.0)
        auto = msg.get("auto")
        if auto == "all":
            self.manual.clear()
        elif auto in KNOBS:
            self.manual.pop(auto, None)
        if msg.get("stage") in STAGE_KEYS:
            if self.started is None:
                self._new_night(now)
            self._enter(STAGE_KEYS.index(msg["stage"]), now)
        if "lock" in msg:
            self.locked = bool(msg["lock"])
        if msg.get("event") in EVENTS:
            self.event = msg["event"]
        if "length_s" in msg:
            self.length = _ramp(float(msg["length_s"]), MIN_LENGTH_S, MAX_LENGTH_S)
        if msg.get("reset"):
            self.started, self.stage, self.stage_since, self.locked = None, 0, 0.0, False
            self.revealed = set()
            self.fast = self.slow = self.bpm_fast = self.bpm_slow = self.bpm_base = None
        if "enabled" in msg:
            self.enabled = bool(msg["enabled"])
        snap = any(k in msg for k in ("stage", "event", "reset", "enabled", "auto", "length_s"))
        self.values = self._glide(self._targets(self.heat(), now), 0.0, snap)
        self._dirty = True  # saved within a few seconds (a slider sends many of these)

    def snapshot(self, now: float) -> dict:
        """For the feed: the clock, the stage, the music's heat and every knob (and which the operator holds)."""
        return {
            "on": self.enabled,
            "length": round(self.length),
            "elapsed": None if self.started is None else round(self.elapsed(now), 1),
            "stage": STAGE_KEYS[self.stage],
            "stages": [[k, n] for k, n in zip(STAGE_KEYS, EVENTS[self.event]["names"])],
            "event": self.event,
            "events": [[k, e["title"]] for k, e in EVENTS.items()],
            "locked": self.locked,
            "heat": round(self.heat(), 3),
            "trend": round(self.trend(), 3),
            "bpm": round(self.bpm_fast, 1) if self.bpm_fast else None,
            "base_bpm": round(self.bpm_base, 1) if self.bpm_base else None,
            "values": {k: round(v, 3) for k, v in self.values.items()},
            "manual": sorted(self.manual),
            "groups": len(self.groups),
            "playing": self.playing_groups,
            "movement_level": self.movement_level(),
            "hold": self.hold(),
            "drop_look": self.plan_shape()[2],
            "ambient": self.plan_shape()[3],
        }

    # ------------------------------------------------------------ remembered between engine starts

    def save(self, now: float):
        self._last_save, self._dirty = now, False
        data = {
            "enabled": self.enabled,
            "event": self.event,
            "length_s": self.length,
            "started": self.started,
            "seen": self.seen,
            "stage": STAGE_KEYS[self.stage],
            "stage_since": self.stage_since,
            "locked": self.locked,
            "manual": self.manual,
            "revealed": sorted(getattr(self, "revealed", ())),
            "heat": [self.fast, self.slow],
            "bpm": [self.bpm_fast, self.bpm_slow, self.bpm_base],
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1))
            tmp.replace(self.path)
        except OSError:
            pass

    def _load(self, now: float):
        try:
            d = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return
        self.enabled = bool(d.get("enabled", True))
        self.event = d.get("event") if d.get("event") in EVENTS else DEFAULT_EVENT
        self.length = _ramp(float(d.get("length_s", DEFAULT_LENGTH_S)), MIN_LENGTH_S, MAX_LENGTH_S)
        self.manual = {k: float(v) for k, v in (d.get("manual") or {}).items() if k in KNOBS}
        self.locked = bool(d.get("locked", False))
        if d.get("started") is None or now - float(d.get("seen") or 0) > NEW_NIGHT_AFTER_S:
            return  # the knobs and the length stay; the night itself starts again with the music
        self.started, self.seen = float(d["started"]), float(d["seen"])
        self._revealed_saved = [int(k) for k in d.get("revealed") or []]
        self.stage = STAGE_KEYS.index(d["stage"]) if d.get("stage") in STAGE_KEYS else 0
        self.stage_since = float(d.get("stage_since", 0.0))
        self.fast, self.slow = (d.get("heat") or [None, None])[:2]
        self.bpm_fast, self.bpm_slow, self.bpm_base = (d.get("bpm") or [None, None, None])[:3]


def _towards(v: float, target: float, dt: float, seconds: float) -> float:
    step = dt / seconds if dt else 1.0
    return min(v + step, target) if target > v else max(v - step, target)


def _hm(s: float) -> str:
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}"
