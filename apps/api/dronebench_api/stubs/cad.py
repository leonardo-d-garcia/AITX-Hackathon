"""Reference CAD port (architecture sections 6 and 7), owned by Team A.

**This is Team B's stub.** Team A owns ``packages/cad`` and the CadQuery/OCP kernel. B cannot wait
for it: section 7 gives B the recommendation and approval workflow, and that workflow is defined by
what happens around a CAD call. So this module implements :class:`dronebench_contracts.CadPort`
against the parametric fixture - placements, tube parameters, and envelope swaps - and stamps every
result ``produced_by="B-stub"``.

What it genuinely does, so the workflow around it is exercised for real:

* applies the four typed operations to the parts document and geometry features,
* computes before/after part signatures and verifies that unchanged parts kept theirs,
* re-runs the bounding-box interference screen and fails the edit on unintended overlap,
* reports the mass delta.

What it honestly does not do, and says so in ``diagnostics``: no B-rep kernel, no STEP, no GLB, no
solid volume, no real round trip. :attr:`RoundTripCheck.performed` stays ``False``, which makes
``downloadable`` ``False``, so no export can be presented as verified while this stub is in place.
"""

from __future__ import annotations

import math
from pathlib import Path

from dronebench_contracts import (
    CadEditResult,
    Claim,
    EditOperation,
    GeometryFeatures,
    InterferenceFinding,
    PartOccurrence,
    PartsDocument,
    PartSignature,
    ReplaceCatalogComponent,
    ResizeSpar,
    RoundTripCheck,
    SetWingTipExtension,
    TranslateComponent,
    Transform,
    compute_revision_id,
)
from dronebench_contracts.catalog import CatalogSnapshot

INTERFERENCE_TOL_M = 5e-4

_NO_KERNEL = (
    "B-stub CAD port: placements and parameters are applied to the parametric fixture, but no "
    "B-rep kernel ran. There is no STEP, no GLB, no solid volume, and no export round trip. "
    "Team A's packages/cad replaces this."
)


