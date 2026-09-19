"""Accept, decline, and undo (architecture section 7, Transaction/state machine).

The rules this module implements, stated as the properties they produce:

* **Decline changes nothing.** It records a decision and leaves every design hash untouched.
* **Accept commits precisely the reviewed preview.** The request quotes ``preview_hash``; a
  mismatch is refused rather than silently committing whatever the latest preview happens to be.
* **A repeated idempotency key returns the same outcome.** The key is the primary key of the
  decisions table, so the second call reads the stored outcome instead of acting again.
* **A racing acceptance conflicts.** ``BEGIN IMMEDIATE`` plus a conditional ``UPDATE ... WHERE
  active_revision_id = ?`` makes the pointer switch a genuine compare-and-swap.
* **A failed commit leaves the active revision unchanged.** The pointer moves last, inside the same
  transaction that records the decision.

Approval of one preview does not authorise recalculating a different edit after another commit:
once the active revision has moved, previously reviewed previews become ``stale`` and must be
regenerated.
"""

from __future__ import annotations

import json
from typing import Callable

from dronebench_contracts import (
    DecisionOutcome,
    DecisionRequest,
    DroneBenchError,
    Recommendation,
    RevisionManifest,
    assert_transition,
    canonical_json,
    stale_revision,
)

from .db import transaction
from .repository import Repository, _now
from .revisions import RevisionService

#: Called with the accepted proposal and its preview manifest; returns the manifest to commit.
CommitBuilder = Callable[[Recommendation, RevisionManifest], RevisionManifest]


