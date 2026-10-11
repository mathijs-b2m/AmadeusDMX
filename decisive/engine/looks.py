"""Looks: the colours, levels and hits of pars, heads, blinders and strobes for each phrase."""

from __future__ import annotations

import bisect
import math

import numpy as np

from decisive.director import Decision
from decisive.director.vocabulary import PALETTES
from decisive.engine.state import State
from decisive.engine.timing import _decay

XFADE = 0.6  # seconds of crossfade between scenes at phrase boundaries


PREDROP_BEATS = 2.0  # heads go dark and move to the drop's position/colour/gobo this many beats early


TRIGGER_TAU = {
    "kick": 0.16,
    "backbeat": 0.18,
    "hats": 0.07,
    "accents": 0.35,
    "bars": 0.5,
    "lead": 0.45,
    "eighths": 0.08,
    "sixteenths": 0.045,
    "roll": 0.08,
    "synth": 0.09,
}  # hit decay (s)


MELODY_TAU = 0.7  # how long a melody note keeps its par lit


STUTTER_ON = 0.35  # frame-level stutter strength above which the lights chop along automatically


PAR_BASE_LEVEL = {"off": 0.0, "dim": 0.22, "full": 0.75, "fade": 0.5}


INTENSITY_MASTER = [0.55, 0.7, 0.85, 1.0]  # "Subtle" must still be clearly visible


def _lerp(a, b, k: float):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def _mix(cols, x: float):
    """Cyclic interpolation through a list of colours, x in 0..1."""
    n = len(cols)
    pos = (x % 1.0) * n
    a, b = cols[int(pos) % n], cols[(int(pos) + 1) % n]
    k = pos - int(pos)
    return tuple(a[i] * (1 - k) + b[i] * k for i in range(3))


