"""Revisions, artifacts, and the revision manifest (architecture section 5).

``design_id`` groups immutable ``revision_id``s. Content does not mutate after creation. A revision
records its parent, content hash, mission hash, artifact list, and creation cause; every report,
recommendation, simulation result, graph, GLB, STEP, and SSE event carries a revision id.

An artifact's own hash is never embedded in the bytes it hashes. Checksums live here, in the
enclosing manifest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .identity import artifact_id_from_hash, content_hash, revision_id_from_hash
from .parts import Representation

RevisionStage = Literal["draft", "staged_preview", "committed"]

CreationCause = Literal[
    "import",             # a source archive was ingested
    "confirm",            # the user confirmed units/frame/variants/reconstruction
    "manual_edit",        # a directly authored parameter change
    "proposal_preview",   # an isolated child built to evaluate a proposal
    "proposal_commit",    # an accepted preview promoted to committed
    "undo",               # a switch back to an existing validated revision
]

MediaType = Literal[
    "application/json",
    "application/step",
    "model/gltf-binary",
    "text/plain",
    "text/csv",
    "application/octet-stream",
]


class Artifact(BaseModel):
    """One immutable file belonging to a revision or run."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(pattern=r"^art_[0-9a-f]{16}$")
    relative_path: str = Field(
        description="Path relative to the revision directory. Never an absolute or escaping path."
    )
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: MediaType
    representation: Representation | None = None
    part_ids: list[str] = Field(default_factory=list)
    produced_by: Literal["A", "B", "C"] = Field(
        description="Owning team, so a consumer can tell a stub from a real producer."
    )
    role: str = Field(description="design_manifest | parts | graph | evaluation | step | glb | ...")

    @model_validator(mode="after")
    def _safe_path(self) -> Self:
        path = self.relative_path
        if path.startswith("/") or path.startswith("\\") or ":" in path:
            raise ValueError(f"artifact path must be relative: {path}")
        if ".." in path.replace("\\", "/").split("/"):
            raise ValueError(f"artifact path must not traverse upwards: {path}")
        return self

    @classmethod
    def of_bytes(
        cls,
        data: bytes,
        *,
        relative_path: str,
        media_type: MediaType,
        produced_by: Literal["A", "B", "C"],
        role: str,
        representation: Representation | None = None,
        part_ids: list[str] | None = None,
    ) -> "Artifact":
        from .identity import sha256_hex

        digest = sha256_hex(data)
        return cls(
            artifact_id=artifact_id_from_hash(digest),
            relative_path=relative_path,
            sha256=digest,
            size_bytes=len(data),
            media_type=media_type,
            representation=representation,
            part_ids=part_ids or [],
            produced_by=produced_by,
            role=role,
        )


class Revision(BaseModel):
    """An immutable design state."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{16}$")
    design_id: str = Field(pattern=r"^dsn_[a-z0-9][a-z0-9_-]{2,62}$")
    parent_revision_id: str | None = None
    stage: RevisionStage
    created_cause: CreationCause
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    mission_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Hash of the locked mission. Null before a mission is set.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by_proposal_id: str | None = None
    label: str = ""

    @model_validator(mode="after")
    def _cause_consistency(self) -> Self:
        if self.created_cause in ("proposal_preview", "proposal_commit"):
            if self.created_by_proposal_id is None:
                raise ValueError(f"{self.created_cause} requires created_by_proposal_id")
            if self.parent_revision_id is None:
                raise ValueError(f"{self.created_cause} requires a parent revision")
        if self.created_cause == "import" and self.parent_revision_id is not None:
            raise ValueError("an imported revision has no parent")
        if self.revision_id == self.parent_revision_id:
            raise ValueError("a revision cannot be its own parent")
        return self


class RevisionManifest(BaseModel):
    """``revision_manifest.json`` - B -> all.

    The coherent artifact set that became active atomically. A half-applied CAD/BOM/report
    combination cannot be represented: either the manifest lists the full set or it does not exist.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    revision: Revision
    artifacts: list[Artifact] = Field(default_factory=list)
    is_active: bool = False
    change_summary: list[str] = Field(default_factory=list)
    affected_part_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_paths(self) -> Self:
        paths = [artifact.relative_path for artifact in self.artifacts]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate artifact paths within one revision")
        return self

    def artifact(self, role: str) -> Artifact | None:
        for artifact in self.artifacts:
            if artifact.role == role:
                return artifact
        return None

    def require(self, role: str) -> Artifact:
        artifact = self.artifact(role)
        if artifact is None:
            raise KeyError(f"revision {self.revision.revision_id} has no artifact for role {role}")
        return artifact

    def roles(self) -> list[str]:
        return sorted(artifact.role for artifact in self.artifacts)


#: The artifact roles a committed revision must carry. A commit missing any of these is a partly
#: updated set and is rejected (architecture section 13, workflow checks).
REQUIRED_COMMITTED_ROLES: frozenset[str] = frozenset(
    {"design_manifest", "parts", "geometry_features", "graph"}
)


def compute_revision_id(
    *,
    design_id: str,
    parent_revision_id: str | None,
    payload: dict,
) -> tuple[str, str]:
    """Return ``(revision_id, content_hash)`` for a payload in a lineage.

    Lineage is folded in so that two different designs that happen to hold identical content do not
    collide, and so that re-deriving the same edit from the same parent is idempotent.
    """
    digest = content_hash(
        {
            "design_id": design_id,
            "parent_revision_id": parent_revision_id,
            "payload": payload,
        }
    )
    return revision_id_from_hash(digest), digest
