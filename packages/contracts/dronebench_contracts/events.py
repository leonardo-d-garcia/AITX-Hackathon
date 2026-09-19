"""Auditable events, jobs, and the simulation-run contract (architecture sections 7, 8, 9).

Section 7: "Every mutation emits an auditable event, but events never expose chain-of-thought.
They show tool name, inputs summary, artifact references, status and elapsed time." ``AuditEvent``
has no field capable of carrying reasoning text, and the input summary is a bounded string map.

Section 9: SSE carries a monotonic sequence and supports reconnect with a last event id. Progress
is a structured tool event, never a guessed percentage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .evaluate import FidelityTier, SolverManifest

EventKind = Literal[
    "job_queued",
    "job_started",
    "job_progress",
    "job_succeeded",
    "job_failed",
    "job_cancelled",
    "revision_created",
    "revision_activated",
    "proposal_generated",
    "proposal_previewed",
    "proposal_declined",
    "proposal_committed",
    "proposal_stale",
    "evaluation_completed",
    "export_completed",
]

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]

JobKind = Literal["import", "confirm", "evaluate", "recommend", "preview", "simulate", "export"]

#: Longest input-summary value kept in an event. Keeps mesh paths and blobs out of the audit log.
MAX_SUMMARY_VALUE_CHARS = 200


class AuditEvent(BaseModel):
    """One immutable log line. There is deliberately no field for model reasoning."""

    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=1, description="Monotonic per design. The SSE last-event-id.")
    event_id: str
    kind: EventKind
    design_id: str
    revision_id: str | None = None
    job_id: str | None = None
    proposal_id: str | None = None
    tool_name: str = Field(description="The tool or service function that ran.")
    inputs_summary: dict[str, str] = Field(
        default_factory=dict, description="Short scalars only. Never a payload dump."
    )
    artifact_ids: list[str] = Field(default_factory=list)
    status: Literal["ok", "error", "in_progress"] = "ok"
    error_code: str | None = None
    elapsed_s: float = Field(default=0.0, ge=0.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _summary_is_bounded(self) -> Self:
        for key, value in self.inputs_summary.items():
            if len(value) > MAX_SUMMARY_VALUE_CHARS:
                raise ValueError(
                    f"inputs_summary[{key}] is {len(value)} chars; the audit log keeps short "
                    f"scalars, not payloads"
                )
        if self.status == "error" and not self.error_code:
            raise ValueError("an error event must carry its error code")
        return self

    def to_sse(self) -> str:
        """Render as a Server-Sent Event frame with the sequence as the event id."""
        from .identity import canonical_json

        payload = canonical_json(self.model_dump(mode="json"))
        return f"id: {self.sequence}\nevent: {self.kind}\ndata: {payload}\n\n"


class JobRecord(BaseModel):
    """A queued unit of work. Long native work never runs inside an HTTP request thread."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(pattern=r"^job_[a-z0-9][a-z0-9_.-]{1,62}$")
    kind: JobKind
    status: JobStatus
    design_id: str
    revision_id: str | None = None
    cache_key: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description=(
            "Covers revision content, mission, solver version and settings, model tier, and the "
            "relevant evidence/catalog snapshot hashes."
        ),
    )
    work_dir: str = Field(
        description="Unique per job. Native solvers emit many same-named files, so they cannot share."
    )
    artifact_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    progress_note: str = ""
    cache_hit: bool = False
    reused_job_id: str | None = Field(
        default=None, description="Set on a cache hit so the UI can show the reused run."
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    elapsed_s: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _terminal_consistency(self) -> Self:
        if self.status == "failed" and not self.error_code:
            raise ValueError("a failed job must carry an error code")
        if self.status == "succeeded" and self.error_code:
            raise ValueError("a succeeded job cannot carry an error code")
        if self.cache_hit and self.reused_job_id is None:
            raise ValueError("a cache hit must name the run it reused")
        return self

    @property
    def terminal(self) -> bool:
        return self.status in ("succeeded", "failed", "cancelled")


class TelemetrySample(BaseModel):
    """One state along the reduced-order mission model."""

    model_config = ConfigDict(extra="forbid")

    t_s: float = Field(ge=0)
    distance_km: float = Field(ge=0)
    speed_mps: float = Field(ge=0)
    altitude_m: float
    power_w: float = Field(ge=0)
    remaining_energy_wh: float = Field(
        ge=0,
        description=(
            "Energy usable after the mission reserve has already been withheld. The run terminates "
            "at zero; the display is never clamped while flight continues."
        ),
    )
    position_frd_m: tuple[float, float, float]
    bank_rad: float = 0.0


class SimulationRun(BaseModel):
    """``simulation_run.json`` - C -> UI. Never mutates the design it analysed."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(pattern=r"^run_[a-z0-9][a-z0-9_.-]{1,62}$")
    revision_id: str = Field(pattern=r"^rev_[0-9a-f]{16}$")
    mission_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    fidelity: FidelityTier
    solver: SolverManifest
    flight_model_tier: Literal["reduced_order_mission", "dynamics_engine"] = (
        "reduced_order_mission"
    )
    samples: list[TelemetrySample] = Field(default_factory=list)
    completed_route: bool = Field(
        description="False marks an energy-limited run. The route is not silently shortened."
    )
    termination_reason: Literal["route_complete", "energy_limited", "cancelled", "error"]
    assumptions: list[str] = Field(
        default_factory=list,
        description=(
            "Section 8: straight-and-level v1 omits maneuver loads and turn drag; animated turns "
            "are not a tested turning-flight envelope."
        ),
    )
    telemetry_artifact_id: str | None = None
    log_artifact_ids: list[str] = Field(default_factory=list)
    recorded_fallback: bool = Field(
        default=False, description="A visibly labelled 'Recorded run', not a fresh computation."
    )
    elapsed_s: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="after")
    def _telemetry_is_physical(self) -> Self:
        previous_t = -1.0
        previous_energy: float | None = None
        previous_distance = -1.0
        for index, sample in enumerate(self.samples):
            if sample.t_s <= previous_t:
                raise ValueError(f"sample {index}: time is not strictly increasing")
            if sample.distance_km + 1e-9 < previous_distance:
                raise ValueError(f"sample {index}: distance decreased")
            if previous_energy is not None and sample.remaining_energy_wh > previous_energy + 1e-9:
                raise ValueError(
                    f"sample {index}: remaining energy increased; the stated model has no recharge"
                )
            previous_t, previous_distance = sample.t_s, sample.distance_km
            previous_energy = sample.remaining_energy_wh

        if self.completed_route and self.termination_reason != "route_complete":
            raise ValueError("completed_route contradicts the termination reason")
        if self.termination_reason == "energy_limited" and self.completed_route:
            raise ValueError("an energy-limited run did not complete the route")
        return self

    def duration_s(self) -> float:
        return self.samples[-1].t_s if self.samples else 0.0


def summarize_inputs(payload: dict[str, Any]) -> dict[str, str]:
    """Reduce an arbitrary payload to short scalars fit for an audit event."""
    summary: dict[str, str] = {}
    for key, value in payload.items():
        if value is None or isinstance(value, (dict, list, tuple, set, bytes)):
            continue
        text = str(value)
        if len(text) > MAX_SUMMARY_VALUE_CHARS:
            text = text[: MAX_SUMMARY_VALUE_CHARS - 1] + "…"
        summary[key] = text
    return summary