RANDOM_SHARE = 0.4  # random head light: the share of eighths a head would like to light
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
    """Random but repeatable: does this head light this eighth?"""
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
        in a drop (intensity 2+) they hit the big accents. The drop moment itself flashes everything anyway."""
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
        if nxt is not None and nxt.section == "drop" and d.section != "drop":
            left = d.end - t
            span = d.end - d.start
            if 0 < left < max(span * 0.25, 4 * period):
                every = 0.5 if left < 4 * period else 1.0  # beats between flashes
                while every * period < 1.0 / max_hz:  # photosensitivity: the set's flash limit
                    every *= 2
                since = ((beat + phase) % every) * period
                dim = math.exp(-since / 0.06) * (0.6 + 0.4 * (1 - left / max(span * 0.25, 4 * period)))
        elif d.section == "drop" and d.intensity >= 2:
            dim = max(0.0, (acc_env - 0.55) / 0.45) ** 0.7
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
        return PALETTES.get(d.palette, PALETTES["cool"])[1]

    def _trigger(self, name: str, d: Decision | None = None, t: float = 0.0):
        if name == "roll":  # quarter notes → eighths → sixteenths through the phrase
            progress = (t - d.start) / max(d.end - d.start, 1e-6) if d else 0.0
            name = "kick_grid" if progress < 0.5 else "eighths" if progress < 0.8 else "sixteenths"
            if name == "kick_grid":
                return self.beats, np.ones(len(self.beats), dtype=np.float32)
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

    def _scene(self, d: Decision, t: float) -> dict[str, State]:
        """Render one look from its layers: par base, par accent, trigger, head light/colour, dynamics."""
        cols = self._colours(d)
        base, accent = cols[0], cols[2 % len(cols)]
        n = len(self.pars)
        beat, phase, _ = self.beat_info(t)
        bar = self.bar_info(t)
        progress = min(max((t - d.start) / max(d.end - d.start, 1e-6), 0.0), 1.0)
        if progress >= 0.5 and (d.end - d.start) > 20:  # long phrase: swap colours halfway for variation
            base, accent = accent, base
        trig_t, trig_s = self._trigger(d.trigger, d, t)
        env = _decay(trig_t, trig_s, t, TRIGGER_TAU.get(d.trigger, 0.15))
        if d.trigger in ("eighths", "sixteenths", "roll") and self.stut_depth < 1.0:
            env = 0.5 + 0.5 * env  # >3 pulses/s: half-depth unless allow_fast_strobe (photosensitivity)
        hits = bisect.bisect_right(trig_t, t)  # hits so far: steps chases, alternation, sparkles
        flash = _decay(self.flash_t, self.flash_s, t, 0.07)
        rise = d.dynamics == "rise"
        out: dict[str, State] = {}

        base_level = PAR_BASE_LEVEL[d.par_base]
        bounce = (hits % (2 * n - 2)) if n > 1 else 0
        chase_pos = bounce if bounce < n else 2 * n - 2 - bounce
        sparkle = (hits * 7 + 3) % max(n, 1)
        for f in self.pars:
            k = self.order[f["id"]]
            col = _mix(cols, ((beat + phase) / 32 + k / n) % 1.0) if d.par_base == "fade" else base
            dim = base_level
            a = d.par_accent
            if a == "pulse":
                dim = base_level + (1 - base_level) * env
            elif a == "color_pop":
                col, dim = _lerp(col, accent, env), max(base_level, env)
            elif a == "chase":
                hit = env * max(0.0, 1.0 - abs(k - chase_pos) * 0.7)  # lit par plus a short tail
                col, dim = _lerp(col, accent, min(1.0, hit * 1.5)), max(base_level, hit)
            elif a == "alternate":
                if k % 2 == hits % 2:
                    col, dim = accent, max(base_level, 0.45 + 0.55 * env)
            elif a == "sparkle":
                if k == sparkle:
                    col, dim = _lerp(col, accent, env), max(base_level, env)
            elif a == "stutter":  # the whole par chops with the synth
                dim = max(base_level * 0.5, self._stutter(t, max(base_level, 0.35)))
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
            if d.dynamics == "impact" or rise:
                st.white = flash
            out[f["id"]] = st

        acc_env = _decay(self.acc_t, self.acc_s, t, 0.35)
        head_trig = getattr(d, "head_trigger", "same")
        if head_trig not in ("same", d.trigger):  # layering: heads pulse on their own rhythm
            ht, hs = self._trigger(head_trig, d, t)
            env = _decay(ht, hs, t, TRIGGER_TAU.get(head_trig, 0.15))
            if head_trig in ("eighths", "sixteenths", "roll") and self.stut_depth < 1.0:
                env = 0.5 + 0.5 * env
        grouping = d.grouping if self.multi else "unison"
        for j, f in enumerate(self.heads):
            role = self._role(d, j)
            hc = d.head_color
            if grouping == "split" and not self._featured(d, j):  # the counter-movement in a contrasting colour
                hc = {"base": "accent", "white": "accent", "accent": "base"}.get(hc, hc)
            col = {"base": base, "accent": accent, "white": (1.0, 1.0, 1.0), "cycle": cols[(j + bar) % len(cols)]}[hc]
            hl = d.head_light
            if hl == "flick":  # on around the beat, when the head arrives and turns; dark while travelling
                dim = 1.0 if (phase < 0.22 or phase > 0.85) else 0.0
            elif hl == "beat":  # hard on/off with every beat
                dim = 1.0 if phase < 0.5 else 0.0
            elif hl == "alternate":  # heads take turns per beat (within their group when the groups act apart)
                dim = (1.0 if phase < 0.8 else 0.0) if (beat + role["idx"]) % 2 == 0 else 0.0
            elif hl == "random":  # each head on its own random eighths: a snap on, held for the eighth, off
                slot = int((beat + phase) * 2)
                dim = 1.0 if _chance(j, slot) and not _chance(j, slot - 1) else 0.0
            else:
                dim = {
                    "steady": 1.0,
                    "pulse": 0.25 + 0.75 * env,
                    "accents": 0.12 + 0.88 * acc_env,
                    "breathe": 0.1 + 0.9 * float(self.breath[self._frame(t)]),
                    "stutter": self._stutter(t, 0.15 + 0.85 * float(self.breath[self._frame(t)])),
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
            if rise:
                dim *= 0.4 + 0.6 * progress
            st = State(dimmer=dim, r=col[0], g=col[1], b=col[2])
            if d.dynamics == "impact" and d.head_light != "off":
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
        master = INTENSITY_MASTER[max(0, min(3, d.intensity))] * self.rig["safety"]["master"]
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

    def _stutter_overlay(self, t: float, i: int, states: dict[str, State]) -> None:
        """Wherever the synths clearly stutter, chop the lights with them, whatever look is running.

        Stutters often last a few seconds inside a long phrase, so a per-phrase choice misses them;
        an operator would punch this in. Weighted by how clear the stutter is; skipped for heads
        that are already rhythmic on their own.
        """
        f = self._frame(t)
        strength = float(self.chop_overlay[f])  # per bar: a clear stutter section, not single flickers
        if strength <= 0:
            return
        chopped = 1.0 - self.stut_depth * (1.0 - float(self.stut_gate[f]))
        rhythmic_heads = self.plan[i].head_light in ("flick", "beat", "alternate", "stutter", "random")
        for e in self.rig["elements"]:
            if e["kind"] == "head" and rhythmic_heads:
                continue
            s = states[e["id"]]
            s.dimmer *= (1 - strength) + chopped * strength

    def _drop_moment(self, t: float, states: dict[str, State]) -> None:
        """What an operator does at a drop: a breath of darkness just before it, then everything hits.

        - last half beat before the drop: all lights dark
        - the first beat: a white flash on everything
        - the first bar: everything at full, settling into the drop's own look
        """
        if not self.drops:
            return
        k = bisect.bisect_right(self.drops, t)
        _, _, period = self.beat_info(t)
        if k < len(self.drops) and 0 < self.drops[k] - t < period * 0.5:
            for s in states.values():
                s.dimmer, s.white = 0.0, 0.0
            return
        if k == 0:
            return
        since = t - self.drops[k - 1]
        bar = period * 4
        if since < bar:
            boost = 1.0 - since / bar  # full → the drop's own level over one bar
            flash = math.exp(-since / 0.18)  # one white hit on the downbeat
            main = self.decision_at(self.drops[k - 1])[1].intensity >= 3
            blinders = getattr(self, "_blinder_ids", set())
            for eid, s in states.items():
                if eid in blinders and not main:
                    continue  # blinders punch on main drops only
                s.dimmer = max(s.dimmer, boost)
                s.white = max(s.white, flash)
