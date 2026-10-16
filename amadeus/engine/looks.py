"""Looks: the colours, levels and hits of pars, heads, blinders and strobes for each phrase."""

from __future__ import annotations

import bisect
import math

from amadeus.director import Decision
from amadeus.director.vocabulary import PALETTES
from amadeus.engine.state import State
from amadeus.engine.timing import (
    BREAK_FROM,
    BREAK_TO,
    NO_KICK_S,
    STRUM_HOLD_S,
    STRUM_RELEASE_S,
    _decay,
    _ease,
    _release,
    note_env,
    ring_env,
    stab_env,
)

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

# The kit (the drums trigger, rock): the same two voices by whole groups, the kick and the snare, the snare's light
# ringing out with its reverb; the guitar's strums on the accent lights.
TWO_VOICES = ("dembow", "drums")
KIT_HOLD = 0.6  # no drum around (a drumless verse, a break): both voices hold this, steady, instead of going dark

ACCENT_SHARE = 3  # one light in this many plays the accents (the synth's stabs); the others keep the rhythm
ACCENT_SECTIONS = ("groove", "drop", "buildup", "verse", "chorus")
BLOCK_BARS = 4  # in energetic parts the group's kick pattern and the accent roles change this often
MIN_STABS = 3  # a phrase needs this many stabs before lights are given to them


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


MELODY_TAU = 0.7  # how long a melody note keeps its par lit


