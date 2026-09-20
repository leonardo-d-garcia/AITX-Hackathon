"""Bounds, capabilities and the one real constraint (deliverable A3, B).

Every number this module enforces comes from `packages/edits/edit_policy.yaml`; nothing is
hard-coded here. The file says, per bound, whether it is a demo fixture or a confirmed fact.

The only bound that is *not* invented is the spar outer-diameter ceiling: it is read from the
wing3 variant a human selected at ingest time (`DesignManifest.variants`). wing3_12mm_hole
means a 12 mm rib hole, wing3_16mm_hole means 16 mm, and wing3_no_hole means the wing has no
through-spar passage at all, so no spar resize can be honoured. If nobody confirmed a wing3
variant, the limit is unknown and the edit is refused rather than guessed.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

import yaml

from dronebench_contracts.models import (CadEditRequest, DesignManifest, EditCapability,
                                         EditOperation, ErrorCode)

from .api import EditBlocked

__all__ = [
    "DEFAULT_POLICY_PATH",
    "SUPPORTED_OPERATIONS",
    "REQUIRED_CAPABILITY",
    "load_policy",
    "policy_hash",
    "spar_hole_limit_mm",
    "resolve_target",
    "check_bounds",
]

DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "edit_policy.yaml"

#: The operations this kernel actually implements. `replace_catalog_component` is in the
#: contract's enum as a stretch item and is deliberately refused here.
SUPPORTED_OPERATIONS: dict[EditOperation, str] = {
    EditOperation.translate_component: "translate_component",
    EditOperation.resize_spar: "resize_spar",
    EditOperation.set_wing_tip_extension: "set_wing_tip_extension",
}

REQUIRED_CAPABILITY: dict[EditOperation, EditCapability] = {
    EditOperation.translate_component: EditCapability.translate,
    EditOperation.resize_spar: EditCapability.resize_spar,
    EditOperation.set_wing_tip_extension: EditCapability.wing_tip_extension,
}

_CACHE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------- loading

def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    """Read the declared bounds. Cached by resolved path; the file is never written."""
    resolved = Path(path or DEFAULT_POLICY_PATH).resolve()
    key = str(resolved)
    if key not in _CACHE:
        data = yaml.safe_load(resolved.read_text()) or {}
        data["_path"] = key
        data["_sha256"] = hashlib.sha256(resolved.read_bytes()).hexdigest()
        _CACHE[key] = data
    return _CACHE[key]


def policy_hash(policy: dict[str, Any]) -> str:
    """A stable hash of the bounds, for the revision's content hash."""
    if policy.get("_sha256"):
        return policy["_sha256"]
    payload = {k: v for k, v in policy.items() if not k.startswith("_")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------------------- the real one

def spar_hole_limit_mm(manifest: Any, policy: Optional[dict[str, Any]] = None) -> float:
    """The largest spar OD the *confirmed* wing3 variant will pass, in millimetres.

    Raises `EditBlocked` when no wing3 variant was confirmed (the limit is unknown, so the
    edit cannot be justified) or when the confirmed variant has no through-spar passage.
    """
    policy = policy or load_policy()
    ceiling = policy["spar"]["outer_diameter_ceiling"]
    group_id = ceiling["variant_group"]
    by_variant: dict[str, Optional[float]] = ceiling["by_variant"]

    selected = None
    for group in getattr(manifest, "variants", None) or []:
        gid = group.group_id if hasattr(group, "group_id") else group.get("group_id")
        if gid == group_id:
            selected = group.selected if hasattr(group, "selected") else group.get("selected")
            break

    if not selected:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"spar outer diameter is bounded by the {group_id} rib hole, and no {group_id} "
            "variant has been confirmed for this design: the limit is unknown, so the resize "
            "is refused rather than guessed",
            limit="spar.outer_diameter_ceiling",
            source=ceiling["source"],
            variant_group=group_id,
            selected=None,
        )

    stem = Path(str(selected)).stem
    match = next((name for name in by_variant if name == stem), None)
    if match is None:
        match = next((name for name in by_variant if name in stem), None)
    if match is None:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"confirmed {group_id} variant {stem!r} is not one of the variants whose rib-hole "
            f"diameter is declared ({', '.join(sorted(by_variant))}): the spar limit is unknown",
            limit="spar.outer_diameter_ceiling",
            source=ceiling["source"],
            variant_group=group_id,
            selected=stem,
        )

    limit = by_variant[match]
    if limit is None:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"the confirmed {group_id} variant is {match!r}, which has no through-spar "
            "passage: a spar cannot be resized through a wing that has no hole",
            limit="spar.outer_diameter_ceiling",
            source=ceiling["source"],
            variant_group=group_id,
            selected=match,
            limit_mm=None,
        )
    return float(limit)


# ---------------------------------------------------------------------------- targets

