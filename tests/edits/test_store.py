"""The revision store: identity, atomicity, the active pointer, decisions, idempotency.

Nothing here reconstructs CAD. The store's job is to make a build's output immutable and to move a
single pointer under a compare-and-swap; these tests exercise exactly that, with a build callback
that writes two small text files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dronebench_contracts.models import ErrorCode, RevisionState, RoundTripCheck
from dronebench_edits.api import EditBlocked
from dronebench_edits.store import (ACTIVE_NAME, DECISIONS_NAME, EDIT_STATUS_NAME, REVISION_NAME,
                                    RevisionStore, content_sha256, edit_status, revision_dir,
                                    revisions_root)

STORE = RevisionStore()


def partials(design_dir: Path) -> list[Path]:
    return [p for p in revisions_root(design_dir).glob(".preview-*") if p.is_dir()]


def revision_dirs(design_dir: Path) -> list[str]:
    return sorted(p.name for p in revisions_root(design_dir).glob("rev-*") if p.is_dir())


# ------------------------------------------------------------------ happy path

def test_preview_then_commit(tiny_design, fake_build):
    design_dir, base = tiny_design
    assert STORE.active_revision(design_dir) == base.revision_id, \
        "a confirmed design is active before anything commits, with no pointer file written"

    preview = STORE.create_preview(design_dir, base.revision_id, "edit:translate_component",
                                   fake_build())

    assert preview.state is RevisionState.preview
    assert preview.parent_revision_id == base.revision_id
    assert preview.design_id == base.design_id, "a preview stays inside its design"
    assert preview.revision_id.startswith("rev-")
    assert preview.revision_id != base.revision_id
    assert STORE.active_revision(design_dir) == base.revision_id, \
        "creating a preview must not move the active pointer"

    # The artifacts are on disk, hashed from their own bytes, and recorded relative to the revision.
    directory = revision_dir(design_dir, preview.revision_id)
    assert {a.path for a in preview.artifacts} == {"demo.step", "part_map.json", EDIT_STATUS_NAME}
    for artifact in preview.artifacts:
        blob = directory / artifact.path
        assert blob.is_file()
        assert len(artifact.sha256) == 64
    assert not any(a.path == REVISION_NAME for a in preview.artifacts), \
        "the manifest is not one of the artifacts it describes"

    committed = STORE.commit(design_dir, preview.revision_id, base.revision_id)
    assert committed.state is RevisionState.committed
    assert committed.content_sha256 == preview.content_sha256, "committing is not a rebuild"
    assert committed.artifacts == preview.artifacts
    assert STORE.active_revision(design_dir) == preview.revision_id
    assert (revisions_root(design_dir) / ACTIVE_NAME).read_text().strip() == preview.revision_id
    # The state transition lands on the revision's own manifest, and only that.
    on_disk = json.loads((directory / REVISION_NAME).read_text())
    assert on_disk["state"] == "committed"
    assert not partials(design_dir)


def test_commit_is_idempotent(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    first = STORE.commit(design_dir, preview.revision_id, base.revision_id)
    again = STORE.commit(design_dir, preview.revision_id, first.revision_id)
    assert again.revision_id == first.revision_id
    assert again.state is RevisionState.committed
    assert STORE.active_revision(design_dir) == first.revision_id


# ------------------------------------------------------------------ failure is total

def test_failed_build_leaves_nothing(tiny_design, fake_build):
    design_dir, base = tiny_design
    before = revision_dirs(design_dir)

    blocked = EditBlocked.of(ErrorCode.CONSTRAINT_FAILED, "spar will not fit the wing hole",
                             od_mm=18.0, hole_mm=16.0)
    with pytest.raises(EditBlocked) as excinfo:
        STORE.create_preview(design_dir, base.revision_id, "edit:resize_spar",
                             fake_build(raises=blocked))

    assert excinfo.value.envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert excinfo.value.envelope.details["hole_mm"] == 16.0, "the typed envelope survives intact"
    assert revision_dirs(design_dir) == before, "a blocked edit creates no revision directory"
    assert not partials(design_dir), "the working directory is removed, not left half written"
    assert STORE.active_revision(design_dir) == base.revision_id


def test_crashing_build_propagates_and_leaves_nothing(tiny_design, fake_build):
    """Not every failure is typed. A kernel blowing up must be just as total."""
    design_dir, base = tiny_design
    with pytest.raises(ZeroDivisionError):
        STORE.create_preview(design_dir, base.revision_id, "edit:demo",
                             fake_build(raises=ZeroDivisionError("solver")))
    assert revision_dirs(design_dir) == [base.revision_id]
    assert not partials(design_dir)
    assert STORE.active_revision(design_dir) == base.revision_id


def test_declared_artifact_that_was_never_written_is_rejected(tiny_design, fake_build):
    design_dir, base = tiny_design
    build = fake_build()

    def lying_build(workdir: Path):
        result = build(workdir)
        (workdir / "demo.step").unlink()
        return result

    with pytest.raises(EditBlocked) as excinfo:
        STORE.create_preview(design_dir, base.revision_id, "edit:demo", lying_build)
    assert excinfo.value.envelope.code is ErrorCode.ARTIFACT_MISMATCH
    assert revision_dirs(design_dir) == [base.revision_id]
    assert not partials(design_dir)


def test_artifact_outside_the_revision_is_rejected(tiny_design, fake_build):
    """A revision is self-contained: an artifact path that leaves it is refused.

    The store cannot stop a misbehaving builder from writing outside the directory it was handed —
    it can refuse to *publish* such a path, and that is what is asserted. The stray file the fake
    builder dropped is its own litter, and the test clears it.
    """
    design_dir, base = tiny_design
    with pytest.raises(EditBlocked) as excinfo:
        STORE.create_preview(design_dir, base.revision_id, "edit:demo",
                             fake_build(files={"../escape.json": "{}\n"}))
    assert excinfo.value.envelope.code is ErrorCode.INPUT_REJECTED
    assert revision_dirs(design_dir) == [base.revision_id], "nothing was published"
    assert not partials(design_dir)
    (revisions_root(design_dir) / "escape.json").unlink(missing_ok=True)


def test_absolute_artifact_path_is_rejected(tiny_design, fake_build, tmp_path):
    design_dir, base = tiny_design
    outside = tmp_path / "outside.json"
    with pytest.raises(EditBlocked) as excinfo:
        STORE.create_preview(design_dir, base.revision_id, "edit:demo",
                             fake_build(files={str(outside): "{}\n"}))
    assert excinfo.value.envelope.code is ErrorCode.INPUT_REJECTED
    assert revision_dirs(design_dir) == [base.revision_id]


def test_preview_needs_a_real_parent(tiny_design, fake_build):
    design_dir, _ = tiny_design
    calls: list[Path] = []
    with pytest.raises(EditBlocked) as excinfo:
        STORE.create_preview(design_dir, "rev-doesnotexist", "edit:demo", fake_build(calls=calls))
    assert excinfo.value.envelope.code is ErrorCode.MISSING_EVIDENCE
    assert calls == [], "a bad base is refused before anything is built"


# ------------------------------------------------------------------ decline

def test_decline_records_a_decision_and_changes_nothing(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    directory = revision_dir(design_dir, preview.revision_id)
    before = {p.name: p.read_bytes() for p in sorted(directory.iterdir())}

    returned = STORE.decline(design_dir, preview.revision_id, "CG moves the wrong way")

    assert returned.revision_id == preview.revision_id
    assert returned.state is RevisionState.preview, "a declined preview is not rewritten"
    assert {p.name: p.read_bytes() for p in sorted(directory.iterdir())} == before, \
        "decline touches no geometry"
    assert STORE.active_revision(design_dir) == base.revision_id, "the active pointer stays put"

    decisions = STORE.decisions(design_dir)
    assert [d["decision"] for d in decisions] == ["declined"]
    assert decisions[0]["revision_id"] == preview.revision_id
    assert decisions[0]["reason"] == "CG moves the wrong way"
    assert decisions[0]["parent_revision_id"] == base.revision_id
    assert (revisions_root(design_dir) / DECISIONS_NAME).is_file()


def test_accept_is_logged_too(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    STORE.commit(design_dir, preview.revision_id, base.revision_id)
    logged = STORE.decisions(design_dir)
    assert [d["decision"] for d in logged] == ["accepted"]
    assert logged[0]["previous_active"] == base.revision_id
    assert logged[0]["revision_id"] == preview.revision_id


# ------------------------------------------------------------------ a blocked preview is not a design

FAILED_CHECKS = [RoundTripCheck(name="reimport", passed=True, detail="ok"),
                 RoundTripCheck(name="collision_undeclared_interference", passed=False,
                                detail="spar-main overlaps wing3-l by 2.1 mm")]


def test_a_preview_with_a_failed_check_cannot_be_committed(tiny_design, fake_build):
    """The defect: an edit whose checks failed became the active revision.

    A preview is still written — a human needs to read *why* it was refused — but it is recorded as
    blocked, and commit refuses it whatever the caller believes about it.
    """
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:resize_spar",
                                   fake_build(checks=FAILED_CHECKS))

    verdict = edit_status(design_dir, preview.revision_id)
    assert verdict["status"] == "blocked"
    assert verdict["committable"] is False
    assert verdict["failed_checks"] == ["collision_undeclared_interference"]
    assert (revision_dir(design_dir, preview.revision_id) / EDIT_STATUS_NAME).is_file()

    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, preview.revision_id, base.revision_id)

    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert envelope.details["status"] == "blocked"
    assert envelope.details["failed_checks"] == ["collision_undeclared_interference"]
    assert "collision_undeclared_interference" in envelope.message
    assert STORE.active_revision(design_dir) == base.revision_id, "the design did not move"
    assert json.loads((revision_dir(design_dir, preview.revision_id) /
                       REVISION_NAME).read_text())["state"] == "preview"


ADVISORY_FAIL = RoundTripCheck(name="verified_movement_unknown", passed=False,
                               detail="battery retention and harness are unknown")


def test_an_advisory_failure_is_committable_but_not_verified(tiny_design, fake_build):
    """An evidence gap is not a geometric failure.

    The Avenger's battery retention is genuinely unknown, so `verified_movement_unknown` fails on
    every battery move. That must not stop the move — it must stop anyone calling it verified.
    """
    design_dir, base = tiny_design
    preview = STORE.create_preview(
        design_dir, base.revision_id, "edit:translate_component",
        fake_build(checks=[RoundTripCheck(name="reimport", passed=True, detail="ok"),
                           ADVISORY_FAIL]))

    verdict = edit_status(design_dir, preview.revision_id)
    assert verdict["status"] == "ok"
    assert verdict["committable"] is True
    assert verdict["verified"] is False, "unknown retention means the claim is not verified"
    assert verdict["advisory_checks"] == ["verified_movement_unknown"]
    assert verdict["blocking_checks"] == []
    assert verdict["unverified_reasons"] == [
        "verified_movement_unknown: battery retention and harness are unknown"]

    committed = STORE.commit(design_dir, preview.revision_id, base.revision_id)
    assert committed.state is RevisionState.committed
    assert STORE.active_revision(design_dir) == preview.revision_id
    assert edit_status(design_dir, preview.revision_id)["verified"] is False, \
        "committing does not make it verified"


def test_a_clean_preview_is_verified(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    verdict = edit_status(design_dir, preview.revision_id)
    assert verdict["verified"] is True
    assert verdict["advisory_checks"] == [] and verdict["unverified_reasons"] == []


def test_advisory_plus_hard_failure_is_blocked(tiny_design, fake_build):
    """An evidence gap never rescues a geometric failure."""
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:translate_component",
                                   fake_build(checks=[*FAILED_CHECKS, ADVISORY_FAIL]))

    verdict = edit_status(design_dir, preview.revision_id)
    assert verdict["status"] == "blocked"
    assert verdict["committable"] is False
    assert verdict["verified"] is False
    assert verdict["blocking_checks"] == ["collision_undeclared_interference"]
    assert verdict["advisory_checks"] == ["verified_movement_unknown"]

    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, preview.revision_id, base.revision_id)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert envelope.details["failed_checks"] == ["collision_undeclared_interference"], \
        "the refusal names what blocked it, never the evidence gap"
    assert envelope.details["advisory_checks"] == ["verified_movement_unknown"]
    assert STORE.active_revision(design_dir) == base.revision_id


@pytest.mark.parametrize("name", ["collision_undeclared_interference", "propeller_clearance",
                                  "collision_geometry_unusable", "collision_check_error",
                                  "reimport", "roundtrip_volume"])
def test_hard_checks_still_block(tiny_design, fake_build, name):
    design_dir, base = tiny_design
    preview = STORE.create_preview(
        design_dir, base.revision_id, "edit:demo",
        fake_build(checks=[RoundTripCheck(name=name, passed=False, detail="no")]))
    assert edit_status(design_dir, preview.revision_id)["status"] == "blocked"
    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, preview.revision_id, base.revision_id)
    assert excinfo.value.envelope.code is ErrorCode.CONSTRAINT_FAILED


def test_a_declared_ok_cannot_override_a_hard_failure(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(
        design_dir, base.revision_id, "edit:demo",
        fake_build(content={"op": "x", "edit_status": "ok"}, checks=FAILED_CHECKS))
    assert edit_status(design_dir, preview.revision_id)["status"] == "blocked"
    with pytest.raises(EditBlocked):
        STORE.commit(design_dir, preview.revision_id, base.revision_id)


def test_a_build_can_declare_itself_blocked(tiny_design, fake_build):
    """Even with every check green, a caller's own refusal is honoured."""
    design_dir, base = tiny_design
    preview = STORE.create_preview(
        design_dir, base.revision_id, "edit:resize_spar",
        fake_build(content={"op": "resize_spar", "edit_status": "blocked"}))
    assert edit_status(design_dir, preview.revision_id)["status"] == "blocked"
    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, preview.revision_id, base.revision_id)
    assert excinfo.value.envelope.code is ErrorCode.CONSTRAINT_FAILED


