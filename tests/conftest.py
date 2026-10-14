import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # the engine finds fixtures/ and config/ relative to the project

import tempfile  # noqa: E402

from amadeus.dmx import limiter  # noqa: E402

limiter.use(Path(tempfile.mkdtemp()) / "limiter.json")  # a limiter set while testing the rig never reaches the tests
