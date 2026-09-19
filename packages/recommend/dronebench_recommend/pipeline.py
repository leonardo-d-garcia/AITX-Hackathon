"""The seven-step recommendation pipeline (architecture section 7).

1. Load the exact revision, mission, confirmed evidence, checks, capabilities, and catalog subset.
2. Generate bounded candidates from failing checks and typed dependency paths.
3. Optionally let a provider explain them, or propose inside the same operation schema.
4. Validate schema, target IDs, base revision, locks, bounds, units, evidence, solver availability.
5. Stage each selected candidate and calculate *actual* preview results through A and C.
6. Rank feasible candidates; label anything unevaluated.
7. Present accept and decline. Only acceptance of a verified preview requests a commit.

Step 5 is the one that matters most, and it is why this module takes ports rather than doing the
arithmetic itself: the preview number on the card is computed by the same evaluator that produced
the baseline, on a real child revision, not predicted.
"""

from __future__ import annotations

from dataclasses import dataclass

from dronebench_contracts import (
    CadPort,
    CatalogSnapshot,
    DroneBenchError,
    EvaluatePort,
    Evaluation,
    EvidenceGraph,
    FidelityTier,
    GeometryFeatures,
    MAX_CANDIDATES,
    MAX_DISPLAYED,
    Mission,
    PartsDocument,
    PreviewResult,
    Recommendation,
    RecommendationSet,
    content_hash,
)

from .candidates import Candidate, generate
from .provider import Provider, ProviderBudget, build_context
from .ranking import rank, tradeoffs
from .validate import validate_operation


@dataclass
class PreviewBuilt:
    """What the caller must persist after a preview is staged."""

    recommendation: Recommendation
    preview_parts: PartsDocument
    preview_features: GeometryFeatures
    cad_result: object


