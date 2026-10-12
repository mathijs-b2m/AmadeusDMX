"""What each fixture really puts out, for the visualiser (the engine says what it WANTS).

- Colour wheels only have their slots: the beam snaps to the slot the DMX selects, and when the wheel
  turns to a far slot it scrolls through the colours in between (half/half while a slot edge passes).
- CMY fixtures mix subtractively: what the C/M/Y filters let through.
- Lasers only have their colour macros.
- Brightness of a beam in haze follows the light packed into the beam: lumens / beam angle². A 4° LED
  beam punches about as hard as a 12° 11,600 lm profile; a zoomed-out wash is much softer.
- Beam angle: the lens with the zoom the show sends (tight for beams, wide for frost).
"""

from __future__ import annotations

import math

from amadeus.library import fixtures as fxlib

WHEEL_SLOTS_PER_S = 14.0  # a typical colour wheel moves about 14 slots per second (shortest way round)
REF_INTENSITY = 1500 / 4**2  # lumens per square degree that counts as a full-strength beam (a 4° 1,500 lm beam)


class Realism:
    def __init__(self, rig: dict):
        self.rig = rig
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
            lumens = phys.get("lumens")
            if e["kind"] == "head" and lumens:
                output = min(1.0, max(0.3, math.sqrt(lumens / tight**2 / REF_INTENSITY)))
                output_wide = min(1.0, max(0.15, math.sqrt(lumens / wide**2 / REF_INTENSITY)))
            else:
                output = output_wide = 1.0
            # no colour channels at all: the lamp's own colour (halogen lamps glow warm, strobes are white)
            fixed = None
            if not attrs & {"red", "green", "blue", "cyan", "color_wheel"}:
                fixed = (1.0, 1.0, 1.0) if e["kind"] == "strobe" else (1.0, 0.72, 0.42)
            self.info[e["id"]] = {
                "kind": e["kind"],
                "defn": defn,
                "fixed": fixed,
                "wheel": "color_wheel" in attrs and "cyan" not in attrs and fxlib.has_wheel(defn),
                "cmy": "cyan" in attrs,
                "tight": tight,
                "wide": wide if has_zoom else tight,
                "output": output,
                "output_wide": output_wide if has_zoom else output,
            }
        self.wheel_pos: dict[str, float] = {}  # current (continuous) slot position per wheel fixture

    def hello_info(self, eid: str) -> dict:
        """Static per-fixture facts for the visualiser."""
        i = self.info[eid]
        return {
            "beam_deg": i["tight"],
            "beam_wide": i["wide"],
            "output": round(i["output"], 3),
            "output_wide": round(i["output_wide"], 3),
        }

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
