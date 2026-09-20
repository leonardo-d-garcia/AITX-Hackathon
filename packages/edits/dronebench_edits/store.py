"""The append-only revision store: previews, the active pointer, decisions, idempotency.

This is the A3a half of ``api.py``. It knows nothing about CAD. A caller hands it a ``build``
callback; the store gives that callback a private working directory, verifies and hashes whatever
it wrote there, and only then publishes the result as an immutable revision directory.

On-disk layout, inside an ingest design directory::

    <design_dir>/sources/                     # staged by dronebench_ingest (never touched here)
    <design_dir>/revisions/<revision_id>/     # immutable: artifacts + revision_manifest.json
    <design_dir>/revisions/active             # pointer file: one revision id
    <design_dir>/revisions/decisions.jsonl    # append-only log of accept/decline decisions
    <design_dir>/revisions/idempotency.json   # {"<parent>::<key>": "<revision_id>"}
    <design_dir>/revisions/.lock              # O_EXCL mutex around pointer/index writes
    <design_dir>/revisions/.preview-<uuid>.partial/   # a build in flight; renamed or deleted

The revision id follows A1's scheme, ``rev-<content_sha256[:12]>``, so a preview directory is named
by what is in it. ``content_sha256`` is taken over the canonical sorted JSON of

    {"store_version", "parent_revision_id", "cause", "content"}

where ``content`` is ``BuildResult.content`` — the caller's declaration of the inputs that produced
the geometry. Timestamps, absolute paths and artifact bytes are deliberately *not* in it: two
builds of the same edit from two different working directories must land on the same revision id.
That also means **the caller must put everything that distinguishes one edit from another into
``BuildResult.content``** (operation, target part ids, parameters, parameter set version). Two
edits sharing a ``content`` payload are, to this store, the same edit.

Failure is total: if ``build`` raises, the partial directory is removed and nothing about the design
changes — no revision, no pointer move, no index entry.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from dronebench_contracts.models import (SCHEMA_VERSION, Artifact, ErrorCode, RevisionManifest,
                                         RevisionState)

from .api import BuildResult, EditBlocked

# Bumped when the meaning of a revision's content hash changes, so old ids are never silently
# reused for a different meaning.
STORE_VERSION = "a3a.1"

REVISION_NAME = "revision_manifest.json"       # same file name A1 writes
EDIT_STATUS_NAME = "edit_status.json"          # the store's own verdict on a preview
REVISIONS_DIRNAME = "revisions"
ACTIVE_NAME = "active"
DECISIONS_NAME = "decisions.jsonl"
IDEMPOTENCY_NAME = "idempotency.json"
LOCK_NAME = ".lock"
PARTIAL_PREFIX = ".preview-"
PARTIAL_SUFFIX = ".partial"

# A preview may only become the active revision from this status. Anything else is a preview that
# exists so a human can read *why* it was refused, never a design.
COMMITTABLE_STATUS = "ok"

# Checks that report an **evidence gap**, not a geometric failure. Architecture §6: unknown
# retention or harness interfaces block a *verified movement claim*, not the operation itself. The
# Avenger's battery retention is genuinely unknown, so this check fails for every battery move; if
# that blocked the edit, no battery could ever be moved on the only aircraft we have. A failed
# advisory check therefore leaves the preview committable and sets ``verified: false``, so the UI
# can show the move but can never call it verified. Add a name here only when its failure means
# "we do not know", never when it means "this geometry is wrong".
ADVISORY_CHECKS = frozenset({"verified_movement_unknown"})

LOCK_TIMEOUT_S = 20.0
LOCK_STALE_S = 300.0


# ------------------------------------------------------------------ small helpers

def _blocked(code: ErrorCode, message: str, **details: Any) -> EditBlocked:
    return EditBlocked.of(code, message, **details)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(payload: Any) -> str:
    """Sorted, separator-stable JSON. The only thing a content hash is ever taken over."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str,
                      ensure_ascii=False)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def revisions_root(design_dir: str | Path) -> Path:
    return Path(design_dir) / REVISIONS_DIRNAME


