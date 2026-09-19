"""Bounded typed traversals over the evidence graph (architecture section 7).

"Useful queries are narrow" and "do not send the entire graph to the model." Every function here
returns either a bounded :class:`Neighborhood` or a short :class:`ExplanationPath`. There is
deliberately no "give me the graph" helper for the recommender to reach for.

NetworkX is rebuilt on demand from the revision-scoped JSON rather than kept as a long-lived
mutable object, which is what keeps a stale projection from outliving the revision it described.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable

import networkx as nx

from dronebench_contracts import (
    ClaimStatus,
    EvidenceGraph,
    ExplanationPath,
    GraphEdge,
    GraphNode,
    Neighborhood,
    PathStep,
    RelationType,
)

from .build import constraint_node_id, part_node_id

#: How many nodes a neighborhood may contain before it is truncated.
DEFAULT_NODE_BUDGET = 60

#: Ordering used when a path's overall certainty is summarised. Least certain wins.
_STATUS_ORDER: dict[str, int] = {"known": 0, "estimated": 1, "conflicted": 2, "unknown": 3}


def to_networkx(graph: EvidenceGraph) -> nx.MultiDiGraph:
    """Project to a ``MultiDiGraph``. Parallel typed relations between the same pair are normal."""
    projection = nx.MultiDiGraph()
    for node in graph.nodes:
        projection.add_node(node.node_id, model=node)
    for edge in graph.edges:
        projection.add_edge(edge.source_id, edge.target_id, key=edge.edge_id, model=edge)
    return projection


def weakest(statuses: Iterable[str]) -> ClaimStatus:
    ordered = sorted(statuses, key=lambda s: _STATUS_ORDER.get(s, 3))
    return ordered[-1] if ordered else "known"  # type: ignore[return-value]


# ---------------------------------------------------------------------------------------------
# Bounded neighborhood
# ---------------------------------------------------------------------------------------------


def neighborhood(
    graph: EvidenceGraph,
    center_id: str,
    *,
    radius: int = 2,
    node_budget: int = DEFAULT_NODE_BUDGET,
    relations: Iterable[RelationType] | None = None,
) -> Neighborhood:
    """Breadth-first subgraph around one node, capped at ``node_budget``.

    Traversal is undirected: "what does this touch" is a question about the relation existing, not
    about which way the arrow was authored.
    """
    allowed = set(relations) if relations else None
    adjacency: dict[str, list[GraphEdge]] = {}
    for edge in graph.edges:
        if allowed is not None and edge.relation not in allowed:
            continue
        adjacency.setdefault(edge.source_id, []).append(edge)
        adjacency.setdefault(edge.target_id, []).append(edge)

    if center_id not in {node.node_id for node in graph.nodes}:
        raise KeyError(center_id)

    seen: dict[str, int] = {center_id: 0}
    kept_edges: dict[str, GraphEdge] = {}
    queue: deque[str] = deque([center_id])
    truncated = False

    while queue:
        current = queue.popleft()
        depth = seen[current]
        if depth >= radius:
            continue
        for edge in adjacency.get(current, []):
            other = edge.target_id if edge.source_id == current else edge.source_id
            if other not in seen:
                if len(seen) >= node_budget:
                    truncated = True
                    continue
                seen[other] = depth + 1
                queue.append(other)
            if other in seen:
                kept_edges[edge.edge_id] = edge

    node_index = {node.node_id: node for node in graph.nodes}
    return Neighborhood(
        revision_id=graph.revision_id,
        center_id=center_id,
        radius=radius,
        nodes=[node_index[node_id] for node_id in seen],
        edges=list(kept_edges.values()),
        truncated=truncated,
        node_budget=node_budget,
    )


def _shortest_typed_path(
    graph: EvidenceGraph,
    source_id: str,
    target_id: str,
    *,
    relations: Iterable[RelationType] | None = None,
    max_hops: int = 4,
) -> list[GraphEdge] | None:
    """Fewest-hop undirected path, restricted to the given relations."""
    allowed = set(relations) if relations else None
    adjacency: dict[str, list[GraphEdge]] = {}
    for edge in graph.edges:
        if allowed is not None and edge.relation not in allowed:
            continue
        adjacency.setdefault(edge.source_id, []).append(edge)
        adjacency.setdefault(edge.target_id, []).append(edge)

    queue: deque[tuple[str, list[GraphEdge]]] = deque([(source_id, [])])
    visited = {source_id}
    while queue:
        current, trail = queue.popleft()
        if current == target_id:
            return trail
        if len(trail) >= max_hops:
            continue
        for edge in adjacency.get(current, []):
            other = edge.target_id if edge.source_id == current else edge.source_id
            if other in visited:
                continue
            visited.add(other)
            queue.append((other, [*trail, edge]))
    return None


def _steps(graph: EvidenceGraph, edges: list[GraphEdge], start_id: str) -> list[PathStep]:
    index = {node.node_id: node for node in graph.nodes}
    steps: list[PathStep] = []
    cursor = start_id
    for edge in edges:
        forward = edge.source_id == cursor
        from_id = cursor
        to_id = edge.target_id if forward else edge.source_id
        steps.append(
            PathStep(
                from_id=from_id,
                from_label=index[from_id].label,
                relation=edge.relation,
                to_id=to_id,
                to_label=index[to_id].label,
                status=edge.status,
                evidence_ids=edge.evidence_ids,
            )
        )
        cursor = to_id
    return steps


# ---------------------------------------------------------------------------------------------
# The five narrow questions of section 7
# ---------------------------------------------------------------------------------------------


def mass_evidence(graph: EvidenceGraph, part_id: str) -> ExplanationPath:
    """"What evidence supports this part's mass?\""""
    node_id = part_node_id(part_id)
    node = graph.node(node_id)
    claim = node.claims.get("mass_kg")

    steps = [
        step
        for step in _steps(
            graph,
            [
                edge
                for edge in graph.edges
                if edge.source_id == node_id
                and edge.relation == "supported_by"
                and edge.properties.get("quantity") == "mass_kg"
            ],
            node_id,
        )
    ]

    if claim is None or not claim.is_known:
        return ExplanationPath(
            question=f"What evidence supports the mass of {node.label}?",
            steps=steps,
            conclusion=(
                f"{node.label} has no established mass. It is not zero and it is not ignored: "
                "every mass-dependent result downstream is reported unknown until a value with "
                "provenance is entered."
            ),
            weakest_status="unknown",
            missing_evidence=[f"{part_id}.mass_kg"],
        )

    sources = ", ".join(sorted({graph.node(s.to_id).properties.get("source_kind", "?") for s in steps})) or "none"
    return ExplanationPath(
        question=f"What evidence supports the mass of {node.label}?",
        steps=steps,
        conclusion=(
            f"{claim.value} kg, {claim.status}, from {claim.source_kind} evidence ({sources})."
            + (f" Assumptions: {'; '.join(claim.assumptions)}." if claim.assumptions else "")
        ),
        weakest_status=weakest([claim.status, *(s.status for s in steps)]),
        missing_evidence=[] if steps else [f"{part_id}.mass_kg has no evidence record"],
    )


