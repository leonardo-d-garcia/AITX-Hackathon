"""Typed evidence-graph vocabulary (architecture section 7, Graph semantics).

Three distinctions the type system carries rather than leaving to convention:

* ``near`` is not ``mates_with``. Geometric proximity is stored as inferred; neither relation
  proves load transfer.
* ``compatible_with`` is computed from declared interfaces. It may never be authored from visual
  proximity, so the relation carries a mandatory basis field.
* Signal and power are distinct networks. ``powers`` and ``controls`` are separate relations and a
  traversal that wants one must not pick up the other.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .claims import Claim, ClaimStatus, Evidence

NodeType = Literal[
    "PartOccurrence",
    "PartDefinition",
    "Material",
    "Function",
    "Interface",
    "CatalogItem",
    "Supplier",
    "Constraint",
    "Regulation",
    "Mission",
    "Evidence",
    "AnalysisRun",
]

RelationType = Literal[
    "instance_of",      # PartOccurrence -> PartDefinition
    "made_of",          # PartDefinition/PartOccurrence -> Material
    "performs",         # PartOccurrence -> Function
    "exposes",          # PartOccurrence/CatalogItem -> Interface
    "mates_with",       # confirmed mechanical joint; needs BOM/manual confirmation
    "near",             # inferred geometric proximity; proves nothing
    "powers",           # power network edge
    "controls",         # signal network edge
    "compatible_with",  # computed from declared interfaces only
    "offered_by",       # CatalogItem -> Supplier
    "constrained_by",   # anything -> Constraint
    "applies_to",       # Regulation -> PartOccurrence / Mission
    "supported_by",     # anything -> Evidence
    "evaluated_in",     # anything -> AnalysisRun
]

#: Relations that describe the power network, kept apart from the signal network.
POWER_RELATIONS: frozenset[str] = frozenset({"powers"})
#: Relations that describe the signal network.
SIGNAL_RELATIONS: frozenset[str] = frozenset({"controls"})
#: Relations that carry no functional implication whatsoever.
INFERRED_ONLY_RELATIONS: frozenset[str] = frozenset({"near"})

CompatibilityBasis = Literal[
    "declared_interfaces",  # the only basis that may assert compatible_with
    "not_computed",
]


class GraphNode(BaseModel):
    """A typed node, scoped to one revision."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    node_type: NodeType
    label: str
    revision_id: str
    properties: dict[str, Any] = Field(default_factory=dict)
    claims: dict[str, Claim] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimStatus = "known"


class GraphEdge(BaseModel):
    """A typed relation carrying its own evidence, status, and revision scope."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    source_id: str
    target_id: str
    relation: RelationType
    revision_id: str
    status: ClaimStatus = "known"
    evidence_ids: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    basis: CompatibilityBasis | None = Field(
        default=None,
        description="Required for compatible_with. Anything other than declared_interfaces is a bug.",
    )

    @model_validator(mode="after")
    def _relation_rules(self) -> Self:
        if self.relation == "compatible_with":
            if self.basis != "declared_interfaces":
                raise ValueError(
                    "compatible_with must be computed from declared interfaces, never from "
                    "graph proximity"
                )
        if self.relation == "near" and self.status not in ("unknown", "estimated"):
            raise ValueError("near is an inferred relation; it cannot be asserted as known")
        if self.relation == "mates_with" and self.status == "known" and not self.evidence_ids:
            raise ValueError(
                "a known mates_with edge needs BOM or manual confirmation evidence; downgrade to "
                "near if only proximity is available"
            )
        if self.source_id == self.target_id:
            raise ValueError(f"self-loop on {self.source_id} via {self.relation}")
        return self


class EvidenceGraph(BaseModel):
    """``graph.json`` - B -> UI/recommender."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    revision_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    evidence: list[Evidence] = Field(default_factory=list)
    unknown_relationships: list[str] = Field(
        default_factory=list,
        description=(
            "Relationships the source material does not determine, stated openly rather than "
            "guessed. These drive the 'what evidence is missing' answers in the UI."
        ),
    )

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("duplicate node_id")
        edge_ids = {edge.edge_id for edge in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("duplicate edge_id")
        for edge in self.edges:
            if edge.source_id not in node_ids:
                raise ValueError(f"edge {edge.edge_id} source {edge.source_id} is not a node")
            if edge.target_id not in node_ids:
                raise ValueError(f"edge {edge.edge_id} target {edge.target_id} is not a node")
            if edge.revision_id != self.revision_id:
                raise ValueError(f"edge {edge.edge_id} is scoped to another revision")
        for node in self.nodes:
            if node.revision_id != self.revision_id:
                raise ValueError(f"node {node.node_id} is scoped to another revision")
        return self

    def node(self, node_id: str) -> GraphNode:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        raise KeyError(node_id)

    def nodes_of(self, node_type: NodeType) -> list[GraphNode]:
        return [node for node in self.nodes if node.node_type == node_type]


class PathStep(BaseModel):
    """One hop of an explanation path."""

    model_config = ConfigDict(extra="forbid")

    from_id: str
    from_label: str
    relation: RelationType
    to_id: str
    to_label: str
    status: ClaimStatus
    evidence_ids: list[str] = Field(default_factory=list)


class ExplanationPath(BaseModel):
    """A short typed path answering one of the section 7 narrow queries."""

    model_config = ConfigDict(extra="forbid")

    question: str
    steps: list[PathStep]
    conclusion: str
    weakest_status: ClaimStatus = Field(
        description="The least certain link on the path. An inferred hop caps the whole claim."
    )
    missing_evidence: list[str] = Field(default_factory=list)


class Neighborhood(BaseModel):
    """A bounded subgraph. The whole graph is never sent to a model or rendered at once."""

    model_config = ConfigDict(extra="forbid")

    revision_id: str
    center_id: str
    radius: int = Field(ge=1, le=4)
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = Field(
        default=False, description="True when the node budget cut the traversal short."
    )
    node_budget: int = Field(default=0, ge=0)