def resolve_target(part_id: str, manifest: Any,
                   policy: Optional[dict[str, Any]] = None) -> tuple[str, list[EditCapability]]:
    """Map a requested target onto a reconstruction part and its allowed operations.

    A manifest part carries its own `edit_capabilities` and that list wins; a reconstruction
    part (`recon_*`) has no manifest counterpart, so the policy's `reconstruction_targets`
    table declares what it may do. Anything else is unknown and cannot be edited.
    """
    policy = policy or load_policy()
    recon_table: dict[str, list[str]] = policy.get("reconstruction_targets", {}) or {}
    by_category: dict[str, str] = (
        (policy.get("target_aliases", {}) or {}).get("by_category", {}) or {}
    )

    part = next((p for p in (getattr(manifest, "parts", None) or [])
                 if getattr(p, "part_id", None) == part_id), None)
    if part is not None:
        if getattr(part, "locked", False):
            raise EditBlocked.of(
                ErrorCode.UNSUPPORTED_EDIT,
                f"part {part_id!r} ({part.name}) is locked: it is an imported reference mesh, "
                "not editable topology",
                part_id=part_id, capabilities=[],
            )
        recon_id = by_category.get(str(getattr(part, "category", "")), part_id)
        return recon_id, list(part.edit_capabilities or [])

    if part_id in recon_table:
        return part_id, [EditCapability(c) for c in recon_table[part_id]]

    raise EditBlocked.of(
        ErrorCode.UNSUPPORTED_EDIT,
        f"unknown target part {part_id!r}: it is neither an occurrence in the design manifest "
        f"nor a declared reconstruction target ({', '.join(sorted(recon_table))})",
        part_id=part_id,
    )


# ---------------------------------------------------------------------------- bounds

def _as_float(value: Any, field: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"parameter {field!r} must be a number in SI units, got {value!r}",
            parameter=field, requested=value,
        ) from None


def check_bounds(request: CadEditRequest, manifest: Any, params: Any,
                 policy: Optional[dict[str, Any]] = None) -> None:
    """Refuse the edit, loudly and typed, or return None. Never mutates anything.

    `EditBlocked` carries `ErrorCode.UNSUPPORTED_EDIT` for an operation this kernel does not
    implement or a target that is not allowed to do it, and `ErrorCode.CONSTRAINT_FAILED`
    for a declared bound that the requested value crosses. Every message names the limit,
    where the limit comes from, and the value that was asked for.
    """
    policy = policy or load_policy()

    # ---- operation supported at all
    try:
        operation = EditOperation(request.operation)
    except ValueError:
        raise EditBlocked.of(
            ErrorCode.UNSUPPORTED_EDIT,
            f"unknown edit operation {request.operation!r}; this kernel implements "
            f"{', '.join(sorted(o.value for o in SUPPORTED_OPERATIONS))}",
            operation=str(request.operation),
        ) from None
    if operation not in SUPPORTED_OPERATIONS:
        raise EditBlocked.of(
            ErrorCode.UNSUPPORTED_EDIT,
            f"operation {operation.value!r} is not implemented in this build; this kernel "
            f"implements {', '.join(sorted(o.value for o in SUPPORTED_OPERATIONS))}",
            operation=operation.value,
        )

    if not request.target_part_ids:
        raise EditBlocked.of(
            ErrorCode.UNSUPPORTED_EDIT,
            f"{operation.value} needs at least one target part id",
            operation=operation.value,
        )

    # ---- every target may do it
    needed = REQUIRED_CAPABILITY[operation]
    for part_id in request.target_part_ids:
        recon_id, capabilities = resolve_target(part_id, manifest, policy)
        if needed not in capabilities:
            raise EditBlocked.of(
                ErrorCode.UNSUPPORTED_EDIT,
                f"part {part_id!r} does not allow {operation.value}: its declared edit "
                f"capabilities are {[c.value for c in capabilities] or ['none']}",
                operation=operation.value, part_id=part_id, resolved_part_id=recon_id,
                capabilities=[c.value for c in capabilities],
            )

    # ---- the numbers
    if operation is EditOperation.translate_component:
        _check_translate(request, params, policy)
    elif operation is EditOperation.resize_spar:
        _check_resize_spar(request, manifest, params, policy)
    elif operation is EditOperation.set_wing_tip_extension:
        _check_tip_extension(request, policy)


def _check_translate(request: CadEditRequest, params: Any, policy: dict[str, Any]) -> None:
    corridor = policy["battery_corridor"]
    delta = request.parameters.get("delta_m")
    if not isinstance(delta, (list, tuple)) or len(delta) != 3:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"translate_component needs delta_m as three metres [dx, dy, dz], got {delta!r}",
            parameter="delta_m", requested=delta,
        )
    delta = [_as_float(v, "delta_m") for v in delta]

    travel = sum(v * v for v in delta) ** 0.5
    allowance = float(corridor["harness_allowance_m"])
    if travel > allowance + 1e-12:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"requested travel {travel * 1000:.1f} mm exceeds the declared harness allowance "
            f"of {allowance * 1000:.1f} mm (limit battery_corridor.harness_allowance_m, "
            f"source: {corridor['source']})",
            limit="battery_corridor.harness_allowance_m", limit_value=allowance,
            requested=travel, unit="m", source=corridor["source"],
        )

    before = [float(v) for v in params.battery.center_m]
    after = [b + d for b, d in zip(before, delta)]
    for axis, value in zip("xyz", after):
        lo, hi = float(corridor[f"{axis}_min"]), float(corridor[f"{axis}_max"])
        if not (lo - 1e-12 <= value <= hi + 1e-12):
            raise EditBlocked.of(
                ErrorCode.CONSTRAINT_FAILED,
                f"battery centre {axis}={value:.4f} m leaves the declared corridor "
                f"[{lo:.3f}, {hi:.3f}] m (limit battery_corridor.{axis}_min/_max, "
                f"source: {corridor['source']})",
                limit=f"battery_corridor.{axis}", limit_value=[lo, hi],
                requested=value, unit="m", source=corridor["source"],
            )


