"""Claim-level evidence (architecture section 5).

The rule this module exists to enforce: *unknown is a first-class result*. A missing value stays
``null``, never zero, and carries no numerical confidence. One ``confidence: 1.0`` for a whole part
is not expressible here - every claim carries its own source, evidence, status, and optional
confidence.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .units import NON_NEGATIVE_UNITS, Unit

ClaimStatus = Literal["known", "estimated", "unknown", "conflicted"]

SourceKind = Literal[
    "cad",        # measured off confirmed geometry
    "bom",        # a bill-of-materials entry
    "manual",     # a datasheet or manufacturer document
    "catalog",    # a supplier catalog snapshot
    "computed",   # derived by our own deterministic code from other claims
    "inferred",   # pattern/proximity/name heuristics - never proof
    "assumed",    # a declared modelling assumption
]

#: Source kinds that count as measured or user-confirmed. Architecture section 5: prefer these
#: over inferred ones, and do not let a lower-quality recent source override them automatically.
MEASURED_SOURCE_KINDS: frozenset[str] = frozenset({"cad", "bom", "manual", "catalog"})

#: Ranking used when selecting among conflicting claims. Higher wins.
SOURCE_RANK: dict[str, int] = {
    "manual": 50,
    "bom": 45,
    "catalog": 40,
    "cad": 35,
    "computed": 20,
    "assumed": 10,
    "inferred": 5,
}


class Evidence(BaseModel):
    """One retrievable source record behind a claim."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(pattern=r"^ev_[a-z0-9][a-z0-9_.-]{1,62}$")
    source_uri: str = Field(description="URI or repository-relative path of the source")
    source_kind: SourceKind
    accessed_at: datetime | None = Field(
        default=None, description="When the source was read. Display-only; excluded from hashes."
    )
    content_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Hash of the source bytes when the source is a retrievable file.",
    )
    locator: str | None = Field(
        default=None, description="Page, table, field, body name, or line range in the source."
    )
    extraction_method: str = Field(
        description="How the value was obtained: stl_bounds, manual_entry, catalog_field, ..."
    )
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    note: str | None = Field(default=None, description="Display-only; excluded from hashes.")

    @model_validator(mode="after")
    def _validity_ordered(self) -> Self:
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to precedes valid_from")
        return self


class Claim(BaseModel):
    """A single asserted quantity with its provenance.

    ``value is None`` means unknown. It does not mean zero, and it may not carry a confidence.
    """

    model_config = ConfigDict(extra="forbid")

    value: float | int | str | bool | None = None
    unit: Unit
    status: ClaimStatus
    source_kind: SourceKind
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = Field(
        default=None,
        description=(
            "Optional and uncalibrated unless a calibration record is cited. Not a statistical "
            "probability."
        ),
    )
    assumptions: list[str] = Field(
        default_factory=list,
        description="Declared modelling assumptions this value depends on.",
    )

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("claim value must be finite")

        if self.status == "unknown":
            if self.value is not None:
                raise ValueError("an unknown claim must carry value=None")
            if self.confidence is not None:
                raise ValueError("an unknown claim carries no confidence")
        elif self.value is None:
            raise ValueError(
                f"status={self.status} requires a value; use status unknown instead"
            )

        if self.source_kind == "assumed" and not self.assumptions:
            raise ValueError("an assumed claim must state at least one assumption")

        if (
            self.unit in NON_NEGATIVE_UNITS
            and isinstance(self.value, (int, float))
            and not isinstance(self.value, bool)
            and self.value < 0
        ):
            raise ValueError(f"unit {self.unit} cannot take a negative value ({self.value})")

        return self

    # -- constructors ----------------------------------------------------------------------

    @classmethod
    def unknown(cls, unit: Unit, *, reason: str, source_kind: SourceKind = "inferred") -> "Claim":
        """The value is not determinable from available evidence."""
        return cls(
            value=None,
            unit=unit,
            status="unknown",
            source_kind=source_kind,
            assumptions=[reason] if source_kind == "assumed" else [],
            evidence_ids=[],
        )

    @classmethod
    def measured(
        cls,
        value: float | int | str | bool,
        unit: Unit,
        *,
        source_kind: SourceKind,
        evidence_ids: list[str],
    ) -> "Claim":
        if source_kind not in MEASURED_SOURCE_KINDS:
            raise ValueError(f"{source_kind} is not a measured source kind")
        if not evidence_ids:
            raise ValueError("a measured claim must cite evidence")
        return cls(
            value=value,
            unit=unit,
            status="known",
            source_kind=source_kind,
            evidence_ids=evidence_ids,
        )

    @classmethod
    def computed(
        cls,
        value: float | int,
        unit: Unit,
        *,
        assumptions: list[str] | None = None,
        evidence_ids: list[str] | None = None,
    ) -> "Claim":
        return cls(
            value=value,
            unit=unit,
            status="estimated",
            source_kind="computed",
            assumptions=assumptions or [],
            evidence_ids=evidence_ids or [],
        )

    @classmethod
    def assumed(cls, value: float | int | str, unit: Unit, *, assumption: str) -> "Claim":
        return cls(
            value=value,
            unit=unit,
            status="estimated",
            source_kind="assumed",
            assumptions=[assumption],
        )

    # -- helpers ---------------------------------------------------------------------------

    @property
    def is_known(self) -> bool:
        return self.status in ("known", "estimated", "conflicted") and self.value is not None

    @property
    def is_measured(self) -> bool:
        return self.is_known and self.source_kind in MEASURED_SOURCE_KINDS

    def number(self) -> float | None:
        """Numeric value, or ``None`` when unknown. Never silently substitutes zero."""
        if not self.is_known:
            return None
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            return None
        return float(self.value)

    def require(self, what: str) -> float:
        """Numeric value, raising when unknown. Callers that cannot proceed use this."""
        number = self.number()
        if number is None:
            raise MissingClaimValue(f"{what} is unknown ({self.status})")
        return number