def affected_constraints(graph: EvidenceGraph, part_id: str) -> list[str]:
    """Check ids this occurrence feeds, via ``constrained_by``."""
    node_id = part_node_id(part_id)
    return sorted(
        {
            graph.node(edge.target_id).label
            for edge in graph.edges
            if edge.source_id == node_id and edge.relation == "constrained_by"
        }
    )


def what_fails_if_moved(graph: EvidenceGraph, part_id: str) -> ExplanationPath:
    """"What fails if this battery moves?\""""
    node_id = part_node_id(part_id)
    node = graph.node(node_id)

    edges = [
        edge
        for edge in graph.edges
        if edge.source_id == node_id and edge.relation == "constrained_by"
    ]
    steps = _steps(graph, edges, node_id)
    at_risk = [
        graph.node(edge.target_id)
        for edge in edges
        if graph.node(edge.target_id).properties.get("check_class")
        in ("hard_invariant", "modeled_constraint")
    ]
    unknown = [n.label for n in at_risk if n.properties.get("status") == "unknown"]

    return ExplanationPath(
        question=f"What fails if {node.label} moves?",
        steps=steps,
        conclusion=(
            "Moving it re-opens: "
            + (", ".join(sorted(n.label for n in at_risk)) or "no modelled constraint")
            + ". Placement-dependent results are invalidated; the outer mold line is unchanged, so "
            "fixed-geometry aerodynamic coefficients may legitimately be reused."
        ),
        weakest_status=weakest([e.status for e in edges] or ["known"]),
        missing_evidence=unknown,
    )


