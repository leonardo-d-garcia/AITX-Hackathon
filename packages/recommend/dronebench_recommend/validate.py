"""Validation of a candidate before it is allowed to become a preview (section 7, step 4).

"Validate schema, target IDs, base revision, locks, bounds, units, evidence and solver
availability." Every clause has a function below, and they run in that order so the cheapest
rejection happens first.

This is the gate a provider-authored candidate passes through unchanged. Section 4: "schema-validate
LLM output; edits allowlisted". A model cannot reach the CAD kernel except through here.
"""

from __future__ import annotations

from dataclasses import dataclass

from dronebench_contracts import (
    CatalogSnapshot,
    DroneBenchError,
    EditOperation,
    FidelityTier,
    GeometryFeatures,
    Mission,
    PartsDocument,
    ReplaceCatalogComponent,
    ResizeSpar,
    SetWingTipExtension,
    TranslateComponent,
)

#: Bounds on what a single bounded operation may do. Looser than physics, tight enough that an
#: absurd value is rejected before a kernel ever sees it.
MAX_TRANSLATE_M = 1.0
MAX_SPAR_OUTER_M = 0.060
MIN_SPAR_WALL_M = 0.0005
MAX_TIP_EXTENSION_M = 0.30


@dataclass(frozen=True)
class ValidationOutcome:
    ok: bool
    reasons: tuple[str, ...] = ()

    def raise_if_bad(self, *, revision_id: str) -> None:
        if not self.ok:
            raise DroneBenchError.of(
                "UNSUPPORTED_EDIT",
                "the proposed edit did not validate: " + "; ".join(self.reasons),
                revision_id=revision_id,
                reasons=list(self.reasons),
            )


def validate_operation(
    operation: EditOperation,
    *,
    parts: PartsDocument,
    features: GeometryFeatures,
    mission: Mission,
    base_revision_id: str,
    catalog: CatalogSnapshot | None = None,
    available_tiers: list[FidelityTier] | None = None,
    required_tier: FidelityTier = "analytic",
) -> ValidationOutcome:
    """Run every clause. Returns all failures at once so the UI can show a complete reason."""
    reasons: list[str] = []

    # -- base revision ---------------------------------------------------------------------
    if parts.revision_id != base_revision_id:
        reasons.append(
            f"the parts document is revision {parts.revision_id}, not the stated base "
            f"{base_revision_id}"
        )
    if features.revision_id != base_revision_id:
        reasons.append(
            f"geometry features are revision {features.revision_id}, not the stated base "
            f"{base_revision_id}"
        )

    # -- units and frame confirmation -------------------------------------------------------
    if not features.units_confirmed:
        reasons.append("units have not been confirmed; no edit is proposable yet")
    if not features.frame_confirmed:
        reasons.append("the frame has not been confirmed; no edit is proposable yet")
    if not features.reconstruction_confirmed:
        reasons.append(
            "the reconstruction has not been confirmed, so engineering comparison is blocked"
        )

    # -- target ids -------------------------------------------------------------------------
    targets = list(operation.owned_part_ids)
    known = {occurrence.part_id for occurrence in parts.occurrences}
    for part_id in targets:
        if part_id not in known:
            reasons.append(f"{part_id} is not an occurrence in this revision")
    if reasons:
        return ValidationOutcome(False, tuple(reasons))

    target = parts.by_id(operation.target_part_id)

    # -- locks --------------------------------------------------------------------------------
    for part_id in targets:
        occurrence = parts.by_id(part_id)
        if occurrence.locked or part_id in mission.locked_part_ids:
            reasons.append(f"{part_id} is locked by the mission and cannot be edited")

    # -- capability ---------------------------------------------------------------------------
    if operation.operation not in target.edit_capabilities:
        reasons.append(
            f"{target.part_id} does not declare the {operation.operation} capability "
            f"(it declares: {', '.join(target.edit_capabilities) or 'none'})"
        )

    # -- per-operation bounds, units, and evidence ---------------------------------------------
    reasons += _operation_specific(
        operation, parts=parts, features=features, target=target, catalog=catalog
    )

    # -- solver availability --------------------------------------------------------------------
    if available_tiers is not None and required_tier not in available_tiers:
        reasons.append(
            f"the {required_tier} fidelity tier is not available on this installation "
            f"(available: {', '.join(available_tiers) or 'none'})"
        )

    return ValidationOutcome(not reasons, tuple(reasons))


