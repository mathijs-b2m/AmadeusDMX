"""djay: the playhead from a whole-second label that is late by up to LATE_S, never early."""

import random

from amadeus.show.sources.djay import LATE_S, Playhead, clock, percent


def test_labels():
    assert clock("01:07") == 67 and clock("-01:23") == 83 and clock("1:02:03") == 3723 and clock("x") is None
    assert abs(percent("0.9%") - 0.009) < 1e-12 and percent("100%") == 1.0


def run(head, start, until, speed=1.0, t0=0.0, seed=1, late=LATE_S - 0.05):
    """Play from `start` at time t0: every whole second crossed shows up 0..late later."""
    rnd, k = random.Random(seed), int(start) + 1
    while (t0 + (k - start) / speed) < until:
        cross = t0 + (k - start) / speed
        head.seen(k, cross + rnd.uniform(0, late))
        k += 1


def test_ticks_give_the_playhead_within_some_milliseconds():
    head = Playhead()
    head.seen(10, 0.0)  # paused at 10.x: the first label
    head.set_play(True, 0.0)
    head.frozen = head.coarse[1]
    true_start = 10.3
    head.ticks.clear()
    head.coarse = (0.0, true_start)
    run(head, true_start, 12.0)
    err = head.at(12.0) - (true_start + 12.0)
    assert -0.06 < err <= 0.001  # never ahead; the least late of 8 ticks is close


def test_a_tempo_change_keeps_the_position():
    head = Playhead()
    head.seen(0, 0.0)
    head.set_play(True, 0.0)
    head.coarse = (0.0, 0.0)
    run(head, 0.0, 6.0)
    before = head.at(6.0)
    head.set_speed(1.05, 6.0)
    assert abs(head.at(6.0) - before) < 1e-9 and abs(head.at(7.0) - before - 1.05) < 1e-9


def test_a_seek_starts_over_coarse_then_ticks_again():
    head = Playhead()
    head.seen(0, 0.0)
    head.set_play(True, 0.0)
    head.coarse = (0.0, 0.0)
    run(head, 0.0, 5.0)
    assert head.seen(40, 5.0) == "jump" and not head.ticks and head.coarse == (5.0, 40.5)
    # the real position was 40.2: the next tick (41) comes 0.8 s later and puts it right
    assert head.seen(41, 5.8 + 0.03) == "tick"
    assert abs(head.at(6.0) - (40.2 + 1.0)) < 0.05


def test_pause_holds_the_position():
    head = Playhead()
    head.seen(0, 0.0)
    head.set_play(True, 0.0)
    head.coarse = (0.0, 0.0)
    run(head, 0.0, 3.5)
    head.set_play(False, 3.5)
    assert abs(head.at(10.0) - head.at(3.5)) < 1e-9 and abs(head.at(3.5) - 3.5) < 0.06
