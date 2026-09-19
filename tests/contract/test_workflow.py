"""Workflow checks (architecture section 13).

"Decline changes no geometry; accept commits precisely the reviewed preview; a repeated idempotency
key returns the same outcome; racing/stale acceptance returns conflict; worker failure leaves
active revision unchanged; undo restores a coherent known revision; no partly updated
BOM/STEP/report set."

Each sentence has a test below, named after it.
"""

from __future__ import annotations

import threading

import pytest

from dronebench_contracts import (
    DecisionRequest,
    DroneBenchError,
    IllegalTransition,
    REQUIRED_COMMITTED_ROLES,
    assert_transition,
)
from dronebench_workflow.store import ImmutabilityError

from tests.conftest import DESIGN_ID


def _proposal(recommendations, proposal_id):
    return next(r for r in recommendations.generated if r.proposal_id == proposal_id)


# ---------------------------------------------------------------------------------------------
# Decline changes nothing
# ---------------------------------------------------------------------------------------------


def test_decline_changes_no_geometry(reviewed):
    workbench, revision_id, recommendations = reviewed
    proposal = _proposal(recommendations, "rec_spar-resize")

    before_active = workbench.active_revision(DESIGN_ID)
    before_hash = workbench.get_revision(before_active).revision.content_hash
    before_parts = workbench.get_parts(before_active).model_dump(mode="json")

    outcome = workbench.decide(
        DecisionRequest(
            proposal_id=proposal.proposal_id,
            decision="decline",
            expected_active_revision_id=before_active,
            idempotency_key="decline-0000001",
            reason="the mass cost is not justified",
        )
    )

    assert outcome.state == "declined"
    assert outcome.committed_revision_id is None
    assert workbench.active_revision(DESIGN_ID) == before_active
    assert workbench.get_revision(before_active).revision.content_hash == before_hash
    assert workbench.get_parts(before_active).model_dump(mode="json") == before_parts


def test_decline_is_recorded_as_an_event(reviewed):
    workbench, revision_id, recommendations = reviewed
    proposal = _proposal(recommendations, "rec_spar-resize")
    workbench.decide(
        DecisionRequest(
            proposal_id=proposal.proposal_id,
            decision="decline",
            expected_active_revision_id=workbench.active_revision(DESIGN_ID),
            idempotency_key="decline-0000002",
        )
    )
    kinds = [e.kind for e in workbench.events(DESIGN_ID)]
    assert "proposal_declined" in kinds


# ---------------------------------------------------------------------------------------------
# Accept commits precisely the reviewed preview
# ---------------------------------------------------------------------------------------------


def test_accept_commits_precisely_the_reviewed_preview(reviewed):
    workbench, revision_id, recommendations = reviewed
    proposal = _proposal(recommendations, "rec_battery-cg")
    assert proposal.state == "review_ready"

    reviewed_parts = workbench.get_parts(proposal.preview.preview_revision_id).model_dump(
        mode="json"
    )

    outcome = workbench.decide(
        DecisionRequest(
            proposal_id=proposal.proposal_id,
            decision="accept",
            expected_active_revision_id=revision_id,
            preview_hash=proposal.preview.preview_hash,
            idempotency_key="accept-00000001",
        )
    )

    assert outcome.state == "committed"
    committed = outcome.committed_revision_id
    assert workbench.active_revision(DESIGN_ID) == committed

    committed_parts = workbench.get_parts(committed).model_dump(mode="json")
    # The identity differs - it is a new revision - but everything that describes the design is
    # byte-identical to what the user reviewed.
    reviewed_parts.pop("revision_id")
    committed_parts.pop("revision_id")
    assert committed_parts == reviewed_parts


def test_accepting_a_hash_that_is_not_the_current_preview_is_refused(reviewed):
    workbench, revision_id, recommendations = reviewed
    proposal = _proposal(recommendations, "rec_battery-cg")
    before = workbench.active_revision(DESIGN_ID)

    with pytest.raises(DroneBenchError) as excinfo:
        workbench.decide(
            DecisionRequest(
                proposal_id=proposal.proposal_id,
                decision="accept",
                expected_active_revision_id=revision_id,
                preview_hash="0" * 64,
                idempotency_key="accept-badhash1",
            )
        )
    assert excinfo.value.envelope.code == "CONFLICT"
    assert workbench.active_revision(DESIGN_ID) == before