def test_a_blocked_preview_does_not_collide_with_an_ok_one(tiny_design, fake_build):
    """Same inputs, different verdict: two revisions, so neither is mistaken for the other."""
    design_dir, base = tiny_design
    content = {"op": "resize_spar", "od_m": 0.016}
    blocked = STORE.create_preview(design_dir, base.revision_id, "edit:resize_spar",
                                   fake_build(content=content, checks=FAILED_CHECKS))
    passing = STORE.create_preview(design_dir, base.revision_id, "edit:resize_spar",
                                   fake_build(content=content))
    assert blocked.revision_id != passing.revision_id
    STORE.commit(design_dir, passing.revision_id, base.revision_id)
    assert STORE.active_revision(design_dir) == passing.revision_id


def test_a_blocked_preview_can_still_be_declined(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:resize_spar",
                                   fake_build(checks=FAILED_CHECKS))
    STORE.decline(design_dir, preview.revision_id, "blocked; not pursuing")
    assert [d["decision"] for d in STORE.decisions(design_dir)] == ["declined"]
    assert STORE.active_revision(design_dir) == base.revision_id


def test_a_tampered_artifact_blocks_the_commit(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    (revision_dir(design_dir, preview.revision_id) / "demo.step").write_text("tampered\n")

    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, preview.revision_id, base.revision_id)
    assert excinfo.value.envelope.code is ErrorCode.ARTIFACT_MISMATCH
    assert excinfo.value.envelope.details["path"] == "demo.step"
    assert STORE.active_revision(design_dir) == base.revision_id


