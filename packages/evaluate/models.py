"""Claim, check, and evaluation models. Unknown is a valid result; null is not zero."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ClaimStatus = Literal["known", "unknown", "conflicted", "assumed", "estimated"]
CheckStatus = Literal["pass", "fail", "unknown", "not_applicable"]
FidelityTier = Literal["analytic", "vspaero"]


class FidelityMismatch(ValueError):
    """Raised when an analytic evaluation is compared to a vspaero one (or vice versa)."""


class AssumptionRange(BaseModel):
    """Propagated input-assumption band. Not a confidence interval."""

    low: float
    nominal: float
    high: float

    @model_validator(mode="after")
    def _ordered(self) -> AssumptionRange:
        low = min(self.low, self.nominal)
        high = max(self.high, self.nominal)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)
        return self


class Claim(BaseModel):
    value: Any = None
    status: ClaimStatus = "unknown"
    unit: str | None = None
    source: str | None = None
    notes: str | None = None
    assumption_range: AssumptionRange | None = None
    missing_fields: list[str] = Field(default_factory=list)

    @field_validator("value")
    @classmethod
    def _no_nonfinite(cls, v: Any) -> Any:
        return _finite_or_none(v)


class Check(BaseModel):
    id: str
    status: CheckStatus = "unknown"
    value: Any = None
    limit: list[Any] | None = None
    missing_fields: list[str] = Field(default_factory=list)
    message: str | None = None

    @field_validator("value")
    @classmethod
    def _no_nonfinite_value(cls, v: Any) -> Any:
        return _finite_or_none(v)

    @field_validator("limit")
    @classmethod
    def _no_nonfinite_limit(cls, v: list[Any] | None) -> list[Any] | None:
        if v is None:
            return v
        return [_finite_or_none(x) for x in v]


class Evaluation(BaseModel):
    revision_id: str
    geometry_hash: str
    fidelity_tier: FidelityTier
    metrics: dict[str, Claim]
    checks: list[Check]
    assumptions: list[str] = Field(default_factory=list)
    solver_versions: dict[str, Any] = Field(default_factory=dict)
    input_hashes: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    quarantined: list[Claim] = Field(default_factory=list)


def _is_nonfinite_number(v: Any) -> bool:
    if isinstance(v, bool) or v is None:
        return False
    if isinstance(v, (int, float)):
        return v != v or v == float("inf") or v == float("-inf")
    return False


def _finite_or_none(v: Any) -> Any:
    if _is_nonfinite_number(v):
        return None
    if isinstance(v, list):
        return [_finite_or_none(x) for x in v]
    if isinstance(v, tuple):
        return [_finite_or_none(x) for x in v]
    return v


def make_claim(
    value: Any,
    status: ClaimStatus = "known",
    *,
    unit: str | None = None,
    source: str | None = None,
    notes: str | None = None,
    assumption_range: AssumptionRange | dict | None = None,
    missing_fields: list[str] | None = None,
) -> Claim:
    if value is None and status == "known":
        status = "unknown"
    if _is_nonfinite_number(value):
        value = None
        if status == "known":
            status = "unknown"
    rng = None
    if assumption_range is not None:
        rng = (
            assumption_range
            if isinstance(assumption_range, AssumptionRange)
            else AssumptionRange.model_validate(assumption_range)
        )
    return Claim(
        value=value,
        status=status,
        unit=unit,
        source=source,
        notes=notes,
        assumption_range=rng,
        missing_fields=list(missing_fields or []),
    )


def unknown_claim(
    *,
    unit: str | None = None,
    missing_fields: list[str] | None = None,
    source: str | None = None,
    notes: str | None = None,
) -> Claim:
    return make_claim(
        None,
        "unknown",
        unit=unit,
        source=source,
        notes=notes,
        missing_fields=missing_fields,
    )


def assumption_band(nominal: float, frac: float = 0.15) -> AssumptionRange:
    """Former flat ±15% band, now an explicit assumption range (not a CI)."""
    return AssumptionRange(
        low=nominal * (1.0 - frac),
        nominal=nominal,
        high=nominal * (1.0 + frac),
    )
