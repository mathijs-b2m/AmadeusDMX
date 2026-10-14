"""Smoke machines and hazers: when they fire, and how much, so the room is as hazy as the director asks.

The director picks a haze level per phrase (none, light, medium, heavy, and a burst for a drop). The program
plays it like an operator with a fog button: it keeps a model of how hazy the room is, and fires the machines
on the beat, ahead of time (fog takes a while to spread), until the room gets there.

How much one second of fog adds depends on the machine and the room. A machine's output (m³ of fog per
minute, from the fixture or estimated from its power) against the room's volume (the stage's
`room_volume_m3`, else width × depth × ceiling): a big fogger in a small room fires a short, softer burst
and then rests a long time; a small one in a big hall runs as long as it may (its `max_burst_s`), rests to
reheat, and runs again. A hazer (made for continuous output) runs steadily at the level that holds the haze.
The room clears by itself (`fog_clear_s`, its ventilation), and `safety.max_fog` caps the haze.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass

import numpy as np

from amadeus.library import fixtures as fxlib

FOG_FPS = 20

LEVELS = {"none": 0.0, "light": 0.25, "medium": 0.45, "heavy": 0.65, "burst": 0.45}  # haze, 0..1 (a burst: its blast
# on the downbeat adds BURST_ADD on top of a medium haze)
FULL_FILL = 0.1  # the room is fully hazy (1.0) after fog of 10% of its volume (dense machine fog thins out)
SPREAD_S = 8.0  # fog needs this long to spread through the room: fire this far ahead
DEFAULT_CLEAR_S = 300.0  # an ordinary room clears in about five minutes (1/e)
OUTDOOR_CLEAR_S = 60.0  # outdoors the wind takes it in about a minute
OUTDOOR_HAZE_M = 8.0  # … and it is the air up to this height that needs haze for the beams
DEFAULT_MAX_FOG = 0.7  # never hazier than this: a crowd still sees the DJ, smoke alarms stay calm
MIN_ON_S = 0.5  # shorter bursts don't come out of a fogger
MIN_LEVEL = 0.35  # … nor much below this output
MIN_GAP_S = 3.0  # between two bursts at least
BURST_ADD = 0.2  # a drop's burst: a visible blast that adds this much haze at most
WATT_TO_M3_MIN = {"fog": 0.3, "haze": 0.2}  # estimate when the output isn't known: 1500 W fogger ≈ 450 m³/min


@dataclass
class Machine:
    id: str
    m3_min: float  # output at full
    haze: bool  # a hazer: continuous, proportional output
    max_burst_s: float  # longest it can fog before it has to reheat (foggers)
    rest_s: float  # how long it reheats after a full-length burst


def machine(element_id: str, defn: dict) -> Machine:
    fog = defn.get("physical", {}).get("fog", {})
    haze = fog.get("type") == "haze"
    watts = defn.get("physical", {}).get("watts") or (300 if haze else 900)
    m3 = fog.get("m3_min") or watts * WATT_TO_M3_MIN["haze" if haze else "fog"]
    return Machine(
        element_id,
        float(m3),
        haze,
        float(fog.get("max_burst_s", 600 if haze else 25)),
        float(fog.get("rest_s", 0 if haze else 25)),
    )


def room_volume(stage: dict) -> float:
    """The room's air in m³: as the rig says, else the stage width (plus the room either side), the depth in
    front (plus the stage) and the ceiling."""
    if stage.get("room_volume_m3"):
        return float(stage["room_volume_m3"])
    if stage.get("outdoor"):  # open air: the haze only has to fill the air over the stage and the crowd
        return (stage["width_m"] + 8.0) * (stage["room_depth_m"] + 6.0) * OUTDOOR_HAZE_M
    return (stage["width_m"] + 4.0) * (stage["room_depth_m"] + 3.0) * stage["ceiling_m"]


def plan(
    phrases: list[tuple[float, float, str]],
    beats: np.ndarray,
    duration: float,
    machines: list[Machine],
    volume_m3: float,
    clear_s: float = DEFAULT_CLEAR_S,
    max_fog: float = DEFAULT_MAX_FOG,
    start: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """(output per machine and frame 0..1, (N, T); the room's haze per frame, (T,)) at FOG_FPS.
    `phrases`: (start, end, level) with the director's level per phrase; `start`: the haze at 0 s."""
    n_t = int(duration * FOG_FPS) + 2
    dt = 1 / FOG_FPS
    out = np.zeros((len(machines), n_t), np.float32)
    density = np.zeros(n_t, np.float32)
    if not machines or not phrases:
        return out, density
    starts = [p[0] for p in phrases]
    beats = np.asarray(beats, float)
    rate = [m.m3_min / 60 / (FULL_FILL * volume_m3) for m in machines]  # haze per second at full output
    keep = math.exp(-dt / clear_s)

    def level_at(t: float) -> float:
        i = bisect.bisect_right(starts, t) - 1
        return min(LEVELS.get(phrases[max(i, 0)][2], 0.0), max_fog) if t < duration else 0.0

    def next_beat(t: float) -> float:
        k = int(np.searchsorted(beats, t - 1e-6))
        return float(beats[k]) if k < len(beats) else t

    drops = sorted(p[0] for p in phrases if p[2] == "burst")  # a blast right on these downbeats
    on_until = [-1.0] * len(machines)  # a fogger's current burst ends here
    began = [0.0] * len(machines)
    ready_at = [0.0] * len(machines)  # … and it may fire again from here (reheated, a gap left)
    start_at: list[float | None] = [None] * len(machines)  # a burst waiting for its beat
    level_of = [1.0] * len(machines)
    blast = [False] * len(machines)  # the current burst is a drop's: it runs its length

    def rest(m: Machine, length: float) -> float:
        return max(MIN_GAP_S, m.rest_s * length / m.max_burst_s)

    def fire(j: int, t: float, level: float, length: float, is_blast: bool):
        level_of[j], began[j], on_until[j], blast[j] = level, t, t + length, is_blast
        ready_at[j] = on_until[j] + rest(machines[j], length)

    h = start
    for k in range(n_t):
        t = k * dt
        want = level_at(t + SPREAD_S)
        lack = want - h
        d = bisect.bisect_left(drops, t - 1e-9)
        drop = drops[d] if d < len(drops) else None  # the next drop's downbeat
        for j, m in enumerate(machines):
            if m.haze:  # steady: what holds the level, plus a share of what's missing
                hold = want / (rate[j] * clear_s) if want else 0.0
                v = min(max(hold + lack / (rate[j] * 20.0), 0.0), 1.0) if want else 0.0
                out[j, k] = v if v >= 0.05 else 0.0
                continue
            if t < on_until[j]:
                # there: stop early (but not before a fogger can push fog out at all, unless at the cap)
                if not blast[j] and (h >= max_fog or h >= want and t - began[j] >= MIN_ON_S):
                    on_until[j] = t
                    ready_at[j] = t + rest(m, t - began[j])
                else:
                    out[j, k] = level_of[j]
                    continue
            smallest = rate[j] * MIN_LEVEL * MIN_ON_S  # the least a burst of this machine adds here
            if drop is not None and drop - t < dt and t >= ready_at[j] - 1e-9 and h + smallest <= max_fog + 0.05:
                room = min(BURST_ADD, max_fog - h)  # a blast as big as the room takes, sized to the machine
                level = min(max(room / rate[j], MIN_LEVEL), 1.0)
                fire(j, t, level, min(max(room / (rate[j] * level), MIN_ON_S), m.max_burst_s, 6.0), True)
                start_at[j] = None
                out[j, k] = level
                continue
            if start_at[j] is not None and t >= start_at[j] - 1e-9:
                start_at[j] = None
                need = max(lack, 0.0)
                level = min(max(need / (rate[j] * 2.0), MIN_LEVEL), 1.0)  # a big machine in a small room: softer
                length = min(max(need / (rate[j] * level), MIN_ON_S), m.max_burst_s)
                if drop is not None:  # leave it reheated for the drop's blast
                    length = min(length, (drop - t - MIN_GAP_S) / (1 + m.rest_s / m.max_burst_s))
                if length >= MIN_ON_S:
                    fire(j, t, level, length, False)
                    out[j, k] = level
                continue
            if start_at[j] is None and t >= ready_at[j] and lack > 0.03:
                start_at[j] = next_beat(t)  # fire on the beat
        h = h * keep + sum(rate[j] * out[j, k] for j in range(len(machines))) * dt
        h = min(h, 1.0)
        density[k] = h
    return out, density


class FogMixin:
    def _init_fog(self, rig: dict, fixtures: dict):
        self.smokes = [e for e in rig["elements"] if e["kind"] == "smoke"]
        self.quiet = [e["id"] for e in rig["elements"] if e["kind"] in ("smoke", "inert")]  # no light of their own
        machines = [machine(e["id"], fxlib.get(fixtures[e["fixture"]]["fixture"])) for e in self.smokes]
        st, safety = self.stage, rig["safety"]
        phrases = [(d.start, d.end, getattr(d, "fog", "none")) for d in self.plan]
        # a track in a live set starts in the haze the previous one left (about what it asks for itself)
        start = min(LEVELS.get(phrases[0][2], 0.0), 0.45) if self.fog_carry and phrases else 0.0
        self.fog_out, self.fog_density = plan(
            phrases,
            self.beats,
            self.a.duration,
            machines,
            room_volume(st),
            float(st.get("fog_clear_s", OUTDOOR_CLEAR_S if st.get("outdoor") else DEFAULT_CLEAR_S)),
            float(safety.get("max_fog", DEFAULT_MAX_FOG)),
            start,
        )

    def _fog(self, states: dict, t: float):
        """Every element without light of its own gets a state; a smoke machine's level is its output now."""
        from amadeus.engine.state import State

        for eid in self.quiet:
            states.setdefault(eid, State())
        if not self.smokes:
            return
        k = min(max(int(t * FOG_FPS), 0), self.fog_out.shape[1] - 1)
        for j, e in enumerate(self.smokes):
            states[e["id"]] = State(dimmer=float(self.fog_out[j, k]))