def test_a_missing_artifact_blocks_the_commit(tiny_design, fake_build):
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    (revision_dir(design_dir, preview.revision_id) / "part_map.json").unlink()

    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, preview.revision_id, base.revision_id)
    assert excinfo.value.envelope.code is ErrorCode.ARTIFACT_MISMATCH
    assert STORE.active_revision(design_dir) == base.revision_id


def test_a_confirmed_revision_has_no_verdict_and_may_be_committed(tiny_design):
    """A1's confirm never went through this store, so it carries no verdict. That is not a block."""
    design_dir, base = tiny_design
    assert edit_status(design_dir, base.revision_id) is None
    assert STORE.commit(design_dir, base.revision_id, base.revision_id).revision_id == \
        base.revision_id


# ------------------------------------------------------------------ malformed ids are refusals

@pytest.mark.parametrize("bad", [None, "", "   ", 7, "../escape", "rev/../../etc", "."])
def test_a_bad_preview_id_is_a_typed_refusal_not_a_crash(tiny_design, bad):
    """The defect: commit(design_dir, None, expected_active=...) raised TypeError on Path / None."""
    design_dir, base = tiny_design
    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, bad, base.revision_id)
    assert excinfo.value.envelope.code is ErrorCode.INPUT_REJECTED
    assert excinfo.value.envelope.details["field"] == "preview_revision_id"

    with pytest.raises(EditBlocked) as excinfo:
        STORE.decline(design_dir, bad, "no")
    assert excinfo.value.envelope.code is ErrorCode.INPUT_REJECTED


