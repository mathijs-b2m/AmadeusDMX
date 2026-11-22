"""Looks: the colours, levels and hits of pars, heads, blinders and strobes for each phrase."""

from __future__ import annotations

import bisect
import math

import numpy as np

from amadeus.director import Decision
from amadeus.director.vocabulary import PALETTES
from amadeus.engine.state import State
from amadeus.engine.timing import (
    BREAK_FROM,
    BREAK_TO,
    MIN_GAP_S,
    NO_KICK_S,
    SHORT_HOLD_S,
    SHORT_RELEASE_S,
    STRUM_HOLD_S,
    STRUM_RELEASE_S,
    _decay,
    _ease,
    _release,
    note_env,
    ring_env,
    stab_env,
)
from amadeus.library import fixtures as fxlib
from amadeus.rig import sections

XFADE = 0.6  # seconds of crossfade between scenes at phrase boundaries


DROP_DARK_FROM = 0.35  # drop size (the show arc's knob) from which the breath of darkness comes in, full at 1
PREDROP_BEATS = 2.0  # heads go dark and move to the drop's position/colour/gobo this many beats early


# The kick leads: triggers faster than the kick switch the lights on the kick instead (a light that blinks with
# every hi-hat or synth note reads as a broken bulb, not as rhythm).
KICK_LED = {"hats", "eighths", "sixteenths", "synth", "roll"}


# How a group plays the kicks, a different way per phrase (left to right by position): all together, taking
# turns (odd/even), left against right, or a rotation through three or four sub-groups. Drops lean tutti.
KICK_PATTERNS = ("all", "alternate", "sides", "rotate")
DROP_PATTERNS = ("all", "all", "sides", "rotate")


# Boom-tac (the dembow trigger, reggaeton): the rig plays kick and snare as two voices, whole groups each.
BOOM_TAC_BASE = 0.22  # the pars glow at most this much between their hits (dim), so the hits stand out
BOOM_TAC_HEAD_BASE = 0.08  # the heads' beams, between their hits
BOOM_TAC_HANDOVER_S = 0.12  # a voice lets go this quickly when the other one hits
BREATHER_FADE_S = 0.15  # a breather: the light pauses this quickly (down to a glow) …
BREATHER_GLOW = 0.3  # … of its glow between hits
# A kick run (the kick leaving the dembow, "boom boom boom boom", audio/kickruns.py): the whole rig plays it as a
# waterfall, one group across the stage per kick, every kick of the run, then all of it together on the landing.
KICK_RUN_STEPS = 6  # at most this many groups across the rig (fewer kicks or places: fewer)
KICK_RUN_HOLD = 0.6  # a group holds this share of the time to the next kick …
KICK_RUN_RELEASE_S = 0.25  # … and lets go over this: the groups before it still falling, a waterfall
KICK_RUN_GLOW = 0.05  # the groups waiting for their kick
KICK_RUN_LAND_HOLD_S, KICK_RUN_LAND_RELEASE_S = 0.2, 0.45  # the landing: everything, held a moment, let go
KICK_RUN_WAIT_S = 2.5  # after it, the glow waits at most this long for the beat's next hit
KICK_RUN_LEAD_S = 0.03

# The kit (the drums trigger, rock): the same two voices by whole groups, the kick and the snare, the snare's light
# ringing out with its reverb; the guitar's strums on the accent lights.
TWO_VOICES = ("dembow", "drums", "cumbia")
# Cumbia's swing (the cumbia trigger): boom-tac's two voices on the beat and its "and" (the cha), each section in its
# own colour of the palette, every voice a step apart, all of them moving on to the next colour every bar (with little
# colour variety, every DANCE_SLOW_BARS): a fiesta of colours that changes as the lights hit, never while they glow.
DANCE_SLOW_BARS = 4
KIT_HOLD = 0.6  # no drum around (a drumless verse, a break): both voices hold this, steady, instead of going dark

ACCENT_SHARE = 3  # one light in this many plays the accents (the synth's stabs); the others keep the rhythm
ACCENT_SECTIONS = ("groove", "drop", "buildup", "verse", "chorus")
BLOCK_BARS = 4  # in energetic parts the group's kick pattern and the accent roles change this often
CAMERA_UNITS = 4  # the heads playing the camera go by sections if the rig has this many, else by mirrored pairs
MIN_STABS = 3  # a phrase needs this many stabs before lights are given to them

# The heads' strobe (head light "strobe"): white flashes on the beat grid, as fine as the section asks (notes per
# beat) and the set's flash limit allows (max_flash_hz; allow_fast_strobe: up to FAST_STROBE_HZ; strobe_free: the
# heads pulse on the kick instead). These flashes are on the beat: every head plays them on its dimmer, gated on the
# grid, also one with a strobe channel (only a strobe faster than library/strobe.py DIMMER_FLASH_HZ goes there).
HEAD_STROBE_DIV = {"drop": 4, "groove": 2, "chorus": 2, "buildup": 2}  # elsewhere: on the beat
HEAD_STROBE_ON_S = 0.05  # a flash: two DMX frames
FAST_STROBE_HZ = 10.0
HAMMER_BARS = 4  # the hammer (head light): this many bars of beams punching on the kick, then as many strobing. A
# strobe is dark most of the time: alone it would chop a moving shape into dots, and a long climax needs its turns


