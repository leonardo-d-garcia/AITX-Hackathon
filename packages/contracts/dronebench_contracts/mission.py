"""Mission, objective, and the required-check registry (architecture sections 7 and 8).

The registry is versioned and owned by the mission profile. Architecture section 8 is explicit:
"A proposal or LLM cannot edit that registry, downgrade a check to optional, or alter mission
limits." That is enforced here by making the registry frozen and by hashing it into the mission
hash, so any tampering changes the hash and invalidates every cached evaluation against it.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .identity import content_hash

Objective = Literal["max_endurance"]
"""Only one objective in v1 (architecture section 8). Range/speed/payload come after dimensional
consistency and meaningful constraints are implemented."""

CheckClass = Literal[
    "hard_invariant",        # editable-design invariant; blocks commit
    "modeled_constraint",    # engineering constraint from the model
    "regulatory",            # applicability, not certification
    "informational",         # heuristic; never blocks
]

CheckStatus = Literal["pass", "fail", "unknown", "not_applicable"]

Jurisdiction = Literal["US"]
OperationProfile = Literal["part_107_commercial", "recreational_44809"]


class RequiredCheck(BaseModel):
    """One check the mission profile requires every evaluation to report."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str
    title: str
    check_class: CheckClass
    rationale: str


class CheckRegistry(BaseModel):
    """The versioned set of checks a mission profile requires. Frozen by construction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    registry_version: str
    checks: tuple[RequiredCheck, ...]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [check.check_id for check in self.checks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate check_id in registry")
        return self

    @property
    def check_ids(self) -> frozenset[str]:
        return frozenset(check.check_id for check in self.checks)

    def get(self, check_id: str) -> RequiredCheck:
        for check in self.checks:
            if check.check_id == check_id:
                return check
        raise KeyError(check_id)

    def blocking_ids(self) -> frozenset[str]:
        """Checks whose failure or required-unknown blocks a commit."""
        return frozenset(
            check.check_id
            for check in self.checks
            if check.check_class in ("hard_invariant", "modeled_constraint")
        )


#: The v1 registry for a small electric fixed-wing on a straight-and-level cruise mission.
#: Every id here must appear in every evaluation; an absent check becomes unknown, and a required
#: unknown prevents "verified feasible" (architecture section 8).
FIXED_WING_CRUISE_V1 = CheckRegistry(
    registry_version="fixed_wing_cruise/1.0",
    checks=(
        RequiredCheck(
            check_id="mass_budget",
            title="All-up mass within maximum takeoff mass",
            check_class="hard_invariant",
            rationale="Exceeding MTOM invalidates every downstream performance figure.",
        ),
        RequiredCheck(
            check_id="cg_envelope",
            title="Centre of gravity inside the declared envelope",
            check_class="hard_invariant",
            rationale="Outside the envelope the aircraft is not trimmable by the modelled surfaces.",
        ),
        RequiredCheck(
            check_id="static_margin",
            title="Static margin within bounds",
            check_class="modeled_constraint",
            rationale=(
                "Requires a neutral point from a suitable stability method. A wing quarter-chord "
                "guess does not qualify for a V-tail aircraft, so this is often unknown."
            ),
        ),
        RequiredCheck(
            check_id="energy_reserve",
            title="Mission completes with the declared reserve withheld",
            check_class="modeled_constraint",
            rationale="Usable energy is energy after reserve; a route that needs the reserve fails.",
        ),
        RequiredCheck(
            check_id="spar_stress",
            title="Spar root bending stress within allowable",
            check_class="modeled_constraint",
            rationale=(
                "Bending stress only. Buckling, joints, adhesive, and local damage are not "
                "modelled and are listed as omitted."
            ),
        ),
        RequiredCheck(
            check_id="stall_margin",
            title="Cruise speed above stall by the declared margin",
            check_class="modeled_constraint",
            rationale=(
                "Needs an explicitly supported or assumed CLmax. VSPAERO linear lift does not "
                "establish stall."
            ),
        ),
        RequiredCheck(
            check_id="battery_current",
            title="Cruise current within the pack and ESC ratings",
            check_class="modeled_constraint",
            rationale="Needs a consistent electrical model, not a KV number alone.",
        ),
        RequiredCheck(
            check_id="clearance",
            title="No unintended interference, including propeller swept volume",
            check_class="hard_invariant",
            rationale="Declared mating and nesting pairs are excluded; only unintended overlap fails.",
        ),
        RequiredCheck(
            check_id="registration_applicability",
            title="Aircraft registration applicability for the selected operation",
            check_class="regulatory",
            rationale=(
                "Applicability only. Registration is not governed by a blanket 250 g exemption; "
                "that exemption belongs to qualifying recreational operation."
            ),
        ),
        RequiredCheck(
            check_id="remote_id_applicability",
            title="Remote ID applicability for the selected operation",
            check_class="regulatory",
            rationale=(
                "Follows registration status with operational exceptions such as FRIAs. Cannot be "
                "inferred from a CAD body named 'Remote ID'."
            ),
        ),
        RequiredCheck(
            check_id="tail_volume",
            title="Effective tail volume coefficient in the informational range",
            check_class="informational",
            rationale=(
                "A profile heuristic, not a certification criterion, and computed from effective "
                "V-tail projections."
            ),
        ),
    ),
)

REGISTRIES: dict[str, CheckRegistry] = {
    FIXED_WING_CRUISE_V1.registry_version: FIXED_WING_CRUISE_V1,
}


class RegulatoryProfile(BaseModel):
    """One jurisdiction and operation profile, chosen in mission setup (architecture section 7)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    jurisdiction: Jurisdiction
    operation: OperationProfile
    over_people: bool | None = Field(
        default=None, description="None means the fact was not supplied, not that it is false."
    )
    beyond_visual_line_of_sight: bool | None = None
    in_friaa: bool | None = Field(
        default=None, description="Operating within an FAA-Recognized Identification Area."
    )
    evidence_ids: tuple[str, ...] = ()