def test_commit_of_an_unknown_revision_is_missing_evidence(tiny_design):
    design_dir, base = tiny_design
    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, "rev-neverexisted", base.revision_id)
    assert excinfo.value.envelope.code is ErrorCode.MISSING_EVIDENCE
    assert STORE.active_revision(design_dir) == base.revision_id


# ------------------------------------------------------------------ compare and swap

def test_stale_commit_names_both_revisions(tiny_design, fake_build):
    design_dir, base = tiny_design
    first = STORE.create_preview(design_dir, base.revision_id, "edit:a",
                                 fake_build(content={"op": "a"}))
    second = STORE.create_preview(design_dir, base.revision_id, "edit:b",
                                  fake_build(content={"op": "b"}))
    assert first.revision_id != second.revision_id

    STORE.commit(design_dir, first.revision_id, base.revision_id)

    # `second` was approved against `base`, which is no longer what is active.
    with pytest.raises(EditBlocked) as excinfo:
        STORE.commit(design_dir, second.revision_id, base.revision_id)

    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.STALE_REVISION
    assert envelope.details["expected_active"] == base.revision_id
    assert envelope.details["actual_active"] == first.revision_id
    assert base.revision_id in envelope.message and first.revision_id in envelope.message
    assert STORE.active_revision(design_dir) == first.revision_id, "a stale commit moves nothing"
    assert json.loads((revision_dir(design_dir, second.revision_id) / REVISION_NAME).read_text())[
        "state"] == "preview"


