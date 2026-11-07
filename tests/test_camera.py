"""A camera in the rig (stage.camera_*): most heads play towards it, the others keep the look around it."""

from __future__ import annotations

import numpy as np

from amadeus.engine import motion


def test_no_camera_no_pull():
    assert motion.camera_heads({}, 12) == (None, set())


def test_most_heads_play_the_camera_spread_over_the_rig():
    camera, heads = motion.camera_heads({"camera_x_m": 3, "camera_y_m": 7, "camera_z_m": 1.6}, 12)
    assert camera.tolist() == [3.0, 7.0, 1.6]
    assert len(heads) == 8 and max(np.diff(sorted(heads))) <= 2
    assert len(motion.camera_heads({"camera_x_m": 3, "camera_y_m": 7, "camera_share": 1.0}, 12)[1]) == 12


def test_a_beam_is_pulled_to_the_camera_and_keeps_moving():
    head, camera = np.array([1.0, -1.5, 2.6]), np.array([3.0, 7.0, 1.6])
    to = (camera - head) / np.linalg.norm(camera - head)
    left, right = motion.towards_camera(head, np.array([[-1.0, 0, 0], [1.0, 0, 0]]), camera)
    assert left @ to > 0.8 and right @ to > 0.8
    assert not np.allclose(left, right)
    assert abs(np.linalg.norm(left) - 1) < 1e-6
