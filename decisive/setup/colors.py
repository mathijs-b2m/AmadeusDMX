"""Name a colour wheel: show each slot and type the colour you see.

The engine picks wheel slots by colour, so the slot colours in the library must
match the real wheel; this replaces the guessed values with what you saw.
"""

from __future__ import annotations

import json
import threading
import time

from decisive.dmx.outputs import open_output
from decisive.engine.state import State
from decisive.library import fixtures as fxlib
from decisive.rig import geometry
from decisive.rig.loader import load_rig

NAMED = {  # common gel/wheel colour names → RGB as the engine and visualiser should treat them
    "white": (1.0, 1.0, 1.0),
    "open": (1.0, 1.0, 1.0),
    "red": (1.0, 0.0, 0.0),
    "deep red": (0.8, 0.0, 0.05),
    "dark red": (0.7, 0.0, 0.0),
    "orange": (1.0, 0.45, 0.0),
    "amber": (1.0, 0.6, 0.1),
    "yellow": (1.0, 0.9, 0.0),
    "light yellow": (1.0, 1.0, 0.5),
    "lime": (0.6, 1.0, 0.0),
    "green": (0.0, 1.0, 0.0),
    "light green": (0.5, 1.0, 0.4),
    "dark green": (0.0, 0.6, 0.1),
    "cyan": (0.0, 1.0, 1.0),
    "turquoise": (0.0, 0.9, 0.7),
    "light blue": (0.4, 0.75, 1.0),
    "sky blue": (0.5, 0.8, 1.0),
    "blue": (0.0, 0.2, 1.0),
    "dark blue": (0.0, 0.0, 0.7),
    "deep blue": (0.05, 0.0, 0.8),
    "uv": (0.35, 0.0, 1.0),
    "purple": (0.5, 0.0, 1.0),
    "violet": (0.55, 0.0, 0.9),
    "lavender": (0.7, 0.55, 1.0),
    "magenta": (1.0, 0.0, 0.8),
    "pink": (1.0, 0.4, 0.7),
    "light pink": (1.0, 0.7, 0.8),
    "rose": (1.0, 0.3, 0.5),
    "cto": (1.0, 0.75, 0.45),
    "warm white": (1.0, 0.8, 0.55),
    "ctb": (0.75, 0.85, 1.0),
}


def run(rig_path, fixture_id: str, level: float = 0.8):
    rig = load_rig(rig_path)
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    if fixture_id not in fixtures:
        raise SystemExit(f"No fixture '{fixture_id}' in the rig. Fixtures: {', '.join(fixtures)}")
    fx = fixtures[fixture_id]
    defn = fxlib.get(fx["fixture"])
    if "color_wheel" not in defn:
        raise SystemExit(f"{defn['model']} has no colour wheel (RGB fixtures mix colours themselves).")
    slots = defn["color_wheel"]["slots"]
    element = next(e for e in rig["elements"] if e["fixture"] == fixture_id)
    # aim at the wall/floor straight in front, low, so the colour is easy to judge on a surface
    pan, tilt = geometry.to_dmx(fx, defn, *geometry.ik(fx, defn, geometry.direction(0, 5), None))
    sender = open_output(rig)
    state = {"slot": 0, "run": True}

    def loop():
        while state["run"]:
            states = {e["id"]: State() for e in rig["elements"]}
            s = State(dimmer=level, pan=pan, tilt=tilt)
            s.r, s.g, s.b = slots[state["slot"]]["rgb"]  # patch picks the nearest slot = exactly this one
            states[element["id"]] = s
            unis: dict[int, bytearray] = {}
            for f in rig["fixtures"]:
                fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, states)
            # make sure the wheel sits on this slot even if two guessed slots had the same colour
            off = next(i for i, c in enumerate(fxlib.channels(defn, fx["mode"])) if c["attr"] == "color_wheel")
            slot = slots[state["slot"]]
            unis[fx["universe"]][fx["address"] - 1 + off] = (slot["from"] + slot["to"]) // 2
            sender.send(unis)
            time.sleep(0.025)

    threading.Thread(target=loop, daemon=True).start()
    print(f"{fixture_id} ({defn['model']}) shows its colour wheel slot by slot, aimed at the wall in front.")
    print("Type the colour you see. Known names:")
    print("  " + ", ".join(sorted(NAMED)))
    print("or 'other r g b' (0-1 values). Enter = skip, b = back, q = quit and save.\n")
    i, changed = 0, False
    try:
        while 0 <= i < len(slots):
            state["slot"] = i
            sl = slots[i]
            a = input(f"  slot {i:2d} ({sl['name']}, DMX {sl['from']}-{sl['to']}): ").strip().lower()
            if a == "q":
                break
            if a == "b":
                i = max(0, i - 1)
                continue
            if a.startswith("other"):
                try:
                    sl["rgb"] = [float(x) for x in a.split()[1:4]]
                    sl["seen"] = "custom"
                    changed = True
                except ValueError:
                    print("   use: other 1 0.5 0")
                    continue
            elif a:
                if a not in NAMED:
                    print(f"   Unknown colour '{a}'. Pick a known name or use 'other r g b'.")
                    continue
                sl["rgb"], sl["seen"] = list(NAMED[a]), a
                changed = True
            i += 1
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        state["run"] = False
        time.sleep(0.1)
        sender.blackout(sorted({f["universe"] for f in rig["fixtures"]}))

    if changed:
        path = fxlib.LIB_DIR / f"{defn['key']}.json"
        data = json.loads(path.read_text())
        data["color_wheel"]["slots"] = slots
        data["color_wheel"]["verified"] = all("seen" in s for s in slots[1:])
        data["color_wheel"]["_note"] = "Slot colours as seen on the real fixture (decisive colors)."
        path.write_text(json.dumps(data, indent=2))
        print(f"\nSaved slot colours to {path.relative_to(fxlib.LIB_DIR.parent)}. Blacked out.")
    else:
        print("\nNothing changed. Blacked out.")