class ParametricCadPort:
    """Implements :class:`dronebench_contracts.CadPort` for the parametric fixture."""

    owner = "B-stub"

    def __init__(self, catalog: CatalogSnapshot | None = None) -> None:
        self.catalog = catalog

    # -- pure transformation -------------------------------------------------------------------

    def edited_parts(
        self,
        *,
        parts: PartsDocument,
        features: GeometryFeatures,
        operation: EditOperation,
    ) -> tuple[PartsDocument, GeometryFeatures]:
        """Apply the operation. Pure: the inputs are not mutated."""
        occurrences = [o.model_copy(deep=True) for o in parts.occurrences]
        definitions = [d.model_copy(deep=True) for d in parts.definitions]
        by_id = {o.part_id: i for i, o in enumerate(occurrences)}
        new_features = features.model_copy(deep=True)

        if isinstance(operation, TranslateComponent):
            index = by_id[operation.target_part_id]
            target = occurrences[index]
            axis = {"x": 0, "y": 1, "z": 2}[operation.axis]
            translation = list(target.transform.translation)
            translation[axis] += operation.delta_m
            occurrences[index] = target.model_copy(
                update={"transform": target.transform.with_translation(tuple(translation))}
            )

        elif isinstance(operation, ResizeSpar):
            spar = occurrences[by_id[operation.target_part_id]]
            definition_index = next(
                i for i, d in enumerate(definitions) if d.definition_id == spar.definition_id
            )
            definition = definitions[definition_index]
            parameters = dict(definition.parameters)
            parameters["outer_diameter_m"] = operation.outer_diameter_m
            parameters["inner_diameter_m"] = operation.inner_diameter_m
            definitions[definition_index] = definition.model_copy(
                update={"parameters": parameters}
            )

            density = definition.claims.number("density_kgm3")
            length = parameters.get("length_m")
            if density is not None and length is not None:
                volume = (
                    math.pi
                    * (operation.outer_diameter_m**2 - operation.inner_diameter_m**2)
                    / 4.0
                    * length
                )
                occurrences[by_id[spar.part_id]] = spar.model_copy(
                    update={
                        "mass_kg": Claim.computed(
                            volume * density,
                            "kg",
                            assumptions=["tube volume times the declared density"],
                            evidence_ids=list(spar.mass_kg.evidence_ids),
                        ),
                        "bounds_local_m": _tube_bounds(
                            operation.outer_diameter_m, length
                        ),
                    }
                )

            # The mounts in the same transaction grow their bore to match.
            for mount_id in operation.regenerate_mount_part_ids:
                mount = occurrences[by_id[mount_id]]
                mount_definition_index = next(
                    i for i, d in enumerate(definitions) if d.definition_id == mount.definition_id
                )
                mount_definition = definitions[mount_definition_index]
                mount_parameters = dict(mount_definition.parameters)
                mount_parameters["bore_m"] = operation.outer_diameter_m
                definitions[mount_definition_index] = mount_definition.model_copy(
                    update={"parameters": mount_parameters}
                )

        elif isinstance(operation, SetWingTipExtension):
            for part_id in (operation.target_part_id, operation.paired_part_id):
                panel = occurrences[by_id[part_id]]
                definition_index = next(
                    i for i, d in enumerate(definitions) if d.definition_id == panel.definition_id
                )
                definition = definitions[definition_index]
                parameters = dict(definition.parameters)
                parameters["tip_extension_m"] = (
                    parameters.get("tip_extension_m", 0.0) + operation.extension_m
                )
                parameters["semi_span_m"] = (
                    parameters.get("semi_span_m", 0.0) + operation.extension_m
                )
                definitions[definition_index] = definition.model_copy(
                    update={"parameters": parameters}
                )

            new_features = _extend_span(new_features, operation.extension_m)

        elif isinstance(operation, ReplaceCatalogComponent):
            if self.catalog is None:
                raise ValueError("a catalog snapshot is required to resolve a replacement")
            item = self.catalog.item(operation.catalog_item_id)
            target = occurrences[by_id[operation.target_part_id]]
            envelope = item.interface_of("mass_envelope")
            update: dict = {
                "mass_kg": item.mass_kg.model_copy(),
                "claims": target.claims.model_copy(
                    update={"claims": {**target.claims.claims, **item.claims}}
                ),
            }
            if envelope is not None:
                dimensions = envelope.dimensions_m
                update["bounds_local_m"] = _centered_box(
                    dimensions.get("length_max", 0.0),
                    dimensions.get("width_max", 0.0),
                    dimensions.get("height_max", 0.0),
                )
            occurrences[by_id[target.part_id]] = target.model_copy(update=update)

        else:  # pragma: no cover - the union is closed
            raise ValueError(f"unsupported operation {operation!r}")

        preview_revision_id, _ = compute_revision_id(
            design_id="preview",
            parent_revision_id=parts.revision_id,
            payload={
                "operation": operation.model_dump(mode="json"),
                "occurrences": [o.model_dump(mode="json") for o in occurrences],
                "definitions": [d.model_dump(mode="json") for d in definitions],
            },
        )

        edited_parts = PartsDocument(
            revision_id=preview_revision_id,
            definitions=definitions,
            occurrences=occurrences,
            evidence=parts.evidence,
        )
        edited_features = new_features.model_copy(update={"revision_id": preview_revision_id})
        return edited_parts, edited_features

    # -- the port surface -----------------------------------------------------------------------

    def apply_edit(
        self,
        *,
        base_revision_id: str,
        parts: PartsDocument,
        features: GeometryFeatures,
        operation: EditOperation,
        work_dir: str,
    ) -> CadEditResult:
        """Apply, verify, and report. Writes nothing outside ``work_dir``."""
        Path(work_dir).mkdir(parents=True, exist_ok=True)

        before = {o.part_id: _signature(o) for o in parts.occurrences}

        try:
            edited, _ = self.edited_parts(parts=parts, features=features, operation=operation)
        except Exception as exc:
            return CadEditResult(
                ok=False,
                base_revision_id=base_revision_id,
                operation=operation.operation,
                diagnostics=[f"the operation could not be applied: {exc}", _NO_KERNEL],
                produced_by="B-stub",
            )

        after = {o.part_id: _signature(o) for o in edited.occurrences}
        owned = set(operation.owned_part_ids)

        # Anything outside the operation's own parts must be bit-for-bit unchanged within
        # tolerance. Section 6 calls this the unchanged-part signature check.
        drifted = [
            part_id
            for part_id, signature in after.items()
            if part_id not in owned and not signature.matches(before[part_id])
        ]
        if drifted:
            return CadEditResult(
                ok=False,
                base_revision_id=base_revision_id,
                operation=operation.operation,
                part_signatures_before=list(before.values()),
                part_signatures_after=list(after.values()),
                diagnostics=[
                    "parts outside the operation changed: " + ", ".join(sorted(drifted)),
                    _NO_KERNEL,
                ],
                produced_by="B-stub",
            )

        interference = _interference(edited)
        if interference:
            return CadEditResult(
                ok=False,
                base_revision_id=base_revision_id,
                operation=operation.operation,
                part_signatures_before=list(before.values()),
                part_signatures_after=list(after.values()),
                diagnostics=[
                    "the edited assembly has unintended interference: "
                    + "; ".join(
                        f"{f.part_id_a}/{f.part_id_b}" for f in interference
                    ),
                    _NO_KERNEL,
                ],
                produced_by="B-stub",
            )

        affected = sorted(
            {
                part_id
                for part_id, signature in after.items()
                if not signature.matches(before[part_id])
            }
            | owned
        )

        mass_before = _total_mass(parts)
        mass_after = _total_mass(edited)
        mass_delta = (
            Claim.computed(
                mass_after - mass_before,
                "kg",
                assumptions=["difference of installed occurrence masses"],
            )
            if mass_before is not None and mass_after is not None
            else None
        )

        return CadEditResult(
            ok=True,
            base_revision_id=base_revision_id,
            preview_revision_id=edited.revision_id,
            operation=operation.operation,
            affected_part_ids=affected,
            part_signatures_before=list(before.values()),
            part_signatures_after=list(after.values()),
            unchanged_parts_verified=True,
            requested_parameters_applied=_applied_parameters(operation),
            interference=[],
            round_trip=RoundTripCheck(
                performed=False,
                notes=[
                    "no STEP round trip: this stub has no B-rep kernel, so the edit is not "
                    "downloadable as verified geometry"
                ],
            ),
            representation="editable_reconstruction",
            mass_delta_kg=mass_delta,
            diagnostics=[_NO_KERNEL],
            produced_by="B-stub",
        )

    def export_step(
        self, *, revision_id: str, parts: PartsDocument, work_dir: str
    ) -> CadEditResult:
        """Refuse to export.

        Returning an ``ok`` result with no STEP behind it would let the UI offer a download that
        does not exist. Section 6 requires a successful round trip before a download; this stub
        cannot perform one, so it says so.
        """
        return CadEditResult(
            ok=False,
            base_revision_id=revision_id,
            operation="translate_component",
            round_trip=RoundTripCheck(performed=False),
            diagnostics=[
                "STEP export is not available: Team A's CAD kernel is not installed. No file is "
                "produced rather than an unverified one.",
                _NO_KERNEL,
            ],
            produced_by="B-stub",
        )


