"""Frame proposal and the transforms between native CAD coordinates and the canonical FRD frame.

Canonical frame (architecture §5): right-handed FRD — x forward, y right, z down, origin at the
confirmed nose datum, metres. The candidate mapping for this archive is

    x = -(Y_native - Y_nose) * s,   y = -X_native * s,   z = -Z_native * s

which is the proper rotation ``NATIVE_TO_FRD`` (determinant +1) applied after the datum shift and
scaling. Positive native X therefore lands on the *left* of the aircraft; that side assignment is a
hypothesis until a human confirms it in the viewer.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

import numpy as np

from dronebench_contracts.models import FrameConfirmation, SourceFile

# rows: FRD x from native -Y, FRD y from native -X, FRD z from native -Z
NATIVE_TO_FRD: list[list[float]] = [[0.0, -1.0, 0.0], [-1.0, 0.0, 0.0], [0.0, 0.0, -1.0]]
MM_EXTENT_THRESHOLD_M = 20.0      # a 20 m "metre" aircraft is millimetres
SIDE_TOLERANCE = 1e-6             # native units

# Filename stem -> category. Filenames are evidence, not instructions: the category only drives
# grouping and is recorded as such. Longer keys are matched first.
CATEGORY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("wing_bay_plate", "mount"),
    ("motor_mount", "mount"),
    ("taileron", "ruddervator"),
    ("aileron", "aileron"),
    ("canopy", "canopy"),
    ("hatch", "hatch"),
    ("vtail", "vtail"),
    ("wing", "wing"),
    ("fuse", "fuselage"),
)
AERO_CATEGORIES = ("wing", "aileron", "vtail", "ruddervator")
FUSELAGE_CATEGORIES = ("fuselage", "canopy", "hatch")


def categorize(source_path: str) -> str:
    """Category for a source file from its filename stem. ``other`` when no rule matches."""
    stem = re.split(r"[/\\]", source_path)[-1].rsplit(".", 1)[0].lower()
    for key, category in CATEGORY_KEYWORDS:
        if key in stem:
            return category
    return "other"


def _bounds(sources: Iterable[SourceFile]) -> Optional[np.ndarray]:
    boxes = [np.array(s.qa.bounds_native, dtype=float) for s in sources if s.qa.finite]
    if not boxes:
        return None
    stack = np.array(boxes)
    return np.array([stack[:, 0, :].min(axis=0), stack[:, 1, :].max(axis=0)])


def guess_units(sources: Iterable[SourceFile]) -> tuple[str, float, str]:
    """(units, scale to metres, why). A guess may initialise the control; it never confirms it."""
    box = _bounds(sources)
    if box is None:
        return "mm", 0.001, "no finite bounds; defaulted to mm"
    extent = float((box[1] - box[0]).max())
    if extent > MM_EXTENT_THRESHOLD_M:
        return "mm", 0.001, f"largest native extent {extent:.1f} would be {extent:.0f} m if metres"
    if extent > 1.0:
        return "m", 1.0, f"largest native extent {extent:.3f} is plausible in metres"
    return "in", 0.0254, f"largest native extent {extent:.3f} is small for metres"


def detect_mirror_plane(sources: Iterable[SourceFile]) -> tuple[Optional[str], str]:
    """``("x=0", why)`` when every lifting-surface part sits on one side of native x=0."""
    aero = [s for s in sources if categorize(s.source_path) in AERO_CATEGORIES and s.qa.finite]
    if not aero:
        return None, "no wing or tail parts found; no mirror plane proposed"
    lo = min(s.qa.bounds_native[0][0] for s in aero)
    hi = max(s.qa.bounds_native[1][0] for s in aero)
    names = ", ".join(sorted(s.source_path.rsplit("/", 1)[-1] for s in aero))
    if lo >= -SIDE_TOLERANCE:
        return "x=0", f"all {len(aero)} lifting-surface parts have native x >= {lo:.2f} ({names})"
    if hi <= SIDE_TOLERANCE:
        return "x=0", f"all {len(aero)} lifting-surface parts have native x <= {hi:.2f} ({names})"
    return None, f"lifting-surface parts straddle native x=0 (x from {lo:.2f} to {hi:.2f}); not a half model"


def nose_datum(sources: Iterable[SourceFile]) -> tuple[list[float], str]:
    """Native coordinates of the canonical origin: the forward extreme of the fuselage group."""
    fus = [s for s in sources if categorize(s.source_path) in FUSELAGE_CATEGORIES and s.qa.finite]
    box = _bounds(fus) if fus else _bounds(sources)
    if box is None:
        return [0.0, 0.0, 0.0], "no finite bounds; datum left at the native origin"
    y_nose = float(box[0][1])
    what = "fuselage group" if fus else "all parts"
    return [0.0, y_nose, 0.0], f"most-forward point of the {what} is native Y = {y_nose:.2f}"


def propose_frame(sources: list[SourceFile]) -> FrameConfirmation:
    """Candidate units, rotation, nose datum and mirror plane. Always returned unconfirmed."""
    units, _, unit_why = guess_units(sources)
    scale = {"mm": 0.001, "m": 1.0, "in": 0.0254}[units]
    datum, datum_why = nose_datum(sources)
    plane, plane_why = detect_mirror_plane(sources)
    return FrameConfirmation(
        units=units,
        native_to_frd=[row[:] for row in NATIVE_TO_FRD],
        scale_to_m=scale,
        nose_datum_native=datum,
        mirror_plane_native=plane,
        confirmed=False,
        notes=[
            f"units: {unit_why}",
            f"nose datum: {datum_why}",
            f"mirror: {plane_why}",
            "candidate mapping x=-(Y-Y_nose)*s, y=-X*s, z=-Z*s; this puts positive native X on the "
            "LEFT of the aircraft — confirm the side assignment in the viewer before any metric",
            "aft of the nose is negative canonical x by construction",
        ],
    )


# ------------------------------------------------------------------ transforms

def rotation(frame: FrameConfirmation) -> np.ndarray:
    return np.array(frame.native_to_frd, dtype=float)


def placement_matrix(frame: FrameConfirmation) -> np.ndarray:
    """4x4 rigid placement taking a definition (native coordinates scaled to metres) into FRD.

    p_frd = R @ (s * p_native - s * datum). Rotation part is ``native_to_frd`` (det +1); the
    translation is in metres. No scale and no reflection live in this matrix.
    """
    R = rotation(frame)
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = -R @ (np.array(frame.nose_datum_native, dtype=float) * frame.scale_to_m)
    return T


def to_frd(points: np.ndarray, frame: FrameConfirmation) -> np.ndarray:
    """Native points (n,3) -> FRD metres."""
    p = np.asarray(points, dtype=float) * frame.scale_to_m
    datum = np.array(frame.nose_datum_native, dtype=float) * frame.scale_to_m
    return (rotation(frame) @ (p - datum).T).T


def definition_scale_matrix(frame: FrameConfirmation) -> np.ndarray:
    """4x4 scaling from native file units to metres, applied to a definition's own geometry."""
    T = np.eye(4)
    T[:3, :3] *= frame.scale_to_m
    return T


def mirror_matrix(frame: FrameConfirmation) -> np.ndarray:
    """Reflection of a definition's own (metre) geometry about the confirmed mirror plane.

    This is a geometry operation on the definition — winding is repaired afterwards — and is never
    folded into a placement (architecture §5: reflections are not accepted as rotations).
    """
    plane = (frame.mirror_plane_native or "x=0").lower().replace(" ", "")
    axis = {"x=0": 0, "y=0": 1, "z=0": 2}.get(plane)
    if axis is None:
        raise ValueError(f"unsupported mirror plane {frame.mirror_plane_native!r}")
    T = np.eye(4)
    T[axis, axis] = -1.0
    return T
