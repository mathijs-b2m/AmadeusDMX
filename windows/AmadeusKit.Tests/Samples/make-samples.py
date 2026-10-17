"""The feed samples the C# decoder tests read: a real hello and a full frame per test set (tests/sets), made by the
engine itself with the synthetic track. Run from the checkout after a change to the feed (amadeus/show/feed.py):

    .venv/bin/python windows/AmadeusKit.Tests/Samples/make-samples.py [SET …]
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from amadeus.director import RuleDirector, direct  # noqa: E402
from amadeus.dmx import limiter  # noqa: E402
from amadeus.engine import Engine, motion  # noqa: E402
from amadeus.engine.realism import Realism  # noqa: E402
from amadeus.rig.groups import head_groups, laser_list  # noqa: E402
from amadeus.rig.loader import load_rig  # noqa: E402
from amadeus.show import feed as feedlib  # noqa: E402
from tests.synthetic import synthetic_analysis  # noqa: E402

OUT = Path(__file__).resolve().parent
T = 100.0  # the moment of the frame: well into the synthetic track


def floats(x):
    return [round(float(v), 4) for v in x]


for name in sys.argv[1:] or ["small", "laser-zones", "ring"]:
    rig = load_rig(ROOT / "tests" / "sets" / f"{name}.json")
    a = synthetic_analysis()
    plan = direct(a, RuleDirector(head_groups(rig), laser_list(rig), bool(rig.get("screen"))), verbose=False)
    with tempfile.TemporaryDirectory() as tmp:
        motion.TRAJ_CACHE = Path(tmp)
        limiter.use(Path(tmp) / "limiter.json")
        real = Realism(rig)
        eng = Engine(a, plan, rig)
        hello = feedlib.hello(a, plan, rig, real, title="Deck 1: synthetic.mp3", director="rules")
        feed = feedlib.Feed(rig, real, 1 / 40)
        for k in range(int(T * 40) - 3, int(T * 40) + 1):
            _, states = eng.render(k / 40)
        lasers = eng.laser_beams(states, T) if eng.lasers else None
        frame = {"type": "frame", "t": T, "phrase": 3, "bp": 213.4, "bands": [0.1, 0.5, 0.9], **feed.fixture_fields(states, lasers)}
    (OUT / f"hello-{name}.json").write_text(hello)
    (OUT / f"frame-{name}.json").write_text(json.dumps(frame, default=floats))
    print(name, len(hello), "bytes of hello")
