"""Handing a playing track from one show to the next: no stall in the show's process, no jump in the heads."""

import subprocess
import sys

from amadeus.engine.state import State


def test_looking_for_demucs_imports_no_torch():
    # importing torch in the show's process holds the interpreter for seconds on a slow PC: the lights stall
    code = "import sys; from amadeus.audio import stems; stems.available(); print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"


def test_a_crossfade_moves_the_heads_dmx_target_gradually():
    a, b = State(dmx_pan=0.40, dmx_tilt=0.40), State(dmx_pan=0.55, dmx_tilt=0.60)
    pans = [a.blend(b, k).dmx_pan for k in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert pans == sorted(pans) and abs(pans[2] - 0.475) < 1e-9  # travels, never jumps halfway
    assert abs(a.blend(b, 0.5).dmx_tilt - 0.5) < 1e-9


def test_a_crossfade_never_slides_a_head_a_whole_turn_round():
    # the same aim a pan turn apart (a 540° head: 0.347 and 1.0): sliding between them sweeps the beam round the back
    a, b = (
        State(pan=0.347, tilt=0.95, dmx_pan=0.347, dmx_tilt=0.95),
        State(pan=1.0, tilt=1.0, dmx_pan=1.0, dmx_tilt=1.0),
    )
    assert [a.blend(b, k).dmx_pan for k in (0.25, 0.49)] == [0.347, 0.347]
    assert [a.blend(b, k).dmx_pan for k in (0.5, 0.9)] == [1.0, 1.0]
    assert a.blend(b, 0.3).pan == 0.347  # the visualiser shows no sweep either
    flipped = State(dmx_pan=0.40, dmx_tilt=0.05)  # the tilt over the other side
    assert State(dmx_pan=0.42, dmx_tilt=0.95).blend(flipped, 0.3).dmx_tilt == 0.95


def test_a_head_without_a_dmx_target_keeps_the_others():
    assert State(dmx_pan=None).blend(State(dmx_pan=0.7), 0.6).dmx_pan == 0.7
    assert State(dmx_pan=0.3).blend(State(dmx_pan=None), 0.4).dmx_pan == 0.3
