"""Dubstep's voices (the dubstep trigger): the rig's main group plays the growl, the others the kick and the snare.

A dubstep drop is a growl over half-time drums (amadeus/audio/growl.py). The rig plays it in layers, whole groups
each, the roles fixed for the track: the **main** group (the heads with the most light, else the pars) follows
the growl pulse by pulse, every wobble, stab and yoy a note, hit as it bites and let go as the filter closes; dark
between, a new colour of the palette with each new sound (patch) of the drop. The other groups play the drums
like rock's kit (looks.py `_kit_voices`): some on the kick in the base colour, the others on the snare in the
accent colour, ringing out.

Only an LED's light can pulse like that. A lamp behind a mechanical dimmer or a glowing filament (fxlib.lamp:
Sharpy, Pointe, PAR 64 …) plays the growl's notes instead: pulses closer than LAMP_GAP_S are one note, held.

The pulses are flashes, so the set's flash limit holds (safety.max_flash_hz, FAST_STROBE_HZ with
allow_fast_strobe): a wobble faster than the limit is played on every second (third …) pulse, still on the
wobble; strobe-free plays the notes, like a lamp. Where the growl rests for a beat (a vocal chop, the drums
alone) the main group plays the drums with the others until it comes back.
"""

from __future__ import annotations

import bisect

import numpy as np

from amadeus.audio import drums, growl
from amadeus.engine.timing import _release
from amadeus.library import fixtures as fxlib

GROWL_MIN_PULSES = 0.25  # a phrase needs this many growl pulses a beat for the main group to play it
GROWL_LOUD = 45  # … and to be this loud (a percentile of the track): a quiet part's pad isn't the growl
LAMP_GAP_S = 0.4  # a lamp's light: pulses closer than this are one held note
LAMP_RELEASE_S = 0.25
HOLD_MIN_S = 0.035  # a pulse holds at least this long (two DMX frames at 40 fps, whatever the sound)
RELEASE_MIN_S, RELEASE_MAX_S = 0.03, 0.18  # a pulse lets go over this long, …
RELEASE_SHARE = 0.85  # … within this share of the gap to the next one (dark before it hits)
IDLE_BEATS = 1.0  # the growl silent this long: the main group plays the drums until it is back
IDLE_AHEAD_S = 0.2  # (and not about to come back within this)


class GrowlMixin:
    """The growl voice for the engine (looks.py plays it)."""

    def _init_growl(self, analysis, plan) -> None:
        on = any(getattr(d, "trigger", "") == "dubstep" for d in plan)
        self.growl = growl.growl(analysis) if on else growl.Growl.empty()
        self.dub_kit = drums.half_time(analysis) if on else drums.Kit.empty()
        g, beat = self.growl, self._beat_s()
        hz = self._head_strobe_hz() if on else 0.0
        self.growl_led = _thinned(g, 1.0 / hz) if hz > 0 else _held(g, LAMP_GAP_S)
        self.growl_lamp = _held(g, LAMP_GAP_S)
        phrases = getattr(analysis, "phrases", [])
        self.growl_phrases = {
            i
            for i, d in enumerate(plan)
            if d.trigger == "dubstep"
            and len(g.between(d.start, d.end)) >= GROWL_MIN_PULSES * (d.end - d.start) / beat
            and (len(phrases) != len(plan) or phrases[i].loudness_pct >= GROWL_LOUD)
        }
        fixtures = {f["id"]: f for f in self.rig["fixtures"]}
        self.lamp_lights = set()
        for e in (*self.heads, *self.pars):
            try:
                defn = fxlib.get(fixtures[e["fixture"]]["fixture"])
            except (KeyError, ValueError, FileNotFoundError):
                continue
            if fxlib.lamp(defn):
                self.lamp_lights.add(e["id"])

    def growl_at(self, d, t: float, eid: str) -> tuple[float, int] | None:
        """The growl voice of light `eid` at t: (level 0..1, its sound: the patch), None where the growl rests
        (or this phrase has none): the light plays the drums then."""
        if d.phrase not in self.growl_phrases:
            return None
        on, off, s, patch = self.growl_lamp if eid in self.lamp_lights else self.growl_led
        k = bisect.bisect_right(on, t) - 1
        nxt = float(on[k + 1]) if k + 1 < len(on) else 1e9
        if k < 0 or (t - float(off[k]) > IDLE_BEATS * self._beat_s() and nxt - t > IDLE_AHEAD_S):
            return None
        level = round((0.6 + 0.4 * float(s[k])) * 5) / 5
        hold = max(float(off[k] - on[k]), HOLD_MIN_S)
        room = nxt - float(on[k]) - hold
        if eid in self.lamp_lights:
            release = min(LAMP_RELEASE_S, max(RELEASE_MIN_S, RELEASE_SHARE * room))
        else:
            release = min(RELEASE_MAX_S, max(RELEASE_MIN_S, RELEASE_SHARE * room))
        return _release(t - float(on[k]), level, hold, release), int(patch[k])


def _thinned(g: growl.Growl, gap: float) -> tuple[np.ndarray, ...]:
    """The pulses an LED plays within the flash limit: each at least `gap` after the last one kept (a faster wobble
    is played on every second, third … pulse, still on the wobble); a kept pulse holds no longer than until the
    next kept one might start."""
    keep, last = [], -1e9
    for k, t in enumerate(g.on):
        if t - last >= gap - 1e-6:
            keep.append(k)
            last = float(t)
    k = np.array(keep, int)
    on, off = g.on[k], g.off[k].copy()
    if len(on) > 1:
        off[:-1] = np.minimum(off[:-1], on[1:] - RELEASE_MIN_S)
    return on, np.maximum(off, on + HOLD_MIN_S * 0.5), g.s[k], g.patch[k]


def _held(g: growl.Growl, gap: float) -> tuple[np.ndarray, ...]:
    """The growl as notes: pulses less than `gap` apart joined into one note, held from the first to the last."""
    if not len(g):
        z = np.zeros(0)
        return z, z, z, np.zeros(0, int)
    on, off, s, patch = [float(g.on[0])], [float(g.off[0])], [float(g.s[0])], [int(g.patch[0])]
    for k in range(1, len(g)):
        if float(g.on[k]) - off[-1] < gap:
            off[-1] = max(off[-1], float(g.off[k]))
            s[-1] = max(s[-1], float(g.s[k]))
        else:
            on.append(float(g.on[k]))
            off.append(float(g.off[k]))
            s.append(float(g.s[k]))
            patch.append(int(g.patch[k]))
    return np.array(on), np.array(off), np.array(s, np.float32), np.array(patch, int)