# ---------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------


def _signature(occurrence: PartOccurrence) -> PartSignature:
    """A semantic fingerprint. Volume is the bounding box: this stub has no solid model."""
    bounds = occurrence.world_bounds_m()
    volume = None
    if occurrence.bounds_local_m is not None:
        length, width, height = occurrence.bounds_local_m.size_m
        volume = length * width * height
    return PartSignature(
        part_id=occurrence.part_id,
        volume_m3=volume,
        bounds_min_m=bounds.min_m if bounds else None,
        bounds_max_m=bounds.max_m if bounds else None,
        solid_count=1 if occurrence.bounds_local_m is not None else 0,
        placement_translation_m=occurrence.transform.translation,
    )


def _interference(parts: PartsDocument) -> list[InterferenceFinding]:
    placed = [(o, o.world_bounds_m()) for o in parts.occurrences]
    findings: list[InterferenceFinding] = []
    for index, (a, box_a) in enumerate(placed):
        if box_a is None:
            continue
        for b, box_b in placed[index + 1 :]:
            if box_b is None:
                continue
            if b.part_id in a.allowed_contact_part_ids or a.part_id in b.allowed_contact_part_ids:
                continue
            overlap = min(
                min(box_a.max_m[k], box_b.max_m[k]) - max(box_a.min_m[k], box_b.min_m[k])
                for k in range(3)
            )
            if overlap > INTERFERENCE_TOL_M:
                findings.append(
                    InterferenceFinding(
                        part_id_a=a.part_id,
                        part_id_b=b.part_id,
                        kind=(
                            "propeller_swept_volume"
                            if "propeller" in (a.role, b.role)
                            else "unintended_overlap"
                        ),
                    )
                )
    return findings


