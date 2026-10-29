"""What each fixture really puts out, for the visualiser (the engine says what it WANTS).

- Colour wheels only have their slots: the beam snaps to the slot the DMX selects, and when the wheel
  turns to a far slot it scrolls through the colours in between (half/half while a slot edge passes).
- CMY fixtures mix subtractively: what the C/M/Y filters let through.
- Lasers only have their colour macros.
- Brightness of a beam in haze follows the light packed into the beam: lumens / beam angle². A 4° LED
  beam punches about as hard as a 12° 11,600 lm profile; a zoomed-out wash is much softer.
- Beam angle: the lens with the zoom the show sends (tight for beams, opened up for gobos, wide for frost); a
  zoom motor takes a moment to get there.
- Beam effects: only what the fixture (its mode) has; a rotating gobo it can't turn is a still one, a prism it
  doesn't have an open beam (fixtures.beam_effect).
- Gobo wheels: the wheel turns from gobo to gobo through the ones in between (half one, half the next while it
  passes), scrolls when the show spins it; a rotating gobo turns, a shaking one shakes, at the speed sent.
"""

from __future__ import annotations

import math

from amadeus.library import fixtures as fxlib
from amadeus.library import gobos

WHEEL_SLOTS_PER_S = 14.0  # a typical colour wheel moves about 14 slots per second (shortest way round)
REF_LUMENS = 1500.0  # the light of a beam drawn at full strength (a Sharpy's); the visualisers scale from it
FLUX_RANGE = (0.25, 2.5)  # how much weaker or stronger than that a head is drawn (the square root of its lumens' share)
FIELD = 1.8  # field angle (10 % of the centre's light) over beam angle (50 %): a smooth lens; physical.field_deg says
GOBO_SLOTS_PER_S = 9.0  # a gobo wheel moves about this many slots per second
ZOOM_PER_S = 2.5  # a zoom motor goes from tight to wide in about 0.4 s


def beam_info(lumens, tight: float, wide: float, head: bool, field_deg=None) -> dict:
    """How the visualisers draw a fixture's beam: the lens (beam angle, tightest and widest), the field angle as a
    multiple of it (where the light fades out), and its flux: the light it puts out against a reference beam. The
    visualisers make the shaft brighter the narrower it is and the spot dimmer the further it throws (the same
    light over more of the air and the floor); a head without lumens counts as the reference."""
    flux = 1.0
    if head and lumens:
        flux = min(FLUX_RANGE[1], max(FLUX_RANGE[0], math.sqrt(float(lumens) / REF_LUMENS)))
    field = float(field_deg) / tight if field_deg and float(field_deg) > tight else FIELD
    return {"beam_deg": tight, "beam_wide": wide, "field": round(field, 3), "flux": round(flux, 3)}


