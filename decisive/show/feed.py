"""The visualiser feed: a WebSocket that sends the rig once (`hello`) and then a frame per tick.

Two kinds of client:
- full (the 3D stage, the web visualiser): every fixture's colour, level and beam direction, every tick;
- lite (the Mac app in Perform mode): a small status frame a few times a second (time, phrase, decks).

Full frames are only built while a full client is connected, so a show without a visualiser costs nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

import numpy as np

from decisive.audio.model import Analysis
from decisive.director import Decision
from decisive.library import fixtures as fxlib
from decisive.rig import geometry

LITE_HZ = 5  # status frames per second for lite clients


def is_lite(ws) -> bool:
    req = getattr(ws, "request", None)
    return bool(req and "lite" in req.path)


def element_info(rig: dict, e: dict, real=None) -> dict:
    """One fixture element as the visualiser draws it."""
    fx = next(f for f in rig["fixtures"] if f["id"] == e["fixture"])
    defn = fxlib.get(fx["fixture"])
    info = {
        "id": e["id"],
        "kind": e["kind"],
        "x": e["x"],
        "label": e["label"],
        "pos": [round(v, 3) for v in geometry.position(rig, e, fx)],
        "mount": fx.get("mount", "stand"),
        "beam_deg": defn["physical"].get("beam_deg", 25),
        # how to draw it: the fixture it belongs to, its housing, how it is turned, where a static one shines
        "fixture": fx["id"],
        "body": defn["kind"],
        "rot": fx.get("rot_deg", 0.0),
        "truss": fx.get("truss"),
        "size": [round(v / 1000, 3) for v in defn["physical"].get("size_mm", [])] or None,
    }
    if "offset_m" in e:
        info["cells"] = len(fxlib.heads(defn, fx["mode"]))
        info["length"] = round(fxlib.bar_length_m(fx, defn), 3)
    if e["kind"] == "head":
        info["up"] = [round(float(v), 3) for v in geometry.mount_up(fx)]
    if e["kind"] in ("par", "blinder", "strobe"):
        info["dir"] = [round(float(v), 3) for v in geometry.static_dir(fx, e["kind"])]
    if real is not None:  # real lens, zoom range and beam strength
        info.update(real.hello_info(e["id"]))
    return info


def energy_curve(a: Analysis, n: int = 400) -> list[float]:
    """Loudness over the whole track, 0..1, for the timeline."""
    x = a.rms_db
    edges = np.linspace(0, len(x), n + 1).astype(int)
    v = np.array([x[edges[i] : max(edges[i + 1], edges[i] + 1)].mean() for i in range(n)])
    lo, hi = np.percentile(v, [5, 99])
    return [round(float(y), 3) for y in np.clip((v - lo) / max(hi - lo, 1e-6), 0, 1)]


def hello(a: Analysis, plan: list[Decision], rig: dict, real, *, title: str, director: str) -> str:
    """The rig and the track: sent once to every client, and again when the track changes."""
    return json.dumps(
        {
            "type": "hello",
            "track": title,
            "duration": a.duration,
            "bpm": round(a.bpm, 1),
            "director": director,
            "fixtures": [element_info(rig, e, real) for e in rig["elements"]],
            "stage": geometry.stage(rig),
            "trusses": rig.get("trusses", []),
            "zones": [z for z in rig.get("zones", []) if z.get("enabled", True)],
            "plan": [asdict(d) for d in plan],
            "max_flash_hz": rig["safety"]["max_flash_hz"],
            "energy": energy_curve(a),
            "screen": bool(rig.get("screen")),
            # what kind of music, where that came from, and the program it gets (if any: e.g. cinematic)
            "genre": getattr(a, "genre", ""),
            "genre_source": getattr(a, "genre_source", ""),
            "style": getattr(a, "style", ""),  # the genre whose house style the plan follows
            "program": "cinematic" if getattr(a, "genre", "") == "cinematic" and a.hits is not None else "",
        }
    )


def guard_notes(engine) -> dict[str, str]:
    """What the laser guard did this frame (laser id → note), for the operator."""
    return {k: v for k, v in getattr(engine, "guard_notes", {}).items() if v}


class Feed:
    """The clients and what they get. `send` once per tick; `set_hello` when the rig or the track changes."""

    def __init__(self, rig: dict, real, period: float):
        self.rig, self.real, self.period = rig, real, period
        self.full: set = set()
        self.lite: set = set()
        self.hello: str | None = None
        self.ids = [e["id"] for e in rig["elements"]]
        self.smokes = [e["id"] for e in rig["elements"] if e["kind"] == "smoke"]
        self.dark = {e["id"] for e in rig["elements"] if e["kind"] in ("smoke", "inert")}  # no light of their own
        by_id = {f["id"]: f for f in rig["fixtures"]}
        self.head_fk = {
            e["id"]: (by_id[e["fixture"]], fxlib.get(by_id[e["fixture"]]["fixture"]))
            for e in rig["elements"]
            if e["kind"] == "head"
        }
        self.lite_every = max(1, round(1.0 / (period * LITE_HZ)))
        self.tick = 0

    async def handler(self, ws):
        group = self.lite if is_lite(ws) else self.full
        group.add(ws)
        try:
            if self.hello:
                await ws.send(self.hello)
            await ws.wait_closed()
        finally:
            group.discard(ws)

    @property
    def watched(self) -> bool:
        return bool(self.full or self.lite)

    def set_hello(self, msg: str):
        from websockets.asyncio.server import broadcast

        self.hello = msg
        broadcast(self.full | self.lite, msg)

    def send(self, status: dict, fixtures: Callable[[], dict]):
        """`status`: t, phrase, bp and whatever else both kinds of client get (decks, link, guard).
        `fixtures()`: the full frame's extra fields, only called when a full client is connected."""
        from websockets.asyncio.server import broadcast

        self.tick += 1
        if not self.hello:
            return
        if self.lite and self.tick % self.lite_every == 0:
            broadcast(self.lite, json.dumps({"type": "frame", "lite": True, **status}))
        if self.full:
            broadcast(self.full, json.dumps({"type": "frame", **status, **fixtures()}))

    def fixture_fields(self, states: dict, lasers: dict | None = None) -> dict:
        """Every element's colour and level as the fixtures really show it, each head's beam effect and
        direction (computed back from its DMX pan/tilt), and the beams each laser draws."""
        shown = self.real.step(states, self.period)
        fx = []
        for e in self.ids:
            s = states[e]
            dim, r, g, b, w = shown.get(e, (s.dimmer, s.r, s.g, s.b, s.white))
            if e in self.dark:
                dim = w = 0.0
            fx.append([round(v, 3) for v in (dim, r, g, b, w, s.pan, s.tilt)])
        out = {
            "fx": fx,
            "beam": [states[e].fx if e in self.head_fk else None for e in self.ids],
            "dirs": [
                [round(float(v), 3) for v in geometry.fk(*self.head_fk[e], states[e].pan, states[e].tilt)]
                if e in self.head_fk
                else None
                for e in self.ids
            ],
        }
        if lasers:
            out["lz"] = [lasers.get(e) for e in self.ids]
        if self.smokes:  # each smoke machine's output now, 0..1
            out["fog"] = {e: round(states[e].dimmer, 2) for e in self.smokes}
        return out


def track_title(file: str | Path, deck: int | None = None) -> str:
    name = Path(file).name
    return f"Deck {deck}: {name}" if deck is not None else name
