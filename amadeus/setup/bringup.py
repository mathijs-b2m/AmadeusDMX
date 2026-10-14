"""First contact with real hardware: light each fixture on its own, then calibrate head orientation.

Runs in the terminal; DMX is refreshed continuously in the background at low
brightness. Answers fix the rig on the spot (patch problems are explained,
orientation is calibrated) and changes are saved to the rig file at the end.
"""

from __future__ import annotations

import threading
import time

import numpy as np

from amadeus.dmx.outputs import open_output
from amadeus.engine.state import State
from amadeus.library import fixtures as fxlib
from amadeus.rig import geometry
from amadeus.rig.loader import load_rig


class Output:
    """Keeps sending the current look at the rig's frame rate (Art-Net nodes expect a steady stream)."""

    def __init__(self, rig: dict, ip: str | None, port: int = 6454):
        self.rig, self.sender = rig, open_output(rig, ip)
        self.states = {e["id"]: State() for e in rig["elements"]}
        self.lock, self.running = threading.Lock(), True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        period = 1 / self.rig["artnet"].get("fps", 40)
        while self.running:
            with self.lock:
                unis: dict[int, bytearray] = {}
                for f in self.rig["fixtures"]:
                    fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, self.states)
            self.sender.send(unis)
            time.sleep(period)

    def set(self, states: dict[str, State]):
        with self.lock:
            self.states = states

    def stop(self):
        self.running = False
        time.sleep(0.1)
        self.sender.blackout(sorted({f["universe"] for f in self.rig["fixtures"]}))


def _ask(prompt: str, keys: str = "") -> str:
    while True:
        a = input(f"{prompt} ").strip().lower()
        if a == "" or (a and a[0] in keys):
            return a[:1]
        print(f"   Press Enter, or one of: {', '.join(keys)}")


