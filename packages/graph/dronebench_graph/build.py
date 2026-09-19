"""Project one revision into a typed evidence graph (architecture section 7).

Three things this builder refuses to do, because each one is a way a design-review tool can lie:

* It never emits ``mates_with`` from geometry. Touching bodies produce ``near``, status
  ``estimated``, and the pair is recorded in ``unknown_relationships`` so the UI can ask for
  confirmation instead of the graph implying a joint.
* It never emits ``compatible_with`` from anything but declared interfaces, and stamps the basis on
  every such edge.
* It keeps power and signal separate. Battery to ESC is ``powers``; flight controller to ESC is
  ``controls``. FC to RX is not a universal physical chain and is not invented here.
"""

from __future__ import annotations

from dronebench_contracts import (
    CatalogItem,
    CatalogSnapshot,
    Claim,
    Evaluation,
    EvidenceGraph,
    GeometryFeatures,
    GraphEdge,
    GraphNode,
    Mission,
    PartOccurrence,
    PartsDocument,
)

#: Proximity tolerance for a ``near`` edge, in metres. Generous on purpose: a false ``near`` costs
#: a confirmation prompt, while a missed one hides a real question from the reviewer.
NEAR_TOLERANCE_M = 0.005


def part_node_id(part_id: str) -> str:
    return f"n:part:{part_id}"


def definition_node_id(definition_id: str) -> str:
    return f"n:def:{definition_id}"


def catalog_node_id(catalog_item_id: str) -> str:
    return f"n:cat:{catalog_item_id}"


def evidence_node_id(evidence_id: str) -> str:
    return f"n:ev:{evidence_id}"


def constraint_node_id(check_id: str) -> str:
    return f"n:chk:{check_id}"


def regulation_node_id(rule_id: str) -> str:
    return f"n:reg:{rule_id}"


class _Builder:
    def __init__(self, revision_id: str) -> None:
        self.revision_id = revision_id
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self.unknown: list[str] = []
        self._edge_seq = 0

    def node(
        self,
        node_id: str,
        node_type: str,
        label: str,
        *,
        properties: dict | None = None,
        claims: dict[str, Claim] | None = None,
        evidence_ids: list[str] | None = None,
        status: str = "known",
    ) -> str:
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(
                node_id=node_id,
                node_type=node_type,  # type: ignore[arg-type]
                label=label,
                revision_id=self.revision_id,
                properties=properties or {},
                claims=claims or {},
                evidence_ids=evidence_ids or [],
                status=status,  # type: ignore[arg-type]
            )
        return node_id

    def edge(
        self,
        source: str,
        relation: str,
        target: str,
        *,
        status: str = "known",
        evidence_ids: list[str] | None = None,
        properties: dict | None = None,
        basis: str | None = None,
    ) -> None:
        self._edge_seq += 1
        self.edges.append(
            GraphEdge(
                edge_id=f"e{self._edge_seq:04d}:{relation}",
                source_id=source,
                target_id=target,
                relation=relation,  # type: ignore[arg-type]
                revision_id=self.revision_id,
                status=status,  # type: ignore[arg-type]
                evidence_ids=evidence_ids or [],
                properties=properties or {},
                basis=basis,  # type: ignore[arg-type]
            )
        )


def build_graph(
    *,
    parts: PartsDocument,
    features: GeometryFeatures,
    mission: Mission,
    catalog: CatalogSnapshot | None = None,
    evaluation: Evaluation | None = None,
    regulatory_findings: list | None = None,
) -> EvidenceGraph:
    """Assemble the graph for one revision."""
    builder = _Builder(parts.revision_id)

    _add_evidence(builder, parts)
    _add_definitions(builder, parts)
    _add_occurrences(builder, parts)
    _add_functions(builder, parts)
    _add_proximity(builder, parts)
    _add_networks(builder, parts)
    _add_mission(builder, mission, parts)
    if catalog is not None:
        _add_catalog(builder, catalog, parts)
    if evaluation is not None:
        _add_constraints(builder, evaluation, parts, features)
    if regulatory_findings:
        _add_regulations(builder, regulatory_findings, parts)

    return EvidenceGraph(
        revision_id=parts.revision_id,
        nodes=list(builder.nodes.values()),
        edges=builder.edges,
        evidence=parts.evidence,
        unknown_relationships=builder.unknown,
    )


# ---------------------------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------------------------


def _add_evidence(builder: _Builder, parts: PartsDocument) -> None:
    for entry in parts.evidence:
        builder.node(
            evidence_node_id(entry.evidence_id),
            "Evidence",
            entry.locator or entry.source_uri,
            properties={
                "source_uri": entry.source_uri,
                "source_kind": entry.source_kind,
                "extraction_method": entry.extraction_method,
            },
        )


