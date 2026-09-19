"""The FastAPI application (architecture section 9).

Every endpoint in the section 9 table, over the service functions in
:mod:`dronebench_api.service`. The HTTP layer does three things and nothing else: parse the
request, call one service function, and render the result or the shared error envelope.

Long work returns ``202`` with a job id. Progress reaches the client as structured tool events over
SSE, with a monotonic sequence and reconnect via ``Last-Event-ID`` - never as a guessed percentage.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from dronebench_contracts import (
    CONTRACT_VERSION,
    DecisionRequest,
    DroneBenchError,
    ErrorEnvelope,
    FidelityTier,
    canonical_json,
)

from .service import ClaimEntry, ConfirmRequest, Workbench, build_workbench

DEFAULT_ROOT = Path(os.environ.get("DRONEBENCH_ROOT", "artifacts/workbench"))

app = FastAPI(
    title="DroneBench Studio",
    version=CONTRACT_VERSION,
    description=(
        "Local-first engineering design workbench. Import, inspect evidence, trace dependencies, "
        "propose a bounded change, preview its consequences, accept or decline, compare runs."
    ),
)

_workbench: Workbench | None = None


def workbench() -> Workbench:
    global _workbench
    if _workbench is None:
        _workbench = build_workbench(DEFAULT_ROOT)
    return _workbench


def set_workbench(instance: Workbench | None) -> None:
    """Used by the tests to point the app at a temporary root."""
    global _workbench
    _workbench = instance


# ---------------------------------------------------------------------------------------------
# Error rendering
# ---------------------------------------------------------------------------------------------


@app.exception_handler(DroneBenchError)
async def _dronebench_error(request: Request, exc: DroneBenchError) -> JSONResponse:
    """One envelope shape for every failure, with the right status attached to the code."""
    return JSONResponse(
        status_code=exc.envelope.http_status,
        content=exc.envelope.model_dump(mode="json"),
    )


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
    envelope = ErrorEnvelope.of(
        "NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST", str(exc.detail)
    )
    return JSONResponse(status_code=exc.status_code, content=envelope.model_dump(mode="json"))


def _json(payload: Any, status_code: int = 200) -> Response:
    """Render through canonical JSON so a NaN can never reach a client."""
    return Response(
        content=canonical_json(payload),
        media_type="application/json",
        status_code=status_code,
    )


def _dump(model: Any) -> Any:
    return model.model_dump(mode="json") if isinstance(model, BaseModel) else model


# ---------------------------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------------------------


class ImportBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixture: str = Field(
        default="b",
        description=(
            "Which checked-in fixture to stage. Archive upload belongs to Team A's importer; this "
            "endpoint does not pretend to reconstruct a supplied archive."
        ),
    )


class ClaimEntryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_id: str
    quantity: str = "mass_kg"
    value: float
    unit: str
    source_kind: Literal["bom", "manual", "catalog", "cad"]
    evidence_id: str
    note: str = ""


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    units_confirmed: bool
    frame_confirmed: bool
    reconstruction_confirmed: bool = False
    variant_decisions: dict[str, str] = Field(default_factory=dict)
    claim_entries: list[ClaimEntryBody] = Field(default_factory=list)


class EvaluateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fidelity: FidelityTier = "analytic"
    mission_hash: str | None = Field(
        default=None,
        description="The mission the caller believes is locked. A mismatch is refused.",
    )


class RecommendBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview: bool = Field(
        default=True,
        description="Build and evaluate real previews. False returns unevaluated candidates.",
    )


# ---------------------------------------------------------------------------------------------
# Designs and revisions
# ---------------------------------------------------------------------------------------------


@app.get("/api/health")
def health() -> Response:
    return _json({"status": "ok", "contract_version": CONTRACT_VERSION})


@app.get("/api/doctor")
def doctor() -> Response:
    return _json(workbench().doctor())


@app.get("/api/designs")
def list_designs() -> Response:
    return _json({"designs": workbench().repository.list_designs()})


@app.post("/api/designs/import", status_code=202)
def import_design(body: ImportBody) -> Response:
    job = workbench().import_fixture(body.fixture)
    return _json({"job_id": job.job_id, "job": _dump(job)}, status_code=202)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> Response:
    job = workbench().job(job_id)
    payload = _dump(job)
    payload["artifact_links"] = [f"/api/artifacts/{a}" for a in job.artifact_ids]
    return _json(payload)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> Response:
    cancelled = workbench().cancel_job(job_id)
    return _json({"job_id": job_id, "cancellation_requested": cancelled})


@app.post("/api/designs/{design_id}/confirm")
def confirm(design_id: str, body: ConfirmBody) -> Response:
    manifest = workbench().confirm(
        design_id,
        ConfirmRequest(
            units_confirmed=body.units_confirmed,
            frame_confirmed=body.frame_confirmed,
            reconstruction_confirmed=body.reconstruction_confirmed,
            variant_decisions=body.variant_decisions,
            claim_entries=[
                ClaimEntry(
                    part_id=entry.part_id,
                    quantity=entry.quantity,
                    value=entry.value,
                    unit=entry.unit,
                    source_kind=entry.source_kind,
                    evidence_id=entry.evidence_id,
                    note=entry.note,
                )
                for entry in body.claim_entries
            ],
        ),
    )
    return _json(_dump(manifest))


@app.get("/api/designs/{design_id}/history")
def history(design_id: str) -> Response:
    bench = workbench()
    return _json(
        {
            "design_id": design_id,
            "active_revision_id": bench.active_revision(design_id),
            "revisions": [_dump(r) for r in bench.history(design_id)],
        }
    )


@app.post("/api/designs/{design_id}/undo")
def undo(design_id: str, to_revision_id: str | None = Query(default=None)) -> Response:
    target = workbench().undo(design_id, to_revision_id=to_revision_id)
    return _json({"design_id": design_id, "active_revision_id": target})


@app.get("/api/revisions/{revision_id}")
def get_revision(revision_id: str) -> Response:
    return _json(_dump(workbench().get_revision(revision_id)))


@app.get("/api/revisions/{revision_id}/parts")
def get_parts(revision_id: str) -> Response:
    bench = workbench()
    parts = bench.get_parts(revision_id)
    features = bench.get_features(revision_id)
    return _json(
        {
            "parts": _dump(parts),
            "geometry_features": _dump(features),
            "capabilities": {
                occurrence.part_id: occurrence.edit_capabilities
                for occurrence in parts.occurrences
                if occurrence.edit_capabilities
            },
            "unknown_claims": {
                occurrence.part_id: ["mass_kg"]
                for occurrence in parts.occurrences
                if not occurrence.mass_kg.is_known
            },
        }
    )


@app.get("/api/revisions/{revision_id}/graph")
def get_graph(
    revision_id: str,
    part_id: str | None = Query(default=None),
    radius: int = Query(default=2, ge=1, le=4),
) -> Response:
    """The typed graph, or a bounded neighbourhood when a part is named.

    Section 7 keeps queries narrow. Asking for a whole graph is allowed here because the panel
    renders it, but the recommender never takes this path - it asks for a neighbourhood.
    """
    bench = workbench()
    if part_id:
        return _json(_dump(bench.get_neighborhood(revision_id, part_id, radius=radius)))
    return _json(_dump(bench.get_graph(revision_id)))


@app.get("/api/revisions/{revision_id}/explain")
def explain(revision_id: str, part_id: str, question: str) -> Response:
    return _json(workbench().explain(revision_id, part_id, question))


@app.post("/api/revisions/{revision_id}/evaluate", status_code=202)
def evaluate(revision_id: str, body: EvaluateBody) -> Response:
    bench = workbench()
    if body.mission_hash is not None:
        design_id = bench.get_revision(revision_id).revision.design_id
        actual = bench.repository.design_mission(design_id).mission_hash()
        if actual != body.mission_hash:
            raise DroneBenchError.of(
                "STALE_REVISION",
                "the mission changed since this request was prepared; every cached result against "
                "the old mission is invalid",
                revision_id=revision_id,
                expected_mission_hash=body.mission_hash,
                actual_mission_hash=actual,
            )
    job, evaluation = bench.evaluate(revision_id, fidelity=body.fidelity, wait=True)
    return _json(
        {"job_id": job.job_id, "job": _dump(job), "evaluation": _dump(evaluation)},
        status_code=202,
    )


@app.post("/api/revisions/{revision_id}/recommendations", status_code=202)
def recommend(revision_id: str, body: RecommendBody) -> Response:
    result = workbench().recommend(revision_id, preview_all=body.preview)
    return _json(_dump(result), status_code=202)


@app.get("/api/revisions/{revision_id}/recommendations")
def list_recommendations(revision_id: str) -> Response:
    bench = workbench()
    design_id = bench.get_revision(revision_id).revision.design_id
    proposals = bench.repository.list_proposals(design_id, revision_id)
    return _json({"proposals": [_dump(p) for p in proposals]})


@app.post("/api/recommendations/{proposal_id}/preview")
def preview(proposal_id: str) -> Response:
    return _json(_dump(workbench().preview(proposal_id)))


@app.post("/api/recommendations/{proposal_id}/decision")
def decision(
    proposal_id: str,
    body: DecisionRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    """Accept the exact reviewed preview, or decline. Idempotent, active-revision CAS."""
    if body.proposal_id != proposal_id:
        raise DroneBenchError.of(
            "INVALID_REQUEST",
            "the proposal id in the path and the body disagree",
            path_proposal_id=proposal_id,
            body_proposal_id=body.proposal_id,
        )
    request = body
    if idempotency_key and idempotency_key != body.idempotency_key:
        raise DroneBenchError.of(
            "INVALID_REQUEST",
            "the Idempotency-Key header and the body disagree; one key per decision",
        )
    outcome = workbench().decide(request)
    return _json(_dump(outcome))


@app.post("/api/revisions/{revision_id}/simulate", status_code=202)
def simulate(revision_id: str) -> Response:
    job, run = workbench().simulate(revision_id, wait=True)
    return _json({"job_id": job.job_id, "job": _dump(job), "run": _dump(run)}, status_code=202)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> Response:
    """A run is stored on the revision it analysed, so the id carries the revision."""
    bench = workbench()
    revision_id = f"rev_{run_id[4:]}"
    payload = bench._read_artifact_json(revision_id, "simulation_run")
    if payload is None:
        raise DroneBenchError.of("NOT_FOUND", f"no run {run_id}", revision_id=revision_id)
    return _json(payload)


@app.get("/api/revisions/{revision_id}/compare")
def compare(revision_id: str, against: str, metric: str = "endurance_min") -> Response:
    pair = workbench().compare(against, revision_id, metric)
    return _json(
        {
            "metric": metric,
            "baseline_revision_id": against,
            "candidate_revision_id": revision_id,
            "delta": pair.delta(),
            "feasibility_changed": pair.feasibility_changed,
            "fidelity": pair.candidate.fidelity,
            "ui_claim": pair.candidate.ui_claim,
            "baseline": _dump(pair.baseline),
            "candidate": _dump(pair.candidate),
        }
    )


@app.post("/api/revisions/{revision_id}/export")
def export(revision_id: str) -> Response:
    return _json(workbench().export(revision_id))


@app.get("/api/artifacts/{artifact_id}")
def get_artifact(artifact_id: str) -> Response:
    """Server-resolved immutable download. No caller-supplied filesystem path is ever honoured."""
    data, media_type, filename = workbench().artifact_bytes(artifact_id)
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------------------------


@app.get("/api/events")
async def events(
    design_id: str,
    last_event_id: int | None = Header(default=None, alias="Last-Event-ID"),
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """SSE with a monotonic sequence. Reconnect resumes from ``Last-Event-ID``."""
    bench = workbench()
    cursor = last_event_id if last_event_id is not None else after

    async def stream():
        nonlocal cursor
        idle = 0
        while True:
            batch = bench.events(design_id, cursor, limit=200)
            if batch:
                idle = 0
                for event in batch:
                    cursor = event.sequence
                    yield event.to_sse()
            else:
                idle += 1
                # A comment frame keeps the connection alive without inventing progress.
                yield ": keep-alive\n\n"
                if idle > 600:
                    break
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/events/recent")
def recent_events(design_id: str, after: int = Query(default=0, ge=0)) -> Response:
    """Non-streaming event read, for the CLI and for tests."""
    bench = workbench()
    batch = bench.events(design_id, after)
    return _json(
        {
            "design_id": design_id,
            "last_sequence": bench.repository.last_sequence(design_id),
            "events": [_dump(e) for e in batch],
        }
    )
