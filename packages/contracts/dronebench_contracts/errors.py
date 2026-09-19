"""The shared error envelope and its codes (architecture section 9).

``{code, message, revision_id, details, retryable}``. A null ``revision_id`` is allowed before an
import has happened. Every code below appears in the section 9 list; adding one is a contract
change that needs a decision note.

Modelled infeasibility is *not* an error. A design that fails a constraint returns a normal
evaluation with failing checks. ``CONSTRAINT_FAILED`` is reserved for the case where an operation
was blocked by that infeasibility, which the CLI distinguishes from execution failure by exit code.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ErrorCode = Literal[
    "UNITS_UNCONFIRMED",
    "ASSEMBLY_UNCONFIRMED",
    "MISSING_EVIDENCE",
    "UNSUPPORTED_EDIT",
    "STALE_REVISION",
    "GEOMETRY_INVALID",
    "CONSTRAINT_FAILED",
    "SOLVER_UNAVAILABLE",
    "SOLVER_TIMEOUT",
    "ARTIFACT_MISMATCH",
    # Envelope-level codes for ordinary transport failures. Not design conditions.
    "NOT_FOUND",
    "INVALID_REQUEST",
    "CONFLICT",
    "INTERNAL",
]

#: HTTP status for each code. Kept here so the API layer cannot drift from the contract.
HTTP_STATUS: dict[str, int] = {
    "UNITS_UNCONFIRMED": 409,
    "ASSEMBLY_UNCONFIRMED": 409,
    "MISSING_EVIDENCE": 422,
    "UNSUPPORTED_EDIT": 422,
    "STALE_REVISION": 409,
    "GEOMETRY_INVALID": 422,
    "CONSTRAINT_FAILED": 422,
    "SOLVER_UNAVAILABLE": 503,
    "SOLVER_TIMEOUT": 504,
    "ARTIFACT_MISMATCH": 500,
    "NOT_FOUND": 404,
    "INVALID_REQUEST": 400,
    "CONFLICT": 409,
    "INTERNAL": 500,
}

#: Codes whose condition may clear on its own. Everything else needs the caller to change something.
RETRYABLE_CODES: frozenset[str] = frozenset({"SOLVER_TIMEOUT", "SOLVER_UNAVAILABLE", "INTERNAL"})

#: Exit codes for the CLI. Architecture section 9: modelled infeasibility is a valid report and is
#: distinguished from execution failure.
EXIT_OK = 0
EXIT_INVALID_INPUT = 2
EXIT_TOOL_FAILURE = 3
EXIT_INFEASIBLE = 4


class ErrorEnvelope(BaseModel):
    """The single error shape every endpoint and CLI command returns."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    revision_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False

    @classmethod
    def of(
        cls,
        code: ErrorCode,
        message: str,
        *,
        revision_id: str | None = None,
        **details: Any,
    ) -> "ErrorEnvelope":
        return cls(
            code=code,
            message=message,
            revision_id=revision_id,
            details=details,
            retryable=code in RETRYABLE_CODES,
        )

    @property
    def http_status(self) -> int:
        return HTTP_STATUS[self.code]

    @property
    def exit_code(self) -> int:
        if self.code in ("CONSTRAINT_FAILED", "MISSING_EVIDENCE"):
            return EXIT_INFEASIBLE
        if self.code in ("INVALID_REQUEST", "NOT_FOUND", "UNSUPPORTED_EDIT"):
            return EXIT_INVALID_INPUT
        return EXIT_TOOL_FAILURE


class DroneBenchError(Exception):
    """Raised inside the service layer; the API and CLI both render the envelope."""

    def __init__(self, envelope: ErrorEnvelope) -> None:
        super().__init__(f"{envelope.code}: {envelope.message}")
        self.envelope = envelope

    @classmethod
    def of(
        cls,
        code: ErrorCode,
        message: str,
        *,
        revision_id: str | None = None,
        **details: Any,
    ) -> "DroneBenchError":
        return cls(ErrorEnvelope.of(code, message, revision_id=revision_id, **details))


def stale_revision(expected: str, actual: str, *, design_id: str) -> DroneBenchError:
    """The canonical compare-and-swap failure (architecture section 7)."""
    return DroneBenchError.of(
        "STALE_REVISION",
        (
            "the active revision moved while this proposal was under review; regenerate the "
            "proposal against the current revision"
        ),
        revision_id=actual,
        expected_active_revision_id=expected,
        actual_active_revision_id=actual,
        design_id=design_id,
    )
