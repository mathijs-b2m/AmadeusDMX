"""Golden master: the DMX a set sends for the synthetic track, as one hash per set.

Refactors must not change what the lights do. `python tests/golden_tool.py --update` records new hashes
(only after a deliberate behaviour change).
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from decisive.director import RuleDirector, direct  # noqa: E402
from decisive.engine import Engine, motion  # noqa: E402
from decisive.rig.groups import head_groups, laser_list  # noqa: E402
from decisive.rig.loader import load_rig  # noqa: E402
from tests.synthetic import synthetic_analysis  # noqa: E402

GOLDEN = Path(__file__).parent / "golden.json"
SETS = Path(__file__).parent / "sets"
FPS = 40


def render_hash(rig_path: Path) -> str:
    rig = load_rig(rig_path)
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    with tempfile.TemporaryDirectory() as tmp:
        motion.TRAJ_CACHE = Path(tmp)  # always simulate: a cache hit would hide a change
        eng = Engine(a, plan, rig)
        h = hashlib.sha256()
        h.update(json.dumps([d.__dict__ for d in plan], sort_keys=True, default=str).encode())
        for k in range(int((a.duration - 0.1) * FPS)):
            _, states = eng.render(k / FPS)
            for u, data in sorted(eng.dmx(states).items()):
                h.update(bytes([u % 256]) + bytes(data))
            if eng.lasers:
                beams = eng.laser_beams(states, k / FPS)
                h.update(json.dumps(beams, sort_keys=True, default=lambda x: np.asarray(x).round(4).tolist()).encode())
    return h.hexdigest()


def platform_tag() -> str:
    """Floating point differs a little between CPUs and numpy builds: hashes are only comparable on the
    platform (and with the pinned requirements) they were recorded on."""
    import platform

    return f"{platform.system()}-{platform.machine()}-numpy{np.__version__}"


def all_hashes() -> dict[str, str]:
    return {p.stem: render_hash(p) for p in sorted(SETS.glob("*.json"))}


if __name__ == "__main__":
    import os

    os.chdir(ROOT)
    got = all_hashes()
    if "--update" in sys.argv:
        GOLDEN.write_text(json.dumps({"_platform": platform_tag(), **got}, indent=1) + "\n")
        print("golden hashes recorded:", ", ".join(got))
    else:
        want = json.loads(GOLDEN.read_text())
        for k, v in got.items():
            print(f"{'ok  ' if want.get(k) == v else 'DIFF'} {k}")
