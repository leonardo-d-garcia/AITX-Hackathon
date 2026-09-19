"""Starter wire contract for Team A artifacts (design_manifest, parts, geometry_features, cad_edit_result).

Owned by Team B once merged (see architecture §5, §11). Team A wrote this starter because the
architecture's `contracts/models.py` was not in the handoff; B may rename/extend, but keep
the semantics below:

- Canonical aircraft frame: right-handed FRD. x forward, y right, z down, origin at the
  confirmed nose datum. SI units: m, kg, N, s, A, Wh, rad.
- Unknown values stay null (never 0). Every engineering value is a Claim with its own
  status, source kind, evidence ids and assumptions.
- Transforms: `T_parent_from_local` is a row-major 4x4 homogeneous matrix applied to column
  vectors, translation in metres, rotation with determinant +1. Mirroring is a separate
  reconstruction step on the geometry definition, never a placement.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "0.1.0"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- evidence and claims

class Status(str, Enum):
    known = "known"
    estimated = "estimated"
    unknown = "unknown"
    conflicted = "conflicted"


class SourceKind(str, Enum):
    cad = "cad"
    bom = "bom"
    manual = "manual"
    catalog = "catalog"
    computed = "computed"
    inferred = "inferred"
    assumed = "assumed"
    user = "user"


class Evidence(_Model):
    evidence_id: str
    uri: str                                  # relative artifact path or URL
    sha256: Optional[str] = None
    locator: Optional[str] = None             # page/table/field/body/occurrence path
    method: str                               # e.g. "stl_bounds", "slice_fit", "user_confirmation"
    accessed_at: Optional[str] = None         # ISO 8601; excluded from content hashes
    note: Optional[str] = None


class Claim(_Model):
    value: Any = None                         # null when unknown
    unit: Optional[str] = None
    status: Status = Status.unknown
    source_kind: Optional[SourceKind] = None
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Optional[float] = None        # only when a method provides one; not a probability unless calibrated
    assumptions: list[str] = Field(default_factory=list)

    @classmethod
    def unknown(cls, unit: Optional[str] = None, *assumptions: str) -> "Claim":
        return cls(value=None, unit=unit, status=Status.unknown, assumptions=list(assumptions))


# ---------------------------------------------------------------- errors

class ErrorCode(str, Enum):
    UNITS_UNCONFIRMED = "UNITS_UNCONFIRMED"
    ASSEMBLY_UNCONFIRMED = "ASSEMBLY_UNCONFIRMED"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNSUPPORTED_EDIT = "UNSUPPORTED_EDIT"
    STALE_REVISION = "STALE_REVISION"
    GEOMETRY_INVALID = "GEOMETRY_INVALID"
    CONSTRAINT_FAILED = "CONSTRAINT_FAILED"
    SOLVER_UNAVAILABLE = "SOLVER_UNAVAILABLE"
    SOLVER_TIMEOUT = "SOLVER_TIMEOUT"
    ARTIFACT_MISMATCH = "ARTIFACT_MISMATCH"
    INPUT_REJECTED = "INPUT_REJECTED"


class ErrorEnvelope(_Model):
    code: ErrorCode
    message: str
    revision_id: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


# ---------------------------------------------------------------- artifacts and revisions

Representation = Literal["reference_mesh", "reconstruction", "envelope", "component_export"]


class Artifact(_Model):
    path: str                                 # relative to the revision directory
    sha256: str
    media_type: str
    representation: Optional[Representation] = None
    part_ids: list[str] = Field(default_factory=list)


class RevisionState(str, Enum):
    draft = "draft"
    preview = "preview"
    committed = "committed"


class RevisionManifest(_Model):
    schema_version: str = SCHEMA_VERSION
    design_id: str
    revision_id: str
    parent_revision_id: Optional[str] = None
    state: RevisionState
    content_sha256: str                       # hash of canonical inputs (not timestamps)
    cause: str                                # "import" | "confirm" | "edit:<op>" | ...
    created_at: Optional[str] = None
    artifacts: list[Artifact] = Field(default_factory=list)


# ---------------------------------------------------------------- import / confirmation

class MeshQA(_Model):
    triangles: int
    finite: bool
    watertight: bool
    components: int
    degenerate_faces: int
    consistent_winding: bool
    bounds_native: list[list[float]]          # [[min x,y,z],[max x,y,z]] in native file units


class SourceFile(_Model):
    source_path: str                          # path inside the archive (original filename kept)
    sha256: str
    size_bytes: int
    qa: MeshQA
    folder_hint: Optional[str] = None         # e.g. "High Temp PETG or ABS or ASA" (evidence, not proof)


class VariantGroup(_Model):
    group_id: str                             # e.g. "wing3"
    options: list[str]                        # source paths
    selected: Optional[str] = None            # None until confirmed
    reason: Optional[str] = None


class FrameConfirmation(_Model):
    units: Literal["mm", "m", "in"]
    native_to_frd: list[list[float]]          # 3x3 proper rotation (det +1) applied after scaling
    scale_to_m: float
    nose_datum_native: list[float]            # native coords of canonical origin
    mirror_plane_native: Optional[str] = None  # e.g. "x=0": parts on one side get mirrored instances
    confirmed: bool = False
    confirmed_by: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class EditCapability(str, Enum):
    none = "none"                             # reference mesh only
    translate = "translate_component"
    resize_spar = "resize_spar"
    wing_tip_extension = "set_wing_tip_extension"
    replace_catalog = "replace_catalog_component"


class PartOccurrence(_Model):
    part_id: str                              # stable installed-occurrence id
    definition_id: str                        # reusable geometry id
    name: str
    category: str                             # wing | aileron | fuselage | canopy | hatch | vtail | ruddervator | mount | spar | battery | motor | prop | servo | esc | fc | rx | gps | payload | other
    side: Optional[Literal["left", "right", "center"]] = None
    mirror_of: Optional[str] = None
    representation: Representation
    source: Optional[str] = None              # source_path for reference meshes
    T_parent_from_local: list[list[float]]    # 4x4
    mass_kg: Claim = Field(default_factory=lambda: Claim.unknown("kg"))
    local_com_m: Claim = Field(default_factory=lambda: Claim.unknown("m"))
    material: Claim = Field(default_factory=Claim.unknown)
    function: Claim = Field(default_factory=Claim.unknown)
    edit_capabilities: list[EditCapability] = Field(default_factory=lambda: [EditCapability.none])
    allowed_overlap_with: list[str] = Field(default_factory=list)  # declared mating/nesting pairs
    locked: bool = False
    labels: dict[str, str] = Field(default_factory=dict)


class DesignManifest(_Model):
    schema_version: str = SCHEMA_VERSION
    design_id: str
    revision_id: str
    title: str
    frame: FrameConfirmation
    sources: list[SourceFile] = Field(default_factory=list)
    variants: list[VariantGroup] = Field(default_factory=list)
    excluded_sources: list[str] = Field(default_factory=list)
    parts: list[PartOccurrence] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- geometry features (A -> C/B)

class WingStation(_Model):
    span_y_m: float                           # FRD y (right positive)
    leading_edge_x_m: float                   # FRD x (forward positive)
    chord_m: float
    z_m: float                                # FRD z (down positive)
    twist_rad: float = 0.0
    thickness_ratio: Optional[float] = None


class LiftingSurface(_Model):
    surface_id: str                           # "wing" | "vtail_left" | "vtail_right"
    part_ids: list[str]
    stations: list[WingStation]               # one side for symmetric surfaces, root -> tip
    symmetric: bool = True
    cant_rad: Optional[float] = None          # V-tail panel angle above horizontal
    span_m: Claim                             # tip-to-tip (or panel length for a single V-tail panel)
    area_m2: Claim                            # projected planform area, counted once
    mac_m: Claim
    x_mac_le_m: Claim
    aspect_ratio: Claim
    sweep_le_rad: Claim
    dihedral_rad: Claim
    airfoil: Claim                            # e.g. "NACA 4412 (assumed)"; tentative only
    control_surfaces: list[str] = Field(default_factory=list)
    fit_rms_m: Optional[float] = None


class FuselageStation(_Model):
    x_m: float
    width_m: float
    height_m: float
    z_center_m: float


class GeometryFeatures(_Model):
    schema_version: str = SCHEMA_VERSION
    design_id: str
    revision_id: str
    frame: Literal["FRD"] = "FRD"
    reference_area_m2: Claim
    reference_span_m: Claim
    reference_chord_m: Claim
    surfaces: list[LiftingSurface]
    fuselage: list[FuselageStation] = Field(default_factory=list)
    fuselage_length_m: Claim = Field(default_factory=lambda: Claim.unknown("m"))
    mass_kg: Claim = Field(default_factory=lambda: Claim.unknown("kg"))
    cg_m: Claim = Field(default_factory=lambda: Claim.unknown("m"))
    quality: dict[str, Any] = Field(default_factory=dict)   # fit limits, residuals, warnings


# ---------------------------------------------------------------- CAD edits (B calls A)

class EditOperation(str, Enum):
    translate_component = "translate_component"
    resize_spar = "resize_spar"
    set_wing_tip_extension = "set_wing_tip_extension"
    replace_catalog_component = "replace_catalog_component"


class CadEditRequest(_Model):
    base_revision_id: str
    operation: EditOperation
    target_part_ids: list[str]
    parameters: dict[str, Any]                # SI units, e.g. {"delta_m": [0.02, 0, 0]}
    idempotency_key: Optional[str] = None


class RoundTripCheck(_Model):
    name: str
    passed: bool
    detail: str = ""


class CadEditResult(_Model):
    schema_version: str = SCHEMA_VERSION
    base_revision_id: str
    preview_revision_id: Optional[str] = None
    operation: EditOperation
    status: Literal["ok", "blocked", "failed"]
    affected_part_ids: list[str] = Field(default_factory=list)
    changes: list[dict[str, Any]] = Field(default_factory=list)   # {part_id, field, before, after, unit}
    checks: list[RoundTripCheck] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    error: Optional[ErrorEnvelope] = None
