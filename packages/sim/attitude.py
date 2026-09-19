"""Body attitude for the prescribed mission. Not a 6DOF integrator.

Encoding (frozen for Unreal FRD→UE conversion):
- World: NED metres, down positive.
- Body: FRD, coincident with NED at identity heading/pitch/roll.
- Quaternion: scalar-first (w, x, y, z), unit length.
- Euler: 3-2-1 yaw-pitch-roll. Positive roll about FRD +x is right-wing-down.
"""

from __future__ import annotations

import math


def quat_from_euler_321(phi: float, theta: float, psi: float) -> list[float]:
    """Return scalar-first quaternion for 3-2-1 (yaw, pitch, roll) attitude."""
    cr = math.cos(phi * 0.5)
    sr = math.sin(phi * 0.5)
    cp = math.cos(theta * 0.5)
    sp = math.sin(theta * 0.5)
    cy = math.cos(psi * 0.5)
    sy = math.sin(psi * 0.5)
    w = cy * cp * cr + sy * sp * sr
    x = cy * cp * sr - sy * sp * cr
    y = cy * sp * cr + sy * cp * sr
    z = sy * cp * cr - cy * sp * sr
    return _normalize_quat(w, x, y, z)


def roll_from_quat(quat: list[float]) -> float:
    """Extract 3-2-1 roll (rad). Positive is right-wing-down in FRD."""
    w, x, y, z = quat
    return math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))


def pitch_from_quat(quat: list[float]) -> float:
    w, x, y, z = quat
    sinp = 2.0 * (w * y - z * x)
    if sinp >= 1.0:
        return math.pi / 2.0
    if sinp <= -1.0:
        return -math.pi / 2.0
    return math.asin(sinp)


def yaw_from_quat(quat: list[float]) -> float:
    w, x, y, z = quat
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _normalize_quat(w: float, x: float, y: float, z: float) -> list[float]:
    nrm = math.sqrt(w * w + x * x + y * y + z * z)
    if nrm == 0.0:
        return [1.0, 0.0, 0.0, 0.0]
    return [w / nrm, x / nrm, y / nrm, z / nrm]
