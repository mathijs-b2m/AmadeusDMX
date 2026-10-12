"""Measure how fast a moving head really is: swing on the beat with growing amplitude.

The head gets raw targets (no motion model in between), so it moves as fast as it can.
The largest swing it still completes every beat gives its acceleration, which the engine
uses to size per-beat moves (bounce, swing, step_on_beat) so they land on the beat.
"""

from __future__ import annotations

import json
import threading
import time

from amadeus.dmx.outputs import open_output
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry
from amadeus.rig.loader import load_rig

TEST_BPM = 145
AMPLITUDES = [20, 40, 60, 90, 120]  # degrees, full swing (end to end)


def run(show, fixture_id: str, axis: str = "tilt"):
    rig = load_rig(show)
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    if fixture_id not in fixtures:
        raise SystemExit(f"No fixture '{fixture_id}' in the rig. Fixtures: {', '.join(fixtures)}")
    fx = fixtures[fixture_id]
    defn = fxlib.get(fx["fixture"])
    # centre: pointing forward, a bit up (works for floor and stand mounts)
    centre_phi, centre_theta = geometry.ik(fx, defn, geometry.direction(0, 20), None)
    sender = open_output(rig)
    period = 60 / TEST_BPM
    state = {"amp": 0.0, "run": True}
    element = next(e for e in rig["elements"] if e["fixture"] == fixture_id)

    def loop():
        t0 = time.monotonic()
        while state["run"]:
            beat = int((time.monotonic() - t0) / period)
            half = state["amp"] / 2 * (1 if beat % 2 else -1)  # square wave: jump on every beat
            phi, theta = centre_phi, centre_theta
            if axis == "pan":
                phi += half
            else:
                theta += half
            pan, tilt = geometry.to_dmx(fx, defn, phi, theta)
            states = {e["id"]: State() for e in rig["elements"]}
            states[element["id"]] = State(dimmer=0.8, r=1.0, g=1.0, b=1.0, pan=pan, tilt=tilt)
            unis: dict[int, bytearray] = {}
            for f in rig["fixtures"]:
                fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, states)
            sender.send(unis)
            time.sleep(0.01)

    threading.Thread(target=loop, daemon=True).start()
    print(
        f"{fixture_id} swings its {axis.upper()} sharply on every beat at {TEST_BPM} BPM "
        f"({period * 1000:.0f} ms per beat)."
    )
    print("For each size: does it reach BOTH ends every beat (Enter), or turn back early / lag behind (n)?\n")
    best = None
    try:
        for amp in AMPLITUDES:
            state["amp"] = amp
            a = input(f"  {amp:3d}° swing: [Enter = reaches both ends, n = doesn't keep up] ").strip().lower()
            if a.startswith("n"):
                break
            best = amp
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        state["run"] = False
        time.sleep(0.1)
        sender.blackout(sorted({f["universe"] for f in rig["fixtures"]}))

    if best is None:
        print(
            "\nIt didn't keep up even at 20°: nothing changed. "
            "Check the pan/tilt speed channel (should be 0 = fastest)."
        )
        return
    # A full swing of `best` degrees fits in one beat: with a triangular speed profile (accelerate, brake),
    # distance = accel * period^2 / 4 → accel = 4 * distance / period^2. Use 80% of that as a safe margin.
    accel = 0.8 * 4 * best / period**2
    top = 0.8 * 2 * best / period  # peak speed of that profile
    path = fxlib.path_of(defn["key"])
    data = json.loads(path.read_text())
    m = data.setdefault("motion", {})
    m[f"{axis}_accel_dps2"] = round(accel)
    m["accel_dps2"] = min(m.get("pan_accel_dps2", accel), m.get("tilt_accel_dps2", accel))
    key = "tilt_speed_dps" if axis == "tilt" else "pan_speed_dps"
    m[key] = max(m.get(key, 0), round(top))
    m["estimated"] = False
    m[f"_measured_{axis}"] = f"{best}° full swing per beat at {TEST_BPM} BPM (amadeus motion)"
    path = fxlib.save(defn["key"], data)
    print(
        f"\nLargest swing that keeps up: {best}°. Saved: acceleration {accel:.0f}°/s², {axis} speed ≥ {top:.0f}°/s "
        f"(80% margin) in {path}. Blacked out."
    )