def check_revision_id(revision_id: Any, field: str = "revision_id") -> str:
    """Validate an id *before* it is ever joined onto a path.

    ``None``, an empty string, a non-string and anything with a path separator in it are refused
    here with a typed envelope. A missing id used to reach ``Path / None`` and surface as a
    ``TypeError``, which told the caller nothing and looked like a crash rather than a refusal.
    """
    if revision_id is None or not isinstance(revision_id, str) or not revision_id.strip():
        raise _blocked(ErrorCode.INPUT_REJECTED,
                       f"{field} is required and must be a revision id, got {revision_id!r}",
                       field=field, value=repr(revision_id))
    clean = revision_id.strip()
    if clean != Path(clean).name or clean in (".", ".."):
        raise _blocked(ErrorCode.INPUT_REJECTED,
                       f"{field} {revision_id!r} is not a revision id",
                       field=field, value=revision_id)
    return clean


def revision_dir(design_dir: str | Path, revision_id: str) -> Path:
    return revisions_root(design_dir) / check_revision_id(revision_id)


def content_sha256(parent_revision_id: Optional[str], cause: str, content: dict[str, Any],
                   status: str = COMMITTABLE_STATUS) -> str:
    """The revision identity function. Deterministic, path-free and clock-free.

    ``status`` joins the hash so that a blocked preview can never land on the same id — and so
    reuse the directory — as an otherwise identical preview that passed.
    """
    payload = {
        "store_version": STORE_VERSION,
        "parent_revision_id": parent_revision_id,
        "cause": cause,
        "content": content,
    }
    if status != COMMITTABLE_STATUS:
        payload["status"] = status
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def revision_id_for(content_hash: str) -> str:
    return f"rev-{content_hash[:12]}"


@contextmanager
def _lock(design_dir: str | Path, timeout: float = LOCK_TIMEOUT_S) -> Iterator[None]:
    """A cross-process mutex over the pointer and index files.

    ``O_EXCL`` create, polled. A lock file older than ``LOCK_STALE_S`` is treated as abandoned by a
    killed process and broken, because a stuck lock would otherwise freeze a design for good.
    """
    root = revisions_root(design_dir)
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCK_NAME
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.write(fd, f"{os.getpid()} {_now()}\n".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if age > LOCK_STALE_S:
                path.unlink(missing_ok=True)
                continue
            if time.monotonic() > deadline:
                raise _blocked(ErrorCode.CONSTRAINT_FAILED,
                               "another edit holds the revision lock for this design",
                               lock=str(path), waited_s=round(timeout, 1))
            time.sleep(0.02)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _read_manifest(path: Path) -> RevisionManifest:
    return RevisionManifest.model_validate_json(path.read_text())


def load_revision(design_dir: str | Path, revision_id: str) -> RevisionManifest:
    """Read one revision's manifest, or raise a typed error. Never a ``TypeError``."""
    path = revision_dir(design_dir, revision_id) / REVISION_NAME
    if not path.is_file():
        raise _blocked(ErrorCode.MISSING_EVIDENCE, f"no revision {revision_id!r} in this design",
                       revision_id=revision_id, design_dir=str(design_dir))
    return _read_manifest(path)


# ------------------------------------------------------------------ the verdict on a preview

def derive_status(result: BuildResult) -> dict[str, Any]:
    """Read a build's own evidence and separate "this is wrong" from "we do not know".

    A failed **hard** check (anything not in :data:`ADVISORY_CHECKS` — interference, propeller
    clearance, every reimport/round-trip check, a check that could not run) makes the preview
    ``blocked`` and uncommittable. A failed **advisory** check leaves it ``ok`` and committable but
    sets ``verified`` false: the geometry is sound, the evidence for a claim about it is not.

    A caller may also declare the verdict outright by putting ``"edit_status"`` in
    ``BuildResult.content`` (``"ok"`` | ``"blocked"`` | ``"failed"``); a declared non-``ok`` status
    is honoured even when every check passed, because the caller may have refused for a reason the
    store cannot see. A declared ``"ok"`` never overrides a failed *hard* check — evidence beats a
    claim.

    Returns ``{"status", "blocking_checks", "advisory_checks", "failed_checks", "verified",
    "unverified_reasons"}``.
    """
    blocking, advisory, reasons = [], [], []
    for check in result.checks:
        if check.passed:
            continue
        (advisory if check.name in ADVISORY_CHECKS else blocking).append(check.name)
        reasons.append(f"{check.name}: {check.detail}" if check.detail else check.name)

    declared = result.content.get("edit_status") if isinstance(result.content, dict) else None
    if blocking:
        status = "blocked"
    elif isinstance(declared, str) and declared != COMMITTABLE_STATUS:
        status = declared
    else:
        status = COMMITTABLE_STATUS

    return {
        "status": status,
        "blocking_checks": blocking,
        "advisory_checks": advisory,
        "failed_checks": blocking + advisory,
        # "verified" is a claim about evidence, not about geometry: a committable preview whose
        # retention is unknown is a real change the UI must not describe as verified.
        "verified": status == COMMITTABLE_STATUS and not advisory,
        "unverified_reasons": reasons,
    }


def edit_status(design_dir: str | Path, revision_id: str) -> Optional[dict[str, Any]]:
    """The store's recorded verdict for a revision, or ``None`` for one that predates it.

    A revision written by ``dronebench_ingest.confirm`` has no verdict: it was never an edit. That
    is the only case ``None`` means "fine to commit".
    """
    path = revision_dir(design_dir, revision_id) / EDIT_STATUS_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"status": "failed", "reason": f"{EDIT_STATUS_NAME} is unreadable"}
    return data if isinstance(data, dict) else None


