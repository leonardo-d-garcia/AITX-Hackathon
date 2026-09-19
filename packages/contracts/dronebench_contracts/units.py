"""Canonical units, frames, and boundary conversions (architecture §5).

SI throughout the core: lengths m, mass kg, force N, time s, current A, energy Wh, angles rad,
temperature K. Degrees exist only at the UI boundary; millimetres only at the CAD worker boundary.

Canonical aircraft frame is right-handed **FRD**: X forward, Y right, Z down, origin at an
explicitly identified nose datum. Longitudinal station ``s = -x`` increases aft, which is what the
conventional static-margin formula expects.
"""

from __future__ import annotations

import math
from typing import Final, Literal

# --------------------------------------------------------------------------------------------
# Unit vocabulary
# --------------------------------------------------------------------------------------------

Unit = Literal[
    "m", "m^2", "m^3", "m^4",
    "kg", "kg*m^2",
    "N", "N*m", "Pa",
    "s", "min", "h",
    "A", "V", "W", "Wh", "Wh/km",
    "rad", "K",
    "m/s", "km", "km/h",
    "kg/m^3",
    "1",            # dimensionless ratio
    "count",
    "USD",
]

#: Units whose values must never be negative.
NON_NEGATIVE_UNITS: Final[frozenset[str]] = frozenset(
    {"m^2", "m^3", "m^4", "kg", "s", "min", "h", "Wh", "K", "count", "kg/m^3"}
)

# --------------------------------------------------------------------------------------------
# Scale factors
# --------------------------------------------------------------------------------------------

#: Canonical metres -> native CAD kernel millimetres. Applied only at the CAD worker boundary.
M_TO_MM: Final[float] = 1000.0
MM_TO_M: Final[float] = 1.0 / M_TO_MM

#: Standard gravity used for W = mg. Declared, not assumed silently.
G0: Final[float] = 9.80665  # m/s^2

#: ISA sea-level density. Any evaluator that uses another value must declare it.
RHO_ISA_SL: Final[float] = 1.225  # kg/m^3


def deg(rad_value: float) -> float:
    """rad -> deg. UI boundary only."""
    return math.degrees(rad_value)


def rad(deg_value: float) -> float:
    """deg -> rad. UI boundary only."""
    return math.radians(deg_value)


def station_from_x(x_m: float) -> float:
    """Longitudinal station ``s = -x``: aft-positive, as static-margin formulae expect."""
    return -x_m


def x_from_station(s_m: float) -> float:
    """Inverse of :func:`station_from_x`."""
    return -s_m


# --------------------------------------------------------------------------------------------
# Frame adapters
# --------------------------------------------------------------------------------------------

Vec3 = tuple[float, float, float]


def frd_to_threejs(v: Vec3) -> Vec3:
    """Canonical FRD -> the right-handed Y-up frame the browser viewport uses.

    ``(x, y, z)_FRD -> (y, -z, -x)``. Architecture §5. Each other adapter (VSP, Gazebo) declares
    and tests its own transform; none of them may assume this one.
    """
    x, y, z = v
    return (y, -z, -x)


def threejs_to_frd(v: Vec3) -> Vec3:
    """Inverse of :func:`frd_to_threejs`."""
    a, b, c = v
    return (-c, a, -b)


def frd_m_to_kernel_mm(v: Vec3) -> Vec3:
    """Canonical metres -> CAD kernel millimetres, no rotation."""
    return (v[0] * M_TO_MM, v[1] * M_TO_MM, v[2] * M_TO_MM)


def kernel_mm_to_frd_m(v: Vec3) -> Vec3:
    """CAD kernel millimetres -> canonical metres, no rotation."""
    return (v[0] * MM_TO_M, v[1] * MM_TO_M, v[2] * MM_TO_M)


#: Candidate mapping from the Titan archive's native coordinates, architecture §5.
#: ``x = -(Y - Y_nose) * 0.001``, ``y = -X * 0.001``, ``z = -Z * 0.001``.
#: ``Y_nose`` is an estimate that A must confirm in the viewer before metrics are enabled.
TITAN_Y_NOSE_NATIVE_MM: Final[float] = -403.07


def titan_native_to_frd(
    native_xyz_mm: Vec3, y_nose_native_mm: float = TITAN_Y_NOSE_NATIVE_MM
) -> Vec3:
    """Apply the §5 *candidate* archive mapping. Unconfirmed until A records the decision."""
    nx, ny, nz = native_xyz_mm
    return (
        -(ny - y_nose_native_mm) * MM_TO_M,
        -nx * MM_TO_M,
        -nz * MM_TO_M,
    )
