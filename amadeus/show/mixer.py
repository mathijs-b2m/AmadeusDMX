"""Several decks at once: brightness and colour blend by volume; heads and lasers follow one deck."""

from __future__ import annotations

from amadeus.engine import NUMERIC, State

DOMINANCE_MARGIN = 1.2  # the heads switch decks only when the other deck is clearly louder
HEAD_FIELDS = ("pan", "tilt", "dmx_pan", "dmx_tilt", "fx", "gobo", "fx_speed", "fx_reverse")
LASER_FIELDS = ("pan", "tilt", "fx", "size", "spin", "lcolor", "phase", "dimmer", "r", "g", "b", "white")


def blend(parts: list[tuple[float, dict[str, State]]]) -> dict[str, State]:
    """Volume-weighted mix of several decks' fixture states (brightness and colour)."""
    total = sum(w for w, _ in parts) or 1.0
    out = {}
    for eid in parts[0][1]:
        s = State()
        for f in NUMERIC:
            setattr(s, f, sum(w * getattr(st[eid], f) for w, st in parts) / total)
        out[eid] = s
    return out


class Mixer:
    """Mixes what the audible decks render. A part is (volume, states, deck, show, t, phrase)."""

    def __init__(self, rig: dict):
        self.heads = [e["id"] for e in rig["elements"] if e["kind"] == "head"]
        self.lasers = [e["id"] for e in rig["elements"] if e["kind"] == "laser"]
        self.dominant: int | None = None  # the deck the heads follow

    def mix(self, parts: list[tuple]) -> tuple[dict[str, State], tuple]:
        """The blended states, and the dominant part (whose position, beam effects and lasers win)."""
        cur = next((p for p in parts if p[2].deck == self.dominant), None)
        loudest = max(parts, key=lambda p: p[0])
        dom = cur if cur and loudest[0] < cur[0] * DOMINANCE_MARGIN else loudest
        self.dominant = dom[2].deck
        states = blend([(w, st) for w, st, *_ in parts])
        for ids, fields in ((self.heads, HEAD_FIELDS), (self.lasers, LASER_FIELDS)):
            for eid in ids:
                src = dom[1][eid]
                for f in fields:
                    setattr(states[eid], f, getattr(src, f))
        return states, dom