class RecommendationPipeline:
    """Generates, validates, previews, and ranks. Owns no storage."""

    def __init__(
        self,
        *,
        cad: CadPort,
        evaluate: EvaluatePort,
        provider: Provider,
    ) -> None:
        self.cad = cad
        self.evaluate = evaluate
        self.provider = provider

    # -- steps 1-4 ---------------------------------------------------------------------------

    def propose(
        self,
        *,
        design_id: str,
        parts: PartsDocument,
        features: GeometryFeatures,
        mission: Mission,
        evaluation: Evaluation,
        catalog: CatalogSnapshot,
        graph: EvidenceGraph | None = None,
    ) -> tuple[list[Recommendation], RecommendationSet]:
        """Steps 1-4. Returns validated, not-yet-previewed recommendations plus the empty set."""
        base_revision_id = parts.revision_id
        mission_hash = mission.mission_hash()

        candidates, requests = generate(
            parts=parts,
            features=features,
            mission=mission,
            evaluation=evaluation,
            catalog=catalog,
            graph=graph,
        )

        budget = ProviderBudget()
        provider_candidates: list[Recommendation] = []
        if budget.take():
            context = build_context(
                design_id=design_id,
                revision_id=base_revision_id,
                mission_hash=mission_hash,
                objective=mission.objective,
                parts=parts,
                evaluation=evaluation,
                catalog=catalog,
                evidence_notes=list(graph.unknown_relationships) if graph else [],
            )
            provider_candidates = list(
                self.provider.propose(context, list(_ALLOWED_OPERATIONS))
            )

        recommendations: list[Recommendation] = []
        budget_notes: list[str] = []

        for candidate in candidates:
            outcome = validate_operation(
                candidate.operation,  # type: ignore[arg-type]
                parts=parts,
                features=features,
                mission=mission,
                base_revision_id=base_revision_id,
                catalog=catalog,
                available_tiers=self.evaluate.available_tiers(),
                required_tier="analytic",
            )
            if not outcome.ok:
                budget_notes.append(
                    f"dropped {candidate.key}: " + "; ".join(outcome.reasons)
                )
                continue
            recommendations.append(
                _to_recommendation(
                    candidate,
                    design_id=design_id,
                    base_revision_id=base_revision_id,
                    mission_hash=mission_hash,
                    origin="deterministic",
                )
            )

        # A provider-authored candidate passes through exactly the same gate.
        for proposal in provider_candidates:
            if len(recommendations) >= MAX_CANDIDATES:
                budget_notes.append("provider candidates dropped: candidate budget reached")
                break
            outcome = validate_operation(
                proposal.operation,
                parts=parts,
                features=features,
                mission=mission,
                base_revision_id=base_revision_id,
                catalog=catalog,
                available_tiers=self.evaluate.available_tiers(),
                required_tier="analytic",
            )
            if not outcome.ok:
                budget_notes.append(
                    f"dropped provider candidate {proposal.proposal_id}: "
                    + "; ".join(outcome.reasons)
                )
                continue
            recommendations.append(
                proposal.model_copy(
                    update={
                        "origin": "provider",
                        "base_revision_id": base_revision_id,
                        "mission_hash": mission_hash,
                        "design_id": design_id,
                        "state": "proposed",
                        "preview": None,
                    }
                )
            )

        recommendations = recommendations[:MAX_CANDIDATES]
        if requests:
            budget_notes.insert(
                0,
                f"{len(requests)} missing-evidence request(s) take priority over edit proposals: "
                "a required check is unknown, so no gain can be promised yet",
            )

        empty = RecommendationSet(
            base_revision_id=base_revision_id,
            mission_hash=mission_hash,
            generated=recommendations,
            evidence_requests=requests,
            displayed_proposal_ids=[],
            provider_calls_used=budget.used,
            budget_notes=budget_notes,
            unevaluated_count=len(recommendations),
        )
        return recommendations, empty

    # -- step 5 ------------------------------------------------------------------------------

    def preview(
        self,
        recommendation: Recommendation,
        *,
        parts: PartsDocument,
        features: GeometryFeatures,
        mission: Mission,
        baseline: Evaluation,
        work_dir: str,
        fidelity: FidelityTier = "analytic",
    ) -> PreviewBuilt:
        """Stage one candidate and compute its real result through the CAD and evaluate ports."""
        cad_result = self.cad.apply_edit(
            base_revision_id=parts.revision_id,
            parts=parts,
            features=features,
            operation=recommendation.operation,
            work_dir=work_dir,
        )

        if not cad_result.ok:
            blocked = recommendation.transition("previewing").transition("blocked")
            preview = PreviewResult(
                preview_revision_id=recommendation.base_revision_id,
                preview_hash=content_hash(
                    {"blocked": recommendation.proposal_id, "base": recommendation.base_revision_id}
                ),
                base_revision_id=recommendation.base_revision_id,
                cad_ok=False,
                blocked_reasons=list(cad_result.diagnostics)
                or ["the CAD operation did not produce valid geometry"],
            )
            return PreviewBuilt(
                recommendation=blocked.model_copy(update={"preview": preview}),
                preview_parts=parts,
                preview_features=features,
                cad_result=cad_result,
            )

        preview_parts, preview_features = self.cad.edited_parts(
            parts=parts, features=features, operation=recommendation.operation
        )

        evaluation = self.evaluate.evaluate(
            revision_id=preview_parts.revision_id,
            parts=preview_parts,
            features=preview_features,
            mission=mission,
            fidelity=fidelity,
        )

        # Section 8: if the candidate came back at a different fidelity than the baseline,
        # recompute the baseline at the candidate's tier rather than subtracting across tiers.
        comparable_baseline = baseline
        if baseline.fidelity != evaluation.fidelity:
            comparable_baseline = self.evaluate.evaluate(
                revision_id=parts.revision_id,
                parts=parts,
                features=features,
                mission=mission,
                fidelity=evaluation.fidelity,
            )

        preview_hash = content_hash(
            {
                "base": recommendation.base_revision_id,
                "operation": recommendation.operation.model_dump(mode="json"),
                "parts": preview_parts.model_dump(mode="json"),
                "features": preview_features.model_dump(mode="json"),
                "evaluation": evaluation.model_dump(mode="json"),
            }
        )

        blocked_reasons = [
            f"{check.check_id} is {check.status}: {check.reason}"
            for check in evaluation.blocking()
        ]

        preview = PreviewResult(
            preview_revision_id=cad_result.preview_revision_id or preview_parts.revision_id,
            preview_hash=preview_hash,
            base_revision_id=recommendation.base_revision_id,
            cad_ok=True,
            evaluation=evaluation,
            baseline_evaluation=comparable_baseline,
            change_summary=_change_summary(recommendation, cad_result),
            blocked_reasons=blocked_reasons,
        )

        staged = recommendation.transition("previewing")
        with_preview = staged.model_copy(update={"preview": preview})
        with_preview = with_preview.model_copy(
            update={"tradeoffs": tradeoffs(with_preview)}
        )
        final_state = "review_ready" if not blocked_reasons else "blocked"
        return PreviewBuilt(
            recommendation=with_preview.transition(final_state),  # type: ignore[arg-type]
            preview_parts=preview_parts,
            preview_features=preview_features,
            cad_result=cad_result,
        )

    # -- step 6 ------------------------------------------------------------------------------

    def finalise(
        self,
        previewed: list[Recommendation],
        *,
        base_revision_id: str,
        mission_hash: str,
        evidence_requests: list,
        provider_calls_used: int,
        budget_notes: list[str],
    ) -> RecommendationSet:
        """Rank and select the displayed subset."""
        ranked = rank(previewed)
        displayed = [row.recommendation.proposal_id for row in ranked[:MAX_DISPLAYED]]
        notes = list(budget_notes)
        for row in ranked:
            notes.append(f"{row.recommendation.proposal_id}: {row.note}")
        if len(ranked) > MAX_DISPLAYED:
            notes.append(
                f"{len(ranked) - MAX_DISPLAYED} lower-ranked candidate(s) generated but not "
                "displayed; they remain retrievable by id"
            )
        return RecommendationSet(
            base_revision_id=base_revision_id,
            mission_hash=mission_hash,
            generated=[row.recommendation for row in ranked],
            evidence_requests=evidence_requests,
            displayed_proposal_ids=displayed,
            provider_calls_used=provider_calls_used,
            budget_notes=notes,
            unevaluated_count=sum(
                1
                for row in ranked
                if row.recommendation.preview is None
                or not row.recommendation.preview.evaluated
            ),
        )