def test_a_blocked_preview_cannot_be_accepted(reviewed):
    """The spar proposal leaves the CG check failing, so it is not acceptable."""
    workbench, revision_id, recommendations = reviewed
    proposal = _proposal(recommendations, "rec_spar-resize")
    assert proposal.state == "blocked"
    before = workbench.active_revision(DESIGN_ID)

    with pytest.raises(DroneBenchError) as excinfo:
        workbench.decide(
            DecisionRequest(
                proposal_id=proposal.proposal_id,
                decision="accept",
                expected_active_revision_id=revision_id,
                preview_hash=proposal.preview.preview_hash,
                idempotency_key="accept-blocked1",
            )
        )
    assert excinfo.value.envelope.code == "CONSTRAINT_FAILED"
    assert workbench.active_revision(DESIGN_ID) == before


# ---------------------------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------------------------


def test_a_repeated_idempotency_key_returns_the_same_outcome(reviewed):
    workbench, revision_id, recommendations = reviewed
    proposal = _proposal(recommendations, "rec_battery-cg")
    request = DecisionRequest(
        proposal_id=proposal.proposal_id,
        decision="accept",
        expected_active_revision_id=revision_id,
        preview_hash=proposal.preview.preview_hash,
        idempotency_key="accept-idem-0001",
    )

    first = workbench.decide(request)
    revisions_after_first = len(workbench.history(DESIGN_ID))
    second = workbench.decide(request)

    assert second.replayed is True
    assert first.replayed is False
    assert second.committed_revision_id == first.committed_revision_id
    assert second.state == first.state
    assert len(workbench.history(DESIGN_ID)) == revisions_after_first, (
        "a replay must not create a second revision"
    )


def test_reusing_a_key_for_different_work_is_refused(reviewed):
    workbench, revision_id, recommendations = reviewed
    cg = _proposal(recommendations, "rec_battery-cg")
    spar = _proposal(recommendations, "rec_spar-resize")

    workbench.decide(
        DecisionRequest(
            proposal_id=spar.proposal_id,
            decision="decline",
            expected_active_revision_id=revision_id,
            idempotency_key="shared-key-0001",
        )
    )
    with pytest.raises(DroneBenchError) as excinfo:
        workbench.decide(
            DecisionRequest(
                proposal_id=cg.proposal_id,
                decision="accept",
                expected_active_revision_id=revision_id,
                preview_hash=cg.preview.preview_hash,
                idempotency_key="shared-key-0001",
            )
        )
    assert excinfo.value.envelope.code == "CONFLICT"


# ---------------------------------------------------------------------------------------------
# Stale acceptance
# ---------------------------------------------------------------------------------------------


def test_stale_acceptance_returns_conflict_and_moves_nothing(reviewed):
    workbench, revision_id, recommendations = reviewed
    cg = _proposal(recommendations, "rec_battery-cg")

    workbench.decide(
        DecisionRequest(
            proposal_id=cg.proposal_id,
            decision="accept",
            expected_active_revision_id=revision_id,
            preview_hash=cg.preview.preview_hash,
            idempotency_key="accept-first-01",
        )
    )
    moved_to = workbench.active_revision(DESIGN_ID)

    regenerated = workbench.recommend(moved_to)
    spar = _proposal(regenerated, "rec_spar-resize")

    with pytest.raises(DroneBenchError) as excinfo:
        workbench.decide(
            DecisionRequest(
                proposal_id=spar.proposal_id,
                decision="accept",
                expected_active_revision_id=revision_id,  # the superseded base
                preview_hash=spar.preview.preview_hash,
                idempotency_key="accept-stale-01",
            )
        )
    assert excinfo.value.envelope.code == "STALE_REVISION"
    assert workbench.active_revision(DESIGN_ID) == moved_to


