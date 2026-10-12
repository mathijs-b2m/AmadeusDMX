"""A digital twin of one moving head, driven only by the DMX it receives, next to what the engine predicts.

The visualiser draws where the engine *thinks* a head is (its own motor model). The real fixture only gets
DMX. This twin also only gets DMX, decodes it independently, and moves with its own motor model whose
range and speed you calibrate against the real fixture, fixture by fixture. Where twin and engine disagree,
the visualiser shows something the light won't do.

    python tools/twin.py check fuze1 [--set fuze24] [--bpm 145] [--fit] [--apply]
        offline: render the synthetic track, drive the twin with the engine's DMX, compare, fit
    python tools/twin.py live fuze1 [--forward IP] [--listen 127.0.0.1:6454] [--feed ws://127.0.0.1:8765]
        live: a relay between the engine and the node (start the show with `--artnet 127.0.0.1`), a page at
        http://127.0.0.1:8790 with the twin, the engine's prediction and the DMX side by side, and test
        patterns to calibrate the twin's range and speed by eye against the real fixture

The twin profile is saved in the fixture's library file (`"twin"`); "apply" copies its range and speed into
the engine's model of that fixture (`physical`, `motion`).
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import struct
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, fields
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from decisive.engine.motion import DEFAULT_MOTION, DMX_LEAD_S, MOTION_FPS, _slew  # noqa: E402
from decisive.engine.state import State  # noqa: E402
from decisive.library import fixtures as fxlib  # noqa: E402
from decisive.rig import store  # noqa: E402
from decisive.rig.loader import load_rig  # noqa: E402

AXES = ("pan", "tilt")
SUBSTEP = 0.001  # the twin's motors are simulated in 1 ms steps
SAMPLE_HZ = 50  # what gets compared and drawn
PAGE = Path(__file__).with_name("twin.html")


# ---------------------------------------------------------------- the twin


@dataclass
class Axis:
    """How one motor of the real fixture behaves. Everything here is meant to be calibrated by eye."""

    range_deg: float  # what a full DMX sweep (0 → 255/65535) really turns
    vmax_dps: float  # top speed
    accel_dps2: float  # speeding up
    decel_dps2: float  # braking (cheap motors often brake harder or softer than they start)
    latency_ms: float = 40.0  # from DMX in to the motor starting: receiving, firmware, filtering
    smooth_ms: float = 0.0  # firmware smoothing of the DMX target (a first-order filter), 0 = none
    slowest: float = 0.05  # pan/tilt speed channel at 255: this fraction of the top speed


def default_profile(defn: dict) -> dict[str, Axis]:
    """The fixture's twin profile, else a start from what the engine believes about it."""
    saved = defn.get("twin", {})
    motion = defn.get("motion", DEFAULT_MOTION)
    out = {}
    for axis in AXES:
        if axis in saved:
            known = {f.name for f in fields(Axis)}
            out[axis] = Axis(**{k: v for k, v in saved[axis].items() if k in known})
            continue
        acc = motion.get(f"{axis}_accel_dps2", motion["accel_dps2"])
        out[axis] = Axis(
            range_deg=float(defn["physical"].get(f"{axis}_deg") or 0),
            vmax_dps=float(motion[f"{axis}_speed_dps"]),
            accel_dps2=float(acc),
            decel_dps2=float(acc),
            latency_ms=DMX_LEAD_S * 1000,  # uncalibrated: exactly the engine's assumption
        )
    return out


class Motor:
    """One axis: delayed target → optional smoothing → speed and acceleration limits."""

    def __init__(self, axis: Axis):
        self.axis = axis
        self.pos: float | None = None
        self.vel = 0.0
        self.filt = 0.0

    def step(self, target: float, dt: float, speed: float = 1.0):
        a = self.axis
        if self.pos is None:
            self.pos = self.filt = target
        if a.smooth_ms > 0:
            self.filt += (target - self.filt) * (1 - math.exp(-dt * 1000 / a.smooth_ms))
        else:
            self.filt = target
        err = self.filt - self.pos
        v_want = math.copysign(min(a.vmax_dps * speed, math.sqrt(2 * a.decel_dps2 * abs(err))), err)
        speeding_up = abs(v_want) > abs(self.vel) and v_want * self.vel >= 0
        lim = (a.accel_dps2 if speeding_up else a.decel_dps2) * dt
        self.vel += max(-lim, min(lim, v_want - self.vel))
        self.pos += self.vel * dt
        if abs(self.filt - self.pos) < 1e-3 and abs(self.vel) < 0.5:
            self.pos, self.vel = self.filt, 0.0

    @property
    def settled(self) -> bool:
        return self.pos is not None and abs(self.vel) < 3.0 and abs(self.filt - self.pos) < 0.5