_ALLOWED_OPERATIONS = (
    "translate_component",
    "resize_spar",
    "set_wing_tip_extension",
    "replace_catalog_component",
)


def _to_recommendation(
    candidate: Candidate,
    *,
    design_id: str,
    base_revision_id: str,
    mission_hash: str,
    origin: str,
) -> Recommendation:
    return Recommendation(
        proposal_id=f"rec_{candidate.key.replace('prt_', '').replace('_', '-')}",
        design_id=design_id,
        base_revision_id=base_revision_id,
        mission_hash=mission_hash,
        title=candidate.title,
        issue=candidate.issue,
        operation=candidate.operation,  # type: ignore[arg-type]
        prerequisites=list(candidate.prerequisites),
        rationale=candidate.rationale,
        evidence_ids=list(candidate.evidence_ids),
        evidence_path=candidate.evidence_path,
        origin=origin,  # type: ignore[arg-type]
        state="proposed",
    )


def _change_summary(recommendation: Recommendation, cad_result) -> list[str]:
    operation = recommendation.operation
    lines = [
        f"{operation.operation} on {operation.target_part_id}",
        "affected: " + ", ".join(cad_result.affected_part_ids),
    ]
    for name, value in sorted(cad_result.requested_parameters_applied.items()):
        lines.append(f"{name} -> {value:g}")
    if cad_result.mass_delta_kg is not None:
        delta = cad_result.mass_delta_kg.number()
        if delta is not None:
            lines.append(f"mass change {delta * 1000:+.1f} g")
    return lines