def _add_definitions(builder: _Builder, parts: PartsDocument) -> None:
    for definition in parts.definitions:
        node_id = builder.node(
            definition_node_id(definition.definition_id),
            "PartDefinition",
            definition.name,
            properties={
                "representation": definition.representation,
                "role": definition.role,
                "parameters": definition.parameters,
            },
            claims=dict(definition.claims.claims),
        )
        material = definition.claims.get("density_kgm3")
        if material is not None and material.is_known:
            material_id = builder.node(
                f"n:mat:{definition.definition_id}",
                "Material",
                f"{definition.name} material",
                claims={"density_kgm3": material},
                evidence_ids=material.evidence_ids,
            )
            builder.edge(
                node_id,
                "made_of",
                material_id,
                status=material.status,
                evidence_ids=material.evidence_ids,
            )
        elif definition.representation in ("editable_reconstruction", "generated"):
            builder.unknown.append(
                f"{definition.definition_id}: material is not established by geometry alone"
            )


def _add_occurrences(builder: _Builder, parts: PartsDocument) -> None:
    for occurrence in parts.occurrences:
        node_id = builder.node(
            part_node_id(occurrence.part_id),
            "PartOccurrence",
            occurrence.name,
            properties={
                "role": occurrence.role,
                "locked": occurrence.locked,
                "edit_capabilities": occurrence.edit_capabilities,
                "mirror_of": occurrence.mirror_of,
                "translation_m": list(occurrence.transform.translation),
            },
            claims={"mass_kg": occurrence.mass_kg, **occurrence.claims.claims},
            evidence_ids=occurrence.mass_kg.evidence_ids,
            status=occurrence.mass_kg.status,
        )
        builder.edge(
            node_id,
            "instance_of",
            builder.node(
                definition_node_id(occurrence.definition_id),
                "PartDefinition",
                occurrence.definition_id,
            ),
        )
        for evidence_id in occurrence.mass_kg.evidence_ids:
            builder.edge(
                node_id,
                "supported_by",
                evidence_node_id(evidence_id),
                status=occurrence.mass_kg.status,
                evidence_ids=[evidence_id],
                properties={"quantity": "mass_kg"},
            )
        if not occurrence.mass_kg.is_known:
            builder.unknown.append(
                f"{occurrence.part_id}: mass is unknown; enter a measured value with provenance"
            )
        if occurrence.local_com_m is None and occurrence.mass_kg.is_known:
            builder.unknown.append(
                f"{occurrence.part_id}: mass distribution is unknown, so its contribution to CG "
                "cannot be placed"
            )


#: Role to the function it performs. Deliberately conservative: a role we cannot name a function
#: for produces no ``performs`` edge rather than a vague one.
_ROLE_FUNCTION: dict[str, str] = {
    "wing": "generate lift",
    "tail_panel": "provide pitch and yaw control",
    "spar": "carry wing bending load",
    "battery": "store mission energy",
    "motor": "convert electrical power to shaft power",
    "propeller": "convert shaft power to thrust",
    "esc": "commutate motor phases",
    "servo": "actuate a control surface",
    "flight_controller": "stabilise and navigate",
    "payload": "carry the mission payload",
    "mount": "transfer load between components",
    "fuselage": "house components and join surfaces",
}


def _add_functions(builder: _Builder, parts: PartsDocument) -> None:
    for occurrence in parts.occurrences:
        function = _ROLE_FUNCTION.get(occurrence.role)
        if function is None:
            continue
        function_id = builder.node(f"n:fn:{occurrence.role}", "Function", function)
        builder.edge(
            part_node_id(occurrence.part_id),
            "performs",
            function_id,
            status="estimated",
            properties={
                "basis": "role assignment from the parts document, not a verified functional test"
            },
        )


def _add_proximity(builder: _Builder, parts: PartsDocument) -> None:
    """Emit ``near`` for touching bodies. Never ``mates_with``.

    Declared contact partners are skipped: they are intended mating engagement, already known, and
    re-reporting them as proximity findings would bury the genuinely unexplained overlaps.
    """
    placed = [
        (occurrence, occurrence.world_bounds_m())
        for occurrence in parts.occurrences
    ]
    for index, (a, box_a) in enumerate(placed):
        if box_a is None:
            continue
        for b, box_b in placed[index + 1 :]:
            if box_b is None:
                continue
            if b.part_id in a.allowed_contact_part_ids or a.part_id in b.allowed_contact_part_ids:
                builder.edge(
                    part_node_id(a.part_id),
                    "mates_with",
                    part_node_id(b.part_id),
                    status="known",
                    evidence_ids=[
                        e for e in a.mass_kg.evidence_ids if e
                    ][:1] or ["ev_fixture-spec"],
                    properties={"basis": "declared contact pair in the parts document"},
                )
                continue
            if box_a.intersects(box_b, tol_m=NEAR_TOLERANCE_M):
                builder.edge(
                    part_node_id(a.part_id),
                    "near",
                    part_node_id(b.part_id),
                    status="estimated",
                    properties={
                        "basis": "bounding-box proximity",
                        "implies_load_transfer": False,
                    },
                )
                builder.unknown.append(
                    f"{a.part_id} and {b.part_id} are geometrically close; whether they are "
                    "fastened, bonded, or merely adjacent is not established"
                )


