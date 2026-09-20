"""Adapter tests for NED/FRD -> renderer frames. Not a dynamics suite."""

from __future__ import annotations

import math

import pytest

from sim.attitude import quat_from_euler_321
from sim.frames import (
    identity_quat,
    ned_to_three_m,
    ned_to_ue_cm,
    rotate_body_point_three,
    rotate_body_point_ue,
)

BODY_RIGHT = (0.0, 1.0, 0.0)
POS_NED = (10.0, 20.0, -30.0)


def test_identity_position_maps_to_three_and_ue() -> None:
    """Identity attitude, NED (10, 20, -30) m -> three.js m and UE cm."""
    assert identity_quat() == (1.0, 0.0, 0.0, 0.0)
    assert ned_to_three_m(POS_NED) == pytest.approx((20.0, 30.0, -10.0))
    assert ned_to_ue_cm(POS_NED) == pytest.approx((1000.0, 2000.0, 3000.0))


def test_right_wing_down_lowers_body_right_in_three_and_ue() -> None:
    """+30 deg FRD roll (right-wing-down) drops body-right in engine up axes."""
    q_id = identity_quat()
    q_roll = quat_from_euler_321(math.radians(30.0), 0.0, 0.0)

    three_id = rotate_body_point_three(q_id, BODY_RIGHT)
    three_roll = rotate_body_point_three(q_roll, BODY_RIGHT)
    # three.js Y is up; right wing going down must decrease Y.
    assert three_roll[1] < three_id[1]

    ue_id = rotate_body_point_ue(q_id, BODY_RIGHT)
    ue_roll = rotate_body_point_ue(q_roll, BODY_RIGHT)
    # Unreal Z is up; right wing going down must decrease Z.
    assert ue_roll[2] < ue_id[2]


def test_commanded_right_turn_lowers_body_right_engine_up() -> None:
    """Commanded right turn is phi>0; body-right engine-up is below identity."""
    phi = math.radians(30.0)
    assert phi > 0.0
    q_id = identity_quat()
    q_right = quat_from_euler_321(phi, 0.0, 0.0)

    three_id = rotate_body_point_three(q_id, BODY_RIGHT)
    three_right = rotate_body_point_three(q_right, BODY_RIGHT)
    assert three_right[1] < three_id[1]

    ue_id = rotate_body_point_ue(q_id, BODY_RIGHT)
    ue_right = rotate_body_point_ue(q_right, BODY_RIGHT)
    assert ue_right[2] < ue_id[2]
