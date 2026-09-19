"""NACA 4-digit section coordinates.

The airfoil is an **assumed** shape. Nothing in the Avenger archive identifies a section;
the printed shells are hollow and noisy. We take the 4-digit family because it is
parameterised by exactly the two things a slice can measure (thickness ratio) and one thing
it cannot (camber), so the assumption stays visible in the parameter set instead of being
baked into a table of coordinates.
"""
from __future__ import annotations

import math

__all__ = ["naca4_points", "DEFAULT_CAMBER", "DEFAULT_CAMBER_POS"]

DEFAULT_CAMBER = 0.04      # m in the NACA 44xx sense: max camber as a fraction of chord
DEFAULT_CAMBER_POS = 0.4   # p: chordwise position of max camber


def _cosine_spacing(n: int) -> list[float]:
    """Chordwise stations clustered at the leading and trailing edges."""
    return [0.5 * (1.0 - math.cos(math.pi * i / (n - 1))) for i in range(n)]


def naca4_points(
    thickness: float,
    camber: float = DEFAULT_CAMBER,
    camber_pos: float = DEFAULT_CAMBER_POS,
    n_per_side: int = 41,
    closed_te: bool = True,
) -> list[tuple[float, float]]:
    """Unit-chord section outline, counter-clockwise from the trailing edge.

    Returns `(x, y)` with x in [0, 1] aft of the leading edge and y positive **up**
    (the caller maps that onto the aircraft frame). The trailing edge is closed so the
    loft produces a solid rather than an open shell.
    """
    if not 0.0 < thickness < 1.0:
        raise ValueError(f"thickness ratio out of range: {thickness}")
    if n_per_side < 8:
        raise ValueError("n_per_side must be >= 8")

    t = thickness
    m, p = camber, camber_pos
    a4 = -0.1036 if closed_te else -0.1015  # closed-TE variant of the standard coefficient

    def half_thickness(x: float) -> float:
        return (
            5.0
            * t
            * (0.2969 * math.sqrt(x) - 0.1260 * x - 0.3516 * x**2 + 0.2843 * x**3 + a4 * x**4)
        )

    def camber_line(x: float) -> tuple[float, float]:
        if m == 0.0 or p == 0.0:
            return 0.0, 0.0
        if x < p:
            yc = m / p**2 * (2 * p * x - x**2)
            dy = 2 * m / p**2 * (p - x)
        else:
            yc = m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x**2)
            dy = 2 * m / (1 - p) ** 2 * (p - x)
        return yc, dy

    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    for x in _cosine_spacing(n_per_side):
        yt = half_thickness(x)
        yc, dy = camber_line(x)
        theta = math.atan(dy)
        upper.append((x - yt * math.sin(theta), yc + yt * math.cos(theta)))
        lower.append((x + yt * math.sin(theta), yc - yt * math.cos(theta)))

    # TE -> LE along the lower surface, then LE -> TE along the upper surface.
    pts = list(reversed(lower[1:])) + upper[:-1]
    # Force an exactly shared leading-edge point and a single closed trailing edge.
    return [(round(x, 12), round(y, 12)) for x, y in pts]
