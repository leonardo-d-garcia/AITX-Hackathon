"""Append-only artifact storage on disk (architecture sections 4 and 5).

One directory per revision, written once and never modified. Attempting to write a path that
already exists with different bytes raises, so "content does not mutate after creation" is a
property of the storage layer rather than a rule everyone has to remember.

Artifacts are served through :meth:`ArtifactStore.resolve`, which maps an artifact id to bytes.
Section 9 requires exactly that: "Server-resolved immutable download; no arbitrary filesystem
path." Nothing above this layer ever sees a caller-supplied path.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

import json

from dronebench_contracts import (
    Artifact,
    DroneBenchError,
    MediaType,
    Representation,
    canonical_bytes,
    sha256_hex,
    strip_display_only,
)


class ImmutabilityError(RuntimeError):
    """An attempt to change bytes that have already been written."""


class ArtifactStore:
    """Filesystem side of the revision store."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- layout ---------------------------------------------------------------------------

    def design_dir(self, design_id: str) -> Path:
        return self.root / "designs" / _safe(design_id)

    def revision_dir(self, design_id: str, revision_id: str) -> Path:
        return self.design_dir(design_id) / "revisions" / _safe(revision_id)

    def job_dir(self, job_id: str) -> Path:
        """A unique directory per job.

        Section 9: native solvers emit many same-named files, so jobs may never share a directory.
        """
        path = self.root / "jobs" / _safe(job_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def discard_job_dir(self, job_id: str) -> None:
        shutil.rmtree(self.root / "jobs" / _safe(job_id), ignore_errors=True)

    # -- writing --------------------------------------------------------------------------

    def write(
        self,
        *,
        design_id: str,
        revision_id: str,
        relative_path: str,
        data: bytes,
        media_type: MediaType,
        produced_by: str,
        role: str,
        representation: Representation | None = None,
        part_ids: Iterable[str] = (),
    ) -> Artifact:
        """Write one artifact. Rewriting identical bytes is a no-op; different bytes raise."""
        artifact = Artifact.of_bytes(
            data,
            relative_path=relative_path,
            media_type=media_type,
            produced_by=produced_by,  # type: ignore[arg-type]
            role=role,
            representation=representation,
            part_ids=list(part_ids),
        )
        target = self.revision_dir(design_id, revision_id) / relative_path
        _assert_inside(target, self.revision_dir(design_id, revision_id))

        if target.exists():
            existing = target.read_bytes()
            if sha256_hex(existing) != artifact.sha256 and not _same_but_for_timing(existing, data):
                raise ImmutabilityError(
                    f"{design_id}/{revision_id}/{relative_path} already exists with other content; "
                    "revisions are append-only"
                )
            return artifact

        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".partial")
        temporary.write_bytes(data)
        temporary.replace(target)
        return artifact

    def write_json(
        self,
        *,
        design_id: str,
        revision_id: str,
        relative_path: str,
        payload: object,
        produced_by: str,
        role: str,
        representation: Representation | None = None,
        part_ids: Iterable[str] = (),
    ) -> Artifact:
        """Write a JSON artifact in canonical form.

        Canonical bytes mean two structurally identical documents hash identically, so a rebuilt
        preview of the same edit reuses the same artifact id instead of forking the store.
        """
        from pydantic import BaseModel

        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        return self.write(
            design_id=design_id,
            revision_id=revision_id,
            relative_path=relative_path,
            data=canonical_bytes(payload),
            media_type="application/json",
            produced_by=produced_by,
            role=role,
            representation=representation,
            part_ids=part_ids,
        )

    # -- reading --------------------------------------------------------------------------

    def read(self, *, design_id: str, revision_id: str, relative_path: str) -> bytes:
        target = self.revision_dir(design_id, revision_id) / relative_path
        _assert_inside(target, self.revision_dir(design_id, revision_id))
        if not target.is_file():
            raise DroneBenchError.of(
                "NOT_FOUND",
                f"artifact {relative_path} is not present in {revision_id}",
                revision_id=revision_id,
            )
        return target.read_bytes()

    def verify(self, *, design_id: str, revision_id: str, artifact: Artifact) -> None:
        """Confirm stored bytes still match the checksum held in the manifest."""
        data = self.read(
            design_id=design_id, revision_id=revision_id, relative_path=artifact.relative_path
        )
        actual = sha256_hex(data)
        if actual != artifact.sha256:
            raise DroneBenchError.of(
                "ARTIFACT_MISMATCH",
                f"{artifact.relative_path} no longer matches the checksum recorded in its manifest",
                revision_id=revision_id,
                expected_sha256=artifact.sha256,
                actual_sha256=actual,
            )

    def discard_revision(self, design_id: str, revision_id: str) -> None:
        """Remove a preview directory that never became a revision.

        Only ever called for a preview whose construction failed. A revision recorded in the
        database is never deleted - undo switches pointers, it does not erase history.
        """
        shutil.rmtree(self.revision_dir(design_id, revision_id), ignore_errors=True)


def _same_but_for_timing(existing: bytes, incoming: bytes) -> bool:
    """True when two JSON artifacts differ only in display-only fields.

    Recomputing the same evaluation produces the same numbers but a fresh ``elapsed_s`` and a fresh
    timestamp. Those are display-only - they are already excluded from every content hash - so
    treating them as a content change would make regenerating a preview fail against its own
    append-only revision. The stored bytes win; the recomputation is discarded.
    """
    try:
        a = strip_display_only(json.loads(existing))
        b = strip_display_only(json.loads(incoming))
    except Exception:
        return False
    return a == b


def _safe(component: str) -> str:
    """Reject anything that could escape the store root."""
    if not component or "/" in component or "\\" in component or component in (".", ".."):
        raise ValueError(f"unsafe path component: {component!r}")
    return component


def _assert_inside(target: Path, root: Path) -> None:
    resolved_root = root.resolve()
    resolved = (root / target.relative_to(root)).resolve() if target.is_absolute() else target.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValueError(f"path escapes the revision directory: {target}") from exc
