"""Lasers: shapes, colours and movement on the music, and the laser guard that keeps beams out of laser zones."""

from __future__ import annotations

import bisect
import math

import numpy as np

from amadeus.director import Decision
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry

LASER_SHAPES = {  # look: (beams drawn, share of the scan angle used, elevation of the axis above the minimum)
    "beams": (5, 0.5, 8.0),
    "fan": (36, 1.0, 16.0),
    "sheet": (48, 1.0, 0.5),
    "tunnel": (24, 0.6, 4.0),
    "cone": (12, 0.25, 4.0),
    "wave": (36, 1.0, 10.0),
}


LASER_RAINBOW = [
    (1.0, 0.0, 0.0),
    (1.0, 0.55, 0.0),
    (1.0, 1.0, 0.0),
    (0.0, 1.0, 0.0),
    (0.0, 1.0, 1.0),
    (0.0, 0.3, 1.0),
    (0.6, 0.0, 1.0),
    (1.0, 0.0, 0.8),
]


LASER_CLEAR_M = (
    3.0  # laser beams are at least this high by the stage edge (and rise from there): never into the audience
)


LASER_MIN_EL_DEG = 3.0  # lasers aim at least this far above horizontal


class LasersMixin:
    """Laser states, the beams they draw, and the laser guard."""

    def _init_lasers(self, rig: dict, fixtures: dict):
        """Lasers: position, definition and the lowest safe elevation of any beam. Every beam must be above
        LASER_CLEAR_M by the time it reaches the stage edge (and keep rising): never into the audience."""
        self.lasers = sorted([e for e in rig["elements"] if e["kind"] == "laser"], key=lambda e: e["x"])
        self.laser_info = []
        for e in self.lasers:
            fx = fixtures[e["fixture"]]
            pos = np.array(geometry.position(rig, e, fx))
            dist = max(0.5, -pos[1])  # to the stage edge
            min_el = max(LASER_MIN_EL_DEG, math.degrees(math.atan2(LASER_CLEAR_M - pos[2], dist)) + 2.0)
            defn = fxlib.get(fx["fixture"])
            laser = defn.get("laser", {})
            offset = float(laser.get("offset_deg", 20))
            aim = fx.get("aim")  # the laser's centre beam at neutral offsets, as mounted (rig editor)
            self.laser_info.append(
                {
                    "pos": pos,
                    "defn": defn,
                    "min_el": min_el,
                    "offset": offset,
                    "aim_az": (aim[0] if aim else 0.0) - fx.get("rot_deg", 0.0),
                    "base_el": aim[1] if aim else min_el + offset / 2,
                    "verified": bool(laser.get("verified")),
                }
            )

    def _laser_states(
        self,
        d: Decision,
        t: float,
        out: dict,
        env: float,
        acc_env: float,
        beat: int,
        phase: float,
        cols,
        base,
        accent,
        bar: int,
    ):
        n = len(self.lasers)
        if not n:
            return
        look, move = getattr(d, "laser_look", "off"), getattr(d, "laser_move", "still")
        mode = getattr(d, "laser_color", "base")
        col = {"base": base, "accent": accent, "white": (1.0, 1.0, 1.0)}.get(mode, cols[bar % len(cols)])
        hl = d.head_light
        on = {
            "steady": 1.0,
            "pulse": 1.0 if env > 0.35 else 0.0,
            "accents": 1.0 if acc_env > 0.4 else 0.0,
            "flick": 1.0 if (phase < 0.22 or phase > 0.85) else 0.0,
            "beat": 1.0 if phase < 0.5 else 0.0,
            "alternate": 1.0 if phase < 0.8 else 0.0,
            "breathe": 1.0,
            "stutter": 1.0 if env > 0.35 else 0.0,  # (older plans: as pulse)
            "off": 1.0,
        }.get(hl, 1.0)
        if move in ("pulse", "ripple"):  # the shape itself carries the rhythm: keep the beams on
            on = 1.0
        pos = beat + phase
        note = None
        if move == "melody" and len(self.syn_t):
            q = bisect.bisect_right(self.syn_t, t) - 1
            if q >= 0:
                env_n = float(self.syn_s[q]) * math.exp(-(t - self.syn_t[q]) / 0.11)
                note = (float(self.syn_s[q]), float(self.syn_p[q]), env_n)
            else:
                note = (0.0, 0.5, 0.0)
        if move in ("melody",):
            on = 1.0  # the notes themselves switch the beams
        rise = d.dynamics == "rise"
        progress = min(max((t - d.start) / max(d.end - d.start, 1e-6), 0.0), 1.0)
        for k, e in enumerate(self.lasers):
            s = State(dimmer=0.0 if look == "off" else on, r=col[0], g=col[1], b=col[2], pan=0.5, tilt=0.5)
            s.fx, s.lcolor = look, mode
            s.size = 0.55 + 0.15 * max(0, min(3, d.intensity))
            if hl == "alternate" and (beat + k) % 2:
                s.dimmer = 0.0
            if move == "scan":
                s.pan = 0.5 + 0.5 * math.sin(2 * math.pi * pos / 8 + (k % 2) * math.pi)
            elif move == "wave":
                s.tilt = 0.5 + 0.5 * math.sin(2 * math.pi * pos / 4 + k * 0.7)
            elif move == "rotate":
                s.spin = (0.15 + 0.15 * max(0, min(3, d.intensity))) * (1 if k % 2 == 0 else -1)
            elif move == "pulse":  # open on the beat, close in between
                s.size = 0.3 + 0.7 * (1.0 - min(phase, 1.0 - phase) * 2) ** 2
            elif move == "ripple":  # a window of lit beams runs across the fan every two beats
                s.phase = (pos % 2) / 2 if k % 2 == 0 else 1 - (pos % 2) / 2
            elif move == "chase":
                s.dimmer *= 1.0 if beat % n == k else 0.0
            elif move == "melody" and note is not None:  # play the synth line note for note
                strength, pitch, env_n = note
                s.dimmer *= 1.0 if env_n > 0.18 else 0.0
                s.phase = pitch  # the lit part of the fan follows the pitch
                s.tilt = 0.5 + 0.5 * pitch  # higher notes aim higher (never lower than safe)
                s.size = 0.45 + 0.55 * strength
            if rise:  # building towards the drop: lasers come in halfway, open up and turn faster and faster
                if progress < 0.5:
                    s.dimmer = 0.0
                s.size = min(1.0, s.size * (0.6 + 0.6 * progress))
                if move in ("still", "rotate", "wave"):
                    s.spin = (1 if k % 2 == 0 else -1) * (0.05 + 0.75 * progress**2)
            out[e["id"]] = s

    def laser_beams(self, states: dict, t: float) -> dict[str, list]:
        """Every beam each laser draws right now, as [dx, dy, dz, r, g, b, brightness] (for the visualiser).

        Shapes as a scanning laser draws them, inside its scan angle: fans and sheets are dozens of beams in
        a plane (rotating around the laser's axis), tunnels and cones beams on a cone. Safety: whatever the
        shape and its movement, the beams are what the DMX state really draws (_laser_dirs): the laser guard
        (render) has already lifted, shrunk or blanked it to stay out of laser zones and above min_el."""
        out = {}
        if not self.lasers:
            return out
        i, d = self.decision_at(t)
        cols = self._colours(d)
        for e, info in zip(self.lasers, self.laser_info):
            s = states.get(e["id"])
            if s is None or s.dimmer <= 0.05 or s.fx in ("off", "open"):
                out[e["id"]] = None
                continue
            dirs = self._laser_dirs(s, info, t)
            n = len(dirs)
            beams = []
            for q, v in enumerate(dirs):
                c = self._laser_beam_colour(s, q, n, t, cols, info)
                bright = 1.0
                if s.phase >= 0:  # ripple: a lit window runs across the fan
                    bright = max(0.08, 1.0 - abs(q / max(n - 1, 1) - s.phase) * 5)
                beams.append([round(float(x), 3) for x in (*v, *c, bright)])
            out[e["id"]] = beams
        return out

    def _laser_dirs(self, s: State, info: dict, t: float, rot: float | None = None) -> np.ndarray:
        """The beams a laser draws for its DMX state (shape, size, x/y offset, rotation) as unit directions:
        the model the laser guard checks, and what the visualiser draws. The pattern's centre points along the
        laser's aim (set in the rig editor, or a safe default), moved by the offsets within the laser's range."""
        scan = float(info["defn"].get("physical", {}).get("scan_deg", 40))
        n, frac, lift = LASER_SHAPES.get(s.fx, LASER_SHAPES["beams"])
        spread = scan * frac * (0.4 + 0.6 * min(max(s.size, 0.0), 1.0))
        az0 = info["aim_az"] + (s.pan - 0.5) * max(scan - spread, 4.0)
        el_axis = info["base_el"] + lift + (min(max(s.tilt, 0.0), 1.0) - 0.5) * info["offset"]
        rot = math.radians(t * s.spin * 360.0) if rot is None else rot
        up = np.array([0.0, 0.0, 1.0])
        A = geometry.direction(az0, el_axis)
        P0 = np.cross(A, up)
        P0 /= np.linalg.norm(P0) + 1e-9
        V0 = np.cross(P0, A)
        q = np.arange(n)
        if s.fx in ("tunnel", "cone"):
            h = math.radians(spread / 2)
            ang = rot + 2 * math.pi * q / n
            return math.cos(h) * A + math.sin(h) * (np.cos(ang)[:, None] * P0 + np.sin(ang)[:, None] * V0)
        zr = rot if s.fx in ("fan", "wave", "beams") else 0.0  # a sheet stays flat
        P = math.cos(zr) * P0 + math.sin(zr) * V0
        th = np.radians(spread * (q / max(n - 1, 1) - 0.5))
        v = np.cos(th)[:, None] * A + np.sin(th)[:, None] * P
        if s.fx == "wave":
            v = v + (np.sin(t * 4 + q * 0.45) * math.radians(5))[:, None] * V0
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    def _laser_guard(self, states: dict, t: float):
        """Safety for lasers, every frame, on the state that goes out as DMX (so the visualiser shows the truth).

        Rules: every beam at or above the laser's minimum elevation, and no beam - plus each zone's margin, plus
        2° while the laser's patterns aren't calibrated - inside a laser_out zone. A spinning pattern is checked
        over its whole turn. If a pattern breaks a rule it is raised, then shrunk; if that isn't enough, the laser
        is blanked. When DMX goes to real lights, a set with lasers needs at least one laser zone, or the lasers
        stay dark. A software guard on top of the laser's masking plate, scan safety and E-stop: never instead."""
        need_zones = (
            self.real_output and self.rig["safety"].get("laser_zones_required", True) and not self.zones.laser_out
        )
        for e, info in zip(self.lasers, self.laser_info):
            s = states.get(e["id"])
            if s is None or max(s.dimmer, s.white) <= 0.05 or s.fx in ("off", "open"):
                if s is not None:  # dark means dark: a crossfade can leave some dimmer on an "off" look
                    s.dimmer, s.white = 0.0, 0.0
                self._guard_note(e["id"], None)
                continue
            if need_zones:
                s.dimmer, s.white = 0.0, 0.0
                self._guard_note(e["id"], "dark: no laser safety zone in this set (draw one in the rig editor)")
                continue
            extra = 0.0 if info["verified"] else 2.0
            spins = abs(s.spin) > 0.02 and s.fx not in ("sheet",)
            note = None
            for _ in range(24):
                if spins:  # the worst moment of its turn
                    dirs = np.concatenate(
                        [self._laser_dirs(s, info, t, rot=a) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)]
                    )
                else:
                    dirs = self._laser_dirs(s, info, t)
                low = math.degrees(math.asin(float(np.clip(dirs[:, 2].min(), -1, 1))))
                zone = self.zones.laser_violation(info["pos"], dirs, extra)
                if low >= info["min_el"] - 0.05 and zone is None:
                    break
                note = f"zone '{zone}'" if zone else f"below {info['min_el']:.0f}°"
                if s.tilt < 1.0:
                    s.tilt = min(1.0, s.tilt + 0.08)  # raise the pattern
                elif s.size > 0.12:
                    s.size *= 0.7  # then make it smaller
                else:
                    s.dimmer, s.white = 0.0, 0.0  # still unsafe: dark
                    note = f"blanked ({note})"
                    break
            self._guard_note(e["id"], note)

    def _guard_note(self, eid: str, note: str | None):
        """Remember (and say once) what the laser guard did."""
        notes = self.__dict__.setdefault("guard_notes", {})
        if notes.get(eid) != note and note and note.startswith(("blanked", "dark")):
            print(f"  ⚠ laser {eid}: {note}", flush=True)
        notes[eid] = note

    def _laser_beam_colour(self, s: State, q: int, n: int, t: float, cols, info) -> tuple:
        if s.lcolor == "rainbow":  # the laser's own primaries and their mixes, scrolling slowly
            return LASER_RAINBOW[(q + int(t * 6)) % len(LASER_RAINBOW)]
        if s.lcolor == "multi":  # the palette as a gradient across the fan
            x = (q / max(n - 1, 1) + t * 0.05) % 1.0 * (len(cols) - 1)
            k = int(x)
            a, b = cols[k % len(cols)], cols[(k + 1) % len(cols)]
            return tuple(a[m] + (b[m] - a[m]) * (x - k) for m in range(3))
        slot = fxlib.nearest_slot(info["defn"], (s.r, s.g, s.b), s.white) if fxlib.has_wheel(info["defn"]) else None
        return tuple(slot["rgb"]) if slot else (s.r, s.g, s.b)
