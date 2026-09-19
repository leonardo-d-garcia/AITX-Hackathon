"""Parts, placements, and the A -> B/C boundary artifacts (architecture sections 5 and 6).

``design_manifest.json`` and ``parts.json`` are produced by Team A and consumed by B and C. B
models them here so that the contract has one owner, and so that B can run against a frozen
synthetic fixture while A's importer is still being built.

Two invariants from section 5 are enforced structurally rather than by convention:

* A placement datum is not a centre of mass. ``local_com_m`` is a separate, separately-sourced
  field, and aircraft COM is ``R @ local_com_m + translation``.
* A mirrored occurrence is a distinct ``part_id`` with an explicit ``mirror_of``. Mirroring source
  geometry is a reconstruction operation, not a rigid rotation, so a placement transform must have
  determinant +1.
"""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .claims import Claim, ClaimSet, Evidence

Representation = Literal[
    "reference_mesh",           # original supplied mesh, byte-identical, no topology editing
    "editable_reconstruction",  # deliberately authored parametric surrogate
    "catalog_envelope",         # bought component represented by its envelope only
    "generated",                # produced by an edit operation from a parameter set
]

PartRole = Literal[
    "wing", "tail_panel", "fuselage", "spar", "battery", "motor", "propeller", "esc",
    "servo", "flight_controller", "receiver", "gps", "payload", "mount", "fastener",
    "harness", "hatch", "landing_gear", "other", "unknown",
]

EditCapability = Literal[
    "translate_component",
    "resize_spar",
    "set_wing_tip_extension",
    "replace_catalog_component",
]


