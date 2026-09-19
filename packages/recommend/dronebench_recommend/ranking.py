"""Ranking previewed candidates (architecture section 7, step 6).

"Rank feasible candidates by a mission objective under uncertainty, feasibility recovery, and
implementation cost; present all tradeoffs."

The ordering below is lexicographic rather than a weighted score, and deliberately so: a weighted
sum lets a large objective gain outvote an infeasible result, which is exactly the failure section 8
warns about when it says never to compare a failed design's zero with a successful design's minutes.

    1. Feasibility recovery  - a candidate that makes a failing design feasible outranks everything.
    2. Still feasible        - a candidate that keeps feasibility outranks one that breaks it.
    3. Objective gain        - only compared between candidates at the same fidelity tier.
    4. Implementation cost   - fewer affected parts and no aero invalidation wins the tie.

An unevaluated candidate is never ranked above an evaluated one. It cannot be: its gain is unknown,
and unknown does not sort as zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from dronebench_contracts import Recommendation, Tradeoff

#: Rough implementation cost per operation. Not money - reviewer effort and blast radius.
_OPERATION_COST: dict[str, int] = {
    "translate_component": 1,
    "replace_catalog_component": 2,
    "resize_spar": 3,
    "set_wing_tip_extension": 4,  # invalidates the aerodynamic geometry
}


@dataclass(frozen=True)
class RankedCandidate:
    recommendation: Recommendation
    recovers_feasibility: bool
    stays_feasible: bool
    objective_delta: float | None
    implementation_cost: int
    note: str

    @property
    def sort_key(self) -> tuple:
        return (
            0 if self.recovers_feasibility else 1,
            0 if self.stays_feasible else 1,
            -(self.objective_delta if self.objective_delta is not None else float("-inf")),
            self.implementation_cost,
            self.recommendation.proposal_id,
        )


def rank(recommendations: list[Recommendation]) -> list[RankedCandidate]:
    """Order previewed candidates. Unevaluated ones sink to the bottom, labelled."""
    ranked: list[RankedCandidate] = []

    for recommendation in recommendations:
        preview = recommendation.preview
        if preview is None or preview.evaluation is None:
            ranked.append(
                RankedCandidate(
                    recommendation=recommendation,
                    recovers_feasibility=False,
                    stays_feasible=False,
                    objective_delta=None,
                    implementation_cost=_OPERATION_COST.get(
                        recommendation.operation.operation, 9
                    ),
                    note="unevaluated proposal - no computed result to rank on",
                )
            )
            continue

        candidate_eval = preview.evaluation
        baseline_eval = preview.baseline_evaluation

        candidate_feasible = candidate_eval.verified_feasible
        baseline_feasible = baseline_eval.verified_feasible if baseline_eval else False

        delta: float | None = None
        note = ""
        if baseline_eval is not None:
            if baseline_eval.fidelity != candidate_eval.fidelity:
                # Section 8: do not subtract an analytic baseline from a VSPAERO-informed candidate.
                note = (
                    f"not comparable: baseline is {baseline_eval.fidelity}, candidate is "
                    f"{candidate_eval.fidelity}; both sides must be recomputed at one tier"
                )
            else:
                base_metric = baseline_eval.objective_value()
                cand_metric = candidate_eval.objective_value()
                if base_metric is not None and cand_metric is not None:
                    base_value, cand_value = base_metric.number(), cand_metric.number()
                    if base_value is not None and cand_value is not None:
                        if baseline_feasible == candidate_feasible:
                            delta = cand_value - base_value
                        else:
                            note = (
                                "feasibility changed, so the objective values are not directly "
                                "comparable; the feasibility result is what this proposal offers"
                            )
        if not note:
            note = (
                "recovers feasibility"
                if candidate_feasible and not baseline_feasible
                else ("stays feasible" if candidate_feasible else "still infeasible")
            )

        ranked.append(
            RankedCandidate(
                recommendation=recommendation,
                recovers_feasibility=candidate_feasible and not baseline_feasible,
                stays_feasible=candidate_feasible,
                objective_delta=delta,
                implementation_cost=_OPERATION_COST.get(recommendation.operation.operation, 9),
                note=note,
            )
        )

    return sorted(ranked, key=lambda row: row.sort_key)


#: Metrics where a smaller number is unambiguously the better outcome.
LOWER_IS_BETTER: frozenset[str] = frozenset(
    {
        "mass_kg",
        "cruise_power_w",
        "cruise_current_a",
        "wh_per_km",
        "drag_n",
        "cruise_cd",
        "spar_stress_pa",
        "spar_root_moment_nm",
        "v_stall_mps",
    }
)

#: Metrics where a larger number is unambiguously the better outcome.
HIGHER_IS_BETTER: frozenset[str] = frozenset(
    {"endurance_min", "range_km", "spar_safety_factor", "usable_energy_wh"}
)

#: Metrics that are only good or bad relative to a band the mission declares. The sign of the
#: change says nothing on its own - a centre of gravity moving forward is an improvement or a
#: regression depending entirely on where the envelope is. Their direction is taken from the
#: corresponding check instead.
BAND_METRICS: dict[str, str] = {
    "cg_station_m": "cg_envelope",
    "static_margin": "static_margin",
}

#: Everything else that moves is reported without a verdict.


def tradeoffs(recommendation: Recommendation) -> list[Tradeoff]:
    """Every metric that moved, improving or worsening.

    Section 10: "A proposal that increases spar margin but increases mass must show both." This
    reports all metrics present on either side rather than a curated subset, so a worsening metric
    cannot be omitted by whoever writes the card.

    Direction is assigned three ways, and never by guessing the sign convention:

    * monotone metrics by the sign of the change;
    * band metrics by whether their check moved between pass, fail, and unknown;
    * anything else as ``informational`` - shown, but with no verdict attached.
    """
    preview = recommendation.preview
    if preview is None or preview.evaluation is None or preview.baseline_evaluation is None:
        return []

    candidate = preview.evaluation
    baseline = preview.baseline_evaluation
    out: list[Tradeoff] = []

    for name in sorted(set(baseline.metrics) | set(candidate.metrics)):
        base_claim = baseline.metrics.get(name)
        cand_claim = candidate.metrics.get(name)
        base = base_claim.number() if base_claim else None
        cand = cand_claim.number() if cand_claim else None
        unit = (cand_claim or base_claim).unit if (cand_claim or base_claim) else "1"

        if base is None or cand is None:
            out.append(
                Tradeoff(
                    metric=name,
                    unit=unit,
                    baseline=base,
                    candidate=cand,
                    direction="unknown",
                    basis="one side of the comparison could not be computed",
                )
            )
            continue

        if abs(cand - base) <= 1e-9 * max(abs(base), 1.0):
            out.append(
                Tradeoff(
                    metric=name, unit=unit, baseline=base, candidate=cand, direction="unchanged"
                )
            )
            continue

        if name in BAND_METRICS:
            out.append(
                _band_tradeoff(name, unit, base, cand, baseline, candidate)
            )
        elif name in LOWER_IS_BETTER:
            out.append(
                Tradeoff(
                    metric=name,
                    unit=unit,
                    baseline=base,
                    candidate=cand,
                    direction="improves" if cand < base else "worsens",
                    basis="lower is better for this metric",
                )
            )
        elif name in HIGHER_IS_BETTER:
            out.append(
                Tradeoff(
                    metric=name,
                    unit=unit,
                    baseline=base,
                    candidate=cand,
                    direction="improves" if cand > base else "worsens",
                    basis="higher is better for this metric",
                )
            )
        else:
            out.append(
                Tradeoff(
                    metric=name,
                    unit=unit,
                    baseline=base,
                    candidate=cand,
                    direction="informational",
                    basis=(
                        "this metric has no better or worse direction on its own; it is reported "
                        "so the change is visible"
                    ),
                )
            )

    return out


def _band_tradeoff(
    name: str,
    unit: str,
    base: float,
    cand: float,
    baseline,
    candidate,
) -> Tradeoff:
    """Direction from the check the metric feeds, not from the sign of the change."""
    check_id = BAND_METRICS[name]
    rank = {"fail": 0, "unknown": 1, "pass": 2, "not_applicable": 2}
    try:
        before = baseline.check(check_id).status
        after = candidate.check(check_id).status
    except KeyError:  # pragma: no cover - the registry guarantees both are present
        return Tradeoff(
            metric=name, unit=unit, baseline=base, candidate=cand, direction="informational"
        )

    if rank[after] > rank[before]:
        direction, basis = "improves", f"{check_id} moved from {before} to {after}"
    elif rank[after] < rank[before]:
        direction, basis = "worsens", f"{check_id} moved from {before} to {after}"
    else:
        direction = "informational"
        basis = (
            f"{check_id} is {after} on both sides; the value moved but the verdict did not, and "
            "the sign of the change is not itself better or worse for a banded quantity"
        )
    return Tradeoff(
        metric=name, unit=unit, baseline=base, candidate=cand, direction=direction, basis=basis
    )
