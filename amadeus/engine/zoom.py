"""Zoom: how wide each light with a zoom opens, as part of the phrase's look.

A zoom never plays the beat: like a dimmer flickering along with the music, a lens pumping with the kicks looks
broken. It is set per phrase, from what the director already decided (the section, the intensity, where the heads
aim and how they move, the layering, the beam effect), and changes with the phrase. Two slow moves in one
direction are the exceptions: a buildup focuses into its drop, and at a drop the heads take the drop's zoom in the
dark before it (with its colour and position, engine.py).

- **Beams and spots** (heads with a gobo wheel): tight and crisp when the music is big, the beams fly (aim sky, fast
  movement) or a prism splits them; opened up a little when it is calm and they rest on the stage or the crowd, so
  they soften into pools. A gobo opens up enough that its pattern reads on the floor and the walls; frost fully open.
- **Wash heads** (no gobos): wide, gathering into thick beams that punch at the peaks.
- **Fixed washes** (a par with a zoom): wide, a little tighter at the peaks, never so tight that the stage goes dark
  between them.
- **Layers and groups**: an accent layer tighter than the carpet under it; a featured group tighter than the rest.

"Wide" is what the rig needs, not the lens's widest: neighbouring pools overlapping evenly at the throw (in a big
room that may be less than fully open: no hot spots, no light thinned out over the walls).
"""

from __future__ import annotations

import math

from amadeus.library import fixtures as fxlib
from amadeus.library import gobos
from amadeus.rig import geometry

# the zoom of a beam head, per beam effect: a gobo opens up enough that its pattern reads, frost fully open
BEAM_ZOOM = {"gobo": 0.45, "gobo_shake": 0.45, "gobo_rotate": 0.45, "gobo_spin": 0.45, "frost": 1.0}
BEAM_OPEN_ZOOM = (0.35, 0.3, 0.15, 0.0)  # an open beam's zoom by intensity 0..3
BEAM_FLOWING_ZOOM = 0.15  # beams that sweep, circle or wave: tight enough to read as shafts
FAST_MOVES = {"ballyhoo", "swing", "bounce", "step_on_beat"}  # beams that fly: pencil tight
FLOWING_MOVES = {"sweep", "nod", "circle", "figure8", "tilt_wave"}
BEAM_BASE_ZOOM = 0.45  # beam heads holding a soft base layer
WASH_PEAK_ZOOM = 0.3  # a wash head at the peaks: thick beams that punch
WASH_GROOVE = 0.7  # … in a groove: this much of its wide
FIXED_PEAK = 0.6  # a fixed wash at the peaks: this much of its wide (the stage stays covered)
CALM_SECTIONS = {"intro", "breakdown"}
FEATURED_K = 0.5  # a featured group's or an accent layer's zoom against the rest
WASH_OVERLAP = 2.0  # a wash's pool twice as wide as the gap to its neighbour: an even field of light
WASH_WIDE_MIN = 0.6  # … but never less open than this for "wide"


