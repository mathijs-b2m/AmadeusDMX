"""Heads standing on a raised stage's deck play as floor heads: up and over the crowd, not down into the deck."""

from types import SimpleNamespace

import numpy as np

from amadeus.engine.motion import LOW_AIMS, MotionMixin
from amadeus.rig import geometry

RAISED = {**geometry.DEFAULT_STAGE, "deck_m": 1.5, "ceiling_m": 9.0, "room_depth_m": 26}


def test_height_counts_from_the_deck_on_stage_and_from_the_hall_floor_in_front():
    assert np.isclose(geometry.over_ground((7.0, -6.0, 1.8), RAISED), 0.3)  # on the deck, at the back
    assert np.isclose(geometry.over_ground((7.0, 3.0, 0.3), RAISED), 0.3)  # in the hall, in front of the stage
    assert np.isclose(geometry.over_ground((7.0, -1.0, 7.5), RAISED), 6.0)  # hung over the deck
    assert np.isclose(geometry.over_ground((7.0, -6.0, 1.8), geometry.DEFAULT_STAGE), 1.8)  # no deck


def test_a_head_on_the_deck_aims_like_a_floor_head():
    engine = SimpleNamespace(stage=RAISED, head_pos=[np.array([7.0, -6.0, 1.8]), np.array([7.0, -1.0, 7.5])])
    on_deck, hung = engine.head_pos
    crowd = MotionMixin._fit_aim(engine, "crowd", on_deck)
    assert crowd["el"] == LOW_AIMS["crowd"]["el"] > 0  # over the crowd, not down onto the deck in front of it
    assert MotionMixin._fit_aim(engine, "crowd", hung)["el"] < 0  # a hung head still plays down onto the crowd
    assert MotionMixin._aim_name(engine, "stage", 0) == "sky"  # not bent down into the deck by the back guard
    assert MotionMixin._aim_name(engine, "stage", 1) == "stage"