def test_a_commit_that_loses_the_race_never_enters_the_history(reviewed):
    """A revision built but never activated is not a state the design was in."""
    workbench, revision_id, recommendations = reviewed
    cg = _proposal(recommendations, "rec_battery-cg")
    workbench.decide(
        DecisionRequest(
            proposal_id=cg.proposal_id,
            decision="accept",
            expected_active_revision_id=revision_id,
            preview_hash=cg.preview.preview_hash,
            idempotency_key="accept-race-001",
        )
    )
    moved_to = workbench.active_revision(DESIGN_ID)
    regenerated = workbench.recommend(moved_to)
    spar = _proposal(regenerated, "rec_spar-resize")

    with pytest.raises(DroneBenchError):
        workbench.decide(
            DecisionRequest(
                proposal_id=spar.proposal_id,
                decision="accept",
                expected_active_revision_id=revision_id,
                preview_hash=spar.preview.preview_hash,
                idempotency_key="accept-race-002",
            )
        )

    labels = [r.label for r in workbench.history(DESIGN_ID)]
    assert not any("spar" in label.lower() for label in labels), (
        "a stale commit leaked into the timeline"
    )


def test_previews_never_appear_in_the_history(reviewed):
    workbench, revision_id, recommendations = reviewed
    preview_ids = {
        r.preview.preview_revision_id for r in recommendations.generated if r.preview is not None
    }
    history_ids = {r.revision_id for r in workbench.history(DESIGN_ID)}
    assert preview_ids.isdisjoint(history_ids)


# ---------------------------------------------------------------------------------------------
# Worker failure
# ---------------------------------------------------------------------------------------------


def test_worker_failure_leaves_the_active_revision_unchanged(confirmed):
    workbench, revision_id = confirmed
    before = workbench.active_revision(DESIGN_ID)

    def exploding(work_dir: str, cancel: threading.Event) -> list[str]:
        raise RuntimeError("the worker died")

    job = workbench.jobs.submit(
        kind="evaluate",
        design_id=DESIGN_ID,
        revision_id=revision_id,
        cache_key="f" * 64,
        work=exploding,
        allow_cache=False,
    )
    job = workbench.jobs.wait(job.job_id)

    assert job.status == "failed"
    assert job.error_code == "INTERNAL"
    assert workbench.active_revision(DESIGN_ID) == before


def test_a_cancelled_job_is_recorded_as_cancelled(confirmed):
    workbench, revision_id = confirmed
    started = threading.Event()
    release = threading.Event()

    def slow(work_dir: str, cancel: threading.Event) -> list[str]:
        from dronebench_workflow.jobs import JobCancelled

        started.set()
        release.wait(timeout=5)
        if cancel.is_set():
            raise JobCancelled()
        return []

    job = workbench.jobs.submit(
        kind="simulate",
        design_id=DESIGN_ID,
        revision_id=revision_id,
        cache_key="e" * 64,
        work=slow,
        allow_cache=False,
    )
    started.wait(timeout=5)
    assert workbench.jobs.cancel(job.job_id) is True
    release.set()
    assert workbench.jobs.wait(job.job_id).status == "cancelled"


# ---------------------------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------------------------


def test_undo_restores_a_coherent_known_revision(reviewed):
    workbench, revision_id, recommendations = reviewed
    cg = _proposal(recommendations, "rec_battery-cg")
    workbench.decide(
        DecisionRequest(
            proposal_id=cg.proposal_id,
            decision="accept",
            expected_active_revision_id=revision_id,
            preview_hash=cg.preview.preview_hash,
            idempotency_key="accept-undo-001",
        )
    )
    committed = workbench.active_revision(DESIGN_ID)
    assert committed != revision_id

    restored = workbench.undo(DESIGN_ID)
    assert restored == revision_id
    assert workbench.active_revision(DESIGN_ID) == revision_id
    # Coherent means every artifact still verifies against its recorded checksum.
    roles = workbench.revisions.verify_all(restored)
    assert REQUIRED_COMMITTED_ROLES <= set(roles)