def _total_mass(parts: PartsDocument) -> float | None:
    total = 0.0
    for occurrence in parts.occurrences:
        mass = occurrence.mass_kg.number()
        if mass is None:
            return None
        total += mass
    return total


def _applied_parameters(operation: EditOperation) -> dict[str, float]:
    if isinstance(operation, TranslateComponent):
        return {f"translation_{operation.axis}_delta_m": operation.delta_m}
    if isinstance(operation, ResizeSpar):
        return {
            "outer_diameter_m": operation.outer_diameter_m,
            "inner_diameter_m": operation.inner_diameter_m,
        }
    if isinstance(operation, SetWingTipExtension):
        return {"tip_extension_m": operation.extension_m}
    return {}


def _tube_bounds(outer_diameter_m: float, length_m: float):
    from dronebench_contracts import AxisAlignedBox

    radius = outer_diameter_m / 2.0
    return AxisAlignedBox(
        min_m=(-radius, -length_m / 2.0, -radius),
        max_m=(radius, length_m / 2.0, radius),
    )


def _centered_box(length_m: float, width_m: float, height_m: float):
    from dronebench_contracts import AxisAlignedBox

    return AxisAlignedBox(
        min_m=(-length_m / 2.0, -width_m / 2.0, -height_m / 2.0),
        max_m=(length_m / 2.0, width_m / 2.0, height_m / 2.0),
    )


def _extend_span(features: GeometryFeatures, extension_m: float) -> GeometryFeatures:
    """Grow span, reference area, and the outermost station by a straight tip extension."""
    span = features.wing_span_m.number()
    area = features.wing_reference_area_m2.number()
    if span is None or area is None or not features.wing_stations:
        return features

    tip = max(features.wing_stations, key=lambda station: station.span_y_m)
    new_span = span + 2 * extension_m
    # A straight extension at the tip chord adds a rectangular strip on each side.
    new_area = area + 2 * extension_m * tip.chord_m

    stations = [s.model_copy(deep=True) for s in features.wing_stations]
    stations.append(
        tip.model_copy(update={"span_y_m": tip.span_y_m + extension_m})
    )
    stations.sort(key=lambda station: station.span_y_m)

    return features.model_copy(
        update={
            "wing_span_m": Claim.computed(
                new_span,
                "m",
                assumptions=["baseline span plus a straight tip extension on each side"],
                evidence_ids=list(features.wing_span_m.evidence_ids),
            ),
            "wing_reference_area_m2": Claim.computed(
                new_area,
                "m^2",
                assumptions=["baseline area plus a rectangular strip at the tip chord per side"],
                evidence_ids=list(features.wing_reference_area_m2.evidence_ids),
            ),
            "wing_stations": stations,
            "quality_limits": list(features.quality_limits)
            + [
                "span was extended by a parametric edit; the aerodynamic geometry is invalidated "
                "and both baseline and candidate must be re-solved at one fidelity"
            ],
        }
    )
