"""The end-to-end scenario (architecture section 13, UI/E2E).

"import -> confirm -> select -> graph/evidence -> preview -> decline -> preview -> accept ->
compare -> export"

Driven through the HTTP API, because that is the surface the web app uses, and because a service
level test would not catch a route that forgets to render the error envelope or returns the wrong
status for a modelled condition.

The export step ends in a refusal, and that is the correct outcome while Team A's CAD kernel is
absent: section 6 requires a successful round trip before a download exists, so producing a file
here would be the bug.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dronebench_api.main as main
from dronebench_api.service import build_workbench

from tests.conftest import DESIGN_ID, HARNESS_MASS_KG


@pytest.fixture
def client(tmp_path: Path):
    workbench = build_workbench(tmp_path / "store")
    main.set_workbench(workbench)
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client
    main.set_workbench(None)
    workbench.close()


def _await_job(client: TestClient, job_id: str, tries: int = 100) -> dict:
    for _ in range(tries):
        record = client.get(f"/api/jobs/{job_id}").json()
        if record["status"] in ("succeeded", "failed", "cancelled"):
            return record
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never reached a terminal state")


def test_full_review_loop(client: TestClient):
    # -- import ---------------------------------------------------------------------------
    response = client.post("/api/designs/import", json={"fixture": "b"})
    assert response.status_code == 202, "long work returns 202 and a job id"
    job = _await_job(client, response.json()["job_id"])
    assert job["status"] == "succeeded"

    history = client.get(f"/api/designs/{DESIGN_ID}/history").json()
    imported_revision = history["active_revision_id"]

    # An imported design is unconfirmed, so its checks cannot be computed yet.
    features = client.get(f"/api/revisions/{imported_revision}/parts").json()["geometry_features"]
    assert features["units_confirmed"] is False
    assert features["reconstruction_confirmed"] is False

    # -- the unknown is visible and actionable ----------------------------------------------
    parts = client.get(f"/api/revisions/{imported_revision}/parts").json()
    assert parts["unknown_claims"] == {"prt_harness": ["mass_kg"]}

    evaluation = client.post(
        f"/api/revisions/{imported_revision}/evaluate", json={"fidelity": "analytic"}
    ).json()["evaluation"]
    unknown = {c["check_id"] for c in evaluation["checks"] if c["status"] == "unknown"}
    assert {"mass_budget", "cg_envelope"} <= unknown, (
        "one missing mass must make every weight-dependent check unknown, not zero"
    )

    proposals = client.post(
        f"/api/revisions/{imported_revision}/recommendations", json={"preview": False}
    ).json()
    assert proposals["evidence_requests"], "the missing value must be asked for"
    assert not proposals["generated"], "no edit may be proposed on unknown inputs"

    # -- confirm, supplying the missing value with provenance --------------------------------
    response = client.post(
        f"/api/designs/{DESIGN_ID}/confirm",
        json={
            "units_confirmed": True,
            "frame_confirmed": True,
            "reconstruction_confirmed": True,
            "claim_entries": [
                {
                    "part_id": "prt_harness",
                    "quantity": "mass_kg",
                    "value": HARNESS_MASS_KG,
                    "unit": "kg",
                    "source_kind": "manual",
                    "evidence_id": "ev_fixture-spec",
                }
            ],
        },
    )
    assert response.status_code == 200
    baseline = response.json()["revision"]["revision_id"]
    assert baseline != imported_revision

    # -- select a part, read its evidence and its bounded neighbourhood -----------------------
    mass_path = client.get(
        f"/api/revisions/{baseline}/explain",
        params={"part_id": "prt_battery", "question": "mass_evidence"},
    ).json()
    assert mass_path["steps"], "a known mass must trace to evidence"

    whole = client.get(f"/api/revisions/{baseline}/graph").json()
    local = client.get(
        f"/api/revisions/{baseline}/graph", params={"part_id": "prt_battery", "radius": 1}
    ).json()
    assert len(local["nodes"]) < len(whole["nodes"]), "the panel asks for a neighbourhood"

    # -- evaluate: the configured scenario fails -----------------------------------------------
    evaluation = client.post(
        f"/api/revisions/{baseline}/evaluate", json={"fidelity": "analytic"}
    ).json()["evaluation"]
    failing = {c["check_id"] for c in evaluation["checks"] if c["status"] == "fail"}
    assert "cg_envelope" in failing
    assert evaluation["fidelity"] == "analytic"
    assert evaluation["produced_by"] == "B-stub"
    assert evaluation["omitted_physics"], "an honest result lists what it does not model"

    # -- preview ---------------------------------------------------------------------------
    recommendations = client.post(
        f"/api/revisions/{baseline}/recommendations", json={"preview": True}
    ).json()
    by_id = {p["proposal_id"]: p for p in recommendations["generated"]}
    cg = by_id["rec_battery-cg"]
    spar = by_id["rec_spar-resize"]

    assert cg["preview"]["preview_revision_id"] != baseline, (
        "a candidate preview is visibly a different revision"
    )

    # -- decline -----------------------------------------------------------------------------
    before_decline = client.get(f"/api/designs/{DESIGN_ID}/history").json()
    outcome = client.post(
        f"/api/recommendations/{spar['proposal_id']}/decision",
        json={
            "proposal_id": spar["proposal_id"],
            "decision": "decline",
            "expected_active_revision_id": baseline,
            "idempotency_key": "e2e-decline-001",
            "reason": "the mass cost outweighs the margin gain",
        },
    ).json()
    assert outcome["state"] == "declined"
    after_decline = client.get(f"/api/designs/{DESIGN_ID}/history").json()
    assert after_decline == before_decline, "a decline changes nothing"

    # -- accept -------------------------------------------------------------------------------
    outcome = client.post(
        f"/api/recommendations/{cg['proposal_id']}/decision",
        json={
            "proposal_id": cg["proposal_id"],
            "decision": "accept",
            "expected_active_revision_id": baseline,
            "preview_hash": cg["preview"]["preview_hash"],
            "idempotency_key": "e2e-accept-0001",
        },
    ).json()
    assert outcome["state"] == "committed"
    candidate = outcome["committed_revision_id"]

    after_commit = client.get(f"/api/designs/{DESIGN_ID}/history").json()
    assert after_commit["active_revision_id"] == candidate
    assert len(after_commit["revisions"]) == len(before_decline["revisions"]) + 1

    # The accepted design now passes what it previously failed.
    committed_eval = client.post(
        f"/api/revisions/{candidate}/evaluate", json={"fidelity": "analytic"}
    ).json()["evaluation"]
    assert not [c for c in committed_eval["checks"] if c["status"] == "fail"]

    # -- compare ---------------------------------------------------------------------------
    comparison = client.get(
        f"/api/revisions/{candidate}/compare",
        params={"against": baseline, "metric": "endurance_min"},
    ).json()
    assert comparison["fidelity"] == "analytic"
    assert comparison["ui_claim"] == "Engineering estimate - assumptions shown"
    assert comparison["feasibility_changed"] is True

    # -- simulate ---------------------------------------------------------------------------
    run = client.post(f"/api/revisions/{candidate}/simulate").json()["run"]
    assert run["flight_model_tier"] == "reduced_order_mission"
    assert run["samples"], "a replay needs telemetry"
    assert min(s["remaining_energy_wh"] for s in run["samples"]) >= 0.0
    assert any("not physical bench testing" in note for note in run["assumptions"])

    # -- export: correctly refused -----------------------------------------------------------
    response = client.post(f"/api/revisions/{candidate}/export")
    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "SOLVER_UNAVAILABLE"
    assert "not available" in body["message"]

    # -- the audit trail covers the whole loop -------------------------------------------------
    events = client.get("/api/events/recent", params={"design_id": DESIGN_ID}).json()["events"]
    kinds = [e["kind"] for e in events]
    for expected in (
        "revision_created",
        "revision_activated",
        "proposal_generated",
        "proposal_previewed",
        "proposal_declined",
        "proposal_committed",
        "evaluation_completed",
    ):
        assert expected in kinds, f"the audit log is missing {expected}"

    sequences = [e["sequence"] for e in events]
    assert sequences == sorted(sequences) == list(range(1, len(sequences) + 1)), (
        "event sequence must be monotonic and gapless"
    )
    for event in events:
        assert "reasoning" not in event and "thought" not in event


def test_restart_recovers_the_whole_history(tmp_path: Path):
    """Section 13: refresh/restart recovers history. Durable state is on disk, not in memory."""
    root = tmp_path / "store"

    first = build_workbench(root)
    try:
        first.jobs.wait(first.import_fixture("b").job_id)
        from dronebench_api.service import ClaimEntry, ConfirmRequest

        first.confirm(
            DESIGN_ID,
            ConfirmRequest(
                units_confirmed=True,
                frame_confirmed=True,
                reconstruction_confirmed=True,
                variant_decisions={},
                claim_entries=[
                    ClaimEntry(
                        part_id="prt_harness",
                        quantity="mass_kg",
                        value=HARNESS_MASS_KG,
                        unit="kg",
                        source_kind="manual",
                        evidence_id="ev_fixture-spec",
                    )
                ],
            ),
        )
        expected_history = [r.revision_id for r in first.history(DESIGN_ID)]
        expected_active = first.active_revision(DESIGN_ID)
        expected_events = len(first.events(DESIGN_ID))
    finally:
        first.close()

    second = build_workbench(root)
    try:
        assert [r.revision_id for r in second.history(DESIGN_ID)] == expected_history
        assert second.active_revision(DESIGN_ID) == expected_active
        assert len(second.events(DESIGN_ID)) == expected_events
        # And every artifact still verifies after the restart.
        second.revisions.verify_all(expected_active)
    finally:
        second.close()


def test_error_envelope_shape_is_uniform(client: TestClient):
    response = client.get("/api/revisions/rev_0000000000000000")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "revision_id", "details", "retryable"}
    assert body["code"] == "NOT_FOUND"
    assert body["retryable"] is False


def test_doctor_names_what_is_absent(client: TestClient):
    report = client.get("/api/doctor").json()
    assert report["ports"]["cad"]["real_kernel"] is False
    assert report["ports"]["evaluate"]["available_tiers"] == ["analytic"]
    assert any("VSPAERO" in note for note in report["capabilities_absent"])
    assert report["catalog"]["all_synthetic"] is True