def test_undo_will_not_target_a_preview(reviewed):
    workbench, revision_id, recommendations = reviewed
    preview_id = recommendations.generated[0].preview.preview_revision_id
    with pytest.raises(DroneBenchError) as excinfo:
        workbench.undo(DESIGN_ID, to_revision_id=preview_id)
    assert excinfo.value.envelope.code == "CONSTRAINT_FAILED"


# ---------------------------------------------------------------------------------------------
# No partly updated artifact set
# ---------------------------------------------------------------------------------------------


def test_a_committed_revision_carries_a_complete_artifact_set(reviewed):
    workbench, revision_id, recommendations = reviewed
    cg = _proposal(recommendations, "rec_battery-cg")
    outcome = workbench.decide(
        DecisionRequest(
            proposal_id=cg.proposal_id,
            decision="accept",
            expected_active_revision_id=revision_id,
            preview_hash=cg.preview.preview_hash,
            idempotency_key="accept-complete1",
        )
    )
    manifest = workbench.get_revision(outcome.committed_revision_id)
    assert REQUIRED_COMMITTED_ROLES <= set(manifest.roles())


def test_a_committed_revision_missing_an_artifact_is_refused(confirmed):
    workbench, revision_id = confirmed
    builder = workbench.revisions.builder(
        design_id=DESIGN_ID,
        parent_revision_id=revision_id,
        stage="committed",
        cause="manual_edit",
        mission=workbench.repository.design_mission(DESIGN_ID),
        label="incomplete",
    )
    builder.add_json(
        role="parts",
        relative_path="parts.json",
        payload=workbench.get_parts(revision_id),
        produced_by="A",
    )
    with pytest.raises(DroneBenchError) as excinfo:
        builder.seal(workbench.repository)
    assert excinfo.value.envelope.code == "ARTIFACT_MISMATCH"


def test_revision_artifacts_are_append_only(confirmed):
    workbench, revision_id = confirmed
    with pytest.raises(ImmutabilityError):
        workbench.store.write(
            design_id=DESIGN_ID,
            revision_id=revision_id,
            relative_path="parts.json",
            data=b'{"tampered": true}',
            media_type="application/json",
            produced_by="A",
            role="parts",
        )


def test_rewriting_identical_bytes_is_a_no_op(confirmed):
    workbench, revision_id = confirmed
    existing = workbench.store.read(
        design_id=DESIGN_ID, revision_id=revision_id, relative_path="parts.json"
    )
    artifact = workbench.store.write(
        design_id=DESIGN_ID,
        revision_id=revision_id,
        relative_path="parts.json",
        data=existing,
        media_type="application/json",
        produced_by="A",
        role="parts",
    )
    assert artifact.size_bytes == len(existing)


def test_a_tampered_artifact_fails_verification(confirmed):
    workbench, revision_id = confirmed
    manifest = workbench.get_revision(revision_id)
    artifact = manifest.require("parts")
    path = workbench.store.revision_dir(DESIGN_ID, revision_id) / artifact.relative_path
    path.write_bytes(b'{"tampered": true}')

    with pytest.raises(DroneBenchError) as excinfo:
        workbench.revisions.verify_all(revision_id)
    assert excinfo.value.envelope.code == "ARTIFACT_MISMATCH"


# ---------------------------------------------------------------------------------------------
# The state machine itself
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current,target",
    [
        ("proposed", "committed"),
        ("proposed", "review_ready"),
        ("declined", "committing"),
        ("committed", "declined"),
        ("review_ready", "previewing"),
        ("blocked", "committing"),
    ],
)
def test_illegal_transitions_are_refused(current, target):
    with pytest.raises(IllegalTransition):
        assert_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        ("proposed", "previewing"),
        ("previewing", "review_ready"),
        ("previewing", "blocked"),
        ("review_ready", "declined"),
        ("review_ready", "committing"),
        ("committing", "committed"),
        ("committing", "stale"),
    ],
)
def test_legal_transitions_are_allowed(current, target):
    assert_transition(current, target)