def kick_turn(pattern: str, k: int, n: int, hit: int) -> bool:
    """Does element k (of n, left to right) play kick number `hit` in this pattern?"""
    if hit < 0 or n < 2 or pattern == "all":
        return True
    if pattern == "alternate":
        return (k + hit) % 2 == 0
    if pattern == "sides":
        return (k * 2 // n) == hit % 2
    m = min(4, n) if n > 4 else min(3, n)  # rotate
    return (k * m // n) == hit % m


# The run (par accent and head light "run"): a short shot stepping across the rig's mirrored pairs, from the middle
# out, on the beat grid where the kick runs (notes per beat by section, halved until every light keeps the flash
# limit: a light flashes once a lap), on the synth's notes where it doesn't. Hard styles' fast sequences.
RUN_DIV = {"drop": 4, "buildup": 2, "groove": 2}  # 1/16 in a drop, 1/8 in a groove or build (1/16 in its last half)
RUN_HOLD_S, RUN_RELEASE_S = 0.05, 0.1
RUN_STAB_S = 1.0  # no note for this long: the run rests
RUN_NOTE_S = 0.15  # where it runs on the synth's notes: a step at most this often
RUN_GLOW = 0.12  # …and the heads glow this much between their shots, so the beams' moves show
RUN_STEPS = 4  # a lap has at most this many steps: the pairs, middle out, in as many shares


MELODY_TAU = 0.7  # how long a melody note keeps its par lit


# a colour wave through the heads (head_color "wave"): the crest crosses the row in this share of a bar, left to
# right, then back the next bar; each head takes the wave's colour as it arrives, holds it and lets it go (in beats)
WAVE_SPREAD, WAVE_HOLD, WAVE_RELEASE = 0.75, 0.3, 0.9
WAVE_WHITE_BASE = 0.8  # a base this pale (its weakest emitter) has no white to show: the wave plays the accent
# a colour wheel can't blend: the wave wipes it to the slot next to the look's colour (the one nearest the wave's
# colour: the shortest turn), and back on the next pass. The wheels hide each turn in the dark (engine/wheels.py):
# in a pulse's gap every pass plays; under a steady beam a turn waits for a gap or the planner's dip, at most every
# other bar, and the passes in between are skipped. The wave never darkens a beam itself: that flickers.


PAR_BASE_LEVEL = {"off": 0.0, "dim": 0.22, "full": 0.75, "fade": 0.5, "sides": 0.6}
STROBE_WASH = 0.8  # an LED strobe with colour holds the pars' glow, a little under them (it is far brighter)


INTENSITY_MASTER = [0.55, 0.7, 0.85, 1.0]  # "Subtle" must still be clearly visible


# Colour variety (the show arc's knob, 0..1; None: as designed, which is what 0.5..0.85 gives):
COLOUR_HOLD = ((0.25, 4), (0.5, 2))  # below this variety, one palette for this many phrases
COLOUR_BUSY = 0.85  # from this variety, base and accent swap every eight bars


def _lerp(a, b, k: float):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def _mix(cols, x: float):
    """Cyclic interpolation through a list of colours, x in 0..1."""
    n = len(cols)
    pos = (x % 1.0) * n
    a, b = cols[int(pos) % n], cols[(int(pos) + 1) % n]
    k = pos - int(pos)
    return tuple(a[i] * (1 - k) + b[i] * k for i in range(3))


RANDOM_SHARE = 0.4  # random head light: the share of kicks a head would like to light
STAR_SLOT_S = 2.4  # stars: each star light twinkles at most once in this long, at its own moment in it
STAR_RATE, STAR_RATE_BUSY = 1.5, 3.0  # new stars per second over the whole set (calm / drop)
STAR_RISE_S, STAR_HOLD_S, STAR_RELEASE_S = 0.08, 0.25, 0.7  # comes up, holds, fades gently


def _hash(k: int, slot: int, salt: int) -> float:
    """A repeatable random number 0..1."""
    return math.sin(slot * 12.9898 + k * 78.233 + salt * 37.719) * 43758.5453 % 1.0


def envelope_release(dt: float, level: float, hold: float, release: float) -> float:
    """Held at `level` for `hold`, then let go gently (a soft curve) over `release`."""
    if dt < hold:
        return level
    if dt < hold + release:
        return level * 0.5 * (1 + math.cos(math.pi * (dt - hold) / release))
    return 0.0


def _chance(head: int, slot: int) -> bool:
    """Random but repeatable: does this head light this kick?"""
    return math.sin(slot * 12.9898 + head * 78.233) * 43758.5453 % 1.0 < RANDOM_SHARE


class LooksMixin:
    """Per-phrase looks: which fixtures light, in which colours, on which hits."""

    def _blinder_states(self, d: Decision, t: float, out: dict, acc_env: float):
        """Blinders: dark but for the song's heaviest moments (engine/blinders.py)."""
        self._blinders(t, out)

    def _strobe_states(self, d: Decision, t: float, out: dict, acc_env: float, base=None, accent=None):
        """Strobes: white flashes, never a steady white light. Dark by default. A build-up into a drop flashes on
        the beat over its last quarter, twice per beat over its last bar (never faster than the set's
        max_flash_hz); in a drop (intensity 2+) they flash on the big hits, on the kick. The drop moment itself
        flashes everything anyway. An LED strobe with colour (an Atomic 3000 LED) also washes: while the pars
        glow it holds their base colour a little under them, the flashes white on top."""
        strobes = getattr(self, "_strobes", None)
        if strobes is None:
            strobes = self._strobes = [e for e in self.rig["elements"] if e["kind"] == "strobe"]
            self._strobe_rgb = {e["id"] for e in strobes if self._has_colour(e)}
        if not strobes:
            return
        beat, phase, period = self.beat_info(t)
        i = d.phrase  # this look's own phrase (during a crossfade the previous look is rendered too)
        nxt = self.plan[i + 1] if i + 1 < len(self.plan) else None
        max_hz = float(self.rig["safety"].get("max_flash_hz", 4.0))
        dim, gate, hz = 0.0, 1.0, 0.0
        if self.rig["safety"].get("strobe_free"):
            pass  # strobe-free: the strobes stay dark
        elif nxt is not None and nxt.section == "drop" and d.section != "drop":
            left = d.end - t
            span = d.end - d.start
            if 0 < left < max(span * 0.25, 4 * period):
                every = 0.5 if left < 4 * period else 1.0  # beats between flashes
                while every * period < 1.0 / max_hz:  # photosensitivity: the set's flash limit
                    every *= 2
                since = ((beat + phase) % every) * period
                dim = 0.6 + 0.4 * (1 - left / max(span * 0.25, 4 * period))
                gate, hz = math.exp(-since / 0.06), min(1.0 / (every * self._beat_s()), max_hz)
        elif d.section == "drop" and d.intensity >= 2:  # the big hits, on the kick (the flash timeline)
            dim = _decay(self.flash_t, self.flash_s, t, 0.06)
        wash = self._strobe_wash(d, t) if base is not None and hz == 0.0 else 0.0
        for e in strobes:
            if wash > 0 and e["id"] in self._strobe_rgb:  # the wash, the flash white on top of it
                col = base if d.par_base != "sides" or float(e.get("x", 0.5)) <= 0.5 else accent
                lvl = max(wash, dim)
                w = dim / lvl if lvl > 0 else 0.0
                r, g, b = _lerp(col, (1.0, 1.0, 1.0), w)
                out[e["id"]] = State(dimmer=lvl, r=r, g=g, b=b)
                continue
            out[e["id"]] = State(dimmer=dim, r=1.0, g=1.0, b=1.0, strobe_hz=hz, gate=gate)

    def _strobe_wash(self, d: Decision, t: float) -> float:
        """How bright a colour strobe washes in this look: the pars' glow between hits (none when the pars wait
        dark), rising with them in a build-up."""
        level = PAR_BASE_LEVEL.get(d.par_base, 0.0) * STROBE_WASH
        if d.dynamics == "rise":
            progress = min(max((t - d.start) / max(d.end - d.start, 1e-6), 0.0), 1.0)
            level = level * (0.45 + 0.55 * progress) + 0.15 * progress
        return level

    def _has_colour(self, e: dict) -> bool:
        """Does this fixture mix colour (red/green/blue or cyan channels in its mode)?"""
        fx = next((f for f in self.rig["fixtures"] if f["id"] == e["fixture"]), None)
        if fx is None:
            return False
        try:
            defn = fxlib.get(fx["fixture"])
            attrs = {c["attr"] for c in fxlib.channels(defn, fx["mode"])}
        except (KeyError, ValueError, FileNotFoundError):
            return False
        return bool(attrs & {"red", "green", "blue", "cyan"}) and not fxlib.uv_only(defn)

    def _beat_s(self) -> float:
        """The track's beat: a strobe channel gets one steady rate, not every beat's own length."""
        if getattr(self, "_median_beat", None) is None:
            self._median_beat = float(np.median(np.diff(self.beats))) if len(self.beats) > 2 else 0.47
        return self._median_beat

    def _head_strobe_hz(self) -> float:
        """How often a head may flash (0: strobe-free)."""
        safety = self.rig["safety"]
        if safety.get("strobe_free"):
            return 0.0
        return FAST_STROBE_HZ if safety.get("allow_fast_strobe") else float(safety.get("max_flash_hz", 4.0))

    def head_strobe(self, d: Decision, t: float) -> float | None:
        """The heads' strobe at t: 1 while a flash is on, 0 between (None: strobe-free). Flashes on the beat grid,
        1/16 notes in a drop, 1/8 in a groove or a build, else on the beat, halved until the flash limit is kept."""
        hz = self._head_strobe_hz()
        if hz <= 0:
            return None
        beat, phase, period = self.beat_info(t)
        div = self._strobe_notes(d, period, hz)
        # the flash opens half a frame before the grid line: the frame nearest the beat is the first one lit (from
        # the line on, the first lit frame came up to a whole frame after the beat, the strobe sounded late)
        half = 0.5 / float(self.rig["artnet"].get("fps", 40))
        since = ((beat + phase + half / period) * div % 1.0) / div * period
        return 1.0 if since < HEAD_STROBE_ON_S else 0.0

    @staticmethod
    def _strobe_notes(d: Decision, period: float, hz: float) -> float:
        """Flashes per beat: what the section asks, halved until the flash limit is kept."""
        div = float(HEAD_STROBE_DIV.get(d.section, 1))
        while div > 0.25 and div / max(period, 1e-3) > hz + 1e-6:
            div /= 2
        return div

    def _hammering(self, d: Decision, t: float) -> bool:
        """Is the hammer in its strobing bars at t? Counted from the start of the phrase."""
        return int((t - d.start) / (4 * self._beat_s())) // HAMMER_BARS % 2 == 1

    def head_strobe_rate(self, d: Decision) -> float:
        """How fast the heads strobe in this look, flashes a second (0: strobe-free)."""
        hz = self._head_strobe_hz()
        return self._strobe_notes(d, self._beat_s(), hz) / self._beat_s() if hz > 0 else 0.0

    def _layer(self, d: Decision, j: int) -> str | None:
        """Layering: 'base' (holds a soft glow) or 'accent' (plays the hits); None when not layered."""
        split = getattr(d, "layer_split", "none") if self.multi else "none"
        if split == "none":
            return None
        hg = self.hgroup[j]
        k, m = hg["k"], hg["m"]
        if split == "alternate":  # every other section (or pair), so left and right stay alike
            return "base" if self.layer_base.get(self.heads[j]["id"], k % 2) else "accent"
        if split == "inner_outer":
            own = (k / max(m - 1, 1)) * 2 - 1 if m > 1 else 0.0
            return "base" if abs(own) > 0.5 else "accent"
        if split == "high_low":
            return "base" if self.head_pos[j][2] > self._z_median else "accent"
        if split == "featured":
            return "accent" if self._featured(d, j) else "base"
        return None

    def _grouping(self, d: Decision) -> str:
        """How the heads' groups act in this look. A rig with one group of heads acts as one, but it can still play
        a solo: one mirrored pair lit, the rest dark (it needs two pairs at least)."""
        if self.multi:
            return d.grouping
        return "solo" if d.grouping == "solo" and len(self.head_pairs) >= 2 else "unison"

    def _featured(self, d: Decision, j: int) -> bool:
        if not self.multi:  # one group: the solo goes round the pairs, a phrase each
            return self.heads[j]["id"] in self.head_pairs[d.phrase % len(self.head_pairs)]
        hg = self.hgroup[j]
        return d.featured in (hg["cls"], hg["name"])

    def _role(self, d: Decision, j: int) -> dict:
        """What head j does in this decision: its movement/formation and the scope its formation is
        measured in (the whole rig, or its own group)."""
        n = len(self.heads)
        grouping = self._grouping(d)
        mv, f = d.movement, d.formation
        if grouping == "split" and not self._featured(d, j):
            mv, f = d.movement2, d.formation2
        elif grouping == "solo" and not self._featured(d, j):
            mv, f = "still", "sync"
        if grouping == "unison" or not self.multi:
            side = (j / max(n - 1, 1)) * 2 - 1 if n > 1 else 0.0
            return {
                "movement": mv,
                "formation": f,
                "idx": j,
                "count": n,
                "side": side,
                "vside": 0.0,
                "centre": None,
                "width": self.stage["width_m"],
                "phase": 0.0,
                "seed": None,
            }
        hg = self.hgroup[j]
        k, m = hg["k"], hg["m"]
        own = (k / max(m - 1, 1)) * 2 - 1 if m > 1 else 0.0
        if hg["kind"] == "column":  # a tower: left/right comes from the tower, the stack spreads in height
            side, vside = (1.0 if hg["gside"] > 0 else -1.0), own
        else:
            side, vside = own, 0.0
        phase, seed = 0.0, None
        if grouping == "individual":  # every head its own timing and path
            phase, seed = ((j * 0.618034) % 1.0) * 8.0, j + 1
        return {
            "movement": mv,
            "formation": f,
            "idx": k,
            "count": m,
            "side": side,
            "vside": vside,
            "centre": self.group_centre[hg["g"]],
            "width": max(self.group_width[hg["g"]], 1.0),
            "phase": phase,
            "seed": seed,
        }

    # ------------------------------------------------------------ scenes

    def _colours(self, d: Decision):
        return PALETTES.get(self._palette_of(d), PALETTES["cool"])[1]

    def _palette_of(self, d: Decision) -> str:
        """The phrase's palette; with little colour variety (the show arc's knob) one palette is kept for two or
        four phrases, but a drop still brings its own."""
        v = getattr(self, "colour_variety", None)
        if v is None or v >= COLOUR_HOLD[-1][0]:
            return d.palette
        hold = next(n for below, n in COLOUR_HOLD if v < below)
        i = d.phrase
        anchor = max([i - i % hold, *(k for k in self.drop_idx if i - i % hold < k <= i)])
        return self.plan[anchor].palette if 0 <= anchor < len(self.plan) else d.palette

    def _colour_swap(self, d: Decision, t: float, progress: float) -> bool:
        """Base and accent change places: halfway through a long phrase (as designed); with a lot of colour
        variety every eight bars, with little never."""
        v = getattr(self, "colour_variety", None)
        if v is not None and v >= COLOUR_BUSY:
            return (self.bar_info(t) // 8) % 2 == 1
        if v is not None and v < COLOUR_HOLD[-1][0]:
            return False
        return progress >= 0.5 and (d.end - d.start) > 20

    def _trigger(self, name: str, d: Decision | None = None, t: float = 0.0):
        return {
            "eighths": (self.eighth_t, self.eighth_s),
            "sixteenths": (self.sixteenth_t, self.sixteenth_s),
            "synth": (self.synth_t, self.synth_s),
            "kick": (self.kick_t, self.kick_s),
            "backbeat": (self.snare_t, self.snare_s),
            "hats": (self.hat_t, self.hat_s),
            "accents": (self.acc_t, self.acc_s),
            "bars": (self.downbeat_times, self.downbeat_s),
            "lead": (self.lead_t, self.lead_s),
        }[name]

    def _note(self, name: str, t: float) -> tuple[float, int]:
        """The light of a trigger, played as notes (timing.note_env); fast triggers play the kick."""
        name = "kick" if name in KICK_LED or name in TWO_VOICES else name  # dembow, drums: the kick is the boom
        if name == "kick" and (brk := self._break_at(t)) is not None:  # the kick is out: hold and build
            start, end, _ = brk
            return BREAK_FROM + (BREAK_TO - BREAK_FROM) * _ease((t - start) / max(end - start, 1e-6)), -1
        times, strengths = self._trigger(name)
        env, hit = note_env(times, strengths, t, *self._hit_shape())
        if name == "kick" and (hit < 0 or t - float(times[hit]) > NO_KICK_S):
            nxt = bisect.bisect_right(times, t)
            if nxt >= len(times) or float(times[nxt]) - t > 0.5 * NO_KICK_S:  # no kick around: hold, don't blink
                return 0.6, -1
        return env, hit

    def _hit_shape(self) -> tuple[float, float]:
        """How long a hit holds and lets go at most: short shots in a hard style, else notes."""
        return (SHORT_HOLD_S, SHORT_RELEASE_S) if getattr(self, "short_hits", False) else (0.6, 0.8)

    def _run_units(self, kind: str) -> dict[str, tuple[int, int]]:
        """Per light (pars or heads) its place in a run, (k, n): the mirrored pairs from the middle out, in at most
        RUN_STEPS shares."""
        cache = self.__dict__.setdefault("_run_cache", {})
        if kind not in cache:
            items = self.pars if kind == "par" else self.heads
            ids = [e["id"] for e in items]
            units = sections.parts(self.sections, math.inf, ids)
            if kind == "par":
                n = max(len(self.pars) - 1, 1)
                x = {e["id"]: self.order.get(e["id"], k) / n for k, e in enumerate(self.pars)}
            else:
                xs = [float(p[0]) for p in self.head_pos] or [0.0]
                lo, hi = min(xs), max(xs)
                x = {e["id"]: (float(self.head_pos[k][0]) - lo) / max(hi - lo, 1e-6) for k, e in enumerate(items)}
            units.sort(key=lambda u: float(np.mean([abs(x[e] - 0.5) for e in u])))
            steps = min(len(units), RUN_STEPS)  # small groups: a share of the rig per step, never a lone pair
            cache[kind] = {e: (k * steps // len(units), steps) for k, u in enumerate(units) for e in u}
        return cache[kind]

    def _run_notes(self, n: int) -> np.ndarray:
        """The synth's notes a run of n steps steps on: at least RUN_NOTE_S apart, and so far apart that a light
        (lit every n steps) never flashes within MIN_GAP_S."""
        cache = self.__dict__.setdefault("_run_note_cache", {})
        if n not in cache:
            gap, keep, last = max(RUN_NOTE_S, MIN_GAP_S / n), [], -1e9
            for x in self.lead_t:
                if x - last >= gap:
                    keep.append(float(x))
                    last = x
            cache[n] = np.asarray(keep)
        return cache[n]

    def run(self, d: Decision, t: float, eid: str, kind: str) -> float | None:
        """The run's light for one light at t (0..1), or None where it can't run (one unit: play the kick)."""
        k, n = self._run_units(kind).get(eid, (0, 1))
        if n < 2:
            return None
        prev = self.plan[d.phrase - 1] if 0 < d.phrase <= len(self.plan) else None
        if prev is not None and t - d.start < MIN_GAP_S and "run" in (prev.par_accent, prev.head_light):
            return 0.0  # a run after a run: a breath first (the other count could hit a light twice)
        div = RUN_DIV.get(d.section)
        if div is None:  # no kick to run on: a step per note of the synth
            notes = self._run_notes(n)
            i = bisect.bisect_right(notes, t) - 1
            if i < 0 or t - float(notes[i]) > RUN_STAB_S:
                return 0.0
            lit, dt = i % n == k, t - float(notes[i])
        else:
            beat, phase, period = self.beat_info(t)
            nxt = self.plan[d.phrase + 1] if d.phrase + 1 < len(self.plan) else None
            if nxt is not None and nxt.section == "drop" and d.end - t < period:
                return 0.0  # the beat before a drop is dark: then the bang (a shot there would be a blink)
            hz = self._head_strobe_hz() or float(self.rig["safety"].get("max_flash_hz", 4.0))
            hz = min(hz, 1.0 / MIN_GAP_S)  # a light flashes once a lap: never faster than this

            def notes(div: int) -> int:  # halved until each light keeps the limit
                while div > 1 and div / period / n > hz:
                    div //= 2
                return div

            div = notes(div)
            step = beat * div + int(phase * div)
            if d.section == "buildup":  # twice as fast from halfway, the count going on (no light hit twice)
                half = self.beat_info(d.start + 0.5 * (d.end - d.start))[0] + 1
                fast = notes(2 * div)
                if beat >= half and fast > div:
                    step = half * div + (beat - half) * fast + int(phase * fast)
                    div = fast
            lit, dt = step % n == k, (phase * div - int(phase * div)) * period / div
        return envelope_release(dt, 1.0, RUN_HOLD_S, RUN_RELEASE_S) if lit else 0.0

    def _voices_of(self, trigger: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """The two voices' hits (boom times, strengths, tac times, strengths): reggaeton's boom-tac, or cumbia's
        boom and cha."""
        if trigger == "cumbia":
            return (*self.dance_boom, *self.dance_cha)
        return self.boom_t, self.boom_s, self.tac_t, self.tac_s

    def _boom_tac(self, t: float, trigger: str = "dembow") -> tuple[float, float, float]:
        """Reggaeton's two voices, (boom, tac, pause): the boom (the kick, its 1/8 runs too) and the tac (the
        snare on its pattern), call and response: each lets go quickly when the other one hits. In a breather
        (the beat gone for a moment) both pause (`pause` 0..1); the beat's return hits with both voices. Cumbia
        plays its boom and its cha the same way."""
        boom_t, boom_s, tac_t, tac_s = self._voices_of(trigger)
        boom, bi = note_env(boom_t, boom_s, t)
        tac, ti = note_env(tac_t, tac_s, t)
        last_boom = float(boom_t[bi]) if bi >= 0 else -1e9
        last_tac = float(tac_t[ti]) if ti >= 0 else -1e9
        if last_tac > last_boom:
            boom *= _release(t - last_tac, 1.0, 0.0, BOOM_TAC_HANDOVER_S)
        else:
            tac *= _release(t - last_boom, 1.0, 0.0, BOOM_TAC_HANDOVER_S)
        k = bisect.bisect_right(self._breather_starts, t) - 1
        pause = 0.0
        if k >= 0 and t < self.breathers[k][1]:
            pause = _ease((t - self.breathers[k][0]) / BREATHER_FADE_S)
            boom, tac = boom * (1 - pause), tac * (1 - pause)
        elif k >= 0 and abs(last_boom - self.breathers[k][1]) < 0.1:  # the beat is back: both voices, together
            tac = max(tac, boom)
        return boom, tac, pause

    def _dance_colour(self, cols, voice: str, slot: int, t: float, trigger: str) -> tuple:
        """Cumbia's colour for a light in its voice: its section's own colour of the palette (the cha a step on from
        the boom), moving on to the next as the bar of the voice's last hit changes, so a light changes colour as it
        hits, never while it glows."""
        boom_t, _, tac_t, _ = self._voices_of(trigger)
        times = tac_t if voice == "tac" else boom_t
        i = bisect.bisect_right(times, t) - 1
        bar = self.bar_info(float(times[i]) if i >= 0 else t)
        cv = self.colour_variety
        if cv is not None and cv < 0.5:  # little colour variety: a slower dance through the colours
            bar //= DANCE_SLOW_BARS
        return cols[(slot + bar + (1 if voice == "tac" else 0)) % len(cols)]

    def _kick_run(self, t: float) -> tuple[dict[str, float], bool] | None:
        """In a kick run: every boom-tac light's level (0..1), and whether the run has landed (then the lights
        are all hit together, each in its own voice's colour; before, the waterfall plays in the accent colour).
        Left to right and back again, a run each way in turn. None outside the runs."""
        runs = getattr(self, "kick_runs", None)
        lead = KICK_RUN_LEAD_S  # (a frame early: the boom's own hit on the first kick never shows)
        hit = runs.at(t + lead, KICK_RUN_WAIT_S + lead) if runs else None
        if hit is None:
            return None
        i, r = hit
        steps = self._run_steps(min(len(r.t), KICK_RUN_STEPS))
        over = (r.land if r.land is not None else r.end) + KICK_RUN_LAND_HOLD_S + KICK_RUN_LAND_RELEASE_S
        if t >= over:  # let go: the glow waits for the beat's next hit (boom-tac taking over mid-note pops on)
            nxt_hit = min(
                (float(x[j]) for x in (self.boom_t, self.tac_t) if (j := bisect.bisect_left(x, over)) < len(x)),
                default=over,
            )
            return ({eid: KICK_RUN_GLOW for eid in steps}, True) if t < nxt_hit - 0.005 else None
        n = max(steps.values(), default=0) + 1
        k = bisect.bisect_right(r.t, t + lead) - 1
        level = [0.0] * n
        nxt = [*r.t[1:], r.land if r.land is not None else r.end + 0.5]
        for j in range(max(0, k - n + 1), k + 1):  # the last few kicks: the lit group and the ones falling
            step = j % n if i % 2 == 0 else n - 1 - j % n
            hold = KICK_RUN_HOLD * (float(nxt[j]) - float(r.t[j]))
            level[step] = max(level[step], _release(max(0.0, t - float(r.t[j])), 1.0, hold, KICK_RUN_RELEASE_S))
        landed = r.land is not None and t >= r.land
        if landed:
            land = _release(t - r.land, 1.0, KICK_RUN_LAND_HOLD_S, KICK_RUN_LAND_RELEASE_S)
            level = [max(v, land) for v in level]
        return {eid: max(KICK_RUN_GLOW, level[s]) for eid, s in steps.items()}, landed

    def _run_steps(self, n: int) -> dict[str, int]:
        """The boom-tac lights in n groups across the rig, left to right: lights at one place (a tower, a pair
        of pars side by side) in one group."""
        cache = self.__dict__.setdefault("_run_steps_cache", {})
        if n not in cache:
            xs = self._light_xs()
            places = sorted({round(x / 0.3) for x in xs.values()})  # 30 cm apart: one place
            m = max(1, min(n, len(places)))
            at = {p: k * m // len(places) for k, p in enumerate(places)}
            cache[n] = {eid: at[round(x / 0.3)] for eid, x in xs.items()}
        return cache[n]

    def _light_xs(self) -> dict[str, float]:
        """Every par and head and where it stands across the stage (m): pars by their order, heads by where they
        hang."""
        if "_light_x" not in self.__dict__:
            n = max(len(self.pars) - 1, 1)
            width = float(self.stage.get("width_m", 8.0))
            xs = {e["id"]: self.order.get(e["id"], k) / n * width for k, e in enumerate(self.pars)}
            xs.update({e["id"]: float(self.head_pos[k][0]) for k, e in enumerate(self.heads)})
            self._light_x = xs
        return self._light_x

    def _kit_voices(self, t: float) -> tuple[float, float, float]:
        """The kit's two voices, (kick, snare, 0): each drum as notes, the kick held as long as it sounds, the
        snare released over its ring (its reverb). Where neither drum plays for a while both hold KIT_HOLD."""
        k = self.kit
        kick, ki = note_env(k.kick_t, k.kick_s, t)
        snare, si = ring_env(k.snare_t, k.snare_s, k.snare_ring, t)
        last = max(float(k.kick_t[ki]) if ki >= 0 else -1e9, float(k.snare_t[si]) if si >= 0 else -1e9)
        if t - last > NO_KICK_S:
            j, m = bisect.bisect_right(k.kick_t, t), bisect.bisect_right(k.snare_t, t)
            nxt = min(
                float(k.kick_t[j]) if j < len(k.kick_t) else 1e9, float(k.snare_t[m]) if m < len(k.snare_t) else 1e9
            )
            if nxt - t > 0.5 * NO_KICK_S:  # no drum around: hold, don't blink
                return KIT_HOLD, KIT_HOLD, 0.0
        return kick, snare, 0.0

    @property
    def _breather_starts(self) -> list[float]:
        if "_brs" not in self.__dict__:
            self._brs = [s for s, _ in self.breathers]
        return self._brs

    def _voice(self, d: Decision, eid: str) -> str:
        """Which voice of boom-tac a light plays in this phrase: "boom", "tac" or "both" (a rig of one light).
        Whole groups: the pars, and the heads by the class of their group (overhead, front, towers …; with one
        class, by group), the units taking turns; one unit is split left/right. The roles hold all track long (a
        section of the orchestra keeps its part; swapping them reads as a blink at every phrase)."""
        if "_voices" not in self.__dict__:
            classes = {}
            for g in self.groups:
                classes.setdefault(g["cls"], []).extend(g["ids"])
            heads = list(classes.values()) if len(classes) > 1 else [g["ids"] for g in self.groups]
            units = [u for u in [[p["id"] for p in self.pars], *heads] if u]
            if len(units) == 1:
                rank = {**self._x_rank(self.pars), **self._x_rank(self.heads)}
                units = [[e for e in units[0] if rank.get(e, 0) % 2 == k] for k in (0, 1)]
                units = [u for u in units if u]
            self._voices = {e: k % 2 for k, u in enumerate(units) for e in u}
            self._voices_one = len(units) == 1
        if self._voices_one:
            return "both"
        return "boom" if self._voices.get(eid, 0) == 0 else "tac"

    def _accents(self, d: Decision, t: float, out: dict, accent) -> None:
        """Accent lights flash on the synth's stabs, exactly on the note, in the accent colour (white in the
        big drops); dark in between. A single light layers the stabs over its rhythm."""
        players = self._accent_players(d, t)
        lights = self.__dict__.get("_lights_by_x", [])
        solo = len(lights) == 1 and d.section in ACCENT_SECTIONS and d.intensity >= 1
        if not players and not solo:
            return
        fam = self.accent_family[d.phrase] if 0 <= d.phrase < len(self.accent_family) else ""
        if fam == "guitar":  # a strum rings a little longer than a stab
            v = stab_env(self.stab_t, self.stab_s, t, STRUM_HOLD_S, STRUM_RELEASE_S)
        else:
            v = stab_env(self.stab_t, self.stab_s, t)
        col = (1.0, 1.0, 1.0) if d.section == "drop" and d.intensity >= 3 else accent
        dark = self._dark_heads(d)  # heads the look keeps dark stay dark on the stabs too
        for eid in players or lights:
            if eid in dark:
                continue
            s = out[eid]
            if solo:
                if v > s.dimmer:
                    s.dimmer, (s.r, s.g, s.b) = v, col
            else:
                s.dimmer, (s.r, s.g, s.b), s.white = v, col, 0.0

    def _dark_heads(self, d: Decision) -> set[str]:
        """The heads this look keeps dark: all of them while the pars carry the look alone, the others in a solo."""
        if d.head_light == "off" and self.pars:
            return {e["id"] for e in self.heads}
        if self._grouping(d) == "solo":
            return {e["id"] for j, e in enumerate(self.heads) if not self._featured(d, j)}
        return set()

    def _break_at(self, t: float):
        """The kick break t falls in, if any: (start, end, kick_returns)."""
        k = bisect.bisect_right(self._break_starts, t) - 1
        if k >= 0 and t < self.kick_breaks[k][1]:
            return self.kick_breaks[k]
        return None

    @property
    def _break_starts(self) -> list[float]:
        if "_bs" not in self.__dict__:
            self._bs = [b[0] for b in self.kick_breaks]
        return self._bs

    def _kick_return(self, t: float, states: dict[str, State], skip=frozenset()) -> None:
        """The kick comes back after a break: a breath of darkness just before (after a break of two bars or
        more), then everything hits on the downbeat: full, with a white flash, settling over one beat. A real
        drop has its own, bigger moment (_drop_moment), and inside a snare roll the lights play the roll."""
        d = self.decision_at(t)[1]
        if not self.kick_breaks or self._roll_at(t) is not None or d.trigger in TWO_VOICES or d.par_accent == "run":
            return  # (boom-tac has its own breathers; the kit plays the drums' break and return itself; a run: shots)
        _, _, period = self.beat_info(t)
        k = bisect.bisect_right(self._break_starts, t)  # breaks that started before t
        for start, end, returns in self.kick_breaks[max(0, k - 1) : k + 1]:
            if not returns or any(abs(dr - end) < 4 * period for dr in self.drops):
                continue
            if end - start >= 8 * period and 0 < end - t < period * 0.5:
                for s in states.values():
                    s.dimmer, s.white = 0.0, 0.0
                return
            since = t - end
            if 0 <= since < period:
                boost, flash = 1.0 - since / period, math.exp(-since / 0.15)
                blinders = set(self.blinder_ids)  # (they keep to the heaviest moments: engine/blinders.py)
                for eid, s in states.items():
                    if eid in blinders or eid in skip:
                        continue
                    s.dimmer = max(s.dimmer, boost)
                    s.white = max(s.white, flash)
                return

    def _block(self, d: Decision, t: float | None) -> int:
        """Which 4-bar block of its phrase t is in, where the music moves fast (grooves, build-ups and drops with
        some energy: the group changes how it plays every 4 bars there); 0 elsewhere (once per phrase)."""
        if t is None or d.section not in ACCENT_SECTIONS or d.intensity < 1:
            return 0
        _, _, period = self.beat_info(t)
        return max(0, int((t - d.start) / (BLOCK_BARS * 4 * period)))

    def _accent_players(self, d: Decision, t: float | None = None) -> set[str]:
        """The lights that play the accents in this phrase: one in ACCENT_SHARE (heads and pars together, by whole
        sections or mirrored pairs, so a model plays as one and left and right stay alike; of two lights one),
        shifting per phrase. None in calm parts or where the synth has no stabs; a single light plays both (_scene
        layers the stabs over its rhythm)."""
        if d.section not in ACCENT_SECTIONS or d.trigger in ("dembow", "cumbia"):  # boom-tac: the tac is the accent
            return set()
        if d.par_accent == "run" or d.head_light == "run":  # the run plays the accents (two rhythms on a light:
            return set()  # flicker)
        if d.intensity < 1 and d.trigger != "drums":  # (a band's guitar is followed in a calm verse too)
            return set()
        a, b = bisect.bisect_left(self.stab_t, d.start), bisect.bisect_left(self.stab_t, d.end)
        if b - a < MIN_STABS:
            return set()
        lights = self.__dict__.get("_lights_by_x")
        if lights is None:
            both = [(e["id"], k, "par") for k, e in enumerate(self.pars)] + [
                (e["id"], k, "head") for k, e in enumerate(self.heads)
            ]
            n = max(len(self.pars) - 1, 1)
            width = float(self.stage.get("width_m", 8.0))

            def x(item):  # pars by their order across the stage, heads by where they hang
                eid, k, kind = item
                return float(self.head_pos[k][0]) if kind == "head" else self.order.get(eid, k) / n * width

            lights = self._lights_by_x = [eid for eid, _, _ in sorted(both, key=x)]
        if len(lights) < 2:
            return set()
        share = 2 if len(lights) < 4 else ACCENT_SHARE
        shares = self.__dict__.get("_accent_shares")
        if shares is None:
            units = sections.parts(self.sections, share, lights)
            if len(units) < 2:  # one pair and nothing else: the two lights share the part
                units = [[eid] for eid in lights]
            shares = self._accent_shares = sections.share_out(units, min(share, len(units)))
        share = len(shares)
        shift = (d.phrase + self._block(d, t)) % share  # the roles move on every 4 bars in energetic parts
        if d.trigger == "drums":  # a band: the guitar's lights keep their part, like the kit's groups (a swap
            shift = 0  # lands a light in the middle of the other part's note: a blink)
        return set(shares[(share // 2 - shift) % share])

    def _kick_pattern(self, d: Decision, t: float | None = None) -> str:
        """How the group plays the kicks: varied per phrase, and every 4 bars where the music moves fast; mostly
        tutti in the big drops."""
        options = DROP_PATTERNS if d.section == "drop" and d.intensity >= 3 else KICK_PATTERNS
        return options[int(_hash(d.phrase, self._block(d, t), 5) * len(options))]

    def _init_sections(self, rig: dict):
        """The rig's sections (rig/sections.py) and what the show hands out by them: per light its slot among the
        heads' or the pars' sections, for whoever takes turns; per par its place among the mirrored pairs."""
        self.sections = sections.rig_sections(rig)
        heads, pars = [e["id"] for e in self.heads], [e["id"] for e in self.pars]
        self.turn: dict[str, tuple[int, int]] = {}
        for ids in (heads, pars):
            units = sections.parts(self.sections, 2, ids)
            if len(units) >= 2:  # (one pair and nothing else: its lights take turns with each other)
                self.turn |= {eid: (k, len(units)) for k, u in enumerate(units) for eid in u}
        pairs = sections.parts(self.sections, math.inf, pars)
        self.par_pair = {eid: (k, len(pairs)) for k, u in enumerate(pairs) for eid in u}
        units = sections.parts(self.sections, 2, heads)
        base = sections.share_out(units, 2)[1] if len(units) >= 2 else []
        self.layer_base = {eid: eid in base for eid in heads} if base else {}
        self.head_pairs = sections.parts(self.sections, math.inf, heads)  # mirrored pairs of heads (solos)
        at = {eid: j for j, eid in enumerate(heads)}
        self.camera_parts = [[at[eid] for eid in u] for u in sections.parts(self.sections, CAMERA_UNITS, heads)]

    def _turn(self, pattern: str, eid: str, k: int, n: int) -> tuple[int, int]:
        """A light's place in a kick pattern: its section's or pair's slot, so a pattern splits the rig by sections
        with left and right alike; `sides` plays left against right, by where it stands."""
        return (k, n) if pattern == "sides" else self.turn.get(eid, (k, n))

    def _colour_wave(self, t: float, rank: int, n: int) -> float:
        """How much of the wave's colour a head shows (0..1): the crest starts on the downbeat at the stage-left end
        and crosses the row in WAVE_SPREAD of the bar (back from stage right the bar after); each head plays it as
        a note: on as it arrives, held, let go gently. Colour only: the beams' level stays the look's."""
        bars = self.downbeat_times
        k = bisect.bisect_right(bars, t) - 1
        place = rank / (n - 1) if n > 1 else 0.0
        v = 0.0
        for b in (k - 1, k):  # (the bar before's crest may still be letting go)
            if b < 0:
                continue
            start = float(bars[b])
            length = float(bars[b + 1]) - start if b + 1 < len(bars) else 4 * self._beat_s()
            beat = length / 4
            r = place if b % 2 == 0 else 1.0 - place
            dt = t - start - r * WAVE_SPREAD * length
            if dt >= 0:
                v = max(v, _release(dt, 1.0, WAVE_HOLD * beat, WAVE_RELEASE * beat))
        return v

    def _wheel_wave(self, d, t: float, eid: str, rank: int, n: int, base, crest) -> tuple:
        """A wheel head's colour in a colour wave: the look's, or the slot next to it nearest the wave's colour. A
        wipe once a bar from stage left, there in one bar and back the next; the phrase starts and ends in the
        look's colour."""
        from amadeus.engine.wheels import travel_s

        w = self.wheel_heads[eid]
        slots, home = w.slots, w.index(base)
        k = len(slots)

        def other(way: int) -> int:  # the next slot round the wheel that is another colour (wheels repeat colours)
            i = home
            for _ in range(k - 1):
                i = (i + way) % k
                if tuple(slots[i]["rgb"]) != tuple(slots[home]["rgb"]):
                    return i
            return home

        def gap(i: int) -> float:
            return sum((a - b) ** 2 for a, b in zip(slots[i]["rgb"], crest, strict=False))

        near = min((other(-1), other(1)), key=lambda i: (gap(i), travel_s(k, w.slot_s, home, i)))
        colours = (tuple(slots[home]["rgb"]), tuple(slots[near]["rgb"]))
        if near == home:
            return colours[0]
        bars = self.downbeat_times
        k0 = bisect.bisect_left(bars, d.start - 0.02)
        b = bisect.bisect_right(bars, t) - 1
        place = rank / (n - 1) if n > 1 else 0.0

        def switch(bar: int) -> float:  # when the wipe reaches this head in a bar: always from stage left (there
            # and back, the end heads would turn twice at once and never show the colour), on the beat nearest
            # (the wheels hide a turn in the gaps the beat makes; between beats they would have to make one)
            start = float(bars[bar])
            length = float(bars[bar + 1]) - start if bar + 1 < len(bars) else 4 * self._beat_s()
            at = start + place * WAVE_SPREAD * length
            i = bisect.bisect_left(self.beats, at)
            near = [float(self.beats[j]) for j in (i - 1, i) if 0 <= j < len(self.beats)]
            return min(near, key=lambda x: abs(x - at), default=at)

        def plays(bar: int) -> bool:  # a pass there only when the pass back fits in the phrase too: the phrase
            # ends in the look's colour (a wheel left in the wave's would have to turn as the next look hits)
            if (bar - k0) % 2:
                return True
            return bar + 1 < len(bars) and switch(bar + 1) < d.end - 0.1

        now = 0  # passes made: the colour is the look's after an even number
        for bar in range(max(k0, b - 1), b + 1):
            if 0 <= bar < len(bars) and plays(bar - (bar - k0) % 2) and t >= switch(bar):
                now = bar - k0 + 1
        return colours[now % 2]

    def _x_rank(self, elements: list[dict]) -> dict[str, int]:
        """Elements ranked left to right (cached per list)."""
        cache = self.__dict__.setdefault("_x_ranks", {})
        key = id(elements)
        if key not in cache:
            xs = {e["id"]: (self.order.get(e["id"], k) if elements is self.pars else float(self.head_pos[k][0]))
                  for k, e in enumerate(elements)}  # fmt: skip
            cache[key] = {eid: r for r, eid in enumerate(sorted(xs, key=lambda e: xs[e]))}
        return cache[key]

    def _scene(self, d: Decision, t: float) -> dict[str, State]:
        """Render one look from its layers: par base, par accent, trigger, head light/colour, dynamics."""
        cols = self._colours(d)
        base, accent = cols[0], cols[2 % len(cols)]
        n = len(self.pars)
        beat, phase, _ = self.beat_info(t)
        bar = self.bar_info(t)
        progress = min(max((t - d.start) / max(d.end - d.start, 1e-6), 0.0), 1.0)
        if self._colour_swap(d, t, progress):  # long phrase: swap colours halfway for variation
            base, accent = accent, base
        env, hit = self._note(d.trigger, t)
        dembow = d.trigger in TWO_VOICES  # two voices, by whole groups: boom-tac, or the kit's kick and snare
        if d.trigger == "drums":
            boom, tac, pause = self._kit_voices(t)
        else:
            boom, tac, pause = self._boom_tac(t, d.trigger) if dembow else (env, 0.0, 0.0)
        dance = d.trigger == "cumbia"  # cumbia: each section in its own colour, on to the next every bar
        run = self._kick_run(t) if d.trigger == "dembow" else None  # the kick leaves the dembow: a waterfall
        hits = hit + 1  # hits so far: steps chases, alternation, sparkles
        pattern = self._kick_pattern(d, t)
        flash = _decay(self.flash_t, self.flash_s, t, 0.07)
        rise = d.dynamics == "rise"
        out: dict[str, State] = {}

        base_level = PAR_BASE_LEVEL[d.par_base]
        bounce = (hits % (2 * n - 2)) if n > 1 else 0
        chase_pos = bounce if bounce < n else 2 * n - 2 - bounce
        loop = getattr(self, "par_loop", False) and n > 2  # pars round a full ring: the chase runs round it
        if loop:
            chase_pos = hits % n
        pairs = next(iter(self.par_pair.values()))[1] if self.par_pair else 1
        sparkle = (hits * 7 + 3) % max(pairs, 1)
        for f in self.pars:
            k = self.order[f["id"]]
            pair = self.par_pair.get(f["id"], (k, n))[0]  # mirrored pars play as one
            slot = self.turn.get(f["id"], (k, n))[0]
            col = _mix(cols, ((beat + phase) / 32 + pair / pairs) % 1.0) if d.par_base == "fade" else base
            acc = accent
            if d.par_base == "sides" and float(f.get("x", 0.5)) > 0.5:  # stage right in the accent, hits in the base
                col, acc = accent, base
            dim = base_level
            a = d.par_accent
            tac_voice = False
            if dembow and a not in ("none", "melody"):  # boom-tac: this par's voice
                low = min(base_level, BOOM_TAC_BASE) * (1 - (1 - BREATHER_GLOW) * pause)
                voice = self._voice(d, f["id"])
                if run is not None and f["id"] in run[0]:  # a kick run: the waterfall, then the landing
                    v = run[0][f["id"]]
                    col = (base if voice == "boom" else acc) if run[1] else acc
                    dim = low + (1 - low) * v
                elif dance:  # cumbia: its section's colour of the fiesta (one light: the boom's, the cha's)
                    one = voice if voice != "both" else ("tac" if tac > boom else "boom")
                    col = self._dance_colour(cols, one, slot, t, d.trigger)
                    dim = low + (1 - low) * {"boom": boom, "tac": tac}.get(voice, max(boom, tac))
                    tac_voice = voice == "tac"
                elif voice == "both":  # one light plays both: the boom, and the tac in the accent colour
                    col, dim = _lerp(col, acc, tac), low + (1 - low) * max(boom, tac)
                elif voice == "boom":
                    dim = low + (1 - low) * boom
                else:
                    col, dim, tac_voice = acc, low + (1 - low) * tac, True
            elif a in ("pulse", "stutter"):  # on its turn in the phrase's pattern ("stutter": older plans)
                on = kick_turn(pattern, *self._turn(pattern, f["id"], k, n), hit)
                dim = base_level + (1 - base_level) * (env if on else 0.0)
            elif a == "color_pop":
                col, dim = _lerp(col, acc, env), max(base_level, env)
            elif a == "run":  # a short shot stepping across the pairs (one pair: the kick)
                v = self.run(d, t, f["id"], "par")
                v = env if v is None else v
                col, dim = _lerp(col, acc, v), max(base_level, v)
            elif a == "chase":
                gap = abs(k - chase_pos)
                if loop:
                    gap = min(gap, n - gap)
                lit = env * max(0.0, 1.0 - gap * 0.7)  # lit par plus a short tail
                col, dim = _lerp(col, acc, min(1.0, lit * 1.5)), max(base_level, lit)
            elif a == "alternate":
                if slot % 2 == hits % 2:
                    col, dim = acc, max(base_level, 0.45 + 0.55 * env)
            elif a == "sparkle":
                if pair == sparkle:
                    col, dim = _lerp(col, acc, env), max(base_level, env)
            elif a == "melody":  # recent notes, each on the par of its pitch, coloured by its pitch class
                i = bisect.bisect_right(self.lead_t, t)
                for j in range(max(0, i - 6), i):
                    fr = self._frame(self.lead_t[j] + 0.03)
                    if round(float(self.lead_pitch[fr]) * (n - 1)) != k:
                        continue
                    glow = float(self.lead_s[j]) * math.exp(-(t - self.lead_t[j]) / MELODY_TAU)
                    if glow > dim:
                        pc = int(self.lead_pc[fr])
                        col, dim = (cols[pc % len(cols)] if pc >= 0 else acc), max(base_level, glow)
            if rise:  # brighter and whiter towards the drop
                col = _lerp(col, (1.0, 1.0, 1.0), 0.6 * progress**2)
                dim = dim * (0.45 + 0.55 * progress) + 0.15 * progress
            st = State(dimmer=dim, r=col[0], g=col[1], b=col[2])
            zoom = self._fixed_zoom(d, f["id"], progress)
            if zoom is not None:
                st.zoom = zoom
            if (d.dynamics == "impact" or rise) and not tac_voice and a not in ("run", "none"):  # (the flash is on
                st.white = flash  # the kick: the boom's; a run's shots are its hits, a flash on the kick a second
                # rhythm; pars that don't play the hits hold a steady wash under the beams)
            if run is not None and f["id"] in run[0]:  # a kick run: only the group on its kick flashes
                st.white *= run[0][f["id"]]
            out[f["id"]] = st

        acc_env = note_env(self.acc_t, self.acc_s, t)[0]  # big hits as notes: close ones held through
        head_trig = getattr(d, "head_trigger", "same")
        if head_trig not in ("same", d.trigger):  # layering: heads pulse on their own rhythm
            env, hit = self._note(head_trig, t)
        grouping = self._grouping(d)
        head_pattern = pattern if grouping == "unison" else "all"  # groups acting apart have their own roles
        rank, nh = self._x_rank(self.heads), len(self.heads)
        for j, f in enumerate(self.heads):
            role = self._role(d, j)
            hc = d.head_color
            if grouping == "split" and not self._featured(d, j):  # the counter-movement in a contrasting colour
                hc = {"base": "accent", "white": "accent", "accent": "base"}.get(hc, hc)
            cv = self.colour_variety
            step = bar // 4 if cv is not None and cv < 0.5 else bar  # little colour variety: a slower cycle
            slot = self.turn.get(f["id"], (j, nh))[0]  # a section plays as one, left and right alike
            cycle = cols[(slot + step) % len(cols)]
            side = base if self.head_pos[j][0] <= self.stage["width_m"] / 2 else accent  # stage left | stage right
            wave = None  # a colour wave's crest at this head (0..1)
            if hc in ("wave", "wave_accent"):  # the base colour, the wave's colour passing through
                wave = self._colour_wave(t, rank[f["id"]], nh)
                crest = accent if hc == "wave_accent" or min(base) >= WAVE_WHITE_BASE else (1.0, 1.0, 1.0)
                if f["id"] in getattr(self, "wheel_heads", {}):
                    col = self._wheel_wave(d, t, f["id"], rank[f["id"]], nh, base, crest)
                else:
                    col = _lerp(base, crest, wave)
            else:
                col = {"base": base, "accent": accent, "white": (1.0, 1.0, 1.0), "cycle": cycle, "sides": side}[hc]
            hl = d.head_light
            if hl == "off" and not self.pars:  # nothing else to carry the look: the heads keep a pulse
                hl = "pulse"
            if hl == "hammer":
                hl = "strobe" if self._hammering(d, t) else "pulse"
            on = kick_turn(head_pattern, *self._turn(head_pattern, f["id"], rank[f["id"]], nh), hit)
            mine = env if on else 0.0  # this head's kick
            gate = None  # strobing: the flash, applied last (the beam's level is worked out first)
            if role["movement"] == "pour" and hl != "off":  # the pour plays its own light: lit falling, dark rising
                dim = self.pour_light(d, t, j, role)
            elif hl == "strobe":  # white flashes on the beat grid; strobe-free: a pulse on the kick
                gate = self.head_strobe(d, t)
                dim, col = (1.0, (1.0, 1.0, 1.0)) if gate is not None else (0.25 + 0.75 * mine, col)
            elif hl == "flick":  # on around the beat, when the head arrives and turns; dark while travelling
                dim = 1.0 if (phase < 0.22 or phase > 0.85) else 0.0
            elif hl == "beat":  # on with the kick, held, let go: on/off (the phrase's pattern splits the group)
                dim = mine
            elif hl == "run":  # a short shot stepping across the heads' pairs (one pair: the kick)
                v = self.run(d, t, f["id"], "head")
                dim = env if v is None else v
                if d.section not in RUN_DIV:  # on the synth's notes: a glow between, the beams' moves show
                    dim = RUN_GLOW + (1 - RUN_GLOW) * dim
            elif hl == "alternate":  # sections take turns per kick (one section: its pairs)
                dim = env if (hit + self.turn.get(f["id"], (role["idx"], 0))[0]) % 2 == 0 else 0.0
            elif hl == "random":  # each head on its own random kicks: hit, held, let go
                dim = env if _chance(j, hit) and not _chance(j, hit - 1) else 0.0
            else:
                dim = {
                    "steady": 1.0,
                    "pulse": 0.25 + 0.75 * mine,
                    "accents": 0.12 + 0.88 * acc_env,
                    "breathe": 0.1 + 0.9 * float(self.breath[self._frame(t)]),
                    "stutter": 0.25 + 0.75 * mine,  # (older plans: a kick pulse now)
                    "off": 0.0,
                }.get(hl, 1.0)
            layer = self._layer(d, j)
            if layer == "base":  # a soft carpet of light in the base colour, under the accents
                glow = getattr(d, "base_glow", "low")
                dim = {"low": 0.18, "medium": 0.35}.get(glow, 0.1 + 0.35 * float(self.breath[self._frame(t)]))
                col = base
            elif layer == "accent" and hc == "base":
                col = accent  # accents stand out from the carpet
            if grouping == "solo" and not self._featured(d, j):
                dim = 0.0  # the others wait dark: one beam in the room
            elif grouping == "chase":  # one group lit per beat, in turn
                dim *= 1.0 if beat % max(len(self.groups), 1) == self.hgroup[j]["g"] else 0.12
            voice = self._voice(d, f["id"]) if dembow and hl != "off" else ""
            if voice:  # boom-tac: the head's group plays its voice (the tac in the accent colour)
                low = BOOM_TAC_HEAD_BASE * (1 - (1 - BREATHER_GLOW) * pause)
                dim = low + (1 - low) * {"boom": boom, "tac": tac}.get(voice, max(boom, tac))
                if dance:  # cumbia: its section's colour of the fiesta
                    one = voice if voice != "both" else ("tac" if tac > boom else "boom")
                    col = self._dance_colour(cols, one, slot, t, d.trigger)
                elif voice == "tac":
                    col = accent
                elif voice == "boom" and col == accent:
                    col = base
                if run is not None and f["id"] in run[0]:  # a kick run: the waterfall (accent), then the landing
                    dim = low + (1 - low) * run[0][f["id"]]
                    col = accent if not run[1] or voice == "tac" else base
            if rise:
                dim *= 0.4 + 0.6 * progress
            strobing = gate is not None and layer != "base" and not voice
            st = State(dimmer=dim, r=col[0], g=col[1], b=col[2])
            if strobing:
                st.strobe_hz, st.gate = self.head_strobe_rate(d), gate
            if d.dynamics == "impact" and d.head_light != "off" and voice != "tac" and not strobing:  # (the boom's)
                st.white = flash * (dim if role["movement"] == "pour" else 1.0)  # (a pour waits dark at the floor)
                if run is not None and f["id"] in run[0]:  # a kick run: only the group on its kick flashes
                    st.white *= run[0][f["id"]]
            st.fx = d.beam_fx
            featured = self._featured(d, j) if grouping in ("split", "solo") else None
            st.zoom = self._head_zoom(d, f["id"], role, layer, featured, progress)
            group = self.gobo_groups[j].get(d.gobo_style) or self.gobo_all[j]
            st.gobo = group[(d.phrase + bar // 4) % len(group)] - 1  # next gobo of the style every four bars
            st.fx_speed = 0.3 + 0.2 * max(0, min(3, d.intensity))  # calm: slow rotation, drops: fast
            st.fx_reverse = role["formation"] == "mirror" and role["side"] > 0  # mirrored heads turn opposite ways
            out[f["id"]] = st

        self._laser_states(d, t, out, env, acc_env, beat, phase, cols, base, accent, bar)
        self._blinder_states(d, t, out, acc_env)
        self._strobe_states(d, t, out, acc_env, base, accent)
        if getattr(d, "special", "off") == "stars":
            self._stars(d, t, out)
        self._accents(d, t, out, accent)
        self._uplight_states(d, t, out)  # (engine/uplights.py: their level is the phrase's, set just below)
        level = d.intensity if getattr(d, "brightness", -1) < 0 else d.brightness
        master = INTENSITY_MASTER[max(0, min(3, level))] * self.rig["safety"]["master"]
        for st in out.values():
            st.dimmer *= master
        return out

    def _star_lights(self) -> list[str]:
        """The lights that play the stars: one set of small ones, not the rig. The cells of one kind of pixel
        fixture (the one with the most; a second kind if that's under a dozen), else pars, else every other
        moving head."""
        if not hasattr(self, "_stars_cache"):
            model = {f["id"]: f["fixture"] for f in self.rig["fixtures"]}
            kinds: dict[str, list[str]] = {}
            for e in self.rig["elements"]:
                if "offset_m" in e and e["kind"] in ("par", "head") and not e.get("uplight"):
                    kinds.setdefault(model.get(e["fixture"], e["fixture"]), []).append(e["id"])
            cells: list[str] = []
            for ids in sorted(kinds.values(), key=len, reverse=True):
                if len(cells) >= 12:
                    break
                cells += ids
            self._stars_cache = cells or [e["id"] for e in self.pars] or [e["id"] for e in self.heads][::2]
        return self._stars_cache

    def _stars(self, d: Decision, t: float, out: dict) -> None:
        """A starfield over the show (a track about stars, director/themes.py): subtle accents. A set of small
        lights twinkles, each star at its own random moment (no shared beat: a whole rig stepping at once looks
        like a game dropping frames), coming up quickly, holding a moment and fading gently, in star white; the
        rest of the show plays on underneath. A few at a time in calm parts, more in a drop."""
        busy = d.section in ("drop", "buildup") or d.intensity >= 3
        lights = self._star_lights()
        rate = STAR_RATE_BUSY if busy else STAR_RATE  # new stars per second over the set, whatever its size
        share = min(0.6, rate * STAR_SLOT_S / max(len(lights), 1))
        slot0 = int(t // STAR_SLOT_S)
        for k, eid in enumerate(lights):
            st = out.get(eid)
            if st is None:
                continue
            v = 0.0
            for slot in (slot0 - 1, slot0):  # this light's star in this slot of time, and the one before
                if _hash(k, slot, 1) >= share:
                    continue
                t0 = (slot + 0.6 * _hash(k, slot, 2)) * STAR_SLOT_S  # at its own moment in the slot
                level = 0.6 + 0.4 * _hash(k, slot, 3)
                dt = t - t0
                if 0 <= dt < STAR_RISE_S:
                    v = max(v, level * dt / STAR_RISE_S)
                elif dt >= STAR_RISE_S:
                    v = max(v, envelope_release(dt - STAR_RISE_S, level, STAR_HOLD_S, STAR_RELEASE_S))
            if v > 0.01:  # a glint of star white (on a lit light the white is the star), at least as bright
                st.r, st.g, st.b = _lerp((st.r, st.g, st.b), (1.0, 0.97, 0.92), min(1.0, v * 1.2))
                st.dimmer = max(st.dimmer, v)

    def big_moment(self, t: float) -> bool:
        """A moment the surprises come out for (the show arc's special effects): a drop the analysis found, from
        the heads moving in black before it to the end of its phrase."""
        i = self.decision_at(t)[0]
        return i in self.drop_idx or self.in_drop_moment(t)

    def in_drop_moment(self, t: float) -> bool:
        """From the heads moving in black before a drop to the end of its first bar: timing nobody touches."""
        if not self.drops:
            return False
        _, _, period = self.beat_info(t)
        k = bisect.bisect_right(self.drops, t + PREDROP_BEATS * period)
        return k > 0 and -PREDROP_BEATS * period <= t - self.drops[k - 1] < 4 * period

    def _drop_moment(self, t: float, states: dict[str, State]) -> None:
        """What an operator does at a drop: a breath of darkness just before it, then everything hits.

        - last half beat before the drop (or the music's own pause before it, when longer): all lights dark
        - the first beat: a white flash on everything
        - the first bar: everything at full, settling into the drop's own look
        """
        size = 1.0 if self.drop_strength is None else self.drop_strength  # the show arc's "drops" knob
        if not self.drops or size <= 0.01:
            return
        k = bisect.bisect_right(self.drops, t)
        _, _, period = self.beat_info(t)
        if k < len(self.drops) and self._pause_dark(self.drops[k], t, period):
            if size >= DROP_DARK_FROM:  # smaller drops: no breath of darkness, a lift
                keep = 1.0 - min(1.0, (size - DROP_DARK_FROM) / (1.0 - DROP_DARK_FROM))
                for s in states.values():
                    s.dimmer, s.white = s.dimmer * keep, s.white * keep
            return
        if k == 0:
            return
        since = t - self.drops[k - 1]
        bar = period * 4
        if since < bar:
            boost = (1.0 - since / bar) * size  # full → the drop's own level over one bar
            flash = math.exp(-since / 0.18) * size  # one white hit on the downbeat
            blinders = set(self.blinder_ids)
            for eid, s in states.items():
                if eid in blinders:
                    continue  # blinders slam in at the heaviest drops only (blinder_level)
                s.dimmer = max(s.dimmer, boost)
                s.white = max(s.white, flash)
