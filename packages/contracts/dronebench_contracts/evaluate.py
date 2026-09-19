"""``evaluation.json`` - C -> B/UI, plus the fidelity vocabulary (architecture sections 5 and 8).

B owns this contract but not its implementation. Two rules from section 8 are structural here:

* Every required check id from the mission registry must be present. An absent check becomes
  ``unknown``, and a required unknown prevents "verified feasible".
* The fidelity tier bounds what the UI may claim. ``vspaero_informed`` is rejected unless a solver
  manifest with a real run is attached, so a label cannot outrun the artifact behind it.
"""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from .claims import Claim
from .mission import CheckClass, CheckStatus, REGISTRIES

FidelityTier = Literal[
    "analytic",          # mass/CG/aero/propulsion/structure equations only
    "vspaero_informed",  # a real .vsp3 generated from this revision and a real solver run
    "replay",            # telemetry from a declared reduced model or dynamics engine
]

#: What the UI is permitted to say for each tier. Section 8, "What the UI may claim".
TIER_CLAIM_TEXT: dict[str, str] = {
    "analytic": "Engineering estimate - assumptions shown",
    "vspaero_informed": "VSPAERO analysis + mission model",
    "replay": "Model replay",
}


class SolverManifest(BaseModel):
    """Exactly which binary produced a result. Required before a solver label may be shown."""

    model_config = ConfigDict(extra="forbid")

    solver: Literal["vspaero", "none"]
    version: str
    binary_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    geometry_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Hash of the geometry actually handed to the solver.",
    )
    inputs_discovered_at_runtime: bool = Field(
        default=False,
        description="Analysis inputs were enumerated from the installed build, not hardcoded.",
    )
    raw_output_artifact_ids: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    """One check outcome. ``unknown`` is a legitimate result and must not be coerced to a pass."""

    model_config = ConfigDict(extra="forbid")

    check_id: str
    check_class: CheckClass
    status: CheckStatus
    title: str
    value: Claim | None = None
    limit: str | None = Field(default=None, description="Human-readable statement of the bound.")
    reason: str
    missing_inputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unknown_needs_a_cause(self) -> Self:
        if self.status == "unknown" and not self.missing_inputs and not self.reason:
            raise ValueError(f"{self.check_id}: an unknown check must name what is missing")
        if self.status == "pass" and self.value is not None and not self.value.is_known:
            raise ValueError(f"{self.check_id}: cannot pass on an unknown value")
        return self


class SensitivityInterval(BaseModel):
    """A low/nominal/high span over declared uncertain inputs.

    Section 8 is explicit that this is an "assumption range", not a calibrated confidence interval.
    The field name and the required label keep that distinction visible downstream.
    """

    model_config = ConfigDict(extra="forbid")

    metric: str
    unit: str
    low: float
    nominal: float
    high: float
    varied_inputs: list[str]
    label: Literal["assumption range"] = "assumption range"

    @model_validator(mode="after")
    def _ordered_and_finite(self) -> Self:
        for value in (self.low, self.nominal, self.high):
            if not math.isfinite(value):
                raise ValueError(f"{self.metric}: non-finite sensitivity bound")
        if not (self.low <= self.nominal <= self.high):
            raise ValueError(f"{self.metric}: sensitivity bounds are not ordered")
        return self