def run(show, level: float, ip: str | None):
    rig = load_rig(show)
    original = show.load()
    st = geometry.stage(rig)
    port = rig.get("artnet", {}).get("port", 6454)
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    elements = rig["elements"]
    W = st["width_m"]

    def aim(e: dict, point) -> tuple[float, float]:
        fx = fixtures[e["fixture"]]
        defn = fxlib.get(fx["fixture"])
        pos = np.array(geometry.position(rig, e, fx))
        d = np.asarray(point, dtype=float) - pos
        phi, theta = geometry.ik(fx, defn, d / np.linalg.norm(d), None)
        return geometry.to_dmx(fx, defn, phi, theta)

    def look(lit: dict[str, tuple] | None = None, point=(W / 2, 3.0, 0.0)) -> dict[str, State]:
        """Everything dark, heads parked on `point`; `lit` = {element id: (r, g, b)} at the test level."""
        out = {}
        for e in elements:
            s = State()
            if e["kind"] == "head":
                s.pan, s.tilt = aim(e, point)
            if lit and e["id"] in lit:
                s.r, s.g, s.b = lit[e["id"]]
                s.dimmer = level
            out[e["id"]] = s
        return out

    print(f"\nHardware test → Art-Net {ip}:{port}, brightness {level:.0%}. Ctrl+C stops (and blacks out).")
    print("Stand where the audience would be, facing the stage.\n")
    out = Output(rig, ip, port)
    try:
        # 1. nothing should be on
        out.set(look())
        a = _ask("1. Everything should be DARK now. Is it? [Enter = yes, n = no]", "n")
        if a == "n":
            print(
                "   A fixture that's lit without DMX is usually in auto/sound mode: set it to DMX mode "
                "on its display.\n   If it's lit but frozen, it may be receiving DMX on the wrong address."
            )

        # 2. one fixture at a time
        print("\n2. Lighting each fixture on its own.")
        for fx in rig["fixtures"]:
            defn = fxlib.get(fx["fixture"])
            els = [e for e in elements if e["fixture"] == fx["id"]]
            n = fxlib.footprint(fx)
            where = f"universe {fx['universe']}, address {fx['address']}, mode {fx['mode']} ({n} ch)"
            if len(els) == 1 and els[0]["kind"] == "smoke":
                # a smoke machine makes no light: one short burst instead, once it's warm
                a = _ask(
                    f"   {fx['id']}: {defn['manufacturer']} {defn['model']} @ {where}\n"
                    f"   Smoke machine: is it switched on and warmed up (most need 3-8 minutes, a 'ready' light)?\n"
                    f"   [Enter = fire a 2-second burst, s = skip]",
                    "s",
                )
                if a == "s":
                    continue
                while True:
                    out.set({**look(), els[0]["id"]: State(dimmer=0.6)})
                    time.sleep(2.0)
                    out.set(look())
                    a = _ask("   Did smoke come out? [Enter = yes, n = no, r = fire again]", "nr")
                    if a != "r":
                        break
                if a == "n":
                    print(
                        f"   Check: (1) the machine is warm (its ready light) and has fluid; (2) on its display: DMX "
                        f"mode {fx['mode']}, start address {fx['address']}; (3) a wired remote or timer plugged in can "
                        f"lock out DMX on some machines; (4) the DMX cable chain from the node's port for universe "
                        f"{fx['universe']}."
                    )
                continue
            if len(els) == 1:
                out.set(look({els[0]["id"]: (1.0, 1.0, 1.0)}))
                a = _ask(
                    f"   {fx['id']}: {defn['manufacturer']} {defn['model']} @ {where}\n"
                    f"   Only this fixture should be ON (white). Correct? [Enter = yes, n = no]",
                    "n",
                )
            else:
                cols = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)]
                names = ["red", "green", "blue", "white"]
                order = sorted(els, key=lambda e: e["x"])
                out.set(look({e["id"]: cols[i % 4] for i, e in enumerate(order)}))
                seq = ", ".join(names[i % 4] for i in range(len(order)))
                a = _ask(
                    f"   {fx['id']}: {defn['manufacturer']} {defn['model']} @ {where}\n"
                    f"   From your position, left → right: {seq}. Correct? "
                    f"[Enter = yes, r = reversed, n = something else]",
                    "rn",
                )
                if a == "r":
                    fx["reverse"] = not fx.get("reverse", False)
                    print("   ✓ Noted: heads are reversed; the order will be flipped.")
                    a = ""
            if a == "n":
                print(
                    f"   Check: (1) on {fx['id']}'s display: DMX mode {fx['mode']}, start address "
                    f"{fx['address']}; (2) DMX cable chain from the node's port for universe "
                    f"{fx['universe']}; (3) node port set to Output, Network 0, Primary {fx['universe']}."
                )

        # 3. head orientation
        heads = [e for e in elements if e["kind"] == "head"]
        if heads:
            print("\n3. Orientation of the moving heads (white, one at a time).")
        for e in heads:
            fx = fixtures[e["fixture"]]
            defn = fxlib.get(fx["fixture"])
            P = defn["physical"]["pan_deg"]
            front = (e["x"] * W, 4.0, 1.0)
            while True:
                out.set(look({e["id"]: (1, 1, 1)}, point=front))
                a = _ask(
                    f"   {fx['id']} should point straight FORWARD at the audience, slightly upward "
                    "(aimed at ~1 m height, 4 m out).\n"
                    f"   [Enter = yes · b = it points back at the stage · l / r = it points to your left / right"
                    f" · u = it points up]",
                    "blru",
                )
                if a == "":
                    break
                home = fx.get("pan_home_deg", P / 2)
                if a == "b":
                    home = home + 180 if home + 180 <= P else home - 180
                elif a in "lr":
                    home += 90 if a == "l" else -90
                    home = min(max(home, 0), P)
                elif a == "u":
                    fx["mount"] = "hang" if fx.get("mount", "stand") != "hang" else "stand"
                    print(f"   ✓ Mount changed to '{fx['mount']}'.")
                fx["pan_home_deg"] = home
                print(f"   ✓ pan_home_deg = {home:.0f}. Trying again …")
            while True:
                out.set(look({e["id"]: (1, 1, 1)}, point=(0.0, 3.0, 0.0)))
                a = _ask(
                    f"   {fx['id']} should now point to the floor on YOUR LEFT front. "
                    f"[Enter = yes, m = it went to my right]",
                    "m",
                )
                if a == "":
                    break
                fx["pan_invert"] = not fx.get("pan_invert", False)
                print(f"   ✓ pan_invert = {fx['pan_invert']}. Trying again …")

        # 4. all heads together on one point
        if len(heads) > 1:
            print("\n4. All heads on one shared point, moving in a slow circle (5 s) …")
            t0 = time.monotonic()
            while time.monotonic() - t0 < 5:
                w = (time.monotonic() - t0) / 5 * 2 * np.pi
                p = (W / 2 + 1.2 * np.sin(w), 2.5 + 1.0 * np.cos(w), 0.0)
                out.set(look({e["id"]: (1, 1, 1) for e in heads}, point=p))
                time.sleep(0.05)
            a = _ask("   Did the beams meet and circle together? [Enter = yes, n = no]", "n")
            if a == "n":
                print(
                    "   Positions are probably off: set stage.width_m and each head's x / y_m / z_m in the rig "
                    "to match your real setup."
                )
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")
    finally:
        out.stop()

    # save calibration (only the keys this test can change)
    keys = ("pan_home_deg", "pan_invert", "mount", "reverse")
    changed = False
    for f in original["fixtures"]:
        cur = fixtures.get(f["id"], {})
        for k in keys:
            if k in cur and cur[k] != f.get(k):
                f[k] = cur[k]
                changed = True
    if changed:
        show.save(original)
        print(f"Calibration saved to {show.label}.")
    print("Blacked out. Done.")