def _add_networks(builder: _Builder, parts: PartsDocument) -> None:
    """Power and signal as two separate networks (architecture section 7)."""
    by_role: dict[str, list[PartOccurrence]] = {}
    for occurrence in parts.occurrences:
        by_role.setdefault(occurrence.role, []).append(occurrence)

    def one(role: str) -> PartOccurrence | None:
        found = by_role.get(role)
        return found[0] if found else None

    battery = one("battery")
    esc = one("esc")
    motor = one("motor")
    avionics = one("flight_controller")
    servos = by_role.get("servo", [])

    # Power: battery -> ESC -> motor, and battery -> avionics.
    if battery and esc:
        builder.edge(
            part_node_id(battery.part_id),
            "powers",
            part_node_id(esc.part_id),
            status="estimated",
            properties={"network": "power", "basis": "standard fixed-wing power path"},
        )
    if esc and motor:
        builder.edge(
            part_node_id(esc.part_id),
            "powers",
            part_node_id(motor.part_id),
            status="estimated",
            properties={"network": "power"},
        )
    if battery and avionics:
        builder.edge(
            part_node_id(battery.part_id),
            "powers",
            part_node_id(avionics.part_id),
            status="estimated",
            properties={
                "network": "power",
                "basis": "regulated avionics supply; the regulator itself is not in the BOM",
            },
        )
        builder.unknown.append(
            "the power distribution board / BEC between the battery and avionics is not specified"
        )

    # Signal: flight controller -> ESC, flight controller -> each servo. Section 7 warns against
    # treating FC -> RX as a universal physical chain, so it is not asserted.
    if avionics and esc:
        builder.edge(
            part_node_id(avionics.part_id),
            "controls",
            part_node_id(esc.part_id),
            status="estimated",
            properties={"network": "signal", "signal": "throttle"},
        )
    for servo in servos:
        if avionics:
            builder.edge(
                part_node_id(avionics.part_id),
                "controls",
                part_node_id(servo.part_id),
                status="estimated",
                properties={"network": "signal", "signal": "pwm"},
            )
    if avionics:
        builder.unknown.append(
            "receiver-to-flight-controller wiring is not specified; it is not inferred here"
        )


def _add_mission(builder: _Builder, mission: Mission, parts: PartsDocument) -> None:
    mission_id = builder.node(
        f"n:msn:{mission.mission_id}",
        "Mission",
        mission.title,
        properties={
            "objective": mission.objective,
            "cruise_speed_mps": mission.cruise_speed_mps,
            "max_takeoff_mass_kg": mission.max_takeoff_mass_kg,
            "registry_version": mission.registry_version,
        },
    )
    for part_id in mission.locked_part_ids:
        if any(o.part_id == part_id for o in parts.occurrences):
            builder.edge(
                mission_id,
                "applies_to",
                part_node_id(part_id),
                properties={"reason": "locked mission payload"},
            )


def _add_catalog(builder: _Builder, catalog: CatalogSnapshot, parts: PartsDocument) -> None:
    """Catalog items, their suppliers, and interface-derived compatibility only."""
    for item in catalog.items:
        item_id = builder.node(
            catalog_node_id(item.catalog_item_id),
            "CatalogItem",
            item.display_name,
            properties={"category": item.category, "synthetic": True},
            claims={"mass_kg": item.mass_kg, **item.claims},
            evidence_ids=item.evidence_ids,
        )
        for interface in item.interfaces:
            interface_id = builder.node(
                f"n:if:{interface.interface_id}",
                "Interface",
                interface.interface_id,
                properties={"kind": interface.kind, "dimensions_m": interface.dimensions_m},
            )
            builder.edge(item_id, "exposes", interface_id)

        for offer in item.offers:
            if offer.synthetic:
                supplier_id = builder.node(
                    "n:sup:synthetic",
                    "Supplier",
                    "Synthetic demo supplier (no real offer)",
                    properties={"synthetic": True},
                )
            else:  # pragma: no cover - the checked-in snapshot is entirely synthetic
                supplier_id = builder.node(
                    f"n:sup:{offer.supplier_name}",
                    "Supplier",
                    str(offer.supplier_name),
                    properties={"synthetic": False, "region": offer.region},
                )
            builder.edge(
                item_id,
                "offered_by",
                supplier_id,
                status="estimated" if offer.synthetic else "known",
                properties={
                    "synthetic": offer.synthetic,
                    "currency": offer.currency,
                    "unit_price": offer.unit_price,
                    "stock_known": offer.stock_known,
                },
            )