def _check_resize_spar(request: CadEditRequest, manifest: Any, params: Any,
                       policy: dict[str, Any]) -> None:
    spar_policy = policy["spar"]
    p = request.parameters
    if "outer_d_mm" not in p and "outer_diameter_mm" not in p:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"resize_spar needs outer_d_mm, got parameters {sorted(p)}",
            parameter="outer_d_mm", requested=None,
        )
    outer = _as_float(p.get("outer_d_mm", p.get("outer_diameter_mm")), "outer_d_mm")
    raw_inner = p.get("inner_d_mm", p.get("inner_diameter_mm"))

    floor_od = float(spar_policy["min_outer_diameter_mm"])
    if outer < floor_od:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"requested spar outer diameter {outer:g} mm is below the declared minimum of "
            f"{floor_od:g} mm (limit spar.min_outer_diameter_mm, source: demo fixture)",
            limit="spar.min_outer_diameter_mm", limit_value=floor_od,
            requested=outer, unit="mm", source="demo fixture",
        )

    # The one real constraint: the confirmed wing3 rib hole.
    ceiling = spar_hole_limit_mm(manifest, policy)
    variant_source = spar_policy["outer_diameter_ceiling"]["source"]
    if outer > ceiling + 1e-9:
        selected = _confirmed_variant(manifest, spar_policy["outer_diameter_ceiling"])
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"requested spar outer diameter {outer:g} mm exceeds the {ceiling:g} mm rib hole "
            f"of the confirmed wing3 variant {selected!r} (limit "
            f"spar.outer_diameter_ceiling, source: {variant_source})",
            limit="spar.outer_diameter_ceiling", limit_value=ceiling,
            requested=outer, unit="mm", source=variant_source, selected_variant=selected,
        )

    current_wall_mm = (params.spar.outer_diameter_m - params.spar.inner_diameter_m) * 1000.0 / 2.0
    inner = (outer - 2 * current_wall_mm) if raw_inner is None else _as_float(raw_inner, "inner_d_mm")
    wall = (outer - inner) / 2.0
    floor_wall = float(spar_policy["wall_thickness_floor_mm"])
    if inner < 0:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"spar inner diameter would be {inner:g} mm: a tube cannot have a negative bore",
            limit="spar.inner_diameter_mm", limit_value=0.0, requested=inner, unit="mm",
        )
    if wall < floor_wall - 1e-9:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"spar wall would be {wall:g} mm (OD {outer:g} mm, ID {inner:g} mm), below the "
            f"declared floor of {floor_wall:g} mm (limit spar.wall_thickness_floor_mm, "
            f"source: {spar_policy['wall_thickness_floor_source']})",
            limit="spar.wall_thickness_floor_mm", limit_value=floor_wall,
            requested=wall, unit="mm", source=spar_policy["wall_thickness_floor_source"],
        )


def _confirmed_variant(manifest: Any, ceiling: dict[str, Any]) -> Optional[str]:
    for group in getattr(manifest, "variants", None) or []:
        gid = group.group_id if hasattr(group, "group_id") else group.get("group_id")
        if gid == ceiling["variant_group"]:
            selected = group.selected if hasattr(group, "selected") else group.get("selected")
            return Path(str(selected)).stem if selected else None
    return None


def _check_tip_extension(request: CadEditRequest, policy: dict[str, Any]) -> None:
    bounds = policy["wing_tip_extension"]
    raw = request.parameters.get("extension_m")
    if raw is None:
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"set_wing_tip_extension needs extension_m in metres, got parameters "
            f"{sorted(request.parameters)}",
            parameter="extension_m", requested=None,
        )
    extension = _as_float(raw, "extension_m")
    lo, hi = float(bounds["min_m"]), float(bounds["max_m"])
    if not (lo - 1e-12 <= extension <= hi + 1e-12):
        raise EditBlocked.of(
            ErrorCode.CONSTRAINT_FAILED,
            f"requested tip extension {extension:g} m is outside the declared range "
            f"[{lo:g}, {hi:g}] m (limit wing_tip_extension.min_m/max_m, "
            f"source: {bounds['source']})",
            limit="wing_tip_extension", limit_value=[lo, hi],
            requested=extension, unit="m", source=bounds["source"],
        )
