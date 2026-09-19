"""Generate the JSON Schema bundle the TypeScript types are derived from.

Run as ``python -m dronebench_contracts.schema [outdir]``. Architecture section 11: TypeScript
types are generated from JSON Schema / OpenAPI; nobody maintains hand-written lookalikes.

The bundle is committed so a schema drift shows up as a diff in review rather than as a runtime
surprise in another team's branch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from .catalog import CatalogItem, CatalogSnapshot, DeclaredInterface
from .claims import Claim, ClaimSet, ConflictSet, Evidence
from .edits import CadEditResult, EditOperation, PartSignature, RoundTripCheck
from .errors import ErrorEnvelope
from .evaluate import CheckResult, ComparisonPair, Evaluation, SensitivityInterval, SolverManifest
from .events import AuditEvent, JobRecord, SimulationRun, TelemetrySample
from .graph import EvidenceGraph, ExplanationPath, GraphEdge, GraphNode, Neighborhood
from .identity import canonical_json
from .mission import CheckRegistry, Mission, RegulatoryProfile
from .parts import (
    DesignManifest,
    GeometryFeatures,
    PartDefinition,
    PartOccurrence,
    PartsDocument,
    Transform,
)
from .recommend import (
    DecisionOutcome,
    DecisionRequest,
    EvidenceRequest,
    PreviewResult,
    ProposalContext,
    Recommendation,
    RecommendationSet,
)
from .revision import Artifact, Revision, RevisionManifest

#: Everything the web app or another team may need a type for.
EXPORTED_MODELS: tuple[type[BaseModel], ...] = (
    # evidence
    Claim, ClaimSet, ConflictSet, Evidence,
    # parts and geometry
    Transform, PartDefinition, PartOccurrence, PartsDocument, DesignManifest, GeometryFeatures,
    # revisions
    Artifact, Revision, RevisionManifest,
    # mission
    RegulatoryProfile, CheckRegistry, Mission,
    # evaluation
    SolverManifest, CheckResult, SensitivityInterval, Evaluation, ComparisonPair,
    # graph
    GraphNode, GraphEdge, EvidenceGraph, ExplanationPath, Neighborhood,
    # catalog
    DeclaredInterface, CatalogItem, CatalogSnapshot,
    # edits
    PartSignature, RoundTripCheck, CadEditResult,
    # recommendations
    PreviewResult, Recommendation, RecommendationSet, ProposalContext, EvidenceRequest,
    DecisionRequest, DecisionOutcome,
    # events and jobs
    AuditEvent, JobRecord, TelemetrySample, SimulationRun,
    # errors
    ErrorEnvelope,
)

#: Discriminated unions are exported separately; they are not ``BaseModel`` subclasses.
EXPORTED_UNIONS: dict[str, Any] = {
    "EditOperation": EditOperation,
}

BUNDLE_FILENAME = "dronebench.schema.json"


def build_bundle() -> dict[str, Any]:
    """One document with every model under ``$defs`` and a stable ``$id``."""
    defs: dict[str, Any] = {}

    for model in EXPORTED_MODELS:
        # Serialization mode, not validation mode. The consumers of this bundle read what the API
        # *emits*, and model_dump always emits every field - so a field with a default is present
        # in the payload rather than optional. It also includes computed fields such as
        # Evaluation.verified_feasible, which validation mode would omit and which the UI must not
        # re-derive for itself.
        schema = model.model_json_schema(
            ref_template="#/$defs/{model}", mode="serialization"
        )
        nested = schema.pop("$defs", {})
        defs.update(nested)
        defs[model.__name__] = schema

    for name, union in EXPORTED_UNIONS.items():
        adapter = TypeAdapter(union)
        schema = adapter.json_schema(ref_template="#/$defs/{model}", mode="serialization")
        nested = schema.pop("$defs", {})
        defs.update(nested)
        defs[name] = schema

    from . import CONTRACT_VERSION

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://dronebench.local/schema/{CONTRACT_VERSION}/{BUNDLE_FILENAME}",
        "title": "DroneBench contracts",
        "description": (
            "Generated from packages/contracts. Do not hand-edit; run "
            "python -m dronebench_contracts.schema instead."
        ),
        "x-contract-version": CONTRACT_VERSION,
        "$defs": dict(sorted(defs.items())),
    }


def write_bundle(outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    bundle = build_bundle()
    target = outdir / BUNDLE_FILENAME
    target.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def bundle_hash() -> str:
    """Stable hash of the schema bundle, for the contract-freeze test."""
    from .identity import sha256_hex

    return sha256_hex(canonical_json(build_bundle()).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    outdir = Path(args[0]) if args else Path("schema")
    target = write_bundle(outdir)
    bundle = json.loads(target.read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "written": str(target),
                "definitions": len(bundle["$defs"]),
                "bundle_sha256": bundle_hash(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
