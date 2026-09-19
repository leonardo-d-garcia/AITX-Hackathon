"""Recommendations, the transaction state machine, and the review decision (architecture section 7).

The state machine is the safety property of the whole product:

    proposed -> previewing -> review_ready | blocked
    review_ready -> declined
    review_ready -> committing (accept exact preview) -> committed | stale | failed

Acceptance carries the proposal id, the expected active revision, the preview hash, and an
idempotency key. B performs compare-and-swap inside a database transaction and only then switches
the active revision pointer. Approval of one preview does not authorise recalculating a different
edit after another commit.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .claims import Claim
from .edits import EditOperation
from .evaluate import Evaluation
from .graph import ExplanationPath

ProposalState = Literal[
    "proposed",
    "previewing",
    "review_ready",
    "blocked",
    "declined",
    "committing",
    "committed",
    "stale",
    "failed",
]

#: The only legal transitions. Anything else is a bug, not a state to recover from.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"previewing", "blocked"}),
    "previewing": frozenset({"review_ready", "blocked", "failed"}),
    "review_ready": frozenset({"declined", "committing", "stale"}),
    "blocked": frozenset({"declined"}),
    "committing": frozenset({"committed", "stale", "failed"}),
    "committed": frozenset(),
    "declined": frozenset(),
    "stale": frozenset(),
    "failed": frozenset(),
}

TERMINAL_STATES: frozenset[str] = frozenset({"committed", "declined", "stale", "failed"})


class IllegalTransition(ValueError):
    """An attempted state change the machine does not permit."""


def assert_transition(current: ProposalState, target: ProposalState) -> None:
    allowed = ALLOWED_TRANSITIONS[current]
    if target not in allowed:
        raise IllegalTransition(
            f"{current} -> {target} is not allowed; legal targets are "
            f"{sorted(allowed) or 'none (terminal state)'}"
        )


CandidateOrigin = Literal["deterministic", "provider"]
"""Where a candidate came from. A provider-authored candidate is validated exactly as strictly as
a deterministic one, and its predicted gain is discarded in favour of computed results."""


class Tradeoff(BaseModel):
    """One metric that moves, in either direction.

    Section 10: a proposal that increases spar margin but increases mass must show both. A
    recommendation with only improving tradeoffs and a nonzero mass change is rejected below.
    """

    model_config = ConfigDict(extra="forbid")

    metric: str
    unit: str
    baseline: float | None = None
    candidate: float | None = None
    direction: Literal["improves", "worsens", "unchanged", "informational", "unknown"]
    """``informational`` is for a metric that moved but whose direction is not itself a quality
    judgement - a lift coefficient, an aspect ratio. Calling such a change "better" would be a
    claim the model does not support, and hiding it would omit a real difference between the two
    designs. The number is shown; the verdict is withheld."""

    basis: str | None = Field(
        default=None,
        description="Why this direction was assigned, when it came from a check status rather "
        "than from the sign of the change.",
    )

    @model_validator(mode="after")
    def _direction_supported(self) -> Self:
        if self.direction in ("improves", "worsens") and (
            self.baseline is None or self.candidate is None
        ):
            raise ValueError(f"{self.metric}: a direction needs both sides computed")
        if self.direction == "unknown" and self.baseline is not None and self.candidate is not None:
            raise ValueError(f"{self.metric}: both sides are known, so the direction is not unknown")
        return self


class PreviewResult(BaseModel):
    """The concrete, immutable child revision a proposal was actually evaluated on.

    ``preview_hash`` is what an acceptance must quote. Accepting anything else is refused, which is
    how "accept commits precisely the reviewed preview" becomes mechanical.
    """

    model_config = ConfigDict(extra="forbid")

    preview_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{16}$")
    preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{16}$")
    cad_ok: bool
    evaluation: Evaluation | None = None
    baseline_evaluation: Evaluation | None = None
    change_summary: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)

    @property
    def evaluated(self) -> bool:
        return self.evaluation is not None

    @property
    def acceptable(self) -> bool:
        """A preview may be accepted only when geometry is valid and nothing blocking fails."""
        if not self.cad_ok or self.blocked_reasons:
            return False
        if self.evaluation is None:
            return False
        return self.evaluation.verified_feasible


class Recommendation(BaseModel):
    """One bounded proposal, with its evidence, its preview, and its tradeoffs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    proposal_id: str = Field(pattern=r"^rec_[a-z0-9][a-z0-9_.-]{1,62}$")
    design_id: str
    base_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{16}$")
    mission_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    title: str
    issue: str = Field(description="The specific problem this addresses, in plain language.")
    operation: EditOperation
    prerequisites: list[str] = Field(
        default_factory=list,
        description="Facts that had to be known before this was proposable.",
    )
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_path: ExplanationPath | None = None

    origin: CandidateOrigin = "deterministic"
    state: ProposalState = "proposed"
    preview: PreviewResult | None = None
    tradeoffs: list[Tradeoff] = Field(default_factory=list)
    expected_gain_note: str | None = Field(
        default=None,
        description=(
            "A provider's narrative expectation, kept only as text. It is never substituted for a "
            "computed result and never ranked on."
        ),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _state_matches_evidence(self) -> Self:
        if self.state in ("review_ready", "committing", "committed") and self.preview is None:
            raise ValueError(f"state {self.state} requires a preview")
        if self.state == "review_ready" and self.preview is not None:
            if not self.preview.cad_ok:
                raise ValueError("a preview with invalid geometry cannot be review_ready")
        if self.state == "blocked" and self.preview is not None and self.preview.acceptable:
            raise ValueError("an acceptable preview is not blocked")
        return self

    @property
    def display_label(self) -> str:
        """Section 7 step 6: an unevaluated candidate must say so."""
        if self.preview is None or not self.preview.evaluated:
            return "unevaluated proposal"
        return self.title

    @property
    def worsening(self) -> list[Tradeoff]:
        return [t for t in self.tradeoffs if t.direction == "worsens"]

    def transition(self, target: ProposalState) -> "Recommendation":
        assert_transition(self.state, target)
        return self.model_copy(update={"state": target})


class EvidenceRequest(BaseModel):
    """A candidate that asks for a missing fact instead of proposing an edit.

    Section 7 step 2 names this explicitly: "ask for missing battery mass before promising
    endurance." It is modelled separately from :class:`Recommendation` so the edit-operation union
    stays closed - the four operations in section 6 are the only things that can change geometry.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=r"^req_[a-z0-9][a-z0-9_.-]{1,62}$")
    base_revision_id: str
    title: str
    quantity: str = Field(description="Dotted path of the claim to supply, e.g. prt_harness.mass_kg")
    unit: str
    target_part_id: str | None = None
    why_it_matters: str = Field(
        description="Which checks are unknown until this is supplied."
    )
    blocked_check_ids: list[str] = Field(default_factory=list)
    suggested_source_kinds: list[str] = Field(
        default_factory=lambda: ["bom", "manual"],
        description="What would count as adequate evidence. Never 'inferred' for a mass.",
    )


class RecommendationSet(BaseModel):
    """``recommendations.json`` - B -> review UI. Budgeted per section 7."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    base_revision_id: str
    mission_hash: str
    generated: list[Recommendation] = Field(default_factory=list)
    evidence_requests: list[EvidenceRequest] = Field(
        default_factory=list,
        description=(
            "Asked for before promising a number. These are shown above edit proposals when a "
            "required check is unknown, because an edit ranked on unknown inputs is theatre."
        ),
    )
    displayed_proposal_ids: list[str] = Field(default_factory=list)
    provider_calls_used: int = Field(default=0, ge=0)
    budget_notes: list[str] = Field(default_factory=list)
    unevaluated_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _budgets(self) -> Self:
        if len(self.generated) > MAX_CANDIDATES:
            raise ValueError(f"candidate budget is {MAX_CANDIDATES}, got {len(self.generated)}")
        if len(self.displayed_proposal_ids) > MAX_DISPLAYED:
            raise ValueError(f"display budget is {MAX_DISPLAYED}")
        if self.provider_calls_used > MAX_PROVIDER_CALLS:
            raise ValueError(f"provider call budget is {MAX_PROVIDER_CALLS}")
        known = {r.proposal_id for r in self.generated}
        for proposal_id in self.displayed_proposal_ids:
            if proposal_id not in known:
                raise ValueError(f"displayed proposal {proposal_id} was not generated")
        return self

    def displayed(self) -> list[Recommendation]:
        order = {pid: i for i, pid in enumerate(self.displayed_proposal_ids)}
        return sorted(
            (r for r in self.generated if r.proposal_id in order),
            key=lambda r: order[r.proposal_id],
        )


#: Section 7 application limits. Not claims about provider pricing.
MAX_CANDIDATES = 6
MAX_DISPLAYED = 3
MAX_PROVIDER_CALLS = 2
MAX_QUEUED_NATIVE_ANALYSES = 3


class DecisionRequest(BaseModel):
    """An accept or decline. The four fields on an accept are what make CAS possible."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    decision: Literal["accept", "decline"]
    expected_active_revision_id: str = Field(pattern=r"^rev_[0-9a-f]{16}$")
    preview_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Required on accept: the exact preview the user reviewed.",
    )
    idempotency_key: str = Field(min_length=8, max_length=128)
    reason: str | None = Field(default=None, description="Optional note, recorded on a decline.")

    @model_validator(mode="after")
    def _accept_needs_preview_hash(self) -> Self:
        if self.decision == "accept" and self.preview_hash is None:
            raise ValueError("accepting requires the reviewed preview_hash")
        return self


class DecisionOutcome(BaseModel):
    """What a decision did. A repeated idempotency key returns this object unchanged."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    decision: Literal["accept", "decline"]
    state: ProposalState
    active_revision_id: str = Field(
        description="The active revision after the decision. A decline leaves it untouched."
    )
    committed_revision_id: str | None = None
    idempotency_key: str
    replayed: bool = Field(
        default=False, description="True when this outcome was returned from the idempotency store."
    )
    message: str = ""


class ProposalContext(BaseModel):
    """Exactly what a provider adapter is allowed to see.

    Section 7: compute affected constraints with typed traversals; do not send the entire graph to
    the model. This object is the whole input surface, and it carries no raw geometry.
    """

    model_config = ConfigDict(extra="forbid")

    design_id: str
    revision_id: str
    mission_hash: str
    objective: str
    failing_checks: list[str] = Field(default_factory=list)
    unknown_checks: list[str] = Field(default_factory=list)
    editable_parts: dict[str, list[str]] = Field(
        default_factory=dict, description="part_id -> the operations it supports."
    )
    part_summaries: list[str] = Field(
        default_factory=list, description="Compact descriptors. Never triangle dumps."
    )
    metrics: dict[str, Claim] = Field(default_factory=dict)
    catalog_item_ids: list[str] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)