class Transform(BaseModel):
    """``T_parent_from_local``: row-major 4x4 homogeneous, applied to column vectors.

    Translation in metres. A rigid rotation has determinant +1; reflections are rejected here so
    that a mirror cannot be smuggled in as a placement.
    """

    model_config = ConfigDict(extra="forbid")

    matrix: list[list[float]] = Field(
        default_factory=lambda: [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )

    @model_validator(mode="after")
    def _rigid(self) -> Self:
        rows = self.matrix
        if len(rows) != 4 or any(len(row) != 4 for row in rows):
            raise ValueError("transform must be 4x4")
        for row in rows:
            for value in row:
                if not math.isfinite(value):
                    raise ValueError("transform contains a non-finite entry")
        if rows[3] != [0.0, 0.0, 0.0, 1.0]:
            raise ValueError("bottom row of a homogeneous placement must be [0,0,0,1]")

        det = _det3([row[:3] for row in rows[:3]])
        if not math.isclose(det, 1.0, abs_tol=1e-6):
            raise ValueError(
                f"rotation determinant is {det:.6f}, not +1; a reflection is not a placement. "
                "Mirror the source geometry as a reconstruction operation instead."
            )
        return self

    @property
    def translation(self) -> tuple[float, float, float]:
        return (self.matrix[0][3], self.matrix[1][3], self.matrix[2][3])

    def with_translation(self, xyz: tuple[float, float, float]) -> "Transform":
        rows = [list(row) for row in self.matrix]
        rows[0][3], rows[1][3], rows[2][3] = xyz
        return Transform(matrix=rows)

    def apply(self, point: tuple[float, float, float]) -> tuple[float, float, float]:
        rows = self.matrix
        return tuple(  # type: ignore[return-value]
            rows[i][0] * point[0] + rows[i][1] * point[1] + rows[i][2] * point[2] + rows[i][3]
            for i in range(3)
        )

    @classmethod
    def translating(cls, xyz: tuple[float, float, float]) -> "Transform":
        return cls().with_translation(xyz)


def _det3(m: list[list[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


class AxisAlignedBox(BaseModel):
    """Bounds in canonical FRD metres."""

    model_config = ConfigDict(extra="forbid")

    min_m: tuple[float, float, float]
    max_m: tuple[float, float, float]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        for lo, hi in zip(self.min_m, self.max_m):
            if hi < lo:
                raise ValueError("box max precedes min")
        return self

    @property
    def size_m(self) -> tuple[float, float, float]:
        return tuple(hi - lo for lo, hi in zip(self.min_m, self.max_m))  # type: ignore[return-value]

    @property
    def center_m(self) -> tuple[float, float, float]:
        return tuple((hi + lo) / 2 for lo, hi in zip(self.min_m, self.max_m))  # type: ignore[return-value]

    def intersects(self, other: "AxisAlignedBox", *, tol_m: float = 0.0) -> bool:
        return all(
            self.min_m[i] - tol_m <= other.max_m[i] and other.min_m[i] - tol_m <= self.max_m[i]
            for i in range(3)
        )


class TravelCorridor(BaseModel):
    """The modelled envelope inside which a movable component may be repositioned.

    Architecture section 6 makes this a precondition of ``translate_component``: the corridor,
    harness allowance, and mount positions must be known before a move is proposable.
    """

    model_config = ConfigDict(extra="forbid")

    axis: Literal["x", "y", "z"]
    min_m: float
    max_m: float
    harness_allowance_m: Claim
    mount_positions_m: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.max_m < self.min_m:
            raise ValueError("corridor max precedes min")
        return self

    def contains(self, value: float) -> bool:
        return self.min_m <= value <= self.max_m


class SourceRef(BaseModel):
    """Where an occurrence's geometry came from, preserved so identity survives re-import."""

    model_config = ConfigDict(extra="forbid")

    original_filename: str | None = None
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    body_path: str | None = Field(
        default=None, description="Body or occurrence path inside the source assembly."
    )
    variant_decision: str | None = Field(
        default=None,
        description="Which alternative was selected, when the source offered several.",
    )


class PartDefinition(BaseModel):
    """Reusable geometry. Several occurrences may share one definition."""

    model_config = ConfigDict(extra="forbid")

    definition_id: str = Field(pattern=r"^def_[a-z0-9][a-z0-9_.-]{1,62}$")
    name: str
    representation: Representation
    role: PartRole = "unknown"
    source: SourceRef = Field(default_factory=SourceRef)
    parameters: dict[str, float] = Field(
        default_factory=dict,
        description="Editable parameters in canonical SI, for reconstructed/generated geometry.",
    )
    claims: ClaimSet = Field(default_factory=ClaimSet)


class PartOccurrence(BaseModel):
    """One installed instance of a definition, at a placement, with its own claims."""

    model_config = ConfigDict(extra="forbid")

    part_id: str = Field(pattern=r"^prt_[a-z0-9][a-z0-9_.-]{1,62}$")
    definition_id: str = Field(pattern=r"^def_[a-z0-9][a-z0-9_.-]{1,62}$")
    name: str
    role: PartRole = "unknown"
    parent_part_id: str | None = None
    mirror_of: str | None = Field(
        default=None,
        description="The part_id this occurrence mirrors. Distinct identity, possibly shared asset.",
    )
    transform: Transform = Field(default_factory=Transform)
    bounds_local_m: AxisAlignedBox | None = None

    mass_kg: Claim
    local_com_m: tuple[Claim, Claim, Claim] | None = Field(
        default=None,
        description=(
            "Centre of mass in the occurrence's own frame, with its own evidence. Absent means "
            "the mass distribution is unknown, not that it coincides with the placement datum."
        ),
    )

    locked: bool = Field(
        default=False, description="Mission payload or otherwise not removable/movable."
    )
    edit_capabilities: list[EditCapability] = Field(default_factory=list)
    travel_corridor: TravelCorridor | None = None
    allowed_contact_part_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Declared mating/bonded/nesting partners. Overlap with these is intended engagement, "
            "not interference."
        ),
    )

    claims: ClaimSet = Field(default_factory=ClaimSet)

    @model_validator(mode="after")
    def _capability_preconditions(self) -> Self:
        if "translate_component" in self.edit_capabilities:
            if self.locked:
                raise ValueError(f"{self.part_id}: a locked occurrence cannot be translatable")
            if self.travel_corridor is None:
                raise ValueError(
                    f"{self.part_id}: translate_component requires a declared travel corridor"
                )
        if self.mirror_of == self.part_id:
            raise ValueError(f"{self.part_id}: cannot mirror itself")
        return self

    def world_com_m(self) -> tuple[float, float, float] | None:
        """``R @ local_com_m + translation``, or ``None`` when the distribution is unknown."""
        if self.local_com_m is None:
            return None
        local = tuple(claim.number() for claim in self.local_com_m)
        if any(value is None for value in local):
            return None
        return self.transform.apply(local)  # type: ignore[arg-type]

    def world_bounds_m(self) -> AxisAlignedBox | None:
        """Placed bounds, recomputed by transforming the eight local corners."""
        if self.bounds_local_m is None:
            return None
        lo, hi = self.bounds_local_m.min_m, self.bounds_local_m.max_m
        corners = [
            self.transform.apply((x, y, z))
            for x in (lo[0], hi[0])
            for y in (lo[1], hi[1])
            for z in (lo[2], hi[2])
        ]
        return AxisAlignedBox(
            min_m=tuple(min(c[i] for c in corners) for i in range(3)),  # type: ignore[arg-type]
            max_m=tuple(max(c[i] for c in corners) for i in range(3)),  # type: ignore[arg-type]
        )


class WingStation(BaseModel):
    """One spanwise station of the editable parameterisation (architecture section 6)."""

    model_config = ConfigDict(extra="forbid")

    span_y_m: float
    leading_edge_x_m: float
    chord_m: float = Field(gt=0)
    z_m: float = 0.0
    twist_rad: float = 0.0


class VTailPanel(BaseModel):
    """A canted tail panel. This airframe has no conventional horizontal-plus-vertical tail."""

    model_config = ConfigDict(extra="forbid")

    part_id: str
    area_m2: float = Field(gt=0)
    cant_rad: float
    arm_m: float = Field(
        description="Longitudinal distance from the wing quarter-chord to the panel, aft-positive."
    )
    mean_chord_m: float = Field(gt=0)


class GeometryFeatures(BaseModel):
    """``geometry_features.json`` - A -> C/B (architecture section 5).

    The single source of wing/tail dimensions. Section 8 forbids the evaluator from maintaining its
    own copy, so anything downstream that needs a reference area reads it from here.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    revision_id: str
    frame_confirmed: bool = Field(
        description="False until units, axes, nose datum, and symmetry have been confirmed."
    )
    units_confirmed: bool = False
    nose_datum_note: str

    wing_stations: list[WingStation] = Field(default_factory=list)
    wing_reference_area_m2: Claim
    wing_span_m: Claim
    wing_mac_m: Claim
    vtail_panels: list[VTailPanel] = Field(default_factory=list)

    neutral_point_station_m: Claim | None = Field(
        default=None,
        description=(
            "Aft-positive station of the neutral point. Architecture section 8 permits a "
            "documented synthetic fixture to supply this as an assumption for illustrating the "
            "workflow, and requires the report to identify it as assumed. A wing quarter-chord "
            "guess does not qualify for a V-tail aircraft, so the validator below refuses any "
            "source kind other than 'assumed' until a real stability method produces one."
        ),
    )

    fit_error_m: Claim = Field(
        description="Deviation of the reconstruction from the reference silhouette."
    )
    reconstruction_confirmed: bool = Field(
        default=False,
        description="A recorded human decision. Engineering comparison is blocked until true.",
    )
    quality_limits: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _metrics_gated(self) -> Self:
        if self.reconstruction_confirmed and not (self.frame_confirmed and self.units_confirmed):
            raise ValueError(
                "reconstruction cannot be confirmed before units and frame are confirmed"
            )
        neutral_point = self.neutral_point_station_m
        if neutral_point is not None and neutral_point.source_kind not in ("assumed", "computed"):
            raise ValueError(
                "a neutral point may only be recorded as assumed (synthetic fixture) or computed "
                "by a stability method; it is never measured off geometry"
            )
        return self

    def aspect_ratio(self) -> float | None:
        span = self.wing_span_m.number()
        area = self.wing_reference_area_m2.number()
        if span is None or area is None or area <= 0:
            return None
        return span * span / area


class DesignManifest(BaseModel):
    """``design_manifest.json`` - A -> B/C (architecture section 5)."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    design_id: str = Field(pattern=r"^dsn_[a-z0-9][a-z0-9_-]{2,62}$")
    revision_id: str
    display_name: str
    representation_mode: Literal["reference_mesh", "editable_reconstruction"]
    source_archive_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    excluded_alternatives: list[str] = Field(
        default_factory=list,
        description="Variant bodies deliberately not installed. They must not count as mass.",
    )
    notes: list[str] = Field(default_factory=list)


class PartsDocument(BaseModel):
    """``parts.json`` - A -> B/C. Installed occurrences plus their definitions and evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    revision_id: str
    definitions: list[PartDefinition]
    occurrences: list[PartOccurrence]
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        definition_ids = {d.definition_id for d in self.definitions}
        part_ids = {o.part_id for o in self.occurrences}
        if len(definition_ids) != len(self.definitions):
            raise ValueError("duplicate definition_id")
        if len(part_ids) != len(self.occurrences):
            raise ValueError("duplicate part_id")

        evidence_ids = {e.evidence_id for e in self.evidence}
        for occurrence in self.occurrences:
            if occurrence.definition_id not in definition_ids:
                raise ValueError(
                    f"{occurrence.part_id} references unknown definition {occurrence.definition_id}"
                )
            for reference, label in (
                (occurrence.parent_part_id, "parent_part_id"),
                (occurrence.mirror_of, "mirror_of"),
            ):
                if reference is not None and reference not in part_ids:
                    raise ValueError(f"{occurrence.part_id}.{label} -> unknown part {reference}")
            for partner in occurrence.allowed_contact_part_ids:
                if partner not in part_ids:
                    raise ValueError(
                        f"{occurrence.part_id}.allowed_contact_part_ids -> unknown {partner}"
                    )
            for cited in occurrence.mass_kg.evidence_ids:
                if cited not in evidence_ids:
                    raise ValueError(f"{occurrence.part_id}.mass_kg cites unknown {cited}")
        return self

    def by_id(self, part_id: str) -> PartOccurrence:
        for occurrence in self.occurrences:
            if occurrence.part_id == part_id:
                return occurrence
        raise KeyError(part_id)

    def definition(self, definition_id: str) -> PartDefinition:
        for definition in self.definitions:
            if definition.definition_id == definition_id:
                return definition
        raise KeyError(definition_id)

    def evidence_by_id(self, evidence_id: str) -> Evidence:
        for entry in self.evidence:
            if entry.evidence_id == evidence_id:
                return entry
        raise KeyError(evidence_id)

    def with_role(self, role: PartRole) -> list[PartOccurrence]:
        return [o for o in self.occurrences if o.role == role]