class TransactionService:
    """The decision path. Nothing else may move the active revision pointer."""

    def __init__(self, repository: Repository, revisions: RevisionService) -> None:
        self.repository = repository
        self.revisions = revisions

    # -- entry point -------------------------------------------------------------------------

    def decide(
        self,
        request: DecisionRequest,
        *,
        build_commit: CommitBuilder,
    ) -> DecisionOutcome:
        """Apply an accept or decline. Idempotent on ``request.idempotency_key``."""
        replayed = self._replay(request)
        if replayed is not None:
            return replayed

        proposal = self.repository.get_proposal(request.proposal_id)
        design_id = proposal.design_id

        if request.decision == "decline":
            return self._decline(request, proposal)

        return self._accept(request, proposal, design_id=design_id, build_commit=build_commit)

    # -- idempotency -------------------------------------------------------------------------

    def _replay(self, request: DecisionRequest) -> DecisionOutcome | None:
        row = self.repository.connection.execute(
            "SELECT proposal_id, decision, outcome_json FROM decisions WHERE idempotency_key = ?",
            (request.idempotency_key,),
        ).fetchone()
        if row is None:
            return None

        if row["proposal_id"] != request.proposal_id or row["decision"] != request.decision:
            # The same key used for different work is a client bug, not a replay. Returning the
            # stored outcome here would silently answer the wrong question.
            raise DroneBenchError.of(
                "CONFLICT",
                "this idempotency key was already used for a different decision",
                idempotency_key=request.idempotency_key,
                stored_proposal_id=row["proposal_id"],
                stored_decision=row["decision"],
            )

        stored = DecisionOutcome.model_validate(json.loads(row["outcome_json"]))
        return stored.model_copy(update={"replayed": True})

    def _record(self, request: DecisionRequest, outcome: DecisionOutcome) -> None:
        self.repository.connection.execute(
            "INSERT OR IGNORE INTO decisions (idempotency_key, proposal_id, decision, "
            "outcome_json, created_at) VALUES (?,?,?,?,?)",
            (
                request.idempotency_key,
                request.proposal_id,
                request.decision,
                canonical_json(outcome.model_dump(mode="json")),
                _now(),
            ),
        )

    # -- decline -----------------------------------------------------------------------------

    def _decline(self, request: DecisionRequest, proposal: Recommendation) -> DecisionOutcome:
        """Record the decision. No revision is created and no pointer moves."""
        assert_transition(proposal.state, "declined")
        active = self.repository.require_active_revision_id(proposal.design_id)

        declined = proposal.transition("declined")
        outcome = DecisionOutcome(
            proposal_id=proposal.proposal_id,
            decision="decline",
            state="declined",
            active_revision_id=active,
            committed_revision_id=None,
            idempotency_key=request.idempotency_key,
            message=request.reason or "declined; no geometry, BOM, or report changed",
        )
        self.repository.put_proposal(declined)
        self._record(request, outcome)
        self.repository.append_event(
            design_id=proposal.design_id,
            kind="proposal_declined",
            tool_name="workflow.decide",
            revision_id=active,
            proposal_id=proposal.proposal_id,
            inputs_summary={"decision": "decline", "reason": (request.reason or "")[:200]},
        )
        return outcome

    # -- accept ------------------------------------------------------------------------------

    def _accept(
        self,
        request: DecisionRequest,
        proposal: Recommendation,
        *,
        design_id: str,
        build_commit: CommitBuilder,
    ) -> DecisionOutcome:
        preview = proposal.preview
        if preview is None:
            raise DroneBenchError.of(
                "CONSTRAINT_FAILED",
                f"proposal {proposal.proposal_id} has no preview to accept",
                revision_id=proposal.base_revision_id,
            )

        # The user must be accepting the exact artifact they reviewed.
        if request.preview_hash != preview.preview_hash:
            # CONFLICT, not ARTIFACT_MISMATCH: the stored bytes are fine, the client is naming a
            # preview that is no longer current. ARTIFACT_MISMATCH is reserved for a checksum that
            # actually fails to verify, which is a server fault and answers 500.
            raise DroneBenchError.of(
                "CONFLICT",
                "the accepted preview hash does not match the proposal's current preview; "
                "re-open the proposal and review the current preview",
                revision_id=preview.preview_revision_id,
                submitted_preview_hash=request.preview_hash,
                current_preview_hash=preview.preview_hash,
            )

        if not preview.acceptable:
            reasons = list(preview.blocked_reasons)
            if preview.evaluation is not None:
                reasons += [
                    f"{c.check_id}: {c.status}" for c in preview.evaluation.blocking()
                ]
            raise DroneBenchError.of(
                "CONSTRAINT_FAILED",
                "this preview is not acceptable; geometry or a blocking check prevents commit",
                revision_id=preview.preview_revision_id,
                blocked_by=reasons,
            )

        # Cheap pre-check before the expensive build. This does not replace the compare-and-swap
        # below - another writer can still move the pointer in between - but it means the common
        # case of a plainly stale proposal costs a read instead of a full revision build.
        current = self.repository.active_revision_id(design_id)
        if current != request.expected_active_revision_id:
            self._stale(design_id, proposal, request, current)
            raise stale_revision(
                request.expected_active_revision_id, str(current), design_id=design_id
            )

        assert_transition(proposal.state, "committing")
        committing = proposal.transition("committing")
        self.repository.put_proposal(committing)

        preview_manifest = self.repository.get_manifest(preview.preview_revision_id)

        # Build the committed revision *outside* the write transaction: it writes artifacts to
        # disk, and holding the database write lock across filesystem work would serialise the
        # whole app. Nothing is visible until the pointer swap below succeeds.
        try:
            committed = build_commit(committing, preview_manifest)
        except DroneBenchError:
            self._fail(committing, request)
            raise
        except Exception as exc:
            self._fail(committing, request)
            raise DroneBenchError.of(
                "INTERNAL",
                f"building the committed revision failed: {exc}",
                revision_id=preview.preview_revision_id,
            ) from exc

        # Compare-and-swap. BEGIN IMMEDIATE takes the write lock before the read, so no other
        # writer can move the pointer between the check and the update.
        #
        # A stale base is signalled by leaving this block with `outcome` unset rather than by
        # raising inside it: the rollback has to complete before the proposal can be marked stale,
        # because both writes want the same lock.
        outcome: DecisionOutcome | None = None
        actual: str | None = None

        with transaction(self.repository.connection) as db:
            row = db.execute(
                "SELECT active_revision_id FROM designs WHERE design_id = ?", (design_id,)
            ).fetchone()
            actual = row["active_revision_id"] if row else None

            if actual == request.expected_active_revision_id:
                updated = db.execute(
                    "UPDATE designs SET active_revision_id = ? WHERE design_id = ? "
                    "AND active_revision_id IS ?",
                    (
                        committed.revision.revision_id,
                        design_id,
                        request.expected_active_revision_id,
                    ),
                )
                if updated.rowcount != 1:  # pragma: no cover - the lock should prevent this
                    raise DroneBenchError.of(
                        "CONFLICT",
                        "the active revision pointer changed during the swap",
                        revision_id=str(actual),
                    )
                # The revision joins the history only now, in the same transaction as the pointer
                # move. A commit that loses this race stays on disk but never enters the timeline.
                self.repository.mark_activated(committed.revision.revision_id, db)
                outcome = self._commit_outcome(db, request, proposal, committed)

        if outcome is None:
            self._stale(design_id, committing, request, actual)
            raise stale_revision(
                request.expected_active_revision_id, str(actual), design_id=design_id
            )

        self.repository.put_proposal(committing.transition("committed"))
        self.repository.append_event(
            design_id=design_id,
            kind="proposal_committed",
            tool_name="workflow.decide",
            revision_id=committed.revision.revision_id,
            proposal_id=proposal.proposal_id,
            artifact_ids=[a.artifact_id for a in committed.artifacts],
            inputs_summary={
                "operation": proposal.operation.operation,
                "preview": preview.preview_revision_id,
            },
        )
        return outcome

    def _commit_outcome(
        self,
        db,
        request: DecisionRequest,
        proposal: Recommendation,
        committed: RevisionManifest,
    ) -> DecisionOutcome:
        """Record the committed state and the idempotency entry inside the CAS transaction.

        The outcome row and the pointer move land together; a crash between them is impossible, so
        a replay can never report a commit that did not happen.
        """
        outcome = DecisionOutcome(
                proposal_id=proposal.proposal_id,
                decision="accept",
                state="committed",
                active_revision_id=committed.revision.revision_id,
                committed_revision_id=committed.revision.revision_id,
            idempotency_key=request.idempotency_key,
            message=f"committed {committed.revision.revision_id}",
        )
        db.execute(
            "UPDATE proposals SET state = 'committed', updated_at = ? WHERE proposal_id = ?",
            (_now(), proposal.proposal_id),
        )
        db.execute(
            "INSERT OR IGNORE INTO decisions (idempotency_key, proposal_id, decision, "
            "outcome_json, created_at) VALUES (?,?,?,?,?)",
            (
                request.idempotency_key,
                request.proposal_id,
                "accept",
                canonical_json(outcome.model_dump(mode="json")),
                _now(),
            ),
        )
        return outcome

    def _stale(
        self,
        design_id: str,
        proposal: Recommendation,
        request: DecisionRequest,
        actual: str | None,
    ) -> None:
        """Mark a proposal stale after the CAS transaction has released the write lock."""
        self.repository.put_proposal(proposal.model_copy(update={"state": "stale"}))
        self.repository.append_event(
            design_id=design_id,
            kind="proposal_stale",
            tool_name="workflow.decide",
            revision_id=actual,
            proposal_id=proposal.proposal_id,
            inputs_summary={
                "expected": request.expected_active_revision_id,
                "actual": str(actual),
            },
            status="error",
            error_code="STALE_REVISION",
        )

    def _fail(self, proposal: Recommendation, request: DecisionRequest) -> None:
        self.repository.put_proposal(proposal.transition("failed"))
        self.repository.append_event(
            design_id=proposal.design_id,
            kind="proposal_stale",
            tool_name="workflow.decide",
            proposal_id=proposal.proposal_id,
            revision_id=proposal.base_revision_id,
            status="error",
            error_code="INTERNAL",
            inputs_summary={"idempotency_key": request.idempotency_key},
        )

    # -- undo --------------------------------------------------------------------------------

    def undo(self, design_id: str, *, to_revision_id: str | None = None) -> str:
        """Switch to an existing validated revision.

        Section 7: undo does not ask a model to invent an inverse edit. It moves the pointer to a
        revision that already exists and already passed validation, or refuses.
        """
        history = self.repository.revision_history(design_id)
        if len(history) < 2 and to_revision_id is None:
            raise DroneBenchError.of(
                "CONSTRAINT_FAILED",
                "there is no earlier committed revision to return to",
                revision_id=history[-1].revision_id if history else None,
            )

        active = self.repository.require_active_revision_id(design_id)
        if to_revision_id is None:
            index = next(
                (i for i, rev in enumerate(history) if rev.revision_id == active), len(history) - 1
            )
            if index == 0:
                raise DroneBenchError.of(
                    "CONSTRAINT_FAILED",
                    "already at the earliest committed revision",
                    revision_id=active,
                )
            target = history[index - 1].revision_id
        else:
            target = to_revision_id
            revision = self.repository.get_revision(target)
            if revision.design_id != design_id:
                raise DroneBenchError.of(
                    "INVALID_REQUEST", f"{target} belongs to another design", revision_id=target
                )
            if revision.stage == "staged_preview":
                raise DroneBenchError.of(
                    "CONSTRAINT_FAILED",
                    "undo targets a revision the design was actually in; a preview is not one",
                    revision_id=target,
                )
            if target not in {r.revision_id for r in history}:
                raise DroneBenchError.of(
                    "CONSTRAINT_FAILED",
                    "undo targets a revision this design was never in",
                    revision_id=target,
                )

        # The target's artifacts must still verify, or "a coherent known revision" is a fiction.
        self.revisions.verify_all(target)

        with transaction(self.repository.connection) as db:
            db.execute(
                "UPDATE designs SET active_revision_id = ? WHERE design_id = ? "
                "AND active_revision_id = ?",
                (target, design_id, active),
            )
            self.repository.mark_activated(target, db)
        self.repository.append_event(
            design_id=design_id,
            kind="revision_activated",
            tool_name="workflow.undo",
            revision_id=target,
            inputs_summary={"from": active, "to": target},
        )
        return target

    def activate(self, design_id: str, revision_id: str) -> None:
        """Set the first active revision, or move it during import/confirm."""
        with transaction(self.repository.connection) as db:
            db.execute(
                "UPDATE designs SET active_revision_id = ? WHERE design_id = ?",
                (revision_id, design_id),
            )
            self.repository.mark_activated(revision_id, db)
        self.repository.append_event(
            design_id=design_id,
            kind="revision_activated",
            tool_name="workflow.activate",
            revision_id=revision_id,
        )
