"""Typed failures. Anything a caller can act on is an ``ErrorEnvelope``, never a bare exception."""
from __future__ import annotations

from typing import Any

from dronebench_contracts.models import ErrorCode, ErrorEnvelope


class IngestError(Exception):
    """Carries an ErrorEnvelope. Raised only where a caller cannot continue (staging, bad input)."""

    def __init__(self, envelope: ErrorEnvelope):
        super().__init__(f"{envelope.code.value}: {envelope.message}")
        self.envelope = envelope


def rejected(message: str, **details: Any) -> IngestError:
    return IngestError(ErrorEnvelope(code=ErrorCode.INPUT_REJECTED, message=message, details=details))


def units_unconfirmed(message: str = "units and frame are not confirmed", **details: Any) -> ErrorEnvelope:
    return ErrorEnvelope(code=ErrorCode.UNITS_UNCONFIRMED, message=message, details=details)


def assembly_unconfirmed(message: str, **details: Any) -> ErrorEnvelope:
    return ErrorEnvelope(code=ErrorCode.ASSEMBLY_UNCONFIRMED, message=message, details=details)