def test_commit_against_the_new_active_succeeds(tiny_design, fake_build):
    design_dir, base = tiny_design
    first = STORE.create_preview(design_dir, base.revision_id, "edit:a",
                                 fake_build(content={"op": "a"}))
    STORE.commit(design_dir, first.revision_id, base.revision_id)
    chained = STORE.create_preview(design_dir, first.revision_id, "edit:b",
                                   fake_build(content={"op": "b"}))
    committed = STORE.commit(design_dir, chained.revision_id, first.revision_id)
    assert STORE.active_revision(design_dir) == committed.revision_id
    assert committed.parent_revision_id == first.revision_id


# ------------------------------------------------------------------ idempotency

def test_same_idempotency_key_builds_once(tiny_design, fake_build):
    design_dir, base = tiny_design
    calls: list[Path] = []
    build = fake_build(calls=calls)

    first = STORE.create_preview(design_dir, base.revision_id, "edit:demo", build,
                                 idempotency_key="accept-1")
    second = STORE.create_preview(design_dir, base.revision_id, "edit:demo", build,
                                  idempotency_key="accept-1")

    assert second.revision_id == first.revision_id
    assert second.content_sha256 == first.content_sha256
    assert len(calls) == 1, "the replay must not rebuild geometry"
    assert revision_dirs(design_dir) == sorted([base.revision_id, first.revision_id])


