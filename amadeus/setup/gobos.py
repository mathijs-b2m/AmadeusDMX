"""Name a fixture's gobos: project them one by one and type what you see.

The names are saved in the fixture library (`gobo_names`), so the director can
choose gobos by look instead of by number.
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


def run(show, fixture_id: str, level: float = 0.8):
    rig = load_rig(show)
    fixtures = {f["id"]: f for f in rig["fixtures"]}
    if fixture_id not in fixtures:
        raise SystemExit(f"No fixture '{fixture_id}' in the rig. Fixtures: {', '.join(fixtures)}")
    fx = fixtures[fixture_id]
    defn = fxlib.get(fx["fixture"])
    values = defn.get("beam_fx", {}).get("gobo", {}).get("gobo")
    if not values:
        raise SystemExit(f"{defn['model']} has no gobo list in the library.")
    names = list(defn.get("gobo_names", [""] * len(values)))
    names += [""] * (len(values) - len(names))

    element = next(e for e in rig["elements"] if e["fixture"] == fixture_id)
    pan, tilt = geometry.to_dmx(fx, defn, *geometry.ik(fx, defn, geometry.direction(0, 80), None))
    sender = open_output(rig)
    state = {"gobo": 0, "run": True}

    def loop():
        while state["run"]:
            states = {e["id"]: State() for e in rig["elements"]}
            s = State(dimmer=level, r=1.0, g=1.0, b=1.0, pan=pan, tilt=tilt, fx="gobo", gobo=state["gobo"])
            states[element["id"]] = s
            unis: dict[int, bytearray] = {}
            for f in rig["fixtures"]:
                fxlib.patch(unis.setdefault(f["universe"], bytearray(512)), f, states)
            sender.send(unis)
            time.sleep(0.025)

    threading.Thread(target=loop, daemon=True).start()
    print(f"{fixture_id} ({defn['model']}) points almost straight up at the ceiling, white, gobo by gobo.")
    print("Type a short description of what you see (e.g. 'dots', 'star', 'ring', 'flower', 'lines'),")
    print("Enter = keep/skip, b = back, q = quit and save.\n")
    i = 0
    try:
        while 0 <= i < len(values):
            state["gobo"] = i
            current = f" [{names[i]}]" if names[i] else ""
            a = input(f"  gobo {i + 1:2d} (DMX {values[i]:3d}){current}: ").strip()
            if a.lower() == "q":
                break
            if a.lower() == "b":
                i = max(0, i - 1)
                continue
            if a:
                names[i] = a
            i += 1
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        state["run"] = False
        time.sleep(0.1)
        sender.blackout(sorted({f["universe"] for f in rig["fixtures"]}))

    path = fxlib.path_of(defn["key"])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["gobo_names"] = names
    path = fxlib.save(defn["key"], data)
    named = sum(1 for n in names if n)
    print(f"\nSaved {named} of {len(names)} gobo names to {path}. Blacked out.")