class MissingClaimValue(LookupError):
    """A calculation needed a value that is unknown.

    Callers downgrade the affected result to unknown; they do not fabricate a substitute.
    """


class ConflictSet(BaseModel):
    """Conflicting claims for one quantity, preserved with an explicit selection and rationale.

    Architecture section 5: never silently alter evidence. Every candidate stays; the selection
    and the reason for it are recorded alongside them.
    """

    model_config = ConfigDict(extra="forbid")

    quantity: str
    candidates: list[Claim] = Field(min_length=2)
    selected_index: int = Field(ge=0)
    rationale: str

    @model_validator(mode="after")
    def _selected_in_range(self) -> Self:
        if self.selected_index >= len(self.candidates):
            raise ValueError("selected_index out of range")
        return self

    @property
    def selected(self) -> Claim:
        chosen = self.candidates[self.selected_index]
        return chosen.model_copy(update={"status": "conflicted"})

    @classmethod
    def resolve(cls, quantity: str, candidates: list[Claim]) -> "ConflictSet":
        """Select by source rank; ties keep the first. A recent low-quality source cannot win."""
        ranked = sorted(
            range(len(candidates)),
            key=lambda i: (-SOURCE_RANK.get(candidates[i].source_kind, 0), i),
        )
        best = ranked[0]
        chosen = candidates[best]
        return cls(
            quantity=quantity,
            candidates=candidates,
            selected_index=best,
            rationale=(
                f"selected the {chosen.source_kind} value by source rank "
                f"({SOURCE_RANK.get(chosen.source_kind, 0)}); all candidates retained"
            ),
        )


class ClaimSet(BaseModel):
    """Named claims for one entity, plus any preserved conflicts."""

    model_config = ConfigDict(extra="forbid")

    claims: dict[str, Claim] = Field(default_factory=dict)
    conflicts: list[ConflictSet] = Field(default_factory=list)

    def get(self, name: str) -> Claim | None:
        return self.claims.get(name)

    def number(self, name: str) -> float | None:
        claim = self.claims.get(name)
        return claim.number() if claim else None

    def unknown_names(self) -> list[str]:
        return sorted(name for name, claim in self.claims.items() if not claim.is_known)

    def evidence_ids(self) -> list[str]:
        seen: list[str] = []
        for claim in self.claims.values():
            for evidence_id in claim.evidence_ids:
                if evidence_id not in seen:
                    seen.append(evidence_id)
        return seen


def as_json_value(obj: Any) -> Any:
    """Pydantic -> plain JSON value, keeping ``None`` for unknowns."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json", exclude_none=False)
    return obj