class ZoomMixin:
    def _init_zoom(self, rig: dict, fixtures: dict):
        """Per element with a zoom (heads and pars): its kind ('beam', 'wash' or 'fixed') and how far "wide" opens
        on this rig (0..1): until its pool is WASH_OVERLAP × the gap to its nearest neighbour of the same model
        at its throw (heads: the height over the floor they light; fixed washes: along their aim)."""
        self.zoom_kind: dict[str, str] = {}
        self.zoom_wide: dict[str, float] = {}
        st = geometry.stage(rig)
        deck = float(st.get("deck_m", 0.0))
        found = []
        for e in rig["elements"]:
            if e["kind"] not in ("head", "par"):
                continue
            fx = fixtures[e["fixture"]]
            defn = fxlib.get(fx["fixture"])
            if not any(c["attr"] == "zoom" for c in fxlib.channels(defn, fx["mode"])):
                continue
            if e["kind"] == "par":
                kind = "fixed"
            else:
                kind = "beam" if gobos.wheel(defn, "gobo") else "wash"
            pos = geometry.position(rig, e, fx)
            if kind == "fixed":
                throw = geometry.beam_end(pos, geometry.static_dir(fx, e["kind"]), st)[1]
            else:
                throw = pos[2] - (deck if pos[1] <= 0 else 0.0)
            self.zoom_kind[e["id"]] = kind
            found.append((e["id"], fx["fixture"], pos, max(throw, 1.0), defn.get("physical", {})))
        needs: dict[str, list[float]] = {}
        for eid, model, pos, throw, phys in found:
            gaps = [math.hypot(p[0] - pos[0], p[1] - pos[1]) for o, m, p, _, _ in found if m == model and o != eid]
            tight = float(phys.get("beam_deg", 25) or 25)
            wide = float(phys.get("beam_deg_max", tight) or tight)
            gap = min((g for g in gaps if g > 0.05), default=0.0)
            if not gap or wide <= tight:  # on its own (or no lens data): fully open
                needs.setdefault(model, []).append(1.0)
                continue
            need = 2 * math.degrees(math.atan(WASH_OVERLAP * gap / (2 * throw)))
            needs.setdefault(model, []).append(min(max((need - tight) / (wide - tight), WASH_WIDE_MIN), 1.0))
        # one "wide" per model, as an operator's preset: the end of a row or a lower truss doesn't make it uneven
        for eid, model, *_ in found:
            self.zoom_wide[eid] = sorted(needs[model])[len(needs[model]) // 2]

    def _head_zoom(self, d, eid: str, role: dict, layer: str | None, featured: bool | None, progress: float) -> float:
        """A moving head's zoom in phrase d (0 tightest .. 1 widest). `featured`: None when the groups don't play
        apart, else whether this head's group leads."""
        kind = self.zoom_kind.get(eid)
        if kind is None:
            return 0.0
        big = d.section == "drop" or d.dynamics == "impact" or d.intensity >= 3
        building = d.dynamics == "rise" or d.section == "buildup"
        if kind == "beam":
            if d.beam_fx in BEAM_ZOOM:
                return BEAM_ZOOM[d.beam_fx]
            z = 0.0 if big else BEAM_OPEN_ZOOM[max(0, min(3, d.intensity))]
            if d.aim == "sky" or role["movement"] in FAST_MOVES:
                z = 0.0
            elif role["movement"] in FLOWING_MOVES or d.beam_fx.startswith("prism"):
                z = min(z, BEAM_FLOWING_ZOOM)
            if building:  # focusing into the drop: from soft to pencil tight over the phrase
                z = BEAM_OPEN_ZOOM[0] * (1 - progress)
            base = BEAM_BASE_ZOOM
        else:
            wide = self.zoom_wide[eid]
            if building:  # gathering into the drop's thick beams
                z = wide + (WASH_PEAK_ZOOM - wide) * progress
            elif big:
                z = WASH_PEAK_ZOOM
            elif d.intensity <= 1 or d.section in CALM_SECTIONS:
                z = wide
            else:
                z = WASH_GROOVE * wide
            base = wide
        if layer == "base":  # the carpet: soft and wide
            return max(z, base)
        if layer == "accent" or featured:
            z *= FEATURED_K
        return z

    def _fixed_zoom(self, d, eid: str, progress: float) -> float | None:
        """A fixed wash's zoom in phrase d; None for a light without one."""
        wide = self.zoom_wide.get(eid)
        if wide is None:
            return None
        peak = FIXED_PEAK * wide
        if d.dynamics == "rise" or d.section == "buildup":
            return wide + (peak - wide) * progress
        if d.section == "drop" or d.dynamics == "impact" or d.intensity >= 3:
            return peak
        if d.intensity <= 1 or d.section in CALM_SECTIONS:
            return wide
        return (wide + peak) / 2

    def _cine_zoom(self, eid: str, pad: set[str], rank: float) -> float:
        """The cinematic program: beams tight for the stabs and cymbals; washes wide for a held pad and in quiet
        phrases, gathered when the music is big (its loudness rank in the track)."""
        kind = self.zoom_kind.get(eid)
        if kind is None or kind == "beam":
            return 0.0
        wide = self.zoom_wide[eid]
        if eid in pad or rank < 0.6:
            return wide
        return WASH_PEAK_ZOOM if kind == "wash" else FIXED_PEAK * wide
