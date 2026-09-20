"""World-frame adapters for replay renderers.

Plant state is NED metres, body FRD, scalar-first quaternion.
Each renderer converts at this boundary only. Do not duplicate in Blueprints.
"""

from __future__ import annotations

import math
from typing import Sequence

from .attitude import quat_from_euler_321

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]


def ned_to_three_m(pos_ned: Sequence[float]) -> Vec3:
    """NED metres -> three.js Y-up metres: X east, Y up, Z -north."""
    n, e, d = float(pos_ned[0]), float(pos_ned[1]), float(pos_ned[2])
    return (e, -d, -n)


def ned_to_ue_cm(pos_ned: Sequence[float]) -> Vec3:
    """NED metres -> Unreal left-handed Z-up centimetres: X north, Y east, Z up."""
    n, e, d = float(pos_ned[0]), float(pos_ned[1]), float(pos_ned[2])
    return (n * 100.0, e * 100.0, -d * 100.0)


def quat_frd_ned_to_three(quat: Sequence[float]) -> Quat:
    """Body-to-NED quat -> body-to-three.js quat (scalar-first).

    three.js is Y-up right-handed with X=east, Z=-north. Identity FRD
    therefore has body forward along -Z, right along +X, down along -Y.
    """
    r_bn = _rot_from_quat(quat)
    # M maps NED -> three: (n,e,d) -> (e, -d, -n)
    m = (
        (0.0, 1.0, 0.0),
        (0.0, 0.0, -1.0),
        (-1.0, 0.0, 0.0),
    )
    return _quat_from_rot(_mmul(m, r_bn))


def quat_frd_ned_to_ue(quat: Sequence[float]) -> Quat:
    """Body-to-NED quat -> Unreal FRu (forward-right-up) scalar-first quat.

    Unreal is left-handed Z-up with X=north, Y=east. Right-wing-down
    (positive FRD roll) lowers the +Y wing in Unreal Z.
    """
    r_bn = _rot_from_quat(quat)
    fwd_n = _mv(r_bn, (1.0, 0.0, 0.0))
    right_n = _mv(r_bn, (0.0, 1.0, 0.0))
    down_n = _mv(r_bn, (0.0, 0.0, 1.0))
    fwd_ue = (fwd_n[0], fwd_n[1], -fwd_n[2])
    right_ue = (right_n[0], right_n[1], -right_n[2])
    up_ue = (-down_n[0], -down_n[1], down_n[2])
    # Orthonormalize in case of LH reconstruction: columns = forward, right, up
    r_ue = (
        (fwd_ue[0], right_ue[0], up_ue[0]),
        (fwd_ue[1], right_ue[1], up_ue[1]),
        (fwd_ue[2], right_ue[2], up_ue[2]),
    )
    return _quat_from_rot(r_ue)


def rotate_body_point_three(quat: Sequence[float], body_frd_m: Sequence[float]) -> Vec3:
    """Rotate a body FRD point into three.js world axes (translation not applied)."""
    q = quat_frd_ned_to_three(quat)
    return _qv(q, (float(body_frd_m[0]), float(body_frd_m[1]), float(body_frd_m[2])))


def rotate_body_point_ue(quat: Sequence[float], body_frd_m: Sequence[float]) -> Vec3:
    q = quat_frd_ned_to_ue(quat)
    return _qv(q, (float(body_frd_m[0]), float(body_frd_m[1]), float(body_frd_m[2])))


def identity_quat() -> Quat:
    return (1.0, 0.0, 0.0, 0.0)


def _rot_from_quat(quat: Sequence[float]) -> tuple[Vec3, Vec3, Vec3]:
    w, x, y, z = (float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
    )


def _mmul(
    a: tuple[Vec3, Vec3, Vec3], b: tuple[Vec3, Vec3, Vec3]
) -> tuple[Vec3, Vec3, Vec3]:
    rows = []
    for i in range(3):
        rows.append(
            tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
        )
    return (rows[0], rows[1], rows[2])  # type: ignore[return-value]


def _mv(r: tuple[Vec3, Vec3, Vec3], v: Vec3) -> Vec3:
    return (
        r[0][0] * v[0] + r[0][1] * v[1] + r[0][2] * v[2],
        r[1][0] * v[0] + r[1][1] * v[1] + r[1][2] * v[2],
        r[2][0] * v[0] + r[2][1] * v[1] + r[2][2] * v[2],
    )


def _qv(q: Sequence[float], v: Vec3) -> Vec3:
    return _mv(_rot_from_quat(q), v)


def _quat_from_rot(r: tuple[Vec3, Vec3, Vec3]) -> Quat:
    m00, m01, m02 = r[0]
    m10, m11, m12 = r[1]
    m20, m21, m22 = r[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m21 - m12) * s
        y = (m02 - m20) * s
        z = (m10 - m01) * s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * math.sqrt(max(1e-15, 1.0 + m00 - m11 - m22))
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * math.sqrt(max(1e-15, 1.0 + m11 - m00 - m22))
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = 2.0 * math.sqrt(max(1e-15, 1.0 + m22 - m00 - m11))
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    return (w / n, x / n, y / n, z / n)


__all__ = [
    "ned_to_three_m",
    "ned_to_ue_cm",
    "quat_frd_ned_to_three",
    "quat_frd_ned_to_ue",
    "rotate_body_point_three",
    "rotate_body_point_ue",
    "identity_quat",
    "quat_from_euler_321",
]
