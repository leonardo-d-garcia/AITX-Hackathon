"""Database-backed records for designs, revisions, proposals, events, and jobs.

This module holds the SQL. The transaction semantics that make acceptance safe live next door in
:mod:`dronebench_workflow.transactions`; keeping them apart means the compare-and-swap is one
readable function rather than a rule spread across a dozen queries.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Iterable

from dronebench_contracts import (
    Artifact,
    AuditEvent,
    DroneBenchError,
    EventKind,
    JobRecord,
    Mission,
    Recommendation,
    Revision,
    RevisionManifest,
    canonical_json,
)

from .db import transaction


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """All persistent state for one workbench instance."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    # -- designs ---------------------------------------------------------------------------

    def create_design(self, design_id: str, display_name: str) -> None:
        with transaction(self.connection) as db:
            db.execute(
                "INSERT OR IGNORE INTO designs (design_id, display_name, created_at) "
                "VALUES (?, ?, ?)",
                (design_id, display_name, _now()),
            )

    def design_exists(self, design_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM designs WHERE design_id = ?", (design_id,)
        ).fetchone()
        return row is not None

    def list_designs(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.connection.execute(
            "SELECT design_id, display_name, active_revision_id, mission_hash, created_at "
            "FROM designs ORDER BY created_at"
        )]

    def active_revision_id(self, design_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT active_revision_id FROM designs WHERE design_id = ?", (design_id,)
        ).fetchone()
        if row is None:
            raise DroneBenchError.of("NOT_FOUND", f"no design {design_id}")
        return row["active_revision_id"]

    def require_active_revision_id(self, design_id: str) -> str:
        active = self.active_revision_id(design_id)
        if active is None:
            raise DroneBenchError.of(
                "ASSEMBLY_UNCONFIRMED",
                f"design {design_id} has no active revision yet; import and confirm it first",
            )
        return active

    # -- missions --------------------------------------------------------------------------

    def put_mission(self, mission: Mission) -> str:
        mission_hash = mission.mission_hash()
        with transaction(self.connection) as db:
            db.execute(
                "INSERT OR REPLACE INTO missions (mission_hash, mission_json) VALUES (?, ?)",
                (mission_hash, canonical_json(mission.model_dump(mode="json"))),
            )
        return mission_hash

    def get_mission(self, mission_hash: str) -> Mission:
        row = self.connection.execute(
            "SELECT mission_json FROM missions WHERE mission_hash = ?", (mission_hash,)
        ).fetchone()
        if row is None:
            raise DroneBenchError.of("NOT_FOUND", f"no mission {mission_hash}")
        return Mission.model_validate(json.loads(row["mission_json"]))

    def set_design_mission(self, design_id: str, mission: Mission) -> str:
        mission_hash = self.put_mission(mission)
        with transaction(self.connection) as db:
            db.execute(
                "UPDATE designs SET mission_hash = ? WHERE design_id = ?",
                (mission_hash, design_id),
            )
        return mission_hash

    def design_mission(self, design_id: str) -> Mission:
        row = self.connection.execute(
            "SELECT mission_hash FROM designs WHERE design_id = ?", (design_id,)
        ).fetchone()
        if row is None or row["mission_hash"] is None:
            raise DroneBenchError.of(
                "MISSING_EVIDENCE", f"design {design_id} has no locked mission"
            )
        return self.get_mission(row["mission_hash"])

    # -- revisions -------------------------------------------------------------------------

    def put_revision(self, manifest: RevisionManifest) -> None:
        """Insert a revision and its artifacts in one transaction.

        A revision and its artifact rows land together or not at all, which is what stops a failed
        worker from leaving a half-registered artifact set behind.
        """
        revision = manifest.revision
        with transaction(self.connection) as db:
            existing = db.execute(
                "SELECT content_hash FROM revisions WHERE revision_id = ?",
                (revision.revision_id,),
            ).fetchone()
            if existing is not None:
                if existing["content_hash"] != revision.content_hash:
                    raise DroneBenchError.of(
                        "ARTIFACT_MISMATCH",
                        f"revision {revision.revision_id} already exists with different content",
                        revision_id=revision.revision_id,
                    )
                return

            db.execute(
                "INSERT INTO revisions (revision_id, design_id, parent_revision_id, stage, "
                "created_cause, content_hash, mission_hash, created_by_proposal_id, label, "
                "manifest_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    revision.revision_id,
                    revision.design_id,
                    revision.parent_revision_id,
                    revision.stage,
                    revision.created_cause,
                    revision.content_hash,
                    revision.mission_hash,
                    revision.created_by_proposal_id,
                    revision.label,
                    canonical_json(manifest.model_dump(mode="json")),
                    _now(),
                ),
            )
            for artifact in manifest.artifacts:
                db.execute(
                    "INSERT OR REPLACE INTO artifacts (artifact_id, revision_id, relative_path, "
                    "sha256, size_bytes, media_type, representation, produced_by, role, "
                    "part_ids_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        artifact.artifact_id,
                        revision.revision_id,
                        artifact.relative_path,
                        artifact.sha256,
                        artifact.size_bytes,
                        artifact.media_type,
                        artifact.representation,
                        artifact.produced_by,
                        artifact.role,
                        json.dumps(artifact.part_ids),
                    ),
                )

    def get_manifest(self, revision_id: str) -> RevisionManifest:
        row = self.connection.execute(
            "SELECT manifest_json, design_id FROM revisions WHERE revision_id = ?", (revision_id,)
        ).fetchone()
        if row is None:
            raise DroneBenchError.of("NOT_FOUND", f"no revision {revision_id}")
        manifest = RevisionManifest.model_validate(json.loads(row["manifest_json"]))
        active = self.active_revision_id(row["design_id"])
        return manifest.model_copy(update={"is_active": active == revision_id})

    def get_revision(self, revision_id: str) -> Revision:
        return self.get_manifest(revision_id).revision

    def revision_exists(self, revision_id: str) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM revisions WHERE revision_id = ?", (revision_id,)
            ).fetchone()
            is not None
        )

    def find_artifact(self, artifact_id: str) -> tuple[str, str, Artifact]:
        """Resolve an artifact id to ``(design_id, revision_id, artifact)``."""
        row = self.connection.execute(
            "SELECT a.*, r.design_id FROM artifacts a JOIN revisions r "
            "ON a.revision_id = r.revision_id WHERE a.artifact_id = ? LIMIT 1",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise DroneBenchError.of("NOT_FOUND", f"no artifact {artifact_id}")
        artifact = Artifact(
            artifact_id=row["artifact_id"],
            relative_path=row["relative_path"],
            sha256=row["sha256"],
            size_bytes=row["size_bytes"],
            media_type=row["media_type"],
            representation=row["representation"],
            produced_by=row["produced_by"],
            role=row["role"],
            part_ids=json.loads(row["part_ids_json"]),
        )
        return row["design_id"], row["revision_id"], artifact

    def revision_history(self, design_id: str) -> list[Revision]:
        """The states this design was actually in, oldest activation first.

        Previews are absent because they were never active, and so is a commit whose
        compare-and-swap lost the race: it exists as bytes on disk, but the design was never in
        that state, and showing it in the timeline would imply an edit that never took effect.
        """
        out: list[Revision] = []
        for row in self.connection.execute(
            "SELECT manifest_json FROM revisions WHERE design_id = ? AND activated_at IS NOT NULL "
            "ORDER BY activated_at, revision_id",
            (design_id,),
        ):
            out.append(RevisionManifest.model_validate(json.loads(row["manifest_json"])).revision)
        return out

    def mark_activated(self, revision_id: str, db=None) -> None:
        """Stamp the first activation. Re-activating an earlier revision keeps the original stamp,
        so the timeline stays in the order the design first reached each state."""
        connection = db if db is not None else self.connection
        connection.execute(
            "UPDATE revisions SET activated_at = ? WHERE revision_id = ? AND activated_at IS NULL",
            (_now(), revision_id),
        )

    # -- proposals -------------------------------------------------------------------------

    def put_proposal(self, recommendation: Recommendation) -> None:
        now = _now()
        with transaction(self.connection) as db:
            db.execute(
                "INSERT INTO proposals (proposal_id, design_id, base_revision_id, mission_hash, "
                "state, payload_json, preview_revision_id, preview_hash, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(proposal_id) DO UPDATE SET state=excluded.state, "
                "payload_json=excluded.payload_json, "
                "preview_revision_id=excluded.preview_revision_id, "
                "preview_hash=excluded.preview_hash, updated_at=excluded.updated_at",
                (
                    recommendation.proposal_id,
                    recommendation.design_id,
                    recommendation.base_revision_id,
                    recommendation.mission_hash,
                    recommendation.state,
                    canonical_json(recommendation.model_dump(mode="json")),
                    recommendation.preview.preview_revision_id if recommendation.preview else None,
                    recommendation.preview.preview_hash if recommendation.preview else None,
                    now,
                    now,
                ),
            )

    def get_proposal(self, proposal_id: str) -> Recommendation:
        row = self.connection.execute(
            "SELECT payload_json FROM proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise DroneBenchError.of("NOT_FOUND", f"no proposal {proposal_id}")
        return Recommendation.model_validate(json.loads(row["payload_json"]))

    def list_proposals(self, design_id: str, base_revision_id: str | None = None) -> list[Recommendation]:
        sql = "SELECT payload_json FROM proposals WHERE design_id = ?"
        params: list[Any] = [design_id]
        if base_revision_id:
            sql += " AND base_revision_id = ?"
            params.append(base_revision_id)
        sql += " ORDER BY created_at"
        return [
            Recommendation.model_validate(json.loads(row["payload_json"]))
            for row in self.connection.execute(sql, params)
        ]

    # -- events ----------------------------------------------------------------------------

    def append_event(
        self,
        *,
        design_id: str,
        kind: EventKind,
        tool_name: str,
        revision_id: str | None = None,
        job_id: str | None = None,
        proposal_id: str | None = None,
        inputs_summary: dict[str, str] | None = None,
        artifact_ids: Iterable[str] = (),
        status: str = "ok",
        error_code: str | None = None,
        elapsed_s: float = 0.0,
    ) -> AuditEvent:
        """Append one audit event with the next per-design sequence number."""
        with transaction(self.connection) as db:
            row = db.execute(
                "SELECT COALESCE(MAX(sequence), 0) AS last FROM events WHERE design_id = ?",
                (design_id,),
            ).fetchone()
            sequence = int(row["last"]) + 1
            event = AuditEvent(
                sequence=sequence,
                event_id=f"evt_{design_id}_{sequence}",
                kind=kind,
                design_id=design_id,
                revision_id=revision_id,
                job_id=job_id,
                proposal_id=proposal_id,
                tool_name=tool_name,
                inputs_summary=inputs_summary or {},
                artifact_ids=list(artifact_ids),
                status=status,  # type: ignore[arg-type]
                error_code=error_code,
                elapsed_s=elapsed_s,
            )
            db.execute(
                "INSERT INTO events (design_id, sequence, event_json, created_at) VALUES (?,?,?,?)",
                (design_id, sequence, canonical_json(event.model_dump(mode="json")), _now()),
            )
        return event

    def events_since(self, design_id: str, after_sequence: int = 0, limit: int = 500) -> list[AuditEvent]:
        return [
            AuditEvent.model_validate(json.loads(row["event_json"]))
            for row in self.connection.execute(
                "SELECT event_json FROM events WHERE design_id = ? AND sequence > ? "
                "ORDER BY sequence LIMIT ?",
                (design_id, after_sequence, limit),
            )
        ]

    def last_sequence(self, design_id: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS last FROM events WHERE design_id = ?",
            (design_id,),
        ).fetchone()
        return int(row["last"])

    # -- jobs ------------------------------------------------------------------------------

    def put_job(self, job: JobRecord) -> None:
        with transaction(self.connection) as db:
            db.execute(
                "INSERT INTO jobs (job_id, design_id, kind, status, cache_key, record_json, "
                "created_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, "
                "record_json=excluded.record_json",
                (
                    job.job_id,
                    job.design_id,
                    job.kind,
                    job.status,
                    job.cache_key,
                    canonical_json(job.model_dump(mode="json")),
                    _now(),
                ),
            )

    def get_job(self, job_id: str) -> JobRecord:
        row = self.connection.execute(
            "SELECT record_json FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise DroneBenchError.of("NOT_FOUND", f"no job {job_id}")
        return JobRecord.model_validate(json.loads(row["record_json"]))

    def find_cached_job(self, cache_key: str) -> JobRecord | None:
        """A previously succeeded job with the same cache key.

        Section 8: a cache hit must show the reused run id plus newly recomputed downstream
        results, so the caller records ``reused_job_id`` rather than pretending it ran.
        """
        row = self.connection.execute(
            "SELECT record_json FROM jobs WHERE cache_key = ? AND status = 'succeeded' "
            "ORDER BY created_at LIMIT 1",
            (cache_key,),
        ).fetchone()
        return JobRecord.model_validate(json.loads(row["record_json"])) if row else None
