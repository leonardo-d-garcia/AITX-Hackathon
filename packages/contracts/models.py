"""Pydantic models for the reusable Claim shape."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ClaimStatus = Literal[
    "known", "estimated", "unknown", "conflicted", "not_applicable"
]
SourceKind = Literal[
    "cad", "bom", "manual", "catalog", "computed", "inferred", "assumed"
]


class AssumptionRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    low: float
    nominal: float
    high: float

    @model_validator(mode="after")
    def ordered_and_finite(self) -> AssumptionRange:
        for label, value in (
            ("low", self.low),
            ("nominal", self.nominal),
            ("high", self.high),
        ):
            if not math.isfinite(value):
                raise ValueError(f"assumption_range.{label} must be finite")
        if not (self.low <= self.nominal <= self.high):
            raise ValueError("assumption_range must satisfy low <= nominal <= high")
        return self


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | None
    unit: str
    status: ClaimStatus
    source_kind: SourceKind
    evidence_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    assumption_range: AssumptionRange | None = None

    @model_validator(mode="after")
    def value_rules(self) -> Claim:
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("claim value must be finite (no NaN/Infinity)")
        if self.value is None and self.assumption_range is not None:
            raise ValueError("assumption_range must be omitted when value is null")
        if self.status == "unknown" and self.value is not None:
            raise ValueError("unknown claims must have null value")
        if self.status in ("known", "estimated") and self.value is None:
            raise ValueError("known/estimated claims must have a numeric value")
        return self
