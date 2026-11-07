"""What one fixture element does in one frame."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class State:
    dimmer: float = 0.0
    r: float = 0.0
    g: float = 0.0
    b: float = 0.0
    white: float = 0.0
    pan: float = 0.5  # DMX 0..1
    tilt: float = 0.5
    fx: str = "open"  # beam effect (moving heads): open, gobo, prism, frost, …
    gobo: int = 0  # which gobo, for the gobo effects
    fx_speed: float = 0.5  # rotation speed 0..1 for spinning effects
    fx_reverse: bool = False  # rotate the other way (mirrored heads)
    zoom: float = 0.0  # moving heads with a zoom: 0 = the tightest beam .. 1 = the widest
    size: float = 0.5  # lasers: shape size 0..1
    spin: float = 0.0  # lasers: rotation -1..1 (0 = still)
    lcolor: str = ""  # lasers: colour mode (base/accent/white/cycle: one colour; multi/rainbow: per beam)
    phase: float = -1.0  # lasers: ripple position across the fan 0..1 (-1: all beams lit)
    strobe_hz: float = 0.0  # strobing this fast (0: not): a fixture with a strobe channel flashes on it, its dimmer
    # open at `dimmer` (library/strobe.py). Everything that dims or darkens a light works on `dimmer`, so it holds here
    gate: float = 1.0  # the flash on the beat grid: how much of `dimmer` is lit now. A light without a strobe channel
    # flashes with it on its dimmer, and the visualisers show it (`lit`); the show arc holds a head steady at gate 1
    dmx_pan: float | None = None  # pan/tilt sent as DMX (the target, slightly ahead); pan/tilt above is the
    dmx_tilt: float | None = None  # predicted real position, used by the visualiser

    @property
    def lit(self) -> float:
        """The level this frame, with the flash: what a dimmer plays and the visualisers show."""
        return self.dimmer * self.gate

    def blend(self, o: State, k: float) -> State:
        out = State(*(getattr(self, f) * (1 - k) + getattr(o, f) * k for f in NUMERIC))
        src = o if k >= 0.5 else self  # discrete: switch halfway
        out.fx, out.gobo, out.fx_speed, out.fx_reverse = src.fx, src.gobo, src.fx_speed, src.fx_reverse
        out.size, out.spin, out.lcolor, out.phase = src.size, src.spin, src.lcolor, src.phase
        out.dmx_pan, out.dmx_tilt, out.strobe_hz, out.gate = src.dmx_pan, src.dmx_tilt, src.strobe_hz, src.gate
        out.zoom = self.zoom * (1 - k) + o.zoom * k
        return out


NUMERIC = ("dimmer", "r", "g", "b", "white", "pan", "tilt")