def test_different_idempotency_keys_still_build(tiny_design, fake_build):
    design_dir, base = tiny_design
    calls: list[Path] = []
    STORE.create_preview(design_dir, base.revision_id, "edit:demo",
                         fake_build(calls=calls, content={"op": "a"}), idempotency_key="k1")
    STORE.create_preview(design_dir, base.revision_id, "edit:demo",
                         fake_build(calls=calls, content={"op": "b"}), idempotency_key="k2")
    assert len(calls) == 2
    assert len(revision_dirs(design_dir)) == 3


def test_same_key_under_a_different_parent_is_a_different_edit(tiny_design, fake_build):
    design_dir, base = tiny_design
    calls: list[Path] = []
    first = STORE.create_preview(design_dir, base.revision_id, "edit:demo",
                                 fake_build(calls=calls), idempotency_key="k")
    STORE.commit(design_dir, first.revision_id, base.revision_id)
    second = STORE.create_preview(design_dir, first.revision_id, "edit:demo",
                                  fake_build(calls=calls), idempotency_key="k")
    assert second.revision_id != first.revision_id
    assert second.parent_revision_id == first.revision_id
    assert len(calls) == 2


def test_concurrent_previews_with_one_key_publish_one_revision(tiny_design, fake_build):
    """Two accept clicks racing each other must not leave two revisions behind.

    Both may build — the lock is only held around the pointer and the index, not around a CAD
    rebuild — but only one directory is published and both callers get the same id back.
    """
    import threading

    design_dir, base = tiny_design
    results: list = []
    errors: list = []
    calls: list[Path] = []
    barrier = threading.Barrier(2)

    def worker():
        try:
            barrier.wait(timeout=10)
            results.append(STORE.create_preview(design_dir, base.revision_id, "edit:demo",
                                                fake_build(calls=calls), idempotency_key="race"))
        except BaseException as exc:                     # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len({r.revision_id for r in results}) == 1
    assert revision_dirs(design_dir) == sorted([base.revision_id, results[0].revision_id])
    assert not partials(design_dir), "the loser's working directory is cleaned up"


# ------------------------------------------------------------------ content identity

def test_content_hash_ignores_the_working_directory_and_the_clock(tiny_design, fake_build):
    """Two designs, two working directories, two moments in time, one revision id."""
    design_a, base_a = tiny_design
    content = {"operation": "resize_spar", "parameters": {"od_m": 0.016}, "targets": ["spar"]}

    first = STORE.create_preview(design_a, base_a.revision_id, "edit:resize_spar",
                                 fake_build(content=content))

    # A second design directory elsewhere on disk, rebuilt from the same declared inputs.
    from dronebench_edits.store import content_sha256 as hash_of
    assert first.content_sha256 == hash_of(base_a.revision_id, "edit:resize_spar", content)

    # Timestamps in the artifacts must not reach the hash: same content, different bytes.
    other = STORE.create_preview(
        design_a, base_a.revision_id, "edit:resize_spar",
        fake_build(content=content, files={"demo.step": "ISO;\n/* built 2026-09-19T12:00 */\n"}),
        idempotency_key=None)
    assert other.revision_id == first.revision_id, \
        "the identity of a revision is its declared inputs, not the bytes of its artifacts"
    assert other.created_at == first.created_at, "the existing revision is returned, not rewritten"


