"""DroneBench shared wire vocabulary.

Owned by Team B; reviewed by A and C (architecture section 11). Internal Python functions use these
models directly, and the TypeScript types the web app consumes are generated from the JSON Schema
this package emits - no hand-written lookalikes.

Breaking a contract requires a decision note in ``docs/decisions/``, updated examples, and consumer
validation in the same merge.
"""

from __future__ import annotations

CONTRACT_VERSION = "1.0"

from .catalog import (
    CatalogCategory,
    CatalogItem,
    CatalogOffer,
    CatalogSnapshot,
    DeclaredInterface,
    InterfaceKind,
)
from .claims import (
    Claim,
    ClaimSet,
    ClaimStatus,
    ConflictSet,
    Evidence,
    MEASURED_SOURCE_KINDS,
    MissingClaimValue,
    SourceKind,
)
from .edits import (
    CadEditResult,
    EditOperation,
    InterferenceFinding,
    OperationName,
    PartSignature,
    ReplaceCatalogComponent,
    ResizeSpar,
    RoundTripCheck,
    SetWingTipExtension,
    TranslateComponent,
)
from .errors import (
    DroneBenchError,
    EXIT_INFEASIBLE,
    EXIT_INVALID_INPUT,
    EXIT_OK,
    EXIT_TOOL_FAILURE,
    ErrorCode,
    ErrorEnvelope,
    HTTP_STATUS,
    stale_revision,
)
from .evaluate import (
    CheckResult,
    ComparisonPair,
    Evaluation,
    FidelityTier,
    SensitivityInterval,
    SolverManifest,
    TIER_CLAIM_TEXT,
)
from .events import (
    AuditEvent,
    EventKind,
    JobKind,
    JobRecord,
    JobStatus,
    SimulationRun,
    TelemetrySample,
    summarize_inputs,
)
from .graph import (
    EvidenceGraph,
    ExplanationPath,
    GraphEdge,
    GraphNode,
    Neighborhood,
    NodeType,
    PathStep,
    POWER_RELATIONS,
    RelationType,
    SIGNAL_RELATIONS,
)
from .identity import (
    IdentityError,
    NonFiniteNumberError,
    assert_finite,
    canonical_bytes,
    canonical_json,
    content_hash,
    sha256_file,
    sha256_hex,
    strip_display_only,
)
from .mission import (
    CheckClass,
    CheckRegistry,
    CheckStatus,
    FIXED_WING_CRUISE_V1,
    Mission,
    Objective,
    REGISTRIES,
    RegulatoryProfile,
    RequiredCheck,
)
from .parts import (
    AxisAlignedBox,
    DesignManifest,
    EditCapability,
    GeometryFeatures,
    PartDefinition,
    PartOccurrence,
    PartRole,
    PartsDocument,
    Representation,
    SourceRef,
    Transform,
    TravelCorridor,
    VTailPanel,
    WingStation,
)
from .ports import CadPort, EvaluatePort, ProviderPort, SimulatePort
from .recommend import (
    ALLOWED_TRANSITIONS,
    CandidateOrigin,
    DecisionOutcome,
    DecisionRequest,
    EvidenceRequest,
    IllegalTransition,
    MAX_CANDIDATES,
    MAX_DISPLAYED,
    MAX_PROVIDER_CALLS,
    MAX_QUEUED_NATIVE_ANALYSES,
    PreviewResult,
    ProposalContext,
    ProposalState,
    Recommendation,
    RecommendationSet,
    TERMINAL_STATES,
    Tradeoff,
    assert_transition,
)
from .revision import (
    Artifact,
    CreationCause,
    MediaType,
    REQUIRED_COMMITTED_ROLES,
    Revision,
    RevisionManifest,
    RevisionStage,
    compute_revision_id,
)
from .units import (
    G0,
    M_TO_MM,
    MM_TO_M,
    RHO_ISA_SL,
    Unit,
    deg,
    frd_to_threejs,
    rad,
    station_from_x,
    threejs_to_frd,
    x_from_station,
)

__all__ = [
    "CONTRACT_VERSION",
    # units
    "G0", "M_TO_MM", "MM_TO_M", "RHO_ISA_SL", "Unit", "deg", "rad",
    "frd_to_threejs", "threejs_to_frd", "station_from_x", "x_from_station",
    # identity
    "IdentityError", "NonFiniteNumberError", "assert_finite", "canonical_bytes",
    "canonical_json", "content_hash", "sha256_file", "sha256_hex", "strip_display_only",
    # claims
    "Claim", "ClaimSet", "ClaimStatus", "ConflictSet", "Evidence", "MissingClaimValue",
    "SourceKind", "MEASURED_SOURCE_KINDS",
    # parts
    "AxisAlignedBox", "DesignManifest", "EditCapability", "GeometryFeatures", "PartDefinition",
    "PartOccurrence", "PartRole", "PartsDocument", "Representation", "SourceRef", "Transform",
    "TravelCorridor", "VTailPanel", "WingStation",
    # revision
    "Artifact", "CreationCause", "MediaType", "Revision", "RevisionManifest", "RevisionStage",
    "REQUIRED_COMMITTED_ROLES", "compute_revision_id",
    # mission
    "CheckClass", "CheckRegistry", "CheckStatus", "FIXED_WING_CRUISE_V1", "Mission", "Objective",
    "REGISTRIES", "RegulatoryProfile", "RequiredCheck",
    # evaluate
    "CheckResult", "ComparisonPair", "Evaluation", "FidelityTier", "SensitivityInterval",
    "SolverManifest", "TIER_CLAIM_TEXT",
    # graph
    "EvidenceGraph", "ExplanationPath", "GraphEdge", "GraphNode", "Neighborhood", "NodeType",
    "PathStep", "RelationType", "POWER_RELATIONS", "SIGNAL_RELATIONS",
    # catalog
    "CatalogCategory", "CatalogItem", "CatalogOffer", "CatalogSnapshot", "DeclaredInterface",
    "InterfaceKind",
    # edits
    "CadEditResult", "EditOperation", "InterferenceFinding", "OperationName", "PartSignature",
    "ReplaceCatalogComponent", "ResizeSpar", "RoundTripCheck", "SetWingTipExtension",
    "TranslateComponent",
    # recommend
    "ALLOWED_TRANSITIONS", "CandidateOrigin", "DecisionOutcome", "DecisionRequest",
    "EvidenceRequest", "IllegalTransition", "MAX_CANDIDATES", "MAX_DISPLAYED", "MAX_PROVIDER_CALLS",
    "MAX_QUEUED_NATIVE_ANALYSES", "PreviewResult", "ProposalContext", "ProposalState",
    "Recommendation", "RecommendationSet", "TERMINAL_STATES", "Tradeoff", "assert_transition",
    # events and jobs
    "AuditEvent", "EventKind", "JobKind", "JobRecord", "JobStatus", "SimulationRun",
    "TelemetrySample", "summarize_inputs",
    # errors
    "DroneBenchError", "ErrorCode", "ErrorEnvelope", "HTTP_STATUS", "stale_revision",
    "EXIT_OK", "EXIT_INVALID_INPUT", "EXIT_TOOL_FAILURE", "EXIT_INFEASIBLE",
    # ports
    "CadPort", "EvaluatePort", "ProviderPort", "SimulatePort",
]
