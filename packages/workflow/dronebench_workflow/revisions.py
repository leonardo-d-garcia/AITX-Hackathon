"""Building revisions: artifacts to disk, manifest to the database (architecture section 5).

A revision is created in one direction only - write every artifact, then register the manifest. If
artifact writing fails part way, nothing is registered and the orphaned directory is discarded, so
the database never points at an incomplete set.

:class:`DesignState` is the in-memory view of one revision that the graph, recommender, and
evaluator all read from. It is assembled from artifacts, never from a cached mutable object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dronebench_contracts import (
    Artifact,
    CreationCause,
    DesignManifest,
    DroneBenchError,
    EvidenceGraph,
    Evaluation,
    GeometryFeatures,
    Mission,
    PartsDocument,
    REQUIRED_COMMITTED_ROLES,
    Revision,
    RevisionManifest,
    RevisionStage,
    compute_revision_id,
)

from .repository import Repository
from .store import ArtifactStore


@dataclass(frozen=True)
class DesignState:
    """Everything downstream code needs about one revision, loaded from its artifacts."""

    design_id: str
    revision_id: str
    manifest: DesignManifest
    parts: PartsDocument
    features: GeometryFeatures
    graph: EvidenceGraph | None = None
    evaluation: Evaluation | None = None

    def part_ids(self) -> list[str]:
        return [occurrence.part_id for occurrence in self.parts.occurrences]


class RevisionBuilder:
    """Accumulates artifacts for one prospective revision, then seals it."""

    def __init__(
        self,
        *,
        store: ArtifactStore,
        design_id: str,
        parent_revision_id: str | None,
        stage: RevisionStage,
        cause: CreationCause,
        mission: Mission | None,
        proposal_id: str | None = None,
        label: str = "",
    ) -> None:
        self.store = store
        self.design_id = design_id
        self.parent_revision_id = parent_revision_id
        self.stage = stage
        self.cause = cause
        self.mission = mission
        self.proposal_id = proposal_id
        self.label = label
        # role -> (relative_path, payload, produced_by, part_ids, derived)
        self._documents: dict[str, tuple[str, object, str, list[str], bool]] = {}
        self._change_summary: list[str] = []
        self._affected: list[str] = []

    def add_json(
        self,
        *,
        role: str,
        relative_path: str,
        payload: object,
        produced_by: Literal["A", "B", "C"],
        part_ids: list[str] | None = None,
        derived: bool = False,
    ) -> "RevisionBuilder":
        """Attach a document.

        ``derived=True`` marks a document that is a pure function of the source documents plus the
        mission - the graph projection, an evaluation, a CAD result. Derived documents are excluded
        from :meth:`identity`, which is what makes the id computable *before* they are built. Both
        the graph and an evaluation are revision-scoped internally, so they cannot be authored
        until the id exists; if they also fed the hash, the id would depend on itself.
        """
        self._documents[role] = (relative_path, payload, produced_by, part_ids or [], derived)
        return self

    def note(self, *lines: str) -> "RevisionBuilder":
        self._change_summary.extend(lines)
        return self

    def affects(self, *part_ids: str) -> "RevisionBuilder":
        for part_id in part_ids:
            if part_id not in self._affected:
                self._affected.append(part_id)
        return self

    def identity(self) -> tuple[str, str]:
        """``(revision_id, content_hash)`` derived from the source documents added so far.

        Two exclusions, both to break a circularity rather than to weaken the hash:

        * each document's own ``revision_id`` field, because those fields are stamped *with* this
          id at seal time;
        * documents marked ``derived``, because they are revision-scoped projections of the source
          documents and cannot be authored until the id exists.

        Everything that distinguishes one revision from another - geometry, masses, parameters,
        stage, lineage, and the mission - is still covered. Calling this before and after adding a
        derived document returns the same id, which is what callers rely on.
        """
        hashable = {
            role: _without_revision_id(_as_payload(payload))
            for role, (_, payload, _, _, derived) in sorted(self._documents.items())
            if not derived
        }
        return compute_revision_id(
            design_id=self.design_id,
            parent_revision_id=self.parent_revision_id,
            payload={
                "stage": self.stage,
                # The mission is folded in so that identical geometry under two different missions
                # cannot collide on one id, which is what lets derived documents be excluded.
                "mission_hash": self.mission.mission_hash() if self.mission else None,
                "documents": hashable,
            },
        )

    def seal(self, repository: Repository) -> RevisionManifest:
        """Write the artifacts under the content-derived id, then register the manifest."""
        if self.stage == "committed":
            missing = REQUIRED_COMMITTED_ROLES - set(self._documents)
            if missing:
                raise DroneBenchError.of(
                    "ARTIFACT_MISMATCH",
                    "a committed revision needs a complete artifact set; missing "
                    + ", ".join(sorted(missing)),
                )

        revision_id, content_hash = self.identity()

        # Every document carries the id of the revision it belongs to. A document that names a
        # different revision would break every consumer that reads parts.json and trusts its
        # revision_id, which is exactly what the recommender does when it sets a proposal's base.
        self._documents = {
            role: (path, _stamp_revision_id(payload, revision_id), producer, part_ids, derived)
            for role, (path, payload, producer, part_ids, derived) in self._documents.items()
        }

        artifacts: list[Artifact] = []
        try:
            for role, (relative_path, payload, produced_by, part_ids, _) in sorted(
                self._documents.items()
            ):
                artifacts.append(
                    self.store.write_json(
                        design_id=self.design_id,
                        revision_id=revision_id,
                        relative_path=relative_path,
                        payload=payload,
                        produced_by=produced_by,
                        role=role,
                        part_ids=part_ids,
                    )
                )
        except Exception:
            # Nothing was registered, so the directory is an orphan rather than a partial revision.
            self.store.discard_revision(self.design_id, revision_id)
            raise

        revision = Revision(
            revision_id=revision_id,
            design_id=self.design_id,
            parent_revision_id=self.parent_revision_id,
            stage=self.stage,
            created_cause=self.cause,
            content_hash=content_hash,
            mission_hash=self.mission.mission_hash() if self.mission else None,
            created_by_proposal_id=self.proposal_id,
            label=self.label,
        )
        manifest = RevisionManifest(
            revision=revision,
            artifacts=artifacts,
            change_summary=self._change_summary,
            affected_part_ids=self._affected,
        )
        repository.put_revision(manifest)
        return manifest


class RevisionService:
    """Reads and writes revisions. The only thing above it that touches the store."""

    def __init__(self, repository: Repository, store: ArtifactStore) -> None:
        self.repository = repository
        self.store = store

    def builder(
        self,
        *,
        design_id: str,
        parent_revision_id: str | None,
        stage: RevisionStage,
        cause: CreationCause,
        mission: Mission | None,
        proposal_id: str | None = None,
        label: str = "",
    ) -> RevisionBuilder:
        return RevisionBuilder(
            store=self.store,
            design_id=design_id,
            parent_revision_id=parent_revision_id,
            stage=stage,
            cause=cause,
            mission=mission,
            proposal_id=proposal_id,
            label=label,
        )

    def load(self, revision_id: str, *, verify: bool = False) -> DesignState:
        """Assemble a :class:`DesignState` from a revision's artifacts."""
        manifest = self.repository.get_manifest(revision_id)
        design_id = manifest.revision.design_id

        def read(role: str, required: bool = True):
            artifact = manifest.artifact(role)
            if artifact is None:
                if required:
                    raise DroneBenchError.of(
                        "ARTIFACT_MISMATCH",
                        f"revision {revision_id} is missing its {role} artifact",
                        revision_id=revision_id,
                    )
                return None
            if verify:
                self.store.verify(
                    design_id=design_id, revision_id=revision_id, artifact=artifact
                )
            import json

            return json.loads(
                self.store.read(
                    design_id=design_id,
                    revision_id=revision_id,
                    relative_path=artifact.relative_path,
                )
            )

        graph_payload = read("graph", required=False)
        evaluation_payload = read("evaluation", required=False)
        return DesignState(
            design_id=design_id,
            revision_id=revision_id,
            manifest=DesignManifest.model_validate(read("design_manifest")),
            parts=PartsDocument.model_validate(read("parts")),
            features=GeometryFeatures.model_validate(read("geometry_features")),
            graph=EvidenceGraph.model_validate(graph_payload) if graph_payload else None,
            evaluation=Evaluation.model_validate(evaluation_payload) if evaluation_payload else None,
        )

    def verify_all(self, revision_id: str) -> list[str]:
        """Re-hash every artifact. Returns the list of roles checked."""
        manifest = self.repository.get_manifest(revision_id)
        for artifact in manifest.artifacts:
            self.store.verify(
                design_id=manifest.revision.design_id,
                revision_id=revision_id,
                artifact=artifact,
            )
        return manifest.roles()


def _as_payload(payload: object) -> object:
    from pydantic import BaseModel

    return payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload


def _without_revision_id(payload: object) -> object:
    if isinstance(payload, dict):
        return {key: value for key, value in payload.items() if key != "revision_id"}
    return payload


def _stamp_revision_id(payload: object, revision_id: str) -> object:
    """Set ``revision_id`` on a document that has the field, leaving others untouched."""
    from pydantic import BaseModel

    if isinstance(payload, BaseModel):
        if "revision_id" in type(payload).model_fields:
            return payload.model_copy(update={"revision_id": revision_id})
        return payload
    if isinstance(payload, dict) and "revision_id" in payload:
        return {**payload, "revision_id": revision_id}
    return payload