class Mission(BaseModel):
    """The locked mission. Its hash pins every evaluation and cache key."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    mission_id: str
    title: str
    objective: Objective = "max_endurance"

    cruise_speed_mps: float = Field(gt=0)
    altitude_m: float = Field(ge=0)
    air_density_kgm3: float = Field(gt=0)
    max_takeoff_mass_kg: float = Field(gt=0)
    payload_mass_kg: float = Field(ge=0)
    energy_reserve_fraction: float = Field(
        ge=0.0, lt=1.0, description="Withheld before usable energy is computed."
    )
    route_length_km: float = Field(gt=0)
    load_factor_limit: float = Field(gt=0)

    cg_envelope_station_m: tuple[float, float] = Field(
        description="Aft-positive station bounds (s = -x) for the centre of gravity."
    )
    stall_margin_fraction: float = Field(
        ge=0.0, description="Required fraction by which cruise speed exceeds stall speed."
    )
    static_margin_bounds: tuple[float, float] = Field(
        default=(0.08, 0.25),
        description=(
            "Acceptable (min, max) static margin as a fraction of MAC. Must be consistent with "
            "cg_envelope_station_m and the neutral point, or the two checks contradict each other; "
            "the validator below enforces that."
        ),
    )

    locked_part_ids: tuple[str, ...] = Field(
        default=(), description="Mission payload occurrences that may not be removed or moved."
    )
    registry_version: str = FIXED_WING_CRUISE_V1.registry_version
    regulatory: RegulatoryProfile

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.registry_version not in REGISTRIES:
            raise ValueError(f"unknown check registry {self.registry_version}")
        lo, hi = self.cg_envelope_station_m
        if hi <= lo:
            raise ValueError("cg envelope upper bound must exceed the lower bound")
        sm_lo, sm_hi = self.static_margin_bounds
        if sm_hi <= sm_lo or sm_lo < 0:
            raise ValueError("static margin bounds must be a positive, ordered range")
        if self.payload_mass_kg > self.max_takeoff_mass_kg:
            raise ValueError("payload exceeds maximum takeoff mass")
        return self

    @property
    def registry(self) -> CheckRegistry:
        return REGISTRIES[self.registry_version]

    def mission_hash(self) -> str:
        """Hash covering the mission *and* its check registry.

        Folding the registry in is what makes section 8's tamper rule mechanical: editing a check
        changes the hash, which invalidates every cached evaluation rather than silently reusing
        results computed under different rules.
        """
        return content_hash(
            {
                "mission": self.model_dump(mode="json"),
                "registry": self.registry.model_dump(mode="json"),
            }
        )
