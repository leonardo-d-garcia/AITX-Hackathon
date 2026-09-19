"""Candidate generation, validation, preview, and ranking (Team B, architecture section 7)."""

from .candidates import Candidate, generate
from .pipeline import PreviewBuilt, RecommendationPipeline
from .provider import (
    ALLOWED_OPERATIONS,
    ExplanationOnlyProvider,
    NullProvider,
    Provider,
    ProviderBudget,
    build_context,
    default_provider,
)
from .ranking import RankedCandidate, rank, tradeoffs
from .regulatory import (
    Applicability,
    RECREATIONAL_MASS_THRESHOLD_KG,
    RegulatoryFinding,
    RegulatoryReport,
    assess,
)
from .validate import ValidationOutcome, validate_operation

__all__ = [
    "Candidate", "generate",
    "RecommendationPipeline", "PreviewBuilt",
    "Provider", "NullProvider", "ExplanationOnlyProvider", "ProviderBudget",
    "default_provider", "build_context", "ALLOWED_OPERATIONS",
    "rank", "tradeoffs", "RankedCandidate",
    "assess", "RegulatoryFinding", "RegulatoryReport", "Applicability",
    "RECREATIONAL_MASS_THRESHOLD_KG",
    "validate_operation", "ValidationOutcome",
]