class Realism:
    def __init__(self, rig: dict):
        self.rig = rig
        self.gobos: list[str] = []  # the gobo pictures of the rig's heads (catalogue keys)
        self.gobo_index: dict[str, int] = {}
        self.heads: dict[str, dict] = {}
        fixtures = {f["id"]: f for f in rig["fixtures"]}
        self.info: dict[str, dict] = {}
        for e in rig["elements"]:
            fx = fixtures[e["fixture"]]
            defn = fxlib.get(fx["fixture"])
            phys = defn.get("physical", {})
            chans = fxlib.channels(defn, fx["mode"])
            attrs = {c["attr"] for c in chans}
            tight = float(phys.get("beam_deg", 25) or 25)
            wide = float(phys.get("beam_deg_max", tight))
            has_zoom = "zoom" in attrs and wide > tight
            beam = beam_info(
                phys.get("lumens"), tight, wide if has_zoom else tight, e["kind"] == "head", phys.get("field_deg")
            )
            # no colour channels at all: the lamp's own colour (halogen lamps glow warm, strobes are white,
            # blacklights UV)
            fixed = None
            if fxlib.uv_only(defn):
                fixed = fxlib.UV_RGB
            elif not attrs & {"red", "green", "blue", "cyan", "color_wheel"}:
                fixed = (1.0, 1.0, 1.0) if e["kind"] == "strobe" else (1.0, 0.72, 0.42)
            if e["kind"] == "head":
                self.heads[e["id"]] = self._head(defn, chans)
            self.info[e["id"]] = {
                "kind": e["kind"],
                "defn": defn,
                "fixed": fixed,
                "wheel": "color_wheel" in attrs and "cyan" not in attrs and fxlib.has_wheel(defn),
                "cmy": "cyan" in attrs,
                "tight": tight,
                "wide": wide if has_zoom else tight,
                "beam": beam,
                "zoom": has_zoom,
            }
        self.wheel_pos: dict[str, float] = {}  # current (continuous) slot position per wheel fixture
        self.gobo_pos: dict[str, float] = {}  # where each head's gobo wheel is (0 = open, k = its k-th gobo)
        self.zoom_now: dict[str, float] = {}

    def _head(self, defn: dict, chans: list[dict]) -> dict:
        """A moving head's beam effects: the effect it really plays for each, and the pictures on its gobo wheel
        (indices into self.gobos, the rig's gobo pictures)."""
        wheels = {}
        for fx in gobos.BEAM_WHEELS:
            if fxlib.beam_effect(defn, chans, fx) == fx:
                wheels[fx] = [self._gobo(k) for k in gobos.wheel(defn, fx)]
        entry = defn.get("beam_fx", {})
        return {
            "defn": defn,
            "chans": chans,
            "wheels": wheels,
            "slots": len(wheels.get("gobo", [])),
            "spin": fxlib.beam_effect(defn, chans, "gobo_spin") == "gobo_spin",
            "prism": {fx for fx in gobos.BEAM_WHEELS if "prism" in entry.get(fx, {})},
        }

    def _gobo(self, key: str) -> int:
        if key not in self.gobo_index:
            self.gobo_index[key] = len(self.gobos)
            self.gobos.append(key)
        return self.gobo_index[key]

    def gobo_pictures(self) -> list[dict]:
        """The rig's gobo pictures, for the visualisers (the hello): the frames say which is in each beam."""
        return [{"key": k, "img": gobos.picture(k), "style": gobos.style(k)} for k in self.gobos]

    def hello_info(self, eid: str) -> dict:
        """Static per-fixture facts for the visualiser."""
        return self.info[eid]["beam"]

    def step(self, states: dict, dt: float) -> dict[str, tuple[float, float, float, float, float]]:
        """(dimmer, r, g, b, white) as the fixtures really show it, per element."""
        out = {}
        for eid, s in states.items():
            info = self.info.get(eid)
            if info is None:
                continue
            r, g, b, white = s.r, s.g, s.b, s.white
            if info["fixed"]:
                r, g, b = info["fixed"]
                out[eid] = (max(s.dimmer, s.white), r, g, b, 0.0)
                continue
            if info["wheel"] or info["kind"] == "laser":
                slots = info["defn"]["color_wheel"]["slots"]
                target = slots.index(fxlib.nearest_slot(info["defn"], (s.r, s.g, s.b), s.white))
                if info["kind"] == "laser":  # macros switch at once
                    r, g, b = slots[target]["rgb"]
                else:
                    r, g, b = self._wheel(eid, slots, target, dt)
                white = 0.0  # a wheel/macro can't add white on top of a colour: the slot is what you get
            out[eid] = (s.dimmer, r, g, b, white)
        return out

    def beams(self, states: dict, dt: float) -> dict[str, tuple[str, list | None, float | None]]:
        """Per moving head: the beam effect it really shows; its gobo as [picture, next picture, how far the wheel
        has turned towards it 0..1, rotation (turns per second, ± direction), shake (per second), prism 0/1]
        (pictures index gobo_pictures(), -1 = the open hole), None without one; the zoom 0..1, None without one.
        A fixed light with a zoom (a wash par) is in it too, with only its zoom: (None, None, zoom)."""
        out = {}
        for eid, h in self.heads.items():
            s = states[eid]
            fx = fxlib.beam_effect(h["defn"], h["chans"], s.fx)
            gobo = self._gobo_wheel(eid, h, fx, s, dt) if h["slots"] else None
            out[eid] = (fx, gobo, self._zoom(eid, s, dt) if self.info[eid]["zoom"] else None)
        for eid, info in self.info.items():
            if info["zoom"] and eid not in self.heads and eid in states:
                out[eid] = (None, None, self._zoom(eid, states[eid], dt))
        return out

    def _zoom(self, eid: str, s, dt: float) -> float:
        """Where the zoom motor has got: towards what the show sends, at ZOOM_PER_S."""
        want = fxlib.zoom_of(s)
        now = self.zoom_now.get(eid, want)
        step = ZOOM_PER_S * dt
        now = want if abs(want - now) <= step else now + math.copysign(step, want - now)
        self.zoom_now[eid] = now
        return now

    def _gobo_wheel(self, eid: str, h: dict, fx: str, s, dt: float) -> list | None:
        n = h["slots"] + 1  # the open hole and the gobos, round the wheel
        pos = self.gobo_pos.get(eid, 0.0)
        speed = min(max(s.fx_speed, 0.0), 1.0)
        if fx == "gobo_spin":  # the wheel scrolls through every gobo
            pos = (pos + (0.4 + 1.6 * speed) * dt * (-1 if s.fx_reverse else 1)) % n
        else:
            target = 1 + s.gobo % h["slots"] if fx in h["wheels"] else 0
            diff = (target - pos + n / 2) % n - n / 2  # shortest way round
            step = GOBO_SLOTS_PER_S * dt
            pos = float(target) if abs(diff) <= step else (pos + math.copysign(step, diff)) % n
        self.gobo_pos[eid] = pos
        k = int(math.floor(pos)) % n
        frac = pos - math.floor(pos)
        if k == 0 and frac < 0.02 and fx not in h["wheels"] and fx != "gobo_spin":
            return None  # open: no gobo in the beam
        pics = h["wheels"].get(fx) or h["wheels"]["gobo"]

        def pic(slot: int) -> int:
            return -1 if slot == 0 else pics[(slot - 1) % len(pics)]

        turn = 0.1 + 0.9 * speed if fx == "gobo_rotate" else 0.0
        shake = 2.0 + 4.0 * speed if fx == "gobo_shake" else 0.0
        return [
            pic(k),
            pic((k + 1) % n),
            round(frac, 3),
            round(-turn if s.fx_reverse else turn, 3),
            round(shake, 2),
            1 if fx in h["prism"] else 0,
        ]

    def _wheel(self, eid: str, slots: list, target: int, dt: float):
        n = len(slots)
        pos = self.wheel_pos.get(eid, float(target))
        diff = (target - pos + n / 2) % n - n / 2  # shortest way round
        step = WHEEL_SLOTS_PER_S * dt
        pos = target if abs(diff) <= step else (pos + math.copysign(step, diff)) % n
        self.wheel_pos[eid] = pos
        k = int(math.floor(pos)) % n
        frac = pos - math.floor(pos)
        a, c = slots[k]["rgb"], slots[(k + 1) % n]["rgb"]
        if frac < 0.15 or frac > 0.85:  # in a slot (or just at its edge)
            return tuple(a if frac < 0.5 else c)
        # a slot edge in the beam: half one colour, half the next
        return tuple((x + y) / 2 for x, y in zip(a, c))