class Twin:
    """Both motors, fed with decoded DMX (0..1 per axis, the speed channel byte) as it arrives."""

    def __init__(self, profile: dict[str, Axis]):
        self.profile = profile
        self.motors = {a: Motor(profile[a]) for a in AXES}
        self.queue = {a: deque() for a in AXES}  # (time, norm, speed byte) waiting out the latency
        self.now: dict[str, tuple[float, int] | None] = {a: None for a in AXES}  # what each motor is given
        self.t: float | None = None

    def feed(self, t: float, pan: float, tilt: float, speed: int = 0):
        self.queue["pan"].append((t, pan, speed))
        self.queue["tilt"].append((t, tilt, speed))

    def advance(self, t: float):
        if self.t is None:
            self.t = t
        while self.t < t:
            dt = min(SUBSTEP, t - self.t)
            self.t += dt
            for a, m in self.motors.items():
                q, delay = self.queue[a], m.axis.latency_ms / 1000
                while q and q[0][0] <= self.t - delay:
                    _, norm, speed = q.popleft()
                    self.now[a] = (norm, speed)
                if self.now[a] is None:  # no DMX yet: the head stands where the first DMX will say
                    continue
                norm, speed = self.now[a]
                slow = 1 - (speed / 255) * (1 - m.axis.slowest)
                m.step(norm * m.axis.range_deg, dt, slow)

    def deg(self, axis: str) -> float:
        return self.motors[axis].pos if self.motors[axis].pos is not None else float("nan")


# ---------------------------------------------------------------- the fixture and its DMX


class Head:
    """One head of the rig: where its channels are, and the engine's view of its ranges."""

    def __init__(self, rig: dict, fixture_id: str):
        by_id = {f["id"]: f for f in rig["fixtures"]}
        if fixture_id not in by_id:
            heads = [f["id"] for f in rig["fixtures"] if "pan" in _attrs(f)]
            raise SystemExit(f"No fixture '{fixture_id}'. Moving heads in this rig: {', '.join(heads) or 'none'}")
        self.rig, self.fx = rig, by_id[fixture_id]
        self.defn = fxlib.get(self.fx["fixture"])
        attrs = _attrs(self.fx)
        if "tilt" not in attrs:
            raise SystemExit(f"{fixture_id} has no pan/tilt: nothing to compare")
        self.ch = {a: attrs.index(a) for a in ("pan", "pan_fine", "tilt", "tilt_fine", "pan_tilt_speed") if a in attrs}
        self.element = next(e["id"] for e in rig["elements"] if e["fixture"] == fixture_id)
        phys = self.defn["physical"]
        self.engine_range = {"pan": float(phys.get("pan_deg") or 0), "tilt": float(phys["tilt_deg"])}
        self.home_frac = {  # the DMX value (0..1) that points at home: it stays, whatever the range turns out to be
            a: self.fx.get(f"{a}_home_deg", r / 2) / r if r else 0.5 for a, r in self.engine_range.items()
        }
        self.universe = self.fx["universe"]
        self.wire_universe = wire_universe(rig, self.universe)

    def decode(self, data: bytes) -> tuple[float, float, int] | None:
        """DMX bytes of the universe → (pan, tilt) 0..1 and the speed channel, read straight from the bytes."""
        base = self.fx["address"] - 1
        if len(data) < base + max(self.ch.values()) + 1:
            return None

        def axis(a):
            hi = data[base + self.ch[a]]
            lo = data[base + self.ch[f"{a}_fine"]] if f"{a}_fine" in self.ch else 0
            return (hi << 8 | lo) / 65535 if f"{a}_fine" in self.ch else hi / 255

        pan = axis("pan") if "pan" in self.ch else 0.5
        speed = data[base + self.ch["pan_tilt_speed"]] if "pan_tilt_speed" in self.ch else 0
        return pan, axis("tilt"), speed

    def rel(self, axis: str, norm, range_deg: float):
        """DMX 0..1 → degrees from home along that motor, in a given range."""
        return (np.asarray(norm, float) - self.home_frac[axis]) * range_deg

    def norm(self, axis: str, deg: float, range_deg: float) -> float:
        return min(max(self.home_frac[axis] + deg / range_deg, 0.0), 1.0) if range_deg else 0.5

    def universe_with(self, pan: float, tilt: float, dimmer: float) -> bytearray:
        """A universe with only this head on (the patterns), through the library's own patching."""
        buf = bytearray(512)
        master = self.rig["safety"].get("master", 1.0)
        states = {e["id"]: State() for e in self.rig["elements"]}
        states[self.element] = State(dimmer=dimmer * master, r=1.0, g=1.0, b=1.0, pan=pan, tilt=tilt)
        for f in self.rig["fixtures"]:
            if f["universe"] == self.universe:
                fxlib.patch(buf, f, states)
        return buf