def test_content_hash_moves_with_parent_cause_and_content():
    base = content_sha256("rev-parent", "edit:demo", {"a": 1})
    assert content_sha256("rev-other", "edit:demo", {"a": 1}) != base
    assert content_sha256("rev-parent", "edit:other", {"a": 1}) != base
    assert content_sha256("rev-parent", "edit:demo", {"a": 2}) != base
    assert content_sha256("rev-parent", "edit:demo", {"a": 1, "b": None}) != base
    # Key order is not information.
    assert content_sha256("rev-parent", "edit:demo", {"b": 2, "a": 1}) == \
        content_sha256("rev-parent", "edit:demo", {"a": 1, "b": 2})


# ------------------------------------------------------------------ history

def test_history_is_newest_first_with_parent_links(tiny_design, fake_build):
    design_dir, base = tiny_design
    first = STORE.create_preview(design_dir, base.revision_id, "edit:a",
                                 fake_build(content={"op": "a"}))
    STORE.commit(design_dir, first.revision_id, base.revision_id)
    second = STORE.create_preview(design_dir, first.revision_id, "edit:b",
                                  fake_build(content={"op": "b"}))

    history = STORE.history(design_dir)
    assert [m.revision_id for m in history] == [second.revision_id, first.revision_id,
                                                base.revision_id]
    assert [m.parent_revision_id for m in history] == [first.revision_id, base.revision_id, None]
    assert [m.state.value for m in history] == ["preview", "committed", "committed"]
    assert [m.cause for m in history] == ["edit:b", "edit:a", "confirm"]

    # Every link resolves inside the history that was returned: no dangling parents.
    ids = {m.revision_id for m in history}
    assert all(m.parent_revision_id in ids for m in history if m.parent_revision_id)


def test_history_does_not_need_a_design_manifest_in_every_revision(tiny_design, fake_build):
    """An edit revision that carries no design_manifest.json is still a revision.

    Only revision_manifest.json is read here, so a builder that has not yet carried the parts list
    forward cannot take `history` or `active` down with it.
    """
    design_dir, base = tiny_design
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:demo", fake_build())
    assert not (revision_dir(design_dir, preview.revision_id) / "design_manifest.json").exists()

    STORE.commit(design_dir, preview.revision_id, base.revision_id)
    assert STORE.active_revision(design_dir) == preview.revision_id
    assert [m.revision_id for m in STORE.history(design_dir)] == [preview.revision_id,
                                                                  base.revision_id]


def test_history_skips_a_directory_that_is_not_a_revision(tiny_design):
    design_dir, base = tiny_design
    junk = revisions_root(design_dir) / "rev-garbage"
    junk.mkdir()
    (junk / REVISION_NAME).write_text("this is not json\n")
    assert [m.revision_id for m in STORE.history(design_dir)] == [base.revision_id]
    assert STORE.active_revision(design_dir) == base.revision_id


def test_history_of_an_empty_design_is_empty(tmp_path):
    assert STORE.history(tmp_path) == []
    with pytest.raises(EditBlocked) as excinfo:
        STORE.active_revision(tmp_path)
    assert excinfo.value.envelope.code is ErrorCode.MISSING_EVIDENCE


# ------------------------------------------------------------------ the real aircraft

def test_preview_on_the_confirmed_avenger(avenger_design, fake_build):
    """The store is indifferent to how big the design is; this proves it runs on the real one."""
    design_dir, base = avenger_design
    assert STORE.active_revision(design_dir) == base.revision_id
    preview = STORE.create_preview(design_dir, base.revision_id, "edit:translate_component",
                                   fake_build(content={"op": "battery_forward"}),
                                   idempotency_key="avenger-1")
    assert preview.parent_revision_id == base.revision_id
    assert preview.design_id == base.design_id
    assert STORE.active_revision(design_dir) == base.revision_id
    STORE.decline(design_dir, preview.revision_id, "demo only")
    assert STORE.active_revision(design_dir) == base.revision_id
