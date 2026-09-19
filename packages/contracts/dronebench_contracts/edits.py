"""The four typed edit operations and the CAD result contract (architecture sections 5 and 6).

An edit is a *typed* operation with declared preconditions, never interpreted code. Section 6:
"Never interpret arbitrary LLM Python, CadQuery, or shell as an edit." The union below is closed;
anything outside it fails validation with ``UNSUPPORTED_EDIT``.

The v1 starter contract restricts a proposal to one bounded high-level operation. That operation
may deterministically update its own symmetric occurrences - a spar resize regenerating both
compatible mounts is one reviewed transaction, not two edits.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .claims import Claim
from .parts import Representation

OperationName = Literal[
    "translate_component",
    "resize_spar",
    "set_wing_tip_extension",
    "replace_catalog_component",
]


class _BaseOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_part_id: str = Field(pattern=r"^prt_[a-z0-9][a-z0-9_.-]{1,62}$")

    @property
    def owned_part_ids(self) -> list[str]:
        """Occurrences this single operation may deterministically update."""
        return [self.target_part_id]


class TranslateComponent(_BaseOperation):
    """Move an unlocked movable component along its declared travel corridor.

    Preconditions (section 6): the corridor, harness allowance, and mount positions are known.
    CAD effect: change the instance placement only. Geometry shapes stay identical, which the
    export acceptance check verifies by comparing unchanged-part signatures.
    """

    operation: Literal["translate_component"] = "translate_component"
    axis: Literal["x", "y", "z"]
    delta_m: float

    @model_validator(mode="after")
    def _nonzero(self) -> Self:
        if self.delta_m == 0.0:
            raise ValueError("a translate of zero is not an edit")
        return self


class ResizeSpar(_BaseOperation):
    """Regenerate a tubular spar, and any mounts included in the same reviewed transaction.

    Preconditions: the spar is a reconstructed tube, the material assumption is declared, and the
    shaft/wing-hole/connector limits are known.
    """

    operation: Literal["resize_spar"] = "resize_spar"
    outer_diameter_m: float = Field(gt=0)
    inner_diameter_m: float = Field(ge=0)
    regenerate_mount_part_ids: list[str] = Field(
        default_factory=list,
        description="Compatible mounts regenerated inside the same transaction.",
    )

    @model_validator(mode="after")
    def _wall_positive(self) -> Self:
        if self.inner_diameter_m >= self.outer_diameter_m:
            raise ValueError("inner diameter must be smaller than outer diameter")
        return self

    @property
    def owned_part_ids(self) -> list[str]:
        return [self.target_part_id, *self.regenerate_mount_part_ids]

    @property
    def wall_thickness_m(self) -> float:
        return (self.outer_diameter_m - self.inner_diameter_m) / 2.0


class SetWingTipExtension(_BaseOperation):
    """Stretch a parameterised symmetric tip. Regenerates the paired surface too."""

    operation: Literal["set_wing_tip_extension"] = "set_wing_tip_extension"
    extension_m: float
    paired_part_id: str = Field(
        pattern=r"^prt_[a-z0-9][a-z0-9_.-]{1,62}$",
        description="The mirrored occurrence regenerated in the same transaction.",
    )

    @model_validator(mode="after")
    def _distinct_and_nonzero(self) -> Self:
        if self.extension_m == 0.0:
            raise ValueError("a zero extension is not an edit")
        if self.paired_part_id == self.target_part_id:
            raise ValueError("the paired occurrence must be a distinct part_id")
        return self

    @property
    def owned_part_ids(self) -> list[str]:
        return [self.target_part_id, self.paired_part_id]


class ReplaceCatalogComponent(_BaseOperation):
    """Swap an envelope/part and its BOM entry atomically.

    Unresolved fit or current checks block the commit; they do not merely warn.
    """

    operation: Literal["replace_catalog_component"] = "replace_catalog_component"
    catalog_item_id: str

    @property
    def owned_part_ids(self) -> list[str]:
        return [self.target_part_id]


EditOperation = Annotated[
    Union[TranslateComponent, ResizeSpar, SetWingTipExtension, ReplaceCatalogComponent],
    Field(discriminator="operation"),
]


class PartSignature(BaseModel):
    """A semantic fingerprint used to prove an unchanged part really did not change.

    Section 6 export acceptance: compare semantic geometry, not STEP byte hashes, and do not
    require entity numbers or face ordering to remain stable.
    """

    model_config = ConfigDict(extra="forbid")

    part_id: str
    volume_m3: float | None = Field(default=None, ge=0)
    bounds_min_m: tuple[float, float, float] | None = None
    bounds_max_m: tuple[float, float, float] | None = None
    solid_count: int = Field(default=0, ge=0)
    placement_translation_m: tuple[float, float, float] | None = None

    def matches(
        self,
        other: "PartSignature",
        *,
        placement_tol_m: float = 1e-4,
        relative_volume_tol: float = 1e-4,
        absolute_volume_tol_m3: float = 1e-12,
    ) -> bool:
        """Section 6 initial tolerances: 0.1 mm on placement/bounds, 1e-4 relative on volume."""
        if self.part_id != other.part_id or self.solid_count != other.solid_count:
            return False
        if (self.volume_m3 is None) != (other.volume_m3 is None):
            return False
        if self.volume_m3 is not None and other.volume_m3 is not None:
            difference = abs(self.volume_m3 - other.volume_m3)
            allowed = max(relative_volume_tol * max(self.volume_m3, 1e-12), absolute_volume_tol_m3)
            if difference > allowed:
                return False
        for mine, theirs in (
            (self.bounds_min_m, other.bounds_min_m),
            (self.bounds_max_m, other.bounds_max_m),
            (self.placement_translation_m, other.placement_translation_m),
        ):
            if (mine is None) != (theirs is None):
                return False
            if mine is not None and theirs is not None:
                if any(abs(a - b) > placement_tol_m for a, b in zip(mine, theirs)):
                    return False
        return True


class RoundTripCheck(BaseModel):
    """The export/reimport result. A download is refused without a successful round trip."""

    model_config = ConfigDict(extra="forbid")

    performed: bool
    solids_match: bool = False
    bounds_match: bool = False
    placements_match: bool = False
    sidecar_identity_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    reimport_worker_fresh: bool = Field(
        default=False, description="Reimport ran in a fresh worker, not the exporting process."
    )
    notes: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.performed
            and self.solids_match
            and self.bounds_match
            and self.placements_match
            and self.reimport_worker_fresh
            and self.sidecar_identity_coverage >= 1.0
        )


class InterferenceFinding(BaseModel):
    """An overlap that was *not* a declared mating, bonded, or nesting pair."""

    model_config = ConfigDict(extra="forbid")

    part_id_a: str
    part_id_b: str
    overlap_volume_m3: float | None = Field(default=None, ge=0)
    kind: Literal["unintended_overlap", "propeller_swept_volume"]


class CadEditResult(BaseModel):
    """``cad_edit_result.json`` - A's tool, called by B, consumed by everyone.

    ``ok`` false means the edit did not produce valid geometry. B never promotes such a preview.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    ok: bool
    base_revision_id: str
    preview_revision_id: str | None = None
    operation: OperationName
    affected_part_ids: list[str] = Field(default_factory=list)

    part_signatures_before: list[PartSignature] = Field(default_factory=list)
    part_signatures_after: list[PartSignature] = Field(default_factory=list)
    unchanged_parts_verified: bool = False
    requested_parameters_applied: dict[str, float] = Field(default_factory=dict)

    interference: list[InterferenceFinding] = Field(default_factory=list)
    round_trip: RoundTripCheck = Field(default_factory=lambda: RoundTripCheck(performed=False))

    step_artifact_id: str | None = None
    glb_artifact_id: str | None = None
    part_map_artifact_id: str | None = None
    representation: Representation = "editable_reconstruction"

    mass_delta_kg: Claim | None = None
    diagnostics: list[str] = Field(default_factory=list)
    produced_by: Literal["A", "B-stub"] = Field(
        description="B-stub marks the reference CAD port B uses until Team A's kernel lands."
    )

    @model_validator(mode="after")
    def _ok_implies_evidence(self) -> Self:
        if self.ok:
            if self.preview_revision_id is None:
                raise ValueError("a successful edit must name its preview revision")
            if not self.affected_part_ids:
                raise ValueError("a successful edit must name the parts it affected")
            if not self.unchanged_parts_verified:
                raise ValueError(
                    "a successful edit must verify that unchanged parts kept their signatures"
                )
            if self.interference:
                raise ValueError(
                    "unintended interference must fail the edit, not accompany a successful one"
                )
        return self

    @property
    def downloadable(self) -> bool:
        """Section 6: download requires a successful round trip."""
        return self.ok and self.round_trip.passed