def _attrs(fx: dict) -> list[str]:
    return [c["attr"] for c in fxlib.channels(fxlib.get(fx["fixture"]), fx["mode"])]


def wire_universe(rig: dict, u: int) -> int:
    """The Art-Net universe a set's universe goes out as (the output's offset or map)."""
    from decisive.dmx.outputs import _specs

    for s in _specs(rig):
        if s.get("type", "artnet") == "artnet":
            m = {int(k): int(v) for k, v in (s.get("universe_map") or {}).items()}
            return m.get(u, u + int(s.get("universe_offset", 0)))
    return u


def save_profile(defn: dict, profile: dict[str, Axis], calibrated: bool = True):
    path = fxlib.LIB_DIR / f"{defn['key']}.json"
    data = json.loads(path.read_text())
    data["twin"] = {
        "_note": "How the real fixture moves, calibrated with tools/twin.py: what a full DMX sweep turns, top "
        "speed, acceleration, braking, the delay from DMX to motion. `motion` is the engine's model of it.",
        "calibrated": calibrated,
        **{a: {k: round(v, 3) for k, v in asdict(profile[a]).items()} for a in AXES},
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    defn["twin"] = data["twin"]
    return path


def apply_to_engine(head: Head, profile: dict[str, Axis], selection, motion: dict | None = None) -> list[str]:
    """Copy the twin's range and speed into the engine's fixture model; keep every set's home pointing where it
    did (home is a DMX value on the real fixture: its degrees scale with the range)."""
    defn = head.defn
    path = fxlib.LIB_DIR / f"{defn['key']}.json"
    data = json.loads(path.read_text())
    notes = []
    m = data.setdefault("motion", {})
    for a in AXES:
        p, old = profile[a], data["physical"].get(f"{a}_deg") or 0
        if old and abs(p.range_deg - old) > 0.5:
            data["physical"][f"{a}_deg"] = round(p.range_deg, 1)
            notes.append(f"{a} range {old}° → {p.range_deg:.0f}°")
        fit = (motion or {}).get(a)
        v = fit["vmax_dps"] if fit else p.vmax_dps
        acc = fit["accel_dps2"] if fit else (p.accel_dps2 + p.decel_dps2) / 2  # the engine has one for both
        m[f"{a}_speed_dps"], m[f"{a}_accel_dps2"] = round(v), round(acc)
        notes.append(f"{a} {round(v)}°/s, {round(acc)}°/s²")
    m["accel_dps2"] = min(m["pan_accel_dps2"], m["tilt_accel_dps2"])
    m["estimated"] = False
    m["_twin"] = "speed and acceleration from the calibrated twin (tools/twin.py)"
    path.write_text(json.dumps(data, indent=2) + "\n")
    defn.update(data)
    if selection is not None:
        notes += _rescale_homes(selection, defn["key"], head.engine_range, profile)
    head.engine_range = {a: profile[a].range_deg for a in AXES}
    return notes


def _rescale_homes(selection, key: str, old_range: dict, profile: dict[str, Axis]) -> list[str]:
    merged, notes = selection.load(), []
    for f in merged.get("fixtures", []):
        if f.get("fixture") != key:
            continue
        for a in AXES:
            k, old, new = f"{a}_home_deg", old_range[a], profile[a].range_deg
            if k in f and old and abs(new - old) > 0.5:
                was = f[k]
                f[k] = round(was * new / old, 1)
                notes.append(f"{f['id']}: {k} {was} → {f[k]} (same DMX value)")
    if notes:
        selection.save(merged)
    return notes


# ---------------------------------------------------------------- comparing


def compare(engine: np.ndarray, twin: np.ndarray, hz: float = SAMPLE_HZ) -> dict | None:
    """How far the engine's prediction is from the twin, in degrees, how big each one's moves are, and how
    much later (+) or earlier (-) the twin moves than the engine says."""
    ok = ~(np.isnan(engine) | np.isnan(twin))
    if ok.sum() < hz:
        return None
    e, w = engine[ok], twin[ok]
    swing_e = float(np.percentile(e, 95) - np.percentile(e, 5))
    swing_w = float(np.percentile(w, 95) - np.percentile(w, 5))
    n, span = len(e), int(0.5 * hz)
    de, dw = np.diff(e), np.diff(w)
    best, lag = -float("inf"), 0
    for k in range(-span, span + 1):  # twin(t) ≈ engine(t - k): when the moves happen, whatever their size
        a, b = (de[: n - 1 - k], dw[k:]) if k >= 0 else (de[-k:], dw[: n - 1 + k])
        c = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
        if c > best:
            best, lag = c, k
    a, b = (e[: n - lag], w[lag:]) if lag >= 0 else (e[-lag:], w[: n + lag])
    # the range: how far from home the twin stands for the angle the engine shows, only where both stand still
    # (a motor too slow to finish its moves is a speed problem, not a range one)
    still = np.zeros(len(a), bool)
    still[1:] = (np.abs(np.diff(a)) < 0.2) & (np.abs(np.diff(b)) < 0.2) & (np.abs(a[1:]) > 5)
    scale = float(np.sum(a[still] * b[still]) / np.sum(a[still] ** 2)) if still.sum() > hz / 2 else None
    aligned = float(np.sqrt(np.mean((a - b) ** 2)))
    d = np.abs(e - w)
    return {
        "rms": round(float(np.sqrt(np.mean(d**2))), 2),
        "p95": round(float(np.percentile(d, 95)), 2),
        "engine_swing": round(swing_e, 1),
        "twin_swing": round(swing_w, 1),
        "size": round(swing_w / swing_e, 2) if swing_e > 1 else None,
        "range": round(scale, 2) if scale else None,
        "lag_ms": round(lag * 1000 / hz),
        "rms_aligned": round(aligned, 2),
    }


def verdict(axis: str, c: dict | None) -> str:
    if not c:
        return f"{axis}: no data yet"
    if max(c["engine_swing"], c["twin_swing"]) < 5:
        return f"{axis}: hardly moving: nothing to compare yet"
    out = []
    rng, size = c.get("range"), c["size"]
    if rng and abs(rng - 1) > 0.08:
        out.append(f"turns {rng:.2f}× as far from home as shown (range)")
    if size and abs(size / (rng or 1) - 1) > 0.15:  # beyond the range: it doesn't finish its moves (speed)
        out.append(f"its moves are {size:.2f}× the size shown")
    if abs(c["lag_ms"]) >= 40:
        out.append(f"{abs(c['lag_ms'])} ms {'later' if c['lag_ms'] > 0 else 'earlier'} than shown")
    return f"{axis}: " + ("; ".join(out) if out else f"matches (within {c['p95']}° most of the time)")


def fit_engine(goal: np.ndarray, twin: np.ndarray, vmax: float, accel: float) -> dict:
    """The engine's motor model (its own _slew, at its own rate) whose prediction comes closest to the twin.
    `goal`: the engine's targets in twin degrees, sampled at MOTION_FPS."""
    ok = ~(np.isnan(goal) | np.isnan(twin))
    first = int(np.argmax(ok))
    goal, twin = np.nan_to_num(goal[first:], nan=float(goal[first])), twin[first:]
    ok = ok[first:]
    best = (float("inf"), vmax, accel)
    for vs in np.geomspace(0.4, 2.5, 13):
        for as_ in np.geomspace(0.25, 4.0, 17):
            pred = _slew(goal, vmax * vs, accel * as_, 1 / MOTION_FPS)
            err = float(np.mean((pred[ok] - twin[ok]) ** 2))
            if err < best[0]:
                best = (err, vmax * vs, accel * as_)
    return {"vmax_dps": best[1], "accel_dps2": best[2], "rms": round(math.sqrt(best[0]), 2)}


# ---------------------------------------------------------------- offline: the synthetic track


def render(rig: dict, head: Head, bpm: float = 128.0) -> tuple[np.ndarray, float]:
    """The synthetic track through the engine: per DMX frame t, the engine's pan/tilt (what the visualiser
    draws, 0..1), the DMX pan/tilt and the speed channel as decoded from the bytes."""
    from decisive.director import RuleDirector, direct
    from decisive.engine import Engine, motion
    from decisive.rig.groups import head_groups, laser_list
    from tests.synthetic import synthetic_analysis

    a = synthetic_analysis(bpm=bpm)
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    fps = rig["artnet"].get("fps", 40)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        motion.TRAJ_CACHE = Path(tmp)  # always simulate: the fixture file may just have changed
        eng = Engine(a, plan, rig)
        for k in range(int((a.duration - 0.1) * fps)):
            _, states = eng.render(k / fps)
            got = head.decode(bytes(eng.dmx(states).get(head.universe, bytes(512)))) or (np.nan, np.nan, 0)
            s = states[head.element]
            rows.append((k / fps, s.pan, s.tilt, *got))
    return np.array(rows), fps


def drive(r: np.ndarray, profile: dict[str, Axis]) -> np.ndarray:
    """The twin driven by rendered DMX: its pan and tilt in degrees from DMX 0, per frame."""
    twin, out = Twin(profile), []
    for t, _, _, pan, tilt, speed in r:
        twin.advance(t)
        if not math.isnan(pan):
            twin.feed(t, pan, tilt, int(speed))
        out.append((twin.deg("pan"), twin.deg("tilt")))
    return np.array(out)


def measure(head: Head, profile: dict[str, Axis], r: np.ndarray, tw: np.ndarray, fps: float) -> dict:
    every = max(1, round(fps / SAMPLE_HZ))
    out = {}
    for i, axis in enumerate(AXES):
        if head.engine_range[axis]:
            eng = head.rel(axis, r[:, 1 + i], head.engine_range[axis])
            twin = tw[:, i] - head.home_frac[axis] * profile[axis].range_deg
            out[axis] = compare(eng[::every], twin[::every], fps / every)
    return out


def check(args):
    sel = _selection(args)
    rig = load_rig(sel)
    head = Head(rig, args.fixture)
    profile = default_profile(head.defn)
    r, fps = render(rig, head, args.bpm)
    tw = drive(r, profile)
    t = r[:, 0]
    results = measure(head, profile, r, tw, fps)
    src = "calibrated twin" if head.defn.get("twin", {}).get("calibrated") else "twin = the engine's own numbers"
    print(f"{args.fixture} ({head.defn['model']}), synthetic track at {args.bpm:g} BPM, {src}")
    print(
        f"  the engine sends pan/tilt {DMX_LEAD_S * 1000:.0f} ms early; twin latency: "
        + ", ".join(f"{x} {profile[x].latency_ms:.0f} ms" for x in AXES)
    )
    fits = {}
    for i, axis in enumerate(AXES):
        if not head.engine_range[axis]:
            continue
        c = results[axis]
        twin_deg = tw[:, i] - head.home_frac[axis] * profile[axis].range_deg
        print("  " + verdict(axis, c))
        if c:
            print(
                f"     gap {c['rms']}° rms, {c['p95']}° p95; swings: visualiser {c['engine_swing']}°, "
                f"twin {c['twin_swing']}°; twin/visualiser angle from home: {c['range']}"
            )
        if args.fit:
            # the engine's goal at time t is what went out as DMX at t - lead, in the twin's degrees
            tg = np.arange(0, t[-1], 1 / MOTION_FPS)
            dmx = np.interp(tg - DMX_LEAD_S, t, head.rel(axis, r[:, 3 + i], profile[axis].range_deg))
            twin_g = np.interp(tg, t, twin_deg)
            p = profile[axis]
            f = fit_engine(dmx, twin_g, p.vmax_dps, (p.accel_dps2 + p.decel_dps2) / 2)
            if c and f["rms"] < 0.75 * c["rms"]:  # only worth applying when clearly closer
                fits[axis] = f
            print(
                f"     engine model that best predicts the twin: {f['vmax_dps']:.0f}°/s, "
                f"{f['accel_dps2']:.0f}°/s² (gap left: {f['rms']}° rms)"
            )
    if args.apply:
        for note in apply_to_engine(head, profile, sel, fits or None):
            print("  applied: " + note)


# ---------------------------------------------------------------- live: relay, feed, patterns, page


class Live:
    def __init__(self, args):
        self.sel = _selection(args)
        self.rig = load_rig(self.sel)
        self.head = Head(self.rig, args.fixture)
        self.profile = default_profile(self.head.defn)
        self.twin = Twin(self.profile)
        self.lock = threading.Lock()
        self.samples: deque = deque(maxlen=SAMPLE_HZ * 30)  # t, dmx pan/tilt, engine pan/tilt (0..1), twin deg
        self.engine: tuple[float, float, float] | None = None  # (time, pan, tilt) from the feed
        self.dmx: tuple[float, float, float] | None = None
        self.dmx_count, self.dmx_rate = 0, 0.0
        self.feed_state, self.track = "connecting", ""
        self.pattern: dict = {"name": "off", "axis": "tilt", "amp": 60, "bpm": 120, "dwell": 1.2, "pan": 0, "tilt": 45}
        self.t0 = time.monotonic()
        self.lit = False  # the patterns' beam
        self.changed = 0.0  # metrics only look at what happened after the last edit of the twin
        host, _, port = args.listen.partition(":")
        self.listen = (host, int(port or 6454))
        ip = args.forward if args.forward is not None else self.rig.get("artnet", {}).get("ip", "")
        self.forward = None if not ip or ip.startswith("127.") or args.forward == "" else (ip, 6454)
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.feed_url = args.feed

    # -- inputs

    def dmx_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(self.listen)
        while True:
            pkt, _ = sock.recvfrom(1024)
            if pkt[:8] != b"Art-Net\x00":
                continue
            if self.pattern["name"] != "off":  # the patterns own the fixture: the engine's DMX is dropped
                continue
            if self.forward:
                self.out.sendto(pkt, self.forward)
            if struct.unpack_from("<H", pkt, 8)[0] != 0x5000:
                continue
            uni = pkt[14] | (pkt[15] << 8)
            if uni != self.head.wire_universe:
                continue
            length = struct.unpack_from(">H", pkt, 16)[0]
            got = self.head.decode(pkt[18 : 18 + length])
            if got:
                self._input(*got)

    def _input(self, pan: float, tilt: float, speed: int):
        t = time.monotonic() - self.t0
        with self.lock:
            self.twin.feed(t, pan, tilt, speed)
            self.dmx = (t, pan, tilt)
            self.dmx_count += 1

    def feed_loop(self):
        from websockets.sync.client import connect

        while True:
            try:
                with connect(self.feed_url, open_timeout=2, max_size=None) as ws:
                    self.feed_state = "connected"
                    idx = None
                    for msg in ws:
                        m = json.loads(msg)
                        if m.get("type") == "hello":
                            self.track = m.get("track", "")
                            ids = [f["id"] for f in m.get("fixtures", [])]
                            idx = ids.index(self.head.element) if self.head.element in ids else None
                            self.feed_state = "connected" if idx is not None else "connected (fixture not in show)"
                        elif m.get("type") == "frame" and idx is not None and "fx" in m:
                            v = m["fx"][idx]
                            with self.lock:
                                self.engine = (time.monotonic() - self.t0, v[5], v[6])
            except Exception:
                self.feed_state = "not running"
                self.engine = None
                time.sleep(2)

    # -- the twin's clock

    def sim_loop(self):
        next_sample = 0.0
        last_rate, last_count = 0.0, 0
        while True:
            t = time.monotonic() - self.t0
            with self.lock:
                self.twin.advance(t)
                if t >= next_sample:
                    next_sample = t + 1 / SAMPLE_HZ
                    d = self.dmx if self.dmx and t - self.dmx[0] < 0.5 else None
                    e = self.engine if self.engine and t - self.engine[0] < 0.5 else None
                    self.samples.append(
                        (
                            t,
                            *(d[1:] if d else (np.nan, np.nan)),
                            *(e[1:] if e else (np.nan, np.nan)),
                            self.twin.deg("pan"),
                            self.twin.deg("tilt"),
                        )
                    )
                if t - last_rate >= 1.0:
                    self.dmx_rate = (self.dmx_count - last_count) / (t - last_rate)
                    last_rate, last_count = t, self.dmx_count
            time.sleep(0.002)

    # -- calibration patterns: this tool drives the head (and the twin) itself

    def pattern_loop(self):
        start = time.monotonic()
        while True:
            p = dict(self.pattern)
            if p["name"] == "off":
                start = time.monotonic()
                time.sleep(0.05)
                continue
            el = time.monotonic() - start
            pan_deg, tilt_deg, dim = float(p["pan"]), float(p["tilt"]), 1.0
            ax = p["axis"]
            if p["name"] == "swing":  # a jump on every beat, like `decisive motion`
                beat = int(el / (60 / float(p["bpm"])))
                off = float(p["amp"]) / 2 * (1 if beat % 2 else -1)
            elif p["name"] == "marker":  # back and forth with a pause; lit only while the TWIN says it stands still
                side = int(el / float(p["dwell"])) % 2
                off = float(p["amp"]) / 2 * (1 if side else -1)
                with self.lock:
                    dim = 1.0 if self.twin.motors[ax].settled else 0.0
            else:
                off = 0.0
            if ax == "pan":
                pan_deg += off
            else:
                tilt_deg += off
            pan = self.head.norm("pan", pan_deg, self.profile["pan"].range_deg)
            tilt = self.head.norm("tilt", tilt_deg, self.profile["tilt"].range_deg)
            self.lit = dim > 0
            buf = self.head.universe_with(pan, tilt, dim)
            got = self.head.decode(bytes(buf))
            if got:
                self._input(*got)
            if self.forward:
                from decisive.dmx.artnet import ArtNetSender

                self.out.sendto(ArtNetSender.packet(self.head.wire_universe, buf), self.forward)
            time.sleep(1 / 40)

    # -- the page's data

    def info(self) -> dict:
        h = self.head
        return {
            "fixture": self.head.fx["id"],
            "model": f"{h.defn['manufacturer']} {h.defn['model']}",
            "engine": {
                "range": h.engine_range,
                "motion": {k: v for k, v in h.defn.get("motion", {}).items() if not k.startswith("_")},
                "lead_ms": round(DMX_LEAD_S * 1000),
            },
            "home_frac": h.home_frac,
            "profile": {a: asdict(self.profile[a]) for a in AXES},
            "calibrated": bool(h.defn.get("twin", {}).get("calibrated")),
            "listen": f"{self.listen[0]}:{self.listen[1]}",
            "forward": f"{self.forward[0]}:{self.forward[1]}" if self.forward else None,
            "pattern": self.pattern,
        }

    def frame(self, since: float) -> dict:
        with self.lock:
            rows = [s for s in self.samples if s[0] > since]
            window = np.array([s for s in self.samples if s[0] > max(self.changed, self.samples[-1][0] - 15)])
            if not self.samples:
                window = np.array([])
        h, out = self.head, {}
        cols = {}
        for i, a in enumerate(AXES):
            rng = h.engine_range[a]
            if not len(rows):
                cols[a] = []
            else:
                r = np.array(rows)
                dmx = h.rel(a, r[:, 1 + i], rng)
                eng = h.rel(a, r[:, 3 + i], rng)
                tw = r[:, 5 + i] - h.home_frac[a] * self.profile[a].range_deg
                cols[a] = [[round(x, 3), _r(d), _r(e), _r(w)] for x, d, e, w in zip(r[:, 0], dmx, eng, tw)]
            c = None
            if self.pattern["name"] != "off":
                out[a] = {"samples": cols[a], "metrics": None, "verdict": f"{a}: test pattern: compare by eye"}
                continue
            if len(window) and rng:
                eng = h.rel(a, window[:, 3 + i], rng)
                tw = window[:, 5 + i] - h.home_frac[a] * self.profile[a].range_deg
                c = compare(eng, tw)
            out[a] = {"samples": cols[a], "metrics": c, "verdict": verdict(a, c)}
        return {
            "axes": out,
            "status": {
                "dmx_hz": round(self.dmx_rate, 1),
                "feed": self.feed_state,
                "track": self.track,
                "pattern": self.pattern["name"],
                "lit": self.lit,
                "settled": {a: self.twin.motors[a].settled for a in AXES},
            },
        }

    def set_params(self, body: dict):
        with self.lock:
            for a in AXES:
                for k, v in body.get(a, {}).items():
                    if k in {f.name for f in fields(Axis)}:
                        setattr(self.profile[a], k, float(v))
            self.changed = time.monotonic() - self.t0


def _r(x) -> float | None:
    return None if x is None or math.isnan(x) else round(float(x), 2)


def serve(live: Live, port: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/info":
                self._json(live.info())
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                since = 0.0
                try:
                    while True:
                        f = live.frame(since)
                        last = [s[0] for s in f["axes"]["tilt"]["samples"]]
                        since = last[-1] if last else since
                        self.wfile.write(f"data: {json.dumps(f)}\n\n".encode())
                        self.wfile.flush()
                        time.sleep(1 / 15)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                self.send_error(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/params":
                live.set_params(body)
                self._json(live.info())
            elif self.path == "/pattern":
                if body.get("name", live.pattern["name"]) != live.pattern["name"]:
                    live.changed = time.monotonic() - live.t0  # a new start for the comparison
                live.pattern.update({k: v for k, v in body.items() if k in live.pattern})
                self._json(live.info())
            elif self.path == "/save":
                path = save_profile(live.head.defn, live.profile)
                self._json({"message": f"Twin saved in {path.relative_to(ROOT)}", **live.info()})
            elif self.path == "/apply":
                save_profile(live.head.defn, live.profile)
                notes = apply_to_engine(live.head, live.profile, live.sel)
                self._json(
                    {
                        "message": "Engine model updated: " + "; ".join(notes) + ". Restart the show to use it.",
                        **live.info(),
                    }
                )
            else:
                self.send_error(404)

    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


def live_main(args):
    live = Live(args)
    for target in (live.dmx_loop, live.feed_loop, live.sim_loop, live.pattern_loop):
        threading.Thread(target=target, daemon=True).start()
    h = live.head
    print(
        f"Twin of {args.fixture} ({h.defn['manufacturer']} {h.defn['model']}), universe {h.universe} "
        f"(Art-Net {h.wire_universe}), address {h.fx['address']}"
    )
    print(f"  DMX in:  {live.listen[0]}:{live.listen[1]}   start the show with  --artnet {live.listen[0]}")
    print(f"  DMX out: {'relayed to ' + live.forward[0] if live.forward else 'nowhere (twin only)'}")
    print(f"  Engine:  {live.feed_url}")
    print(f"  Page:    http://127.0.0.1:{args.port}")
    try:
        serve(live, args.port)
    except KeyboardInterrupt:
        print("\nStopped")


def _selection(args):
    return store.current(args.rig, args.set_name)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "live"):
        s = sub.add_parser(name)
        s.add_argument("fixture", help="fixture id from the rig, e.g. fuze1")
        s.add_argument("--set", dest="set_name", metavar="NAME")
        s.add_argument("--rig", metavar="NAME")
    c = sub.choices["check"]
    c.add_argument("--bpm", type=float, default=128.0)
    c.add_argument("--fit", action="store_true", help="find the engine motion numbers that best predict the twin")
    c.add_argument("--apply", action="store_true", help="write the twin's range (and the fit) into the fixture")
    lv = sub.choices["live"]
    lv.add_argument("--listen", default="127.0.0.1:6454", help="where the engine sends its Art-Net")
    lv.add_argument("--forward", default=None, metavar="IP", help="relay to this node (default: the set's; '' = none)")
    lv.add_argument("--feed", default="ws://127.0.0.1:8765", help="the running show's visualiser feed")
    lv.add_argument("--port", type=int, default=8790, help="the page")
    args = p.parse_args(argv)
    check(args) if args.cmd == "check" else live_main(args)


if __name__ == "__main__":
    main()
