"""The typed edit kernels (deliverable A3, B).

One pure function per supported operation. Each takes the parent `ReconParams`, returns a
**new** parameter set (the parent is never mutated) and the list of typed changes that
describe what moved, in the shape the contract expects:

    {"part_id": ..., "field": ..., "before": ..., "after": ..., "unit": ...}

A change whose consequence is genuinely unknown is still reported: `before` and `after` stay
`null`, `status` says `"unknown"`, and `note` says why. Mass and CG on this aircraft are
unknown -- the printed parts have no measured mass and the hardware is a synthetic demo
envelope -- so moving the battery reports a CG consequence of *unknown*, never a number.

Bounds are not checked here. `policy.check_bounds()` runs first; these functions assume a
request that already passed it, and raise `EditBlocked(UNSUPPORTED_EDIT)` only when the
target does not exist in the parameter set at all.
"""
from __future__ import annotations

from typing import Any, Optional

from dronebench_cad import ReconParams
from dronebench_contracts.models import ErrorCode

from .api import EditBlocked

__all__ = [
    "Change",
    "translate_component",
    "resize_spar",
    "set_wing_tip_extension",
    "UNKNOWN_MASS_NOTE",
]

Change = dict[str, Any]

UNKNOWN_MASS_NOTE = (
    "Mass is unknown for this aircraft: printed parts carry no measured mass and the "
    "hardware envelopes are a synthetic demo BOM. No mass, CG or balance number is produced."
)


def _change(part_id: str, field: str, before: Any, after: Any, unit: Optional[str],
            **extra: Any) -> Change:
    return {"part_id": part_id, "field": field, "before": before, "after": after,
            "unit": unit, **extra}


def _unknown_change(part_id: str, field: str, unit: Optional[str], note: str) -> Change:
    return _change(part_id, field, None, None, unit, status="unknown", note=note)


# ---------------------------------------------------------------------------- translate

def translate_component(params: ReconParams, part_id: str,
                        delta_m: list[float]) -> tuple[ReconParams, list[Change]]:
    """Move one movable envelope. Placement only: no dimension and no shape changes.

    `delta_m` is [dx, dy, dz] in FRD metres. The battery is the movable component in the
    demo fixture; any other target is refused rather than silently ignored.
    """
    if part_id != params.battery.part_id or not params.battery.enabled:
        raise EditBlocked.of(
            ErrorCode.UNSUPPORTED_EDIT,
            f"translate_component has no movable envelope named {part_id!r} in this "
            f"parameter set; the movable component is {params.battery.part_id!r}",
            part_id=part_id, movable=[params.battery.part_id],
        )
    delta = [float(v) for v in delta_m]
    new = params.model_copy(deep=True)
    before = [float(v) for v in params.battery.center_m]
    after = [round(b + d, 12) for b, d in zip(before, delta)]
    new.battery.center_m = after

    changes: list[Change] = [
        _change(part_id, "center_m", before, after, "m", delta=delta,
                note="Instance placement only; the envelope's dimensions are unchanged."),
        _unknown_change(
            "aircraft", "cg_m", "m",
            "Moving the pack changes the centre of gravity, but this aircraft's mass "
            "breakdown is UNKNOWN, so the CG before and after are both unknown and no shift "
            "is reported. " + UNKNOWN_MASS_NOTE,
        ),
        _unknown_change(
            part_id, "retention_and_harness", None,
            "The battery retention strap and power harness are not in the source archive, "
            "so this movement cannot be called verified until the interface is known.",
        ),
    ]
    return new, changes


# ---------------------------------------------------------------------------- spar

def resize_spar(params: ReconParams, outer_d_mm: float,
                inner_d_mm: Optional[float] = None) -> tuple[ReconParams, list[Change]]:
    """Regenerate the spar tube. Wall thickness is preserved unless a bore is given."""
    if not params.spar.enabled:
        raise EditBlocked.of(
            ErrorCode.UNSUPPORTED_EDIT,
            "this parameter set has no spar to resize (spar.enabled is false)",
            part_id=params.spar.part_id,
        )
    part_id = params.spar.part_id
    outer_m = float(outer_d_mm) / 1000.0
    before_outer = float(params.spar.outer_diameter_m)
    before_inner = float(params.spar.inner_diameter_m)
    before_wall = (before_outer - before_inner) / 2.0
    inner_m = (outer_m - 2 * before_wall) if inner_d_mm is None else float(inner_d_mm) / 1000.0
    after_wall = (outer_m - inner_m) / 2.0

    new = params.model_copy(deep=True)
    new.spar.outer_diameter_m = round(outer_m, 12)
    new.spar.inner_diameter_m = round(inner_m, 12)

    changes: list[Change] = [
        _change(part_id, "outer_diameter_m", before_outer, new.spar.outer_diameter_m, "m"),
        _change(part_id, "inner_diameter_m", before_inner, new.spar.inner_diameter_m, "m",
                note=("Bore kept the parent wall thickness." if inner_d_mm is None
                      else "Bore was given explicitly.")),
        _change(part_id, "wall_thickness_m", round(before_wall, 12), round(after_wall, 12), "m"),
    ]
    if params.spar.mass_kg is None:
        changes.append(_unknown_change(
            part_id, "mass_kg", "kg",
            "The tube's cross-section changed, but no material is claimed for it "
            "(no spar exists in the source archive), so its mass stays unknown. "
            + UNKNOWN_MASS_NOTE,
        ))
    return new, changes


# ---------------------------------------------------------------------------- tip extension

def set_wing_tip_extension(params: ReconParams,
                           extension_m: float) -> tuple[ReconParams, list[Change]]:
    """Stretch both wing tips by the same amount, in one transaction.

    The parameter is symmetric by construction -- `reconstruct()` builds the right panel and
    mirrors it -- so both occurrences are reported as changed and neither can move alone.
    """
    wing = next((s for s in params.surfaces if s.category == "wing"), None)
    if wing is None:
        raise EditBlocked.of(
            ErrorCode.UNSUPPORTED_EDIT,
            "this parameter set has no wing surface to extend",
            part_id=None,
        )
    extension = float(extension_m)
    before = float(params.tip_extension_m)
    new = params.model_copy(deep=True)
    new.tip_extension_m = round(extension, 12)

    tip_y = float(wing.stations[-1].span_y_m)
    half_before, half_after = tip_y + before, tip_y + extension
    part_ids = [pid for pid in (wing.part_id_right, wing.part_id_left) if pid]

    changes: list[Change] = []
    for pid in part_ids:
        changes.append(_change(pid, "tip_extension_m", before, new.tip_extension_m, "m",
                               note="Symmetric: both wing occurrences move in one transaction."))
        changes.append(_change(pid, "tip_station_span_y_m", round(half_before, 12),
                               round(half_after, 12), "m"))
    changes.append(_change("aircraft", "wing_span_m", round(2 * half_before, 12),
                           round(2 * half_after, 12), "m",
                           note="Tip-to-tip, both panels; regenerated geometry, not a formula "
                                "applied to a published number."))
    if params.spar.enabled:
        changes.append(_change(
            params.spar.part_id, "span_m", float(params.spar.span_m), float(params.spar.span_m),
            "m", status="unchanged",
            note="The spar is NOT extended with the tip: the tip joint, rib and spar stub are "
                 "not reconstructed, so lengthening the tube would be an invented structure.",
        ))
    changes.append(_unknown_change(
        "aircraft", "mass_kg", "kg",
        "Added wing area implies added mass, but no mass model exists for the printed "
        "structure. " + UNKNOWN_MASS_NOTE,
    ))
    return new, changes