def _read_index(design_dir: str | Path) -> dict[str, str]:
    path = revisions_root(design_dir) / IDEMPOTENCY_NAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _index_key(parent_revision_id: Optional[str], idempotency_key: str) -> str:
    return f"{parent_revision_id or ''}::{idempotency_key}"


def _record_decision(design_dir: str | Path, **fields: Any) -> None:
    """Append one line to decisions.jsonl. Caller holds the lock."""
    path = revisions_root(design_dir) / DECISIONS_NAME
    with open(path, "a") as fh:
        fh.write(canonical_json({"recorded_at": _now(), **fields}) + "\n")


# ------------------------------------------------------------------ artifacts

def _collect_artifacts(workdir: Path, declared: list[Artifact]) -> list[Artifact]:
    """Re-hash every declared artifact from the bytes on disk; the builder's own hash is advisory.

    Paths must be relative and stay inside the working directory: a revision is self-contained, and
    an artifact pointing outside it would be a dangling reference the moment the design is copied.
    """
    out: list[Artifact] = []
    for artifact in declared:
        rel = artifact.path
        if os.path.isabs(rel) or rel.startswith("~"):
            raise _blocked(ErrorCode.INPUT_REJECTED,
                           f"artifact path {rel!r} is absolute; revision artifacts are relative",
                           path=rel)
        resolved = (workdir / rel).resolve()
        if not str(resolved).startswith(str(workdir.resolve()) + os.sep):
            raise _blocked(ErrorCode.INPUT_REJECTED,
                           f"artifact path {rel!r} escapes the revision directory", path=rel)
        if resolved.is_symlink() or not resolved.is_file():
            raise _blocked(ErrorCode.ARTIFACT_MISMATCH,
                           f"the build declared artifact {rel!r} but wrote no such file",
                           path=rel, workdir=str(workdir))
        out.append(artifact.model_copy(update={
            "path": Path(rel).as_posix(),
            "sha256": sha256_file(resolved),
        }))
    seen = sorted({a.path for a in out})
    if len(seen) != len(out):
        raise _blocked(ErrorCode.ARTIFACT_MISMATCH, "the build declared the same artifact twice",
                       paths=[a.path for a in out])
    for reserved in (REVISION_NAME, EDIT_STATUS_NAME):
        if reserved in seen:
            raise _blocked(ErrorCode.INPUT_REJECTED,
                           f"{reserved} is written by the store, not by the build", path=reserved)
    return sorted(out, key=lambda a: a.path)


# ------------------------------------------------------------------ the store