def affected_by_edit(graph: EvidenceGraph, part_id: str, *, radius: int = 2) -> ExplanationPath:
    """"Which components are affected by a larger spar?\""""
    node_id = part_node_id(part_id)
    node = graph.node(node_id)
    local = neighborhood(
        graph,
        node_id,
        radius=radius,
        relations=["mates_with", "constrained_by", "instance_of", "made_of"],
    )
    touched = [
        n for n in local.nodes if n.node_type == "PartOccurrence" and n.node_id != node_id
    ]
    constraints = [n for n in local.nodes if n.node_type == "Constraint"]
    steps = _steps(
        graph,
        [e for e in local.edges if e.source_id == node_id or e.target_id == node_id],
        node_id,
    )
    return ExplanationPath(
        question=f"Which components are affected by a change to {node.label}?",
        steps=steps,
        conclusion=(
            "Directly coupled parts: "
            + (", ".join(sorted(n.label for n in touched)) or "none")
            + ". Constraints to recompute: "
            + (", ".join(sorted(n.label for n in constraints)) or "none")
            + "."
        ),
        weakest_status=weakest([e.status for e in local.edges] or ["known"]),
        missing_evidence=[
            n.label for n in constraints if n.properties.get("status") == "unknown"
        ],
    )


def why_rule_applies(graph: EvidenceGraph, rule_node_id: str) -> ExplanationPath:
    """"Why is this rule applicable?\""""
    node = graph.node(rule_node_id)
    edges = [
        edge
        for edge in graph.edges
        if edge.source_id == rule_node_id and edge.relation == "applies_to"
    ]
    steps = _steps(graph, edges, rule_node_id)
    applicability = node.properties.get("applicability", "unknown")
    missing = list(node.properties.get("missing_context", []) or [])
    return ExplanationPath(
        question=f"Why does {node.label} apply?",
        steps=steps,
        conclusion=(
            f"{applicability}: {node.properties.get('rationale', '')} "
            "This states applicability for the selected operation profile. It is not a compliance "
            "determination and does not certify the aircraft."
        ).strip(),
        weakest_status="unknown" if applicability == "unknown" else "known",
        missing_evidence=missing,
    )


def evidence_path_to_constraint(
    graph: EvidenceGraph, part_id: str, check_id: str
) -> ExplanationPath | None:
    """The short path the Improve panel lights up: part -> ... -> failing constraint."""
    source = part_node_id(part_id)
    target = constraint_node_id(check_id)
    if target not in {n.node_id for n in graph.nodes}:
        return None
    edges = _shortest_typed_path(graph, source, target, max_hops=3)
    if edges is None:
        return None
    steps = _steps(graph, edges, source)
    constraint = graph.node(target)
    return ExplanationPath(
        question=f"How does {graph.node(source).label} reach {constraint.label}?",
        steps=steps,
        conclusion=(
            f"{constraint.label} is currently {constraint.properties.get('status')}: "
            f"{constraint.properties.get('reason', '')}"
        ).strip(),
        weakest_status=weakest([e.status for e in edges]),
        missing_evidence=list(constraint.properties.get("missing_inputs", []) or []),
    )


def unknown_summary(graph: EvidenceGraph) -> list[str]:
    """Everything the graph openly does not know. Drives the 'missing evidence' UI."""
    return list(graph.unknown_relationships)
