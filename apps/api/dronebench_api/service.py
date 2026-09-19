"""The service functions behind both the HTTP API and the CLI (architecture section 9).

"Implement API and CLI through the same Python service functions." Everything below is transport
agnostic: it takes and returns contract models, raises
:class:`~dronebench_contracts.DroneBenchError`, and never formats output.

The ports for Team A's CAD and Team C's evaluator are injected. Swapping ``dronebench_api.stubs``
for ``packages/cad`` and ``packages/evaluate`` happens in :func:`build_workbench` and nowhere else.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from dronebench_contracts import (
    CONTRACT_VERSION,
    AuditEvent,
    CadPort,
    CatalogSnapshot,
    Claim,
    ComparisonPair,
    DecisionOutcome,
    DecisionRequest,
    DesignManifest,
    DroneBenchError,
    Evaluation,
    EvaluatePort,
    EvidenceGraph,
    FidelityTier,
    GeometryFeatures,
    JobRecord,
    Mission,
    Neighborhood,
    PartsDocument,
    Recommendation,
    RecommendationSet,
    Revision,
    RevisionManifest,
    SimulatePort,
    SimulationRun,
    canonical_json,
    compute_revision_id,
    content_hash,
)
from dronebench_graph import (
    affected_by_edit,
    build_graph,
    compatible_catalog_items,
    evidence_path_to_constraint,
    mass_evidence,
    neighborhood,
    part_node_id,
    regulation_node_id,
    what_fails_if_moved,
    why_rule_applies,
)
from dronebench_recommend import RecommendationPipeline, assess, default_provider
from dronebench_workflow import (
    ArtifactStore,
    Repository,
    RevisionService,
    TransactionService,
    connect,
)
from dronebench_workflow.jobs import JobQueue

from .stubs import AnalyticEvaluator, ParametricCadPort, ReducedOrderSimulator

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures"


@dataclass
class ConfirmRequest:
    """What the user confirms after import (architecture section 6, step 3).

    ``claim_entries`` is Team B's extension of the confirm step: section 10 requires "Unknown mass"
    to be actionable and to accept a value with provenance, and section 9 gives confirm the job of
    creating the revision that results. Recorded in ``docs/decisions/0002``.
    """

    units_confirmed: bool
    frame_confirmed: bool
    reconstruction_confirmed: bool
    variant_decisions: dict[str, str]
    claim_entries: list["ClaimEntry"]


@dataclass
class ClaimEntry:
    """A user-supplied value for a previously unknown claim, with its provenance."""

    part_id: str
    quantity: str
    value: float
    unit: str
    source_kind: str
    evidence_id: str
    note: str = ""


class Workbench:
    """One design workbench: storage, ports, graph, recommender, and transactions."""

    def __init__(
        self,
        *,
        root: Path,
        cad: CadPort,
        evaluate: EvaluatePort,
        simulate: SimulatePort,
        catalog: CatalogSnapshot,
    ) -> None:
        self.root = root
        self.connection = connect(root / "dronebench.sqlite")
        self.store = ArtifactStore(root / "artifacts")
        self.repository = Repository(self.connection)
        self.revisions = RevisionService(self.repository, self.store)
        self.transactions = TransactionService(self.repository, self.revisions)
        self.jobs = JobQueue(self.repository, self.store)
        self.cad = cad
        self.evaluator = evaluate
        self.simulator = simulate
        self.catalog = catalog
        self.pipeline = RecommendationPipeline(
            cad=cad, evaluate=evaluate, provider=default_provider()
        )
        self._lock = threading.Lock()

    def close(self) -> None:
        self.jobs.shutdown()
        self.connection.close()

    # -- ingestion ------------------------------------------------------------------------------

    def import_fixture(self, fixture: str = "b") -> JobRecord:
        """Import the frozen synthetic fixture.

        Team A owns archive ingestion (``packages/ingest``). Until it exists, this is the import
        path, and it is honest about what it is: it stages a checked-in parametric demonstrator,
        not a reconstruction of any supplied archive.
        """
        source = FIXTURE_DIR / fixture
        if not (source / "parts.json").is_file():
            raise DroneBenchError.of(
                "NOT_FOUND", f"no fixture at {source}", fixture=fixture
            )

        manifest = DesignManifest.model_validate(_read(source / "design_manifest.json"))
        design_id = manifest.design_id
        self.repository.create_design(design_id, manifest.display_name)
        mission = Mission.model_validate(_read(source / "mission.json"))
        self.repository.set_design_mission(design_id, mission)

        cache_key = JobQueue.cache_key(
            kind="import",
            revision_content_hash=content_hash(_read(source / "parts.json")),
            mission_hash=mission.mission_hash(),
            solver_version="fixture/1.0",
        )

        def work(work_dir: str, cancel: threading.Event) -> list[str]:
            parts = PartsDocument.model_validate(_read(source / "parts.json"))
            features = GeometryFeatures.model_validate(_read(source / "geometry_features.json"))

            # An imported revision is a draft: units, frame, and the reconstruction are not
            # confirmed yet, so nothing downstream may treat its metrics as engineering results.
            unconfirmed = features.model_copy(
                update={
                    "units_confirmed": False,
                    "frame_confirmed": False,
                    "reconstruction_confirmed": False,
                }
            )
            builder = self.revisions.builder(
                design_id=design_id,
                parent_revision_id=None,
                stage="draft",
                cause="import",
                mission=mission,
                label="import",
            )
            builder.add_json(
                role="design_manifest",
                relative_path="design_manifest.json",
                payload=manifest,
                produced_by="A",
            )
            builder.add_json(
                role="parts", relative_path="parts.json", payload=parts, produced_by="A"
            )
            builder.add_json(
                role="geometry_features",
                relative_path="geometry_features.json",
                payload=unconfirmed,
                produced_by="A",
            )
            builder.note(
                f"imported the {fixture} fixture: {manifest.display_name}",
                "units, frame, and reconstruction are unconfirmed; confirm them before metrics",
            )
            sealed = builder.seal(self.repository)
            self.transactions.activate(design_id, sealed.revision.revision_id)
            self.repository.append_event(
                design_id=design_id,
                kind="revision_created",
                tool_name="service.import_fixture",
                revision_id=sealed.revision.revision_id,
                artifact_ids=[a.artifact_id for a in sealed.artifacts],
                inputs_summary={"fixture": fixture, "occurrences": str(len(parts.occurrences))},
            )
            return [a.artifact_id for a in sealed.artifacts]

        return self.jobs.submit(
            kind="import",
            design_id=design_id,
            revision_id=None,
            cache_key=cache_key,
            work=work,
            allow_cache=False,
        )

    def confirm(self, design_id: str, request: ConfirmRequest) -> RevisionManifest:
        """Record the confirmation decisions and any supplied claims as a new revision."""
        active = self.repository.require_active_revision_id(design_id)
        state = self.revisions.load(active)
        mission = self.repository.design_mission(design_id)

        parts = _apply_claim_entries(state.parts, request.claim_entries)
        features = state.features.model_copy(
            update={
                "units_confirmed": request.units_confirmed,
                "frame_confirmed": request.frame_confirmed,
                "reconstruction_confirmed": request.reconstruction_confirmed,
            }
        )
        manifest = state.manifest

        if request.variant_decisions:
            manifest = manifest.model_copy(
                update={
                    "excluded_alternatives": sorted(
                        set(manifest.excluded_alternatives) | set(request.variant_decisions.values())
                    )
                }
            )

        notes = [
            f"units_confirmed={request.units_confirmed}",
            f"frame_confirmed={request.frame_confirmed}",
            f"reconstruction_confirmed={request.reconstruction_confirmed}",
        ]
        notes += [
            f"{entry.part_id}.{entry.quantity} = {entry.value} {entry.unit} "
            f"({entry.source_kind}, {entry.evidence_id})"
            for entry in request.claim_entries
        ]

        return self._commit_state(
            design_id=design_id,
            parent_revision_id=active,
            manifest=manifest,
            parts=parts,
            features=features,
            mission=mission,
            cause="confirm",
            label="confirm",
            notes=notes,
            affected=[entry.part_id for entry in request.claim_entries],
        )

    # -- reads -------------------------------------------------------------------------------------

    def get_revision(self, revision_id: str) -> RevisionManifest:
        return self.repository.get_manifest(revision_id)

    def get_parts(self, revision_id: str) -> PartsDocument:
        return self.revisions.load(revision_id).parts

    def get_features(self, revision_id: str) -> GeometryFeatures:
        return self.revisions.load(revision_id).features

    def history(self, design_id: str) -> list[Revision]:
        return self.repository.revision_history(design_id)

    def active_revision(self, design_id: str) -> str:
        return self.repository.require_active_revision_id(design_id)

    def get_graph(self, revision_id: str) -> EvidenceGraph:
        """Project the revision into its typed graph.

        The ``graph.json`` artifact stored on a committed revision is the *structural* snapshot:
        parts, interfaces, catalog, and regulatory applicability as they stood when the revision
        was sealed. Constraint nodes come from an evaluation, which is a separate artifact produced
        *about* a revision and often after it. So this composes rather than returning the stored
        copy - otherwise "what fails if this moves" would answer from a graph that predates the
        checks it is supposed to traverse.

        The stored artifact is unchanged and remains the record of what was committed.
        """
        state = self.revisions.load(revision_id)
        mission = self.repository.design_mission(state.design_id)
        report = assess(
            mission=mission, parts=state.parts, total_mass_kg=_total_mass(state.parts)
        )
        return build_graph(
            parts=state.parts,
            features=state.features,
            mission=mission,
            catalog=self.catalog,
            evaluation=state.evaluation,
            regulatory_findings=report.findings,
        )

    def get_neighborhood(
        self, revision_id: str, part_id: str, *, radius: int = 2
    ) -> Neighborhood:
        """A bounded subgraph. The full graph is never handed to a model or rendered whole."""
        graph = self.get_graph(revision_id)
        try:
            return neighborhood(graph, part_node_id(part_id), radius=radius)
        except KeyError as exc:
            raise DroneBenchError.of(
                "NOT_FOUND", f"{part_id} is not in revision {revision_id}", revision_id=revision_id
            ) from exc

    def explain(self, revision_id: str, part_id: str, question: str) -> dict[str, Any]:
        """The section 7 narrow queries, by name."""
        graph = self.get_graph(revision_id)
        node_id = part_node_id(part_id)
        if node_id not in {n.node_id for n in graph.nodes}:
            raise DroneBenchError.of(
                "NOT_FOUND", f"{part_id} is not in revision {revision_id}", revision_id=revision_id
            )

        if question == "mass_evidence":
            return mass_evidence(graph, part_id).model_dump(mode="json")
        if question == "what_fails_if_moved":
            return what_fails_if_moved(graph, part_id).model_dump(mode="json")
        if question == "affected_by_edit":
            return affected_by_edit(graph, part_id).model_dump(mode="json")
        if question == "fitting_alternatives":
            return self._fitting_alternatives(revision_id, part_id)
        if question.startswith("why_rule:"):
            rule = question.split(":", 1)[1]
            path = why_rule_applies(graph, regulation_node_id(rule))
            return path.model_dump(mode="json")
        raise DroneBenchError.of(
            "INVALID_REQUEST",
            f"unknown question {question!r}",
            supported=[
                "mass_evidence",
                "what_fails_if_moved",
                "affected_by_edit",
                "fitting_alternatives",
                "why_rule:<rule_id>",
            ],
        )

    def _fitting_alternatives(self, revision_id: str, part_id: str) -> dict[str, Any]:
        """"Which supplier alternatives actually fit?" - from declared interfaces only."""
        from dronebench_recommend.candidates import _bay_interface

        parts = self.get_parts(revision_id)
        occurrence = parts.by_id(part_id)
        category = {"battery": "battery", "spar": "spar", "servo": "servo"}.get(occurrence.role)
        if category is None:
            return {
                "part_id": part_id,
                "category": None,
                "results": [],
                "note": (
                    f"{occurrence.role} has no catalog category in the snapshot, so no alternatives "
                    "can be compared"
                ),
            }

        required = [_bay_interface(parts, occurrence)]
        results = compatible_catalog_items(
            occurrence=occurrence, required=required, catalog=self.catalog, category=category
        )
        return {
            "part_id": part_id,
            "category": category,
            "results": [
                {
                    "catalog_item_id": item.catalog_item_id,
                    "display_name": item.display_name,
                    "fits": fits,
                    "reasons": reasons,
                    "mass_kg": item.mass_kg.number(),
                    "synthetic": True,
                }
                for item, fits, reasons in results
            ],
            "note": (
                "Fit is computed from declared interfaces only, never from graph proximity. Every "
                "offer in this snapshot is a synthetic demo entry with no implied real supplier."
            ),
        }

    # -- evaluation ----------------------------------------------------------------------------------

    def evaluate(
        self, revision_id: str, *, fidelity: FidelityTier = "analytic", wait: bool = True
    ) -> tuple[JobRecord, Evaluation | None]:
        """Enqueue an evaluation against the locked mission and store it on the revision."""
        state = self.revisions.load(revision_id)
        mission = self.repository.design_mission(state.design_id)
        revision = self.repository.get_revision(revision_id)

        cache_key = JobQueue.cache_key(
            kind="evaluate",
            revision_content_hash=revision.content_hash,
            mission_hash=mission.mission_hash(),
            solver_version=f"{self.evaluator.owner}/{fidelity}",
            solver_settings={"fidelity": fidelity},
            model_tier="none",
            snapshot_hashes={"catalog": self.catalog.snapshot_id},
        )

        # An evaluation already on this revision for the same mission and tier is the answer, not
        # a reason to recompute. The artifact store is append-only, so rewriting it with a
        # byte-different but equivalent result would be an error rather than an update.
        existing = state.evaluation
        if (
            existing is not None
            and existing.mission_hash == mission.mission_hash()
            and existing.fidelity == fidelity
            and existing.registry_version == mission.registry_version
        ):
            manifest = self.repository.get_manifest(revision_id)
            artifact = manifest.artifact("evaluation")
            job = JobRecord(
                job_id=f"job_evaluate-cached-{revision_id[4:]}",
                kind="evaluate",
                status="succeeded",
                design_id=state.design_id,
                revision_id=revision_id,
                cache_key=cache_key,
                work_dir="",
                artifact_ids=[artifact.artifact_id] if artifact else [],
                cache_hit=True,
                reused_job_id=f"stored-evaluation-{existing.evaluation_id}",
                progress_note="reused the evaluation already stored on this revision",
            )
            self.repository.put_job(job)
            return job, existing

        holder: dict[str, Evaluation] = {}

        def work(work_dir: str, cancel: threading.Event) -> list[str]:
            evaluation = self.evaluator.evaluate(
                revision_id=revision_id,
                parts=state.parts,
                features=state.features,
                mission=mission,
                fidelity=fidelity,
            )
            holder["evaluation"] = evaluation
            artifact = self.store.write_json(
                design_id=state.design_id,
                revision_id=revision_id,
                relative_path="evaluation.json",
                payload=evaluation,
                produced_by="C",
                role="evaluation",
            )
            self._attach_artifact(revision_id, artifact)
            self.repository.append_event(
                design_id=state.design_id,
                kind="evaluation_completed",
                tool_name="service.evaluate",
                revision_id=revision_id,
                artifact_ids=[artifact.artifact_id],
                inputs_summary={
                    "fidelity": evaluation.fidelity,
                    "verified_feasible": str(evaluation.verified_feasible),
                    "produced_by": evaluation.produced_by,
                },
            )
            return [artifact.artifact_id]

        job = self.jobs.submit(
            kind="evaluate",
            design_id=state.design_id,
            revision_id=revision_id,
            cache_key=cache_key,
            work=work,
        )
        if wait:
            job = self.jobs.wait(job.job_id)
            if job.status == "failed":
                raise DroneBenchError.of(
                    job.error_code or "INTERNAL",  # type: ignore[arg-type]
                    job.error_message or "evaluation failed",
                    revision_id=revision_id,
                )
        return job, holder.get("evaluation") or self.revisions.load(revision_id).evaluation

    def require_evaluation(self, revision_id: str) -> Evaluation:
        state = self.revisions.load(revision_id)
        if state.evaluation is not None:
            return state.evaluation
        _, evaluation = self.evaluate(revision_id, wait=True)
        if evaluation is None:  # pragma: no cover - evaluate raises on failure
            raise DroneBenchError.of(
                "INTERNAL", "evaluation produced no result", revision_id=revision_id
            )
        return evaluation

    # -- recommendations ------------------------------------------------------------------------------

    def recommend(self, revision_id: str, *, preview_all: bool = True) -> RecommendationSet:
        """Steps 1-6 of section 7: generate, validate, preview for real, rank."""
        state = self.revisions.load(revision_id)
        mission = self.repository.design_mission(state.design_id)
        baseline = self.require_evaluation(revision_id)
        graph = self.get_graph(revision_id)

        proposals, draft = self.pipeline.propose(
            design_id=state.design_id,
            parts=state.parts,
            features=state.features,
            mission=mission,
            evaluation=baseline,
            catalog=self.catalog,
            graph=graph,
        )
        for proposal in proposals:
            self.repository.put_proposal(proposal)
        self.repository.append_event(
            design_id=state.design_id,
            kind="proposal_generated",
            tool_name="service.recommend",
            revision_id=revision_id,
            inputs_summary={
                "candidates": str(len(proposals)),
                "evidence_requests": str(len(draft.evidence_requests)),
                "provider_calls": str(draft.provider_calls_used),
            },
        )

        if not preview_all:
            return draft

        previewed = [self.preview(proposal.proposal_id) for proposal in proposals]
        return self.pipeline.finalise(
            previewed,
            base_revision_id=revision_id,
            mission_hash=mission.mission_hash(),
            evidence_requests=draft.evidence_requests,
            provider_calls_used=draft.provider_calls_used,
            budget_notes=draft.budget_notes,
        )

    def preview(self, proposal_id: str) -> Recommendation:
        """Step 5: build an isolated child revision and compute its real result."""
        proposal = self.repository.get_proposal(proposal_id)
        state = self.revisions.load(proposal.base_revision_id)
        mission = self.repository.design_mission(state.design_id)
        baseline = self.require_evaluation(proposal.base_revision_id)

        active = self.repository.require_active_revision_id(state.design_id)
        if active != proposal.base_revision_id:
            # Section 7: regenerate later proposals against the new active revision.
            stale = proposal.model_copy(update={"state": "stale"})
            self.repository.put_proposal(stale)
            return stale

        work_dir = str(self.store.job_dir(f"preview-{proposal_id}"))
        built = self.pipeline.preview(
            proposal,
            parts=state.parts,
            features=state.features,
            mission=mission,
            baseline=baseline,
            work_dir=work_dir,
        )

        recommendation = built.recommendation
        if recommendation.preview is not None and recommendation.preview.cad_ok:
            # The preview is a concrete immutable child revision, not a projection.
            builder = self.revisions.builder(
                design_id=state.design_id,
                parent_revision_id=proposal.base_revision_id,
                stage="staged_preview",
                cause="proposal_preview",
                mission=mission,
                proposal_id=proposal_id,
                label=f"preview {proposal_id}",
            )
            builder.add_json(
                role="design_manifest",
                relative_path="design_manifest.json",
                payload=state.manifest.model_copy(
                    update={"revision_id": built.preview_parts.revision_id}
                ),
                produced_by="A",
            )
            builder.add_json(
                role="parts",
                relative_path="parts.json",
                payload=built.preview_parts,
                produced_by="A",
            )
            builder.add_json(
                role="geometry_features",
                relative_path="geometry_features.json",
                payload=built.preview_features,
                produced_by="A",
            )
            builder.add_json(
                role="evaluation",
                relative_path="evaluation.json",
                payload=recommendation.preview.evaluation,
                produced_by="C",
                derived=True,
            )
            builder.add_json(
                role="cad_edit_result",
                relative_path="cad_edit_result.json",
                payload=built.cad_result,
                produced_by="A",
                derived=True,
            )
            builder.note(*recommendation.preview.change_summary)
            builder.affects(*recommendation.operation.owned_part_ids)
            sealed = builder.seal(self.repository)

            sealed_id = sealed.revision.revision_id
            evaluation = recommendation.preview.evaluation
            preview = recommendation.preview.model_copy(
                update={
                    "preview_revision_id": sealed_id,
                    # The evaluation was computed before the revision had its final id. Restamp it
                    # so the in-memory copy names the same revision as the stored artifact.
                    "evaluation": (
                        evaluation.model_copy(update={"revision_id": sealed_id})
                        if evaluation is not None
                        else None
                    ),
                }
            )
            recommendation = recommendation.model_copy(update={"preview": preview})
            self.repository.append_event(
                design_id=state.design_id,
                kind="proposal_previewed",
                tool_name="service.preview",
                revision_id=sealed.revision.revision_id,
                proposal_id=proposal_id,
                artifact_ids=[a.artifact_id for a in sealed.artifacts],
                inputs_summary={
                    "operation": recommendation.operation.operation,
                    "state": recommendation.state,
                },
            )

        self.repository.put_proposal(recommendation)
        return recommendation

    def decide(self, request: DecisionRequest) -> DecisionOutcome:
        """Step 7. Accept commits precisely the reviewed preview; decline changes nothing."""
        return self.transactions.decide(request, build_commit=self._build_commit)

    def _build_commit(
        self, proposal: Recommendation, preview_manifest: RevisionManifest
    ) -> RevisionManifest:
        """Promote a staged preview to a committed revision.

        The committed revision is built from the preview's own artifacts, so what is committed is
        byte-identical in content to what was reviewed. It is not recomputed.
        """
        preview_revision_id = preview_manifest.revision.revision_id
        state = self.revisions.load(preview_revision_id, verify=True)
        mission = self.repository.design_mission(state.design_id)

        builder = self.revisions.builder(
            design_id=state.design_id,
            parent_revision_id=proposal.base_revision_id,
            stage="committed",
            cause="proposal_commit",
            mission=mission,
            proposal_id=proposal.proposal_id,
            label=proposal.title,
        )
        builder.add_json(
            role="design_manifest",
            relative_path="design_manifest.json",
            payload=state.manifest,
            produced_by="A",
        )
        builder.add_json(
            role="parts", relative_path="parts.json", payload=state.parts, produced_by="A"
        )
        builder.add_json(
            role="geometry_features",
            relative_path="geometry_features.json",
            payload=state.features,
            produced_by="A",
        )
        # The preview's evaluation is deliberately *not* carried over. Its run input hash names the
        # preview revision, so copying it into the commit would produce an artifact that claims to
        # be about a revision it was not computed for. The design content is identical, so
        # re-evaluating the commit reproduces the same numbers under the correct identity, and the
        # change summary below records which preview this was promoted from.

        # Nodes and edges are revision-scoped, so the graph can only be built once the committed
        # id is known. The content is the reviewed preview's, re-projected under the new id.
        revision_id, _ = builder.identity()
        report = assess(
            mission=mission, parts=state.parts, total_mass_kg=_total_mass(state.parts)
        )
        graph = build_graph(
            parts=state.parts.model_copy(update={"revision_id": revision_id}),
            features=state.features.model_copy(update={"revision_id": revision_id}),
            mission=mission,
            catalog=self.catalog,
            evaluation=state.evaluation,
            regulatory_findings=report.findings,
        )
        builder.add_json(
            role="graph",
            relative_path="graph.json",
            payload=graph,
            produced_by="B",
            derived=True,
        )
        builder.note(
            f"committed {proposal.proposal_id}: {proposal.title}",
            f"promoted from preview {preview_revision_id}",
            *(preview_manifest.change_summary),
        )
        builder.affects(*proposal.operation.owned_part_ids)
        return builder.seal(self.repository)

    def undo(self, design_id: str, to_revision_id: str | None = None) -> str:
        return self.transactions.undo(design_id, to_revision_id=to_revision_id)

    # -- simulation ---------------------------------------------------------------------------------

    def simulate(self, revision_id: str, *, wait: bool = True) -> tuple[JobRecord, SimulationRun | None]:
        """Create an exact-revision run. Never mutates the design."""
        state = self.revisions.load(revision_id)
        mission = self.repository.design_mission(state.design_id)
        evaluation = self.require_evaluation(revision_id)
        revision = self.repository.get_revision(revision_id)

        cache_key = JobQueue.cache_key(
            kind="simulate",
            revision_content_hash=revision.content_hash,
            mission_hash=mission.mission_hash(),
            solver_version=f"{self.simulator.owner}/reduced-order",
        )
        holder: dict[str, SimulationRun] = {}

        def work(work_dir: str, cancel: threading.Event) -> list[str]:
            run = self.simulator.simulate(
                revision_id=revision_id,
                evaluation=evaluation,
                mission=mission,
                run_id=f"run_{revision_id[4:]}",
            )
            holder["run"] = run
            artifact = self.store.write_json(
                design_id=state.design_id,
                revision_id=revision_id,
                relative_path="simulation_run.json",
                payload=run,
                produced_by="C",
                role="simulation_run",
            )
            self._attach_artifact(revision_id, artifact)
            return [artifact.artifact_id]

        job = self.jobs.submit(
            kind="simulate",
            design_id=state.design_id,
            revision_id=revision_id,
            cache_key=cache_key,
            work=work,
        )
        if wait:
            job = self.jobs.wait(job.job_id)
            if job.status == "failed":
                raise DroneBenchError.of(
                    job.error_code or "INTERNAL",  # type: ignore[arg-type]
                    job.error_message or "simulation failed",
                    revision_id=revision_id,
                )
        if "run" in holder:
            return job, holder["run"]
        payload = self._read_artifact_json(revision_id, "simulation_run")
        return job, SimulationRun.model_validate(payload) if payload else None

    def compare(self, baseline_revision_id: str, candidate_revision_id: str, metric: str) -> ComparisonPair:
        """Baseline against candidate at identical conditions, or refuse."""
        return ComparisonPair(
            baseline=self.require_evaluation(baseline_revision_id),
            candidate=self.require_evaluation(candidate_revision_id),
            metric=metric,
        )

    # -- export --------------------------------------------------------------------------------------

    def export(self, revision_id: str) -> dict[str, Any]:
        """Export the editable assembly. Refuses without a successful round trip."""
        state = self.revisions.load(revision_id)
        work_dir = str(self.store.job_dir(f"export-{revision_id}"))
        result = self.cad.export_step(
            revision_id=revision_id, parts=state.parts, work_dir=work_dir
        )
        if not result.downloadable:
            raise DroneBenchError.of(
                "SOLVER_UNAVAILABLE" if not result.ok else "ARTIFACT_MISMATCH",
                "export is not available: "
                + "; ".join(result.diagnostics or ["the round trip did not pass"]),
                revision_id=revision_id,
                round_trip_performed=result.round_trip.performed,
                round_trip_passed=result.round_trip.passed,
                produced_by=result.produced_by,
            )
        artifact = self.store.write_json(
            design_id=state.design_id,
            revision_id=revision_id,
            relative_path="cad_edit_result.json",
            payload=result,
            produced_by="A",
            role="export_result",
        )
        self._attach_artifact(revision_id, artifact)
        self.repository.append_event(
            design_id=state.design_id,
            kind="export_completed",
            tool_name="service.export",
            revision_id=revision_id,
            artifact_ids=[artifact.artifact_id],
        )
        return result.model_dump(mode="json")

    # -- events and artifacts ---------------------------------------------------------------------------

    def events(self, design_id: str, after_sequence: int = 0, limit: int = 500) -> list[AuditEvent]:
        return self.repository.events_since(design_id, after_sequence, limit)

    def artifact_bytes(self, artifact_id: str) -> tuple[bytes, str, str]:
        """Server-resolved download. Returns ``(bytes, media_type, filename)``."""
        design_id, revision_id, artifact = self.repository.find_artifact(artifact_id)
        self.store.verify(design_id=design_id, revision_id=revision_id, artifact=artifact)
        data = self.store.read(
            design_id=design_id, revision_id=revision_id, relative_path=artifact.relative_path
        )
        name = Path(artifact.relative_path).name
        return data, artifact.media_type, f"{revision_id}_{name}"

    def job(self, job_id: str) -> JobRecord:
        return self.repository.get_job(job_id)

    def cancel_job(self, job_id: str) -> bool:
        return self.jobs.cancel(job_id)

    # -- doctor --------------------------------------------------------------------------------------

    def doctor(self) -> dict[str, Any]:
        """What is actually installed, so the demo never claims a capability it lacks."""
        designs = self.repository.list_designs()
        return {
            "contract_version": CONTRACT_VERSION,
            "storage_root": str(self.root),
            "database": str(self.root / "dronebench.sqlite"),
            "designs": len(designs),
            "ports": {
                "cad": {"owner": self.cad.owner, "real_kernel": self.cad.owner == "A"},
                "evaluate": {
                    "owner": self.evaluator.owner,
                    "available_tiers": self.evaluator.available_tiers(),
                },
                "simulate": {"owner": self.simulator.owner},
            },
            "provider": self.pipeline.provider.name,
            "catalog": {
                "snapshot_id": self.catalog.snapshot_id,
                "items": len(self.catalog.items),
                "all_synthetic": self.catalog.all_synthetic,
            },
            "capabilities_absent": [
                note
                for note, present in (
                    ("STEP export (needs Team A's CAD kernel)", self.cad.owner == "A"),
                    (
                        "VSPAERO analysis (needs Team C's solver worker)",
                        "vspaero_informed" in self.evaluator.available_tiers(),
                    ),
                    ("language-model proposals", self.pipeline.provider.name != "none"),
                )
                if not present
            ],
        }

    # -- internals -----------------------------------------------------------------------------------

    def _commit_state(
        self,
        *,
        design_id: str,
        parent_revision_id: str | None,
        manifest: DesignManifest,
        parts: PartsDocument,
        features: GeometryFeatures,
        mission: Mission,
        cause: str,
        label: str,
        notes: list[str],
        affected: list[str],
    ) -> RevisionManifest:
        """Seal a committed revision with a complete artifact set, then activate it."""
        # The builder derives the revision id from these documents and stamps them with it, so
        # nothing here has to guess the id in advance. The graph is built once the id is known,
        # because every node and edge is revision-scoped.
        builder = self.revisions.builder(
            design_id=design_id,
            parent_revision_id=parent_revision_id,
            stage="committed",
            cause=cause,  # type: ignore[arg-type]
            mission=mission,
            label=label,
        )
        builder.add_json(
            role="design_manifest",
            relative_path="design_manifest.json",
            payload=manifest,
            produced_by="A",
        )
        builder.add_json(
            role="parts", relative_path="parts.json", payload=parts, produced_by="A"
        )
        builder.add_json(
            role="geometry_features",
            relative_path="geometry_features.json",
            payload=features,
            produced_by="A",
        )

        revision_id, _ = builder.identity()
        report = assess(mission=mission, parts=parts, total_mass_kg=_total_mass(parts))
        graph = build_graph(
            parts=parts.model_copy(update={"revision_id": revision_id}),
            features=features.model_copy(update={"revision_id": revision_id}),
            mission=mission,
            catalog=self.catalog,
            evaluation=None,
            regulatory_findings=report.findings,
        )
        builder.add_json(
            role="graph",
            relative_path="graph.json",
            payload=graph,
            produced_by="B",
            derived=True,
        )
        builder.note(*notes)
        builder.affects(*affected)
        sealed = builder.seal(self.repository)
        self.transactions.activate(design_id, sealed.revision.revision_id)
        self.repository.append_event(
            design_id=design_id,
            kind="revision_created",
            tool_name=f"service.{cause}",
            revision_id=sealed.revision.revision_id,
            artifact_ids=[a.artifact_id for a in sealed.artifacts],
            inputs_summary={"cause": cause, "label": label},
        )
        return sealed

    def _attach_artifact(self, revision_id: str, artifact) -> None:
        """Add a late artifact (evaluation, run) to an existing revision's manifest.

        This does not change the revision's content hash: the hash covers the design documents that
        define the revision, and an evaluation is a result *about* that revision, not part of it.
        Re-evaluating the same revision therefore cannot fork its identity.
        """
        manifest = self.repository.get_manifest(revision_id)
        artifacts = [a for a in manifest.artifacts if a.relative_path != artifact.relative_path]
        updated = manifest.model_copy(update={"artifacts": [*artifacts, artifact]})
        with self._lock:
            self.repository.connection.execute(
                "UPDATE revisions SET manifest_json = ? WHERE revision_id = ?",
                (canonical_json(updated.model_dump(mode="json")), revision_id),
            )
            self.repository.connection.execute(
                "INSERT OR REPLACE INTO artifacts (artifact_id, revision_id, relative_path, "
                "sha256, size_bytes, media_type, representation, produced_by, role, part_ids_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    artifact.artifact_id,
                    revision_id,
                    artifact.relative_path,
                    artifact.sha256,
                    artifact.size_bytes,
                    artifact.media_type,
                    artifact.representation,
                    artifact.produced_by,
                    artifact.role,
                    json.dumps(artifact.part_ids),
                ),
            )

    def _read_artifact_json(self, revision_id: str, role: str) -> dict | None:
        manifest = self.repository.get_manifest(revision_id)
        artifact = manifest.artifact(role)
        if artifact is None:
            return None
        return json.loads(
            self.store.read(
                design_id=manifest.revision.design_id,
                revision_id=revision_id,
                relative_path=artifact.relative_path,
            )
        )


# ---------------------------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------------------------


def build_workbench(root: str | Path, *, catalog_path: Path | None = None) -> Workbench:
    """Assemble a workbench with the reference ports.

    The single place Team A's and Team C's real packages replace the stubs.
    """
    catalog = CatalogSnapshot.model_validate(
        _read(catalog_path or (FIXTURE_DIR / "common" / "catalog.json"))
    )
    return Workbench(
        root=Path(root),
        cad=ParametricCadPort(catalog=catalog),
        evaluate=AnalyticEvaluator(),
        simulate=ReducedOrderSimulator(),
        catalog=catalog,
    )


def _read(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _total_mass(parts: PartsDocument) -> float | None:
    total = 0.0
    for occurrence in parts.occurrences:
        mass = occurrence.mass_kg.number()
        if mass is None:
            return None
        total += mass
    return total


def _apply_claim_entries(parts: PartsDocument, entries: Iterable[ClaimEntry]) -> PartsDocument:
    """Apply user-supplied values, each with its own provenance.

    A user-entered value is ``manual`` or ``bom`` evidence, never ``inferred``. The entry must cite
    an evidence id that exists in the document, so a number cannot arrive without a source.
    """
    entries = list(entries)
    if not entries:
        return parts

    known_evidence = {e.evidence_id for e in parts.evidence}
    occurrences = [o.model_copy(deep=True) for o in parts.occurrences]
    index = {o.part_id: i for i, o in enumerate(occurrences)}

    for entry in entries:
        if entry.part_id not in index:
            raise DroneBenchError.of(
                "INVALID_REQUEST",
                f"{entry.part_id} is not an occurrence in revision {parts.revision_id}",
                revision_id=parts.revision_id,
            )
        if entry.source_kind not in ("bom", "manual", "catalog", "cad"):
            raise DroneBenchError.of(
                "MISSING_EVIDENCE",
                f"a user-entered value needs a measured source kind, not {entry.source_kind!r}",
                revision_id=parts.revision_id,
            )
        if entry.evidence_id not in known_evidence:
            raise DroneBenchError.of(
                "MISSING_EVIDENCE",
                f"evidence {entry.evidence_id} is not recorded in this revision",
                revision_id=parts.revision_id,
            )

        occurrence = occurrences[index[entry.part_id]]
        claim = Claim.measured(
            entry.value,
            entry.unit,  # type: ignore[arg-type]
            source_kind=entry.source_kind,  # type: ignore[arg-type]
            evidence_ids=[entry.evidence_id],
        )
        if entry.quantity == "mass_kg":
            occurrences[index[entry.part_id]] = occurrence.model_copy(update={"mass_kg": claim})
        else:
            updated = dict(occurrence.claims.claims)
            updated[entry.quantity] = claim
            occurrences[index[entry.part_id]] = occurrence.model_copy(
                update={"claims": occurrence.claims.model_copy(update={"claims": updated})}
            )

    return parts.model_copy(update={"occurrences": occurrences})