def _operation_specific(
    operation: EditOperation,
    *,
    parts: PartsDocument,
    features: GeometryFeatures,
    target,
    catalog: CatalogSnapshot | None,
) -> list[str]:
    reasons: list[str] = []

    if isinstance(operation, TranslateComponent):
        corridor = target.travel_corridor
        if corridor is None:
            reasons.append(f"{target.part_id} has no declared travel corridor")
            return reasons
        if corridor.axis != operation.axis:
            reasons.append(
                f"the corridor runs along {corridor.axis}, not {operation.axis}"
            )
        if abs(operation.delta_m) > MAX_TRANSLATE_M:
            reasons.append(f"a {operation.delta_m:+.3f} m move exceeds the {MAX_TRANSLATE_M} m bound")
        axis_index = {"x": 0, "y": 1, "z": 2}[operation.axis]
        destination = target.transform.translation[axis_index] + operation.delta_m
        if not corridor.contains(destination):
            reasons.append(
                f"the destination {destination:+.3f} m is outside the corridor "
                f"[{corridor.min_m:+.3f}, {corridor.max_m:+.3f}] m"
            )
        if not corridor.harness_allowance_m.is_known:
            reasons.append("the harness allowance is unknown, so the move is not verifiable")
        else:
            allowance = corridor.harness_allowance_m.require("harness allowance")
            if abs(operation.delta_m) > allowance:
                reasons.append(
                    f"the {abs(operation.delta_m) * 1000:.0f} mm move exceeds the "
                    f"{allowance * 1000:.0f} mm harness allowance"
                )
        if not target.mass_kg.is_known:
            reasons.append(
                f"{target.part_id} has no established mass, so the effect of moving it on the "
                "centre of gravity cannot be computed"
            )

    elif isinstance(operation, ResizeSpar):
        definition = parts.definition(target.definition_id)
        if definition.claims.number("density_kgm3") is None:
            reasons.append("the spar material density is not declared")
        if definition.claims.number("allowable_stress_pa") is None:
            reasons.append("the spar allowable stress is not declared")
        if operation.outer_diameter_m > MAX_SPAR_OUTER_M:
            reasons.append(
                f"{operation.outer_diameter_m * 1000:.0f} mm outer diameter exceeds the "
                f"{MAX_SPAR_OUTER_M * 1000:.0f} mm bound"
            )
        if operation.wall_thickness_m < MIN_SPAR_WALL_M:
            reasons.append(
                f"a {operation.wall_thickness_m * 1000:.2f} mm wall is below the "
                f"{MIN_SPAR_WALL_M * 1000:.2f} mm minimum"
            )
        # The mounts that carry the spar must be regenerated in the same transaction, or the
        # committed assembly would contain a tube its own mounts cannot accept.
        dependent = {
            o.part_id
            for o in parts.occurrences
            if o.role == "mount" and target.part_id in o.allowed_contact_part_ids
        }
        missing = dependent - set(operation.regenerate_mount_part_ids)
        if missing:
            reasons.append(
                "these mounts bear on the spar and must be regenerated in the same transaction: "
                + ", ".join(sorted(missing))
            )

    elif isinstance(operation, SetWingTipExtension):
        if abs(operation.extension_m) > MAX_TIP_EXTENSION_M:
            reasons.append(
                f"a {operation.extension_m * 1000:.0f} mm extension exceeds the "
                f"{MAX_TIP_EXTENSION_M * 1000:.0f} mm bound"
            )
        paired = parts.by_id(operation.paired_part_id)
        if paired.mirror_of != target.part_id and target.mirror_of != paired.part_id:
            reasons.append(
                f"{operation.paired_part_id} is not the mirrored counterpart of {target.part_id}; "
                "a symmetric tip edit must regenerate the pair"
            )
        if "set_wing_tip_extension" not in paired.edit_capabilities:
            reasons.append(f"{paired.part_id} does not declare the tip-extension capability")
        if not features.wing_stations:
            reasons.append("the wing is not parameterised by stations, so the tip is not editable")

    elif isinstance(operation, ReplaceCatalogComponent):
        if catalog is None:
            reasons.append("no catalog snapshot is loaded, so a replacement cannot be resolved")
            return reasons
        try:
            item = catalog.item(operation.catalog_item_id)
        except KeyError:
            reasons.append(f"{operation.catalog_item_id} is not in the catalog snapshot")
            return reasons
        if not item.mass_kg.is_known:
            reasons.append(f"{item.catalog_item_id} has no mass; a swap cannot be evaluated")
        if not item.evidence_ids:
            reasons.append(f"{item.catalog_item_id} carries no evidence record")
        envelope = item.interface_of("mass_envelope")
        if envelope is None:
            reasons.append(f"{item.catalog_item_id} declares no envelope, so fit is unresolved")
        elif target.bounds_local_m is not None:
            length, width, height = target.bounds_local_m.size_m
            slack = 0.005
            limits = envelope.dimensions_m
            for name, installed, limit_key in (
                ("length", length, "length_max"),
                ("width", width, "width_max"),
                ("height", height, "height_max"),
            ):
                limit = limits.get(limit_key)
                if limit is None:
                    reasons.append(f"{item.catalog_item_id} does not declare {limit_key}")
                elif limit > installed + slack:
                    reasons.append(
                        f"{item.catalog_item_id} {name} {limit * 1000:.0f} mm exceeds the "
                        f"{(installed + slack) * 1000:.0f} mm bay"
                    )

    return reasons