class RevisionStore:
    """The concrete ``Store`` (see ``api.Store``). Stateless: every call takes a design dir."""

    # -------------------------------------------------------------- creating

    def create_preview(self, design_dir: Path, parent_revision_id: str, cause: str,
                       build: Callable[[Path], BuildResult],
                       idempotency_key: Optional[str] = None) -> RevisionManifest:
        """Build into a temp dir and publish it as an immutable ``preview`` revision.

        The active pointer is never touched here — a preview is something to look at, not the
        design. If ``build`` raises anything at all the temp directory is deleted and the exception
        propagates unchanged, so a blocked or crashed edit leaves the design byte-identical.

        With an ``idempotency_key``, a repeat call under the same parent returns the revision the
        first call produced and ``build`` is not run again.
        """
        design_dir = Path(design_dir)
        parent = load_revision(design_dir, parent_revision_id)   # a preview needs a real parent
        root = revisions_root(design_dir)
        root.mkdir(parents=True, exist_ok=True)

        if idempotency_key:
            with _lock(design_dir):
                known = _read_index(design_dir).get(_index_key(parent_revision_id,
                                                               idempotency_key))
            if known and (revision_dir(design_dir, known) / REVISION_NAME).is_file():
                return load_revision(design_dir, known)

        workdir = root / f"{PARTIAL_PREFIX}{uuid.uuid4().hex[:12]}{PARTIAL_SUFFIX}"
        workdir.mkdir(parents=True)
        try:
            result = build(workdir)
            if not isinstance(result, BuildResult):
                raise _blocked(ErrorCode.ARTIFACT_MISMATCH,
                               "the build callback did not return a BuildResult",
                               returned=type(result).__name__)
            artifacts = _collect_artifacts(workdir, list(result.artifacts))

            # The verdict is written *into* the revision, next to the geometry it judges, so that
            # "may this become the design?" is answered by the revision itself and not by whatever
            # the caller happens to remember. commit() reads it back.
            verdict = derive_status(result)
            status = verdict["status"]
            blocking = verdict["blocking_checks"]
            status_path = workdir / EDIT_STATUS_NAME
            status_path.write_text(json.dumps({
                **verdict,
                "committable": status == COMMITTABLE_STATUS,
                "reason": (f"{len(blocking)} check(s) failed: {', '.join(blocking)}" if blocking
                           else None if status == COMMITTABLE_STATUS
                           else f"the build declared status {status!r}"),
                "cause": cause,
                "parent_revision_id": parent_revision_id,
                "checks": [c.model_dump(mode="json") for c in result.checks],
                "changes": list(result.changes),
                "affected_part_ids": list(result.affected_part_ids),
            }, indent=2, sort_keys=True) + "\n")
            artifacts = sorted([*artifacts, Artifact(path=EDIT_STATUS_NAME,
                                                     sha256=sha256_file(status_path),
                                                     media_type="application/json")],
                               key=lambda a: a.path)

            content_hash = content_sha256(parent_revision_id, cause, dict(result.content), status)
            revision_id = revision_id_for(content_hash)
            target = revision_dir(design_dir, revision_id)

            manifest = RevisionManifest(
                schema_version=SCHEMA_VERSION,
                design_id=parent.design_id,
                revision_id=revision_id,
                parent_revision_id=parent_revision_id,
                state=RevisionState.preview,
                content_sha256=content_hash,
                cause=cause,
                created_at=_now(),
                artifacts=artifacts,
            )
            with _lock(design_dir):
                index = _read_index(design_dir)
                key = _index_key(parent_revision_id, idempotency_key) if idempotency_key else None
                if key and (known := index.get(key)) \
                        and (revision_dir(design_dir, known) / REVISION_NAME).is_file():
                    # A concurrent caller won the race with the same key: theirs is the revision.
                    shutil.rmtree(workdir, ignore_errors=True)
                    return load_revision(design_dir, known)
                if (target / REVISION_NAME).is_file():
                    # Same content hash, so the same edit off the same parent: reuse it rather than
                    # mutate an immutable directory.
                    existing = _read_manifest(target / REVISION_NAME)
                    shutil.rmtree(workdir, ignore_errors=True)
                else:
                    (workdir / REVISION_NAME).write_text(
                        json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n")
                    if target.exists():                       # a leftover dir with no manifest
                        shutil.rmtree(target, ignore_errors=True)
                    os.replace(workdir, target)               # atomic publish
                    existing = manifest
                if key:
                    index[key] = existing.revision_id
                    _write_atomic(root / IDEMPOTENCY_NAME, json.dumps(index, indent=2,
                                                                      sort_keys=True) + "\n")
            return existing
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

    # -------------------------------------------------------------- committing / declining

    def commit(self, design_dir: Path, preview_revision_id: str,
               expected_active: Optional[str]) -> RevisionManifest:
        """Compare-and-swap the active pointer onto a preview, and mark that preview committed.

        Three gates, in this order, all of them typed refusals and none of them a crash:

        1. ``preview_revision_id`` must name a revision that exists (``INPUT_REJECTED`` /
           ``MISSING_EVIDENCE``). This is checked before any path is built from it.
        2. That revision's recorded verdict must be ``ok`` (``CONSTRAINT_FAILED``). A blocked edit
           is never the design, whatever the caller believes about it.
        3. Its artifacts must still be on disk with the hashes the manifest recorded
           (``ARTIFACT_MISMATCH``), so a commit can never publish a half-written revision.

        Then ``expected_active`` is compared against what is actually active. If it no longer
        matches, the commit raises ``STALE_REVISION`` naming both ids and nothing moves — approval
        of a preview built on one base never silently lands on another. Passing ``None`` waives
        that one check; only do that for the first commit of a design or a deliberate force.

        Rewriting the preview's own ``state`` to ``committed`` is the one edit a revision directory
        ever receives. Its artifacts and its content hash are untouched.
        """
        design_dir = Path(design_dir)
        preview_revision_id = check_revision_id(preview_revision_id, "preview_revision_id")
        manifest = load_revision(design_dir, preview_revision_id)
        self._require_committable(design_dir, manifest)
        with _lock(design_dir):
            current = self._active(design_dir)
            if expected_active is not None and current != expected_active:
                raise _blocked(
                    ErrorCode.STALE_REVISION,
                    f"expected active revision {expected_active!r} but {current!r} is active; "
                    f"preview {preview_revision_id!r} was built on a base that has moved",
                    expected_active=expected_active, actual_active=current,
                    preview_revision_id=preview_revision_id,
                    parent_revision_id=manifest.parent_revision_id)
            if manifest.state is not RevisionState.committed:
                committed = manifest.model_copy(update={"state": RevisionState.committed})
                _write_atomic(revision_dir(design_dir, preview_revision_id) / REVISION_NAME,
                              json.dumps(committed.model_dump(mode="json"), indent=2) + "\n")
            else:
                committed = manifest
            _write_atomic(revisions_root(design_dir) / ACTIVE_NAME, committed.revision_id + "\n")
            _record_decision(design_dir, decision="accepted",
                             revision_id=committed.revision_id,
                             parent_revision_id=committed.parent_revision_id,
                             previous_active=current, expected_active=expected_active,
                             content_sha256=committed.content_sha256)
        return committed

    def _require_committable(self, design_dir: Path, manifest: RevisionManifest) -> None:
        """Gates 2 and 3 of :meth:`commit`: the verdict, then the bytes."""
        verdict = edit_status(design_dir, manifest.revision_id)
        if verdict is not None and verdict.get("status") != COMMITTABLE_STATUS:
            raise _blocked(
                ErrorCode.CONSTRAINT_FAILED,
                f"preview {manifest.revision_id!r} is not committable: its recorded status is "
                f"{verdict.get('status')!r}"
                + (f" ({verdict['reason']})" if verdict.get("reason") else ""),
                preview_revision_id=manifest.revision_id,
                status=verdict.get("status"),
                reason=verdict.get("reason"),
                # The checks that caused the refusal. Advisory failures are listed separately and
                # never appear here: an evidence gap does not block an operation.
                failed_checks=verdict.get("blocking_checks", verdict.get("failed_checks", [])),
                advisory_checks=verdict.get("advisory_checks", []))

        directory = revision_dir(design_dir, manifest.revision_id)
        for artifact in manifest.artifacts:
            path = directory / artifact.path
            if not path.is_file():
                raise _blocked(ErrorCode.ARTIFACT_MISMATCH,
                               f"artifact {artifact.path!r} of preview {manifest.revision_id!r} is "
                               "missing; this revision cannot become the design",
                               preview_revision_id=manifest.revision_id, path=artifact.path)
            actual = sha256_file(path)
            if actual != artifact.sha256:
                raise _blocked(ErrorCode.ARTIFACT_MISMATCH,
                               f"artifact {artifact.path!r} of preview {manifest.revision_id!r} "
                               "does not match the hash its manifest recorded",
                               preview_revision_id=manifest.revision_id, path=artifact.path,
                               expected_sha256=artifact.sha256, actual_sha256=actual)

    def decline(self, design_dir: Path, preview_revision_id: str,
                reason: str) -> RevisionManifest:
        """Log a decision against a preview. No geometry changes, the active pointer stays put.

        A preview that was blocked can still be declined — declining is how a human disposes of it.
        """
        design_dir = Path(design_dir)
        preview_revision_id = check_revision_id(preview_revision_id, "preview_revision_id")
        manifest = load_revision(design_dir, preview_revision_id)
        with _lock(design_dir):
            _record_decision(design_dir, decision="declined", revision_id=preview_revision_id,
                             parent_revision_id=manifest.parent_revision_id, reason=reason,
                             active=self._active(design_dir),
                             content_sha256=manifest.content_sha256)
        return manifest

    def decisions(self, design_dir: Path) -> list[dict[str, Any]]:
        """The decision log, oldest first. Not part of the Store protocol; handy for the CLI."""
        path = revisions_root(design_dir) / DECISIONS_NAME
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    # -------------------------------------------------------------- reading

    def _active(self, design_dir: Path) -> Optional[str]:
        """The active id, or None. Caller holds the lock when it matters."""
        path = revisions_root(design_dir) / ACTIVE_NAME
        if path.is_file():
            pointer = path.read_text().strip()
            try:
                if pointer and (revision_dir(design_dir, pointer) / REVISION_NAME).is_file():
                    return pointer
            except EditBlocked:
                pass        # a pointer file someone hand-edited into nonsense is not a revision
        return self._newest_committed(design_dir)

    def _newest_committed(self, design_dir: Path) -> Optional[str]:
        """Fall back to the newest committed revision, which is what A1's ``confirm`` leaves.

        A design that has only been confirmed has no pointer file yet; the confirmed revision is
        plainly the active one, and reading it is not a mutation, so the pointer is only written
        when something commits.
        """
        committed = [m for m in self.history(design_dir) if m.state is RevisionState.committed]
        return committed[0].revision_id if committed else None

    def active_or_none(self, design_dir: Path) -> Optional[str]:
        """Like :meth:`active_revision` but ``None`` instead of raising, for reports."""
        return self._active(Path(design_dir))

    def active_revision(self, design_dir: Path) -> str:
        """The revision every metric and every new edit is measured against."""
        active = self._active(Path(design_dir))
        if active is None:
            raise _blocked(ErrorCode.MISSING_EVIDENCE,
                           "this design has no committed revision; confirm it first",
                           design_dir=str(design_dir))
        return active

    def history(self, design_dir: Path) -> list[RevisionManifest]:
        """Every revision, newest first, with ``parent_revision_id`` links intact.

        Ordered by ``created_at`` descending and tie-broken so that a child never sorts above its
        own parent — clocks are coarse enough that a preview can share a timestamp with its base.

        Only ``revision_manifest.json`` is read. A revision that carries no ``design_manifest.json``
        (an edit revision whose builder did not carry the parts list forward) still appears in the
        history and can still be the active revision; a directory whose own manifest is unreadable
        is not a revision and is skipped rather than taking the whole listing down with it.
        """
        root = revisions_root(design_dir)
        if not root.is_dir():
            return []
        manifests: list[RevisionManifest] = []
        for path in sorted(root.glob("rev-*")):
            manifest_path = path / REVISION_NAME
            if manifest_path.is_file():
                try:
                    manifests.append(_read_manifest(manifest_path))
                except (ValueError, OSError):
                    continue
        by_id = {m.revision_id: m for m in manifests}

        def depth(manifest: RevisionManifest) -> int:
            seen, n, cur = set(), 0, manifest
            while cur.parent_revision_id and cur.parent_revision_id in by_id:
                if cur.revision_id in seen:
                    break
                seen.add(cur.revision_id)
                cur = by_id[cur.parent_revision_id]
                n += 1
            return n

        return sorted(manifests,
                      key=lambda m: (m.created_at or "", depth(m), m.revision_id),
                      reverse=True)


# A module-level instance: the store holds no state, so there is nothing to construct per call.
store = RevisionStore()

create_preview = store.create_preview
commit = store.commit
decline = store.decline
active_revision = store.active_revision
active_or_none = store.active_or_none
history = store.history
decisions = store.decisions