class Evaluation(BaseModel):
    """``evaluation.json`` - C -> B/UI."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: str
    revision_id: str
    mission_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_version: str
    fidelity: FidelityTier
    solver: SolverManifest

    metrics: dict[str, Claim] = Field(default_factory=dict)
    checks: list[CheckResult] = Field(default_factory=list)
    sensitivity: list[SensitivityInterval] = Field(default_factory=list)

    inputs_used: dict[str, Claim] = Field(
        default_factory=dict,
        description="Section 8: report inputs and unknowns before numbers.",
    )
    unknown_inputs: list[str] = Field(default_factory=list)
    omitted_physics: list[str] = Field(
        default_factory=list,
        description="Openly listed. A short list here is what keeps the numbers honest.",
    )
    run_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    produced_by: Literal["C", "B-stub"] = Field(
        description="B-stub marks the reference evaluator B uses until Team C's lands."
    )
    elapsed_s: float = Field(default=0.0, ge=0.0)

    @model_validator(mode="before")
    @classmethod
    def _drop_derived(cls, data):
        """Ignore ``verified_feasible`` on the way in.

        It is serialised so the UI has one definition of "verified", but it is derived from the
        checks, so accepting it as input would let a caller assert a feasibility the checks do not
        support. Dropping it here is what makes an evaluation round-trip through its own artifact.
        """
        if isinstance(data, dict) and "verified_feasible" in data:
            data = {key: value for key, value in data.items() if key != "verified_feasible"}
        return data

    @model_validator(mode="after")
    def _registry_coverage_and_tier_honesty(self) -> Self:
        registry = REGISTRIES.get(self.registry_version)
        if registry is None:
            raise ValueError(f"unknown registry {self.registry_version}")

        reported = {check.check_id for check in self.checks}
        missing = registry.check_ids - reported
        if missing:
            raise ValueError(
                "evaluation omits required checks: " + ", ".join(sorted(missing))
            )
        unexpected = reported - registry.check_ids
        if unexpected:
            raise ValueError(
                "evaluation reports checks outside the registry: " + ", ".join(sorted(unexpected))
            )
        for check in self.checks:
            declared = registry.get(check.check_id)
            if check.check_class != declared.check_class:
                raise ValueError(
                    f"{check.check_id}: class {check.check_class} contradicts the registry "
                    f"({declared.check_class}); a proposal may not reclassify a check"
                )

        if self.fidelity == "vspaero_informed":
            if self.solver.solver != "vspaero":
                raise ValueError("vspaero_informed requires a vspaero solver manifest")
            if not self.solver.raw_output_artifact_ids:
                raise ValueError(
                    "vspaero_informed requires raw solver output artifacts; without a real run "
                    "the tier downgrades to analytic"
                )
            if self.solver.geometry_hash is None:
                raise ValueError("vspaero_informed requires the analysed geometry hash")
        return self

    # -- feasibility -------------------------------------------------------------------------

    def check(self, check_id: str) -> CheckResult:
        for result in self.checks:
            if result.check_id == check_id:
                return result
        raise KeyError(check_id)

    def failing(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status == "fail"]

    def required_unknown(self) -> list[CheckResult]:
        blocking = REGISTRIES[self.registry_version].blocking_ids()
        return [c for c in self.checks if c.status == "unknown" and c.check_id in blocking]

    def blocking(self) -> list[CheckResult]:
        """Checks that block a commit: failing hard/modelled checks, plus required unknowns."""
        blocking_ids = REGISTRIES[self.registry_version].blocking_ids()
        return [
            c
            for c in self.checks
            if c.check_id in blocking_ids and c.status in ("fail", "unknown")
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verified_feasible(self) -> bool:
        """True only when nothing blocking fails and nothing blocking is unknown.

        Serialised deliberately. The UI must not re-derive feasibility from the check list: that
        would put a second definition of "verified" in the codebase, and the two would drift.
        """
        return not self.blocking()

    @property
    def ui_claim(self) -> str:
        return TIER_CLAIM_TEXT[self.fidelity]

    def objective_value(self) -> Claim | None:
        """The metric the mission objective ranks on. ``None`` when it could not be computed."""
        return self.metrics.get("endurance_min")


class ComparisonPair(BaseModel):
    """Baseline and candidate evaluated at identical conditions (architecture section 8).

    Construction fails if the two sides used different missions, registries, or fidelity tiers, so
    an analytic baseline can never be subtracted from a VSPAERO-informed candidate.
    """

    model_config = ConfigDict(extra="forbid")

    baseline: Evaluation
    candidate: Evaluation
    metric: str

    @model_validator(mode="after")
    def _like_for_like(self) -> Self:
        if self.baseline.mission_hash != self.candidate.mission_hash:
            raise ValueError("comparison across different missions")
        if self.baseline.registry_version != self.candidate.registry_version:
            raise ValueError("comparison across different check registries")
        if self.baseline.fidelity != self.candidate.fidelity:
            raise ValueError(
                f"comparison across fidelity tiers ({self.baseline.fidelity} vs "
                f"{self.candidate.fidelity}); recompute both sides before showing a gain"
            )
        if self.baseline.revision_id == self.candidate.revision_id:
            raise ValueError("baseline and candidate are the same revision")
        return self

    def delta(self) -> float | None:
        """Candidate minus baseline, or ``None`` when either side is unknown.

        Section 8: never compare a failed design's zero with a successful design's minutes. If
        either side is not feasible the delta is still returned, but ``feasibility_changed`` tells
        the caller the comparison is not like-for-like in outcome.
        """
        base = self.baseline.metrics.get(self.metric)
        cand = self.candidate.metrics.get(self.metric)
        if base is None or cand is None:
            return None
        base_value, cand_value = base.number(), cand.number()
        if base_value is None or cand_value is None:
            return None
        return cand_value - base_value

    @property
    def feasibility_changed(self) -> bool:
        return self.baseline.verified_feasible != self.candidate.verified_feasible