PAR_BASE_LEVEL = {"off": 0.0, "dim": 0.22, "full": 0.75, "fade": 0.5}


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
        """Blinders: the punch for the biggest moments only. Dark by default; on a main drop (intensity 3) the
        drop moment slams them in, then they flash on the big accents; a build into such a drop swells them up
        over its last two beats. Gentle drops leave them dark."""
        blinders = [e for e in self.rig["elements"] if e["kind"] == "blinder"]
        if not blinders:
            return
        _, _, period = self.beat_info(t)
        dim = 0.0
        i = d.phrase  # this look's own phrase (during a crossfade the previous look is rendered too)
        nxt = self.plan[i + 1] if i + 1 < len(self.plan) else None
        if d.section == "drop" and d.intensity >= 3:
            dim = max(0.0, (acc_env - 0.45) / 0.55)  # the big hits only
        elif d.dynamics == "rise" and nxt is not None and nxt.section == "drop" and nxt.intensity >= 3:
            left = d.end - t
            if left < 2 * period:
                dim = (1.0 - left / (2 * period)) ** 2 * 0.8  # swell into the drop
        for e in blinders:
            out[e["id"]] = State(dimmer=dim, r=1.0, g=0.72, b=0.42)
        self._blinder_ids = {e["id"] for e in blinders}

    def _strobe_states(self, d: Decision, t: float, out: dict, acc_env: float):
        """Strobes: flashes, never a steady light. Dark by default. A build-up into a drop flashes on the beat
        over its last quarter, twice per beat over its last bar (never faster than the set's max_flash_hz);
        in a drop (intensity 2+) they flash on the big hits, on the kick. The drop moment itself flashes
        everything anyway."""
        strobes = getattr(self, "_strobes", None)
        if strobes is None:
            strobes = self._strobes = [e for e in self.rig["elements"] if e["kind"] == "strobe"]
        if not strobes:
            return
        beat, phase, period = self.beat_info(t)
        i = d.phrase  # this look's own phrase (during a crossfade the previous look is rendered too)
        nxt = self.plan[i + 1] if i + 1 < len(self.plan) else None
        max_hz = float(self.rig["safety"].get("max_flash_hz", 3.0))
        dim = 0.0
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
                dim = math.exp(-since / 0.06) * (0.6 + 0.4 * (1 - left / max(span * 0.25, 4 * period)))
        elif d.section == "drop" and d.intensity >= 2:  # the big hits, on the kick (the flash timeline)
            dim = _decay(self.flash_t, self.flash_s, t, 0.06)
        for e in strobes:
            out[e["id"]] = State(dimmer=dim, r=1.0, g=1.0, b=1.0)

    def _layer(self, d: Decision, j: int) -> str | None:
        """Layering: 'base' (holds a soft glow) or 'accent' (plays the hits); None when not layered."""
        split = getattr(d, "layer_split", "none") if self.multi else "none"
        if split == "none":
            return None
        hg = self.hgroup[j]
        k, m = hg["k"], hg["m"]
        if split == "alternate":
            return "base" if k % 2 else "accent"
        if split == "inner_outer":
            own = (k / max(m - 1, 1)) * 2 - 1 if m > 1 else 0.0
            return "base" if abs(own) > 0.5 else "accent"
        if split == "high_low":
            return "base" if self.head_pos[j][2] > self._z_median else "accent"
        if split == "featured":
            return "accent" if self._featured(d, j) else "base"
        return None

    def _featured(self, d: Decision, j: int) -> bool:
        hg = self.hgroup[j]
        return d.featured in (hg["cls"], hg["name"])

    def _role(self, d: Decision, j: int) -> dict:
        """What head j does in this decision: its movement/formation and the scope its formation is
        measured in (the whole rig, or its own group)."""
        n = len(self.heads)
        grouping = d.grouping if self.multi else "unison"
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
        env, hit = note_env(times, strengths, t)
        if name == "kick" and (hit < 0 or t - float(times[hit]) > NO_KICK_S):
            nxt = bisect.bisect_right(times, t)
            if nxt >= len(times) or float(times[nxt]) - t > 0.5 * NO_KICK_S:  # no kick around: hold, don't blink
                return 0.6, -1
        return env, hit

    def _boom_tac(self, t: float) -> tuple[float, float, float]:
        """Reggaeton's two voices, (boom, tac, pause): the boom (the kick, its 1/8 runs too) and the tac (the
        snare on its pattern), call and response: each lets go quickly when the other one hits. In a breather
        (the beat gone for a moment) both pause (`pause` 0..1); the beat's return hits with both voices."""
        boom, bi = note_env(self.boom_t, self.boom_s, t)
        tac, ti = note_env(self.tac_t, self.tac_s, t)
        last_boom = float(self.boom_t[bi]) if bi >= 0 else -1e9
        last_tac = float(self.tac_t[ti]) if ti >= 0 else -1e9
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
        for eid in players or lights:
            s = out[eid]
            if solo:
                if v > s.dimmer:
                    s.dimmer, (s.r, s.g, s.b) = v, col
            else:
                s.dimmer, (s.r, s.g, s.b), s.white = v, col, 0.0

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

    def _kick_return(self, t: float, states: dict[str, State]) -> None:
        """The kick comes back after a break: a breath of darkness just before (after a break of two bars or
        more), then everything hits on the downbeat: full, with a white flash, settling over one beat. A real
        drop has its own, bigger moment (_drop_moment), and inside a snare roll the lights play the roll."""
        if not self.kick_breaks or self._roll_at(t) is not None or self.decision_at(t)[1].trigger in TWO_VOICES:
            return  # (boom-tac has its own breathers; the kit plays the drums' break and return itself)
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
                for s in states.values():
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
        """The lights that play the accents in this phrase: one in ACCENT_SHARE (heads and pars together, left
        to right, so they're spread over the rig; of two lights one), shifting per phrase. None in calm parts or
        where the synth has no stabs; a single light plays both (_scene layers the stabs over its rhythm)."""
        if d.section not in ACCENT_SECTIONS or d.trigger == "dembow":  # boom-tac: the tac is the accent
            return set()
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
        shift = (d.phrase + self._block(d, t)) % share  # the roles move on every 4 bars in energetic parts
        if d.trigger == "drums":  # a band: the guitar's lights keep their part, like the kit's groups (a swap
            shift = 0  # lands a light in the middle of the other part's note: a blink)
        return {eid for k, eid in enumerate(lights) if (k + shift) % share == share // 2}

    def _kick_pattern(self, d: Decision, t: float | None = None) -> str:
        """How the group plays the kicks: varied per phrase, and every 4 bars where the music moves fast; mostly
        tutti in the big drops."""
        options = DROP_PATTERNS if d.section == "drop" and d.intensity >= 3 else KICK_PATTERNS
        return options[int(_hash(d.phrase, self._block(d, t), 5) * len(options))]

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
            boom, tac, pause = self._boom_tac(t) if dembow else (env, 0.0, 0.0)
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
        sparkle = (hits * 7 + 3) % max(n, 1)
        for f in self.pars:
            k = self.order[f["id"]]
            col = _mix(cols, ((beat + phase) / 32 + k / n) % 1.0) if d.par_base == "fade" else base
            dim = base_level
            a = d.par_accent
            tac_voice = False
            if dembow and a not in ("none", "melody"):  # boom-tac: this par's voice
                low = min(base_level, BOOM_TAC_BASE) * (1 - (1 - BREATHER_GLOW) * pause)
                voice = self._voice(d, f["id"])
                if voice == "both":  # one light plays both: the boom, and the tac in the accent colour
                    col, dim = _lerp(col, accent, tac), low + (1 - low) * max(boom, tac)
                elif voice == "boom":
                    dim = low + (1 - low) * boom
                else:
                    col, dim, tac_voice = accent, low + (1 - low) * tac, True
            elif a in ("pulse", "stutter"):  # on its turn in the phrase's pattern ("stutter": older plans)
                dim = base_level + (1 - base_level) * (env if kick_turn(pattern, k, n, hit) else 0.0)
            elif a == "color_pop":
                col, dim = _lerp(col, accent, env), max(base_level, env)
            elif a == "chase":
                gap = abs(k - chase_pos)
                if loop:
                    gap = min(gap, n - gap)
                hit = env * max(0.0, 1.0 - gap * 0.7)  # lit par plus a short tail
                col, dim = _lerp(col, accent, min(1.0, hit * 1.5)), max(base_level, hit)
            elif a == "alternate":
                if k % 2 == hits % 2:
                    col, dim = accent, max(base_level, 0.45 + 0.55 * env)
            elif a == "sparkle":
                if k == sparkle:
                    col, dim = _lerp(col, accent, env), max(base_level, env)
            elif a == "melody":  # recent notes, each on the par of its pitch, coloured by its pitch class
                i = bisect.bisect_right(self.lead_t, t)
                for j in range(max(0, i - 6), i):
                    fr = self._frame(self.lead_t[j] + 0.03)
                    if round(float(self.lead_pitch[fr]) * (n - 1)) != k:
                        continue
                    glow = float(self.lead_s[j]) * math.exp(-(t - self.lead_t[j]) / MELODY_TAU)
                    if glow > dim:
                        pc = int(self.lead_pc[fr])
                        col, dim = (cols[pc % len(cols)] if pc >= 0 else accent), max(base_level, glow)
            if rise:  # brighter and whiter towards the drop
                col = _lerp(col, (1.0, 1.0, 1.0), 0.6 * progress**2)
                dim = dim * (0.45 + 0.55 * progress) + 0.15 * progress
            st = State(dimmer=dim, r=col[0], g=col[1], b=col[2])
            if (d.dynamics == "impact" or rise) and not tac_voice:  # (the flash is on the kick: the boom's)
                st.white = flash
            out[f["id"]] = st

        acc_env = note_env(self.acc_t, self.acc_s, t)[0]  # big hits as notes: close ones held through
        head_trig = getattr(d, "head_trigger", "same")
        if head_trig not in ("same", d.trigger):  # layering: heads pulse on their own rhythm
            env, hit = self._note(head_trig, t)
        grouping = d.grouping if self.multi else "unison"
        head_pattern = pattern if grouping == "unison" else "all"  # groups acting apart have their own roles
        rank, nh = self._x_rank(self.heads), len(self.heads)
        for j, f in enumerate(self.heads):
            role = self._role(d, j)
            hc = d.head_color
            if grouping == "split" and not self._featured(d, j):  # the counter-movement in a contrasting colour
                hc = {"base": "accent", "white": "accent", "accent": "base"}.get(hc, hc)
            cv = self.colour_variety
            step = bar // 4 if cv is not None and cv < 0.5 else bar  # little colour variety: a slower cycle
            col = {"base": base, "accent": accent, "white": (1.0, 1.0, 1.0), "cycle": cols[(j + step) % len(cols)]}[hc]
            hl = d.head_light
            mine = env if kick_turn(head_pattern, rank[f["id"]], nh, hit) else 0.0  # this head's kick
            if hl == "flick":  # on around the beat, when the head arrives and turns; dark while travelling
                dim = 1.0 if (phase < 0.22 or phase > 0.85) else 0.0
            elif hl == "beat":  # on with the kick, held, let go: on/off (the phrase's pattern splits the group)
                dim = mine
            elif hl == "alternate":  # heads take turns per kick (within their group when the groups act apart)
                dim = env if (hit + role["idx"]) % 2 == 0 else 0.0
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
                dim *= 0.1  # the others wait, barely glowing
            elif grouping == "chase":  # one group lit per beat, in turn
                dim *= 1.0 if beat % max(len(self.groups), 1) == self.hgroup[j]["g"] else 0.12
            voice = self._voice(d, f["id"]) if dembow and hl != "off" else ""
            if voice:  # boom-tac: the head's group plays its voice (the tac in the accent colour)
                low = BOOM_TAC_HEAD_BASE * (1 - (1 - BREATHER_GLOW) * pause)
                dim = low + (1 - low) * {"boom": boom, "tac": tac}.get(voice, max(boom, tac))
                if voice == "tac":
                    col = accent
                elif voice == "boom" and col == accent:
                    col = base
            if rise:
                dim *= 0.4 + 0.6 * progress
            st = State(dimmer=dim, r=col[0], g=col[1], b=col[2])
            if d.dynamics == "impact" and d.head_light != "off" and voice != "tac":  # (the flash: the boom's)
                st.white = flash
            st.fx = d.beam_fx
            group = self.gobo_groups[j].get(d.gobo_style) or self.gobo_all[j]
            st.gobo = group[(d.phrase + bar // 4) % len(group)] - 1  # next gobo of the style every four bars
            st.fx_speed = 0.3 + 0.2 * max(0, min(3, d.intensity))  # calm: slow rotation, drops: fast
            st.fx_reverse = role["formation"] == "mirror" and role["side"] > 0  # mirrored heads turn opposite ways
            out[f["id"]] = st

        self._laser_states(d, t, out, env, acc_env, beat, phase, cols, base, accent, bar)
        self._blinder_states(d, t, out, acc_env)
        self._strobe_states(d, t, out, acc_env)
        if getattr(d, "special", "off") == "stars":
            self._stars(d, t, out)
        self._accents(d, t, out, accent)
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
                if "offset_m" in e and e["kind"] in ("par", "head"):
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
            main = self.decision_at(self.drops[k - 1])[1].intensity >= 3
            blinders = getattr(self, "_blinder_ids", set())
            for eid, s in states.items():
                if eid in blinders and not main:
                    continue  # blinders punch on main drops only
                s.dimmer = max(s.dimmer, boost)
                s.white = max(s.white, flash)