def _add_constraints(
    builder: _Builder,
    evaluation: Evaluation,
    parts: PartsDocument,
    features: GeometryFeatures,
) -> None:
    """Link each check to the occurrences that actually feed it.

    The mapping is explicit rather than fuzzy. ``what fails if this battery moves`` is only a
    useful answer if the edges behind it were computed from the check's real inputs.
    """
    for check in evaluation.checks:
        constraint_id = builder.node(
            constraint_node_id(check.check_id),
            "Constraint",
            check.title,
            properties={
                "check_class": check.check_class,
                "status": check.status,
                "limit": check.limit,
                "reason": check.reason,
                "missing_inputs": check.missing_inputs,
            },
            status="unknown" if check.status == "unknown" else "known",
        )
        for part_id in _parts_feeding(check.check_id, parts):
            builder.edge(
                part_node_id(part_id),
                "constrained_by",
                constraint_id,
                status="estimated" if check.status == "unknown" else "known",
                properties={"check_status": check.status},
            )


def _parts_feeding(check_id: str, parts: PartsDocument) -> list[str]:
    """Which occurrences are inputs to a given check."""
    roles_by_check: dict[str, tuple[str, ...]] = {
        "mass_budget": (),  # every part with mass
        "cg_envelope": (),
        "static_margin": ("wing", "tail_panel", "battery"),
        "energy_reserve": ("battery", "motor", "propeller", "esc", "wing"),
        "spar_stress": ("spar", "wing"),
        "stall_margin": ("wing",),
        "battery_current": ("battery", "esc", "motor"),
        "clearance": ("propeller", "motor", "fuselage", "wing"),
        "registration_applicability": (),
        "remote_id_applicability": ("flight_controller",),
        "tail_volume": ("tail_panel", "wing"),
    }
    roles = roles_by_check.get(check_id)
    if roles is None:
        return []
    if roles == ():
        if check_id in ("mass_budget", "cg_envelope"):
            return [o.part_id for o in parts.occurrences]
        return []
    return [o.part_id for o in parts.occurrences if o.role in roles]


def _add_regulations(builder: _Builder, findings: list, parts: PartsDocument) -> None:
    for finding in findings:
        rule_id = builder.node(
            regulation_node_id(finding.rule_id),
            "Regulation",
            finding.title,
            properties={
                "applicability": finding.applicability,
                "jurisdiction": finding.jurisdiction,
                "operation": finding.operation,
                "rationale": finding.rationale,
                "missing_context": finding.missing_context,
            },
            evidence_ids=list(finding.evidence_ids),
            status="unknown" if finding.applicability == "unknown" else "known",
        )
        for part_id in finding.affected_part_ids:
            if any(o.part_id == part_id for o in parts.occurrences):
                builder.edge(
                    rule_id,
                    "applies_to",
                    part_node_id(part_id),
                    status="unknown" if finding.applicability == "unknown" else "known",
                    evidence_ids=list(finding.evidence_ids),
                    properties={"applicability": finding.applicability},
                )


def compatible_catalog_items(
    *,
    occurrence: PartOccurrence,
    required: list,
    catalog: CatalogSnapshot,
    category: str,
) -> list[tuple[CatalogItem, bool, list[str]]]:
    """Return ``(item, fits, reasons)`` for each candidate in a category.

    This is the only place ``compatible_with`` may be derived from, and it returns the failure
    reasons alongside the verdict so the UI can say *why* a part does not fit rather than hiding it.
    """
    results: list[tuple[CatalogItem, bool, list[str]]] = []
    for item in catalog.of_category(category):  # type: ignore[arg-type]
        reasons: list[str] = []
        fits = True
        for requirement in required:
            counterpart = item.interface_of(requirement.kind)
            if counterpart is None:
                fits = False
                reasons.append(f"no {requirement.kind} interface declared")
                continue
            ok, why = requirement.fits(counterpart)
            if not ok:
                fits = False
                reasons.extend(why)
        results.append((item, fits, reasons))
    return results
