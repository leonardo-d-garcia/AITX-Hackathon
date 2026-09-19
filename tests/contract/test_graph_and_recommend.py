"""Graph semantics, regulatory applicability, and recommendation honesty (sections 7 and 8)."""

from __future__ import annotations

import pytest

from dronebench_contracts import (
    DroneBenchError,
    MAX_CANDIDATES,
    MAX_DISPLAYED,
    Mission,
    PartsDocument,
    ResizeSpar,
    TranslateComponent,
)
from dronebench_graph import (
    affected_by_edit,
    mass_evidence,
    neighborhood,
    part_node_id,
    to_networkx,
    what_fails_if_moved,
)
from dronebench_recommend import assess, validate_operation
from dronebench_recommend.regulatory import RECREATIONAL_MASS_THRESHOLD_KG

from tests.conftest import DESIGN_ID, fixture_json


# ---------------------------------------------------------------------------------------------
# Graph semantics
# ---------------------------------------------------------------------------------------------


def test_proximity_never_becomes_mates_with(confirmed):
    """Section 7: separate `near` from `mates_with`; neither proves load transfer."""
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)

    for edge in graph.edges:
        if edge.relation == "near":
            assert edge.status in ("estimated", "unknown")
            assert edge.properties.get("implies_load_transfer") is False
        if edge.relation == "mates_with":
            assert edge.properties.get("basis") == "declared contact pair in the parts document"


def test_compatible_with_edges_declare_their_basis(confirmed):
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    for edge in graph.edges:
        if edge.relation == "compatible_with":
            assert edge.basis == "declared_interfaces"


def test_power_and_signal_are_distinct_networks(confirmed):
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    power = {e.edge_id for e in graph.edges if e.relation == "powers"}
    signal = {e.edge_id for e in graph.edges if e.relation == "controls"}
    assert power and signal
    assert power.isdisjoint(signal)
    for edge in graph.edges:
        if edge.relation == "powers":
            assert edge.properties.get("network") == "power"
        if edge.relation == "controls":
            assert edge.properties.get("network") == "signal"


def test_receiver_to_flight_controller_is_not_invented(confirmed):
    """Section 7: do not treat FC->RX as a universal physical chain."""
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    assert any("receiver" in note for note in graph.unknown_relationships)


def test_unknown_relationships_are_stated_openly(confirmed):
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    assert graph.unknown_relationships, "a graph with no declared unknowns is overclaiming"


def test_neighborhood_is_bounded_by_the_node_budget(confirmed):
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    small = neighborhood(graph, part_node_id("prt_battery"), radius=4, node_budget=5)
    assert len(small.nodes) <= 5
    assert small.truncated is True


def test_neighborhood_is_smaller_than_the_whole_graph(confirmed):
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    local = workbench.get_neighborhood(revision_id, "prt_battery", radius=1)
    assert len(local.nodes) < len(graph.nodes)


def test_networkx_projection_round_trips_the_graph(confirmed):
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    projection = to_networkx(graph)
    assert projection.number_of_nodes() == len(graph.nodes)
    assert projection.number_of_edges() == len(graph.edges)


# ---------------------------------------------------------------------------------------------
# The five narrow questions
# ---------------------------------------------------------------------------------------------


def test_mass_evidence_for_an_unknown_mass_says_so(imported):
    workbench, revision_id = imported
    graph = workbench.get_graph(revision_id)
    path = mass_evidence(graph, "prt_harness")
    assert path.weakest_status == "unknown"
    assert "prt_harness.mass_kg" in path.missing_evidence
    assert "not zero" in path.conclusion


def test_mass_evidence_for_a_known_mass_cites_its_source(confirmed):
    workbench, revision_id = confirmed
    graph = workbench.get_graph(revision_id)
    path = mass_evidence(graph, "prt_battery")
    assert path.steps, "a known mass must have at least one evidence hop"
    assert "bom" in path.conclusion


def test_what_fails_if_the_battery_moves_names_real_constraints(confirmed):
    workbench, revision_id = confirmed
    workbench.evaluate(revision_id)
    graph = workbench.get_graph(revision_id)
    path = what_fails_if_moved(graph, "prt_battery")
    assert "centre of gravity" in path.conclusion.lower()
    assert "aerodynamic coefficients may legitimately be reused" in path.conclusion


def test_affected_by_a_spar_change_lists_coupled_parts(confirmed):
    workbench, revision_id = confirmed
    workbench.evaluate(revision_id)
    graph = workbench.get_graph(revision_id)
    path = affected_by_edit(graph, "prt_spar")
    assert "Wing panel" in path.conclusion


def test_fitting_alternatives_uses_declared_interfaces(confirmed):
    workbench, revision_id = confirmed
    answer = workbench.explain(revision_id, "prt_battery", "fitting_alternatives")
    by_id = {row["catalog_item_id"]: row for row in answer["results"]}
    assert by_id["cat_bat_4s4000_light"]["fits"] is True
    oversize = by_id["cat_bat_6s5000_oversize"]
    assert oversize["fits"] is False
    assert oversize["reasons"], "a non-fitting part must say why"
    assert "synthetic" in answer["note"]


def test_an_unknown_question_is_refused_with_the_supported_list(confirmed):
    workbench, revision_id = confirmed
    with pytest.raises(DroneBenchError) as excinfo:
        workbench.explain(revision_id, "prt_battery", "is_it_pretty")
    assert excinfo.value.envelope.code == "INVALID_REQUEST"
    assert "mass_evidence" in excinfo.value.envelope.details["supported"]


# ---------------------------------------------------------------------------------------------
# Regulatory applicability
# ---------------------------------------------------------------------------------------------


def test_part_107_registration_does_not_consult_the_250_gram_threshold():
    """Section 7: that exemption belongs to qualifying recreational operation."""
    mission = Mission.model_validate(fixture_json("mission"))
    parts = PartsDocument.model_validate(fixture_json("parts"))

    heavy = assess(mission=mission, parts=parts, total_mass_kg=1.9)
    light = assess(mission=mission, parts=parts, total_mass_kg=0.1)

    assert heavy.by_id("registration").applicability == "applies"
    assert light.by_id("registration").applicability == "applies", (
        "a sub-250 g aircraft under Part 107 still requires registration"
    )
    assert "recreational carve-out" in light.by_id("registration").rationale


def test_recreational_operation_does_consult_the_threshold():
    mission = Mission.model_validate(fixture_json("mission"))
    parts = PartsDocument.model_validate(fixture_json("parts"))
    recreational = mission.model_copy(
        update={
            "regulatory": mission.regulatory.model_copy(
                update={"operation": "recreational_44809"}
            )
        }
    )
    below = assess(
        mission=recreational, parts=parts, total_mass_kg=RECREATIONAL_MASS_THRESHOLD_KG - 0.01
    )
    above = assess(
        mission=recreational, parts=parts, total_mass_kg=RECREATIONAL_MASS_THRESHOLD_KG + 0.01
    )
    assert below.by_id("registration").applicability == "does_not_apply"
    assert above.by_id("registration").applicability == "applies"


def test_unknown_mass_makes_recreational_registration_unknown():
    mission = Mission.model_validate(fixture_json("mission"))
    parts = PartsDocument.model_validate(fixture_json("parts"))
    recreational = mission.model_copy(
        update={
            "regulatory": mission.regulatory.model_copy(
                update={"operation": "recreational_44809"}
            )
        }
    )
    report = assess(mission=recreational, parts=parts, total_mass_kg=None)
    finding = report.by_id("registration")
    assert finding.applicability == "unknown"
    assert finding.missing_context


def test_remote_id_is_not_inferred_from_a_part_name():
    mission = Mission.model_validate(fixture_json("mission"))
    parts = PartsDocument.model_validate(fixture_json("parts"))
    report = assess(mission=mission, parts=parts, total_mass_kg=1.9)
    finding = report.by_id("remote_id")
    assert finding.applicability == "applies"
    assert any("cannot be inferred" in note for note in finding.missing_context)


def test_a_fria_operation_is_an_exception():
    mission = Mission.model_validate(fixture_json("mission"))
    parts = PartsDocument.model_validate(fixture_json("parts"))
    in_fria = mission.model_copy(
        update={"regulatory": mission.regulatory.model_copy(update={"in_friaa": True})}
    )
    report = assess(mission=in_fria, parts=parts, total_mass_kg=1.9)
    assert report.by_id("remote_id").applicability == "does_not_apply"


def test_every_finding_carries_the_non_certification_disclaimer():
    mission = Mission.model_validate(fixture_json("mission"))
    parts = PartsDocument.model_validate(fixture_json("parts"))
    for finding in assess(mission=mission, parts=parts, total_mass_kg=1.9).findings:
        assert "does not certify" in finding.disclaimer


# ---------------------------------------------------------------------------------------------
# Candidate validation
# ---------------------------------------------------------------------------------------------


def test_an_edit_is_refused_before_units_are_confirmed(imported):
    workbench, revision_id = imported
    parts = workbench.get_parts(revision_id)
    features = workbench.get_features(revision_id)
    outcome = validate_operation(
        TranslateComponent(target_part_id="prt_battery", axis="x", delta_m=0.02),
        parts=parts,
        features=features,
        mission=workbench.repository.design_mission(DESIGN_ID),
        base_revision_id=revision_id,
        catalog=workbench.catalog,
    )
    assert not outcome.ok
    assert any("units have not been confirmed" in reason for reason in outcome.reasons)


def test_a_locked_part_cannot_be_edited(confirmed):
    workbench, revision_id = confirmed
    parts = workbench.get_parts(revision_id)
    outcome = validate_operation(
        TranslateComponent(target_part_id="prt_payload", axis="x", delta_m=0.02),
        parts=parts,
        features=workbench.get_features(revision_id),
        mission=workbench.repository.design_mission(DESIGN_ID),
        base_revision_id=revision_id,
        catalog=workbench.catalog,
    )
    assert not outcome.ok
    assert any("locked" in reason for reason in outcome.reasons)


def test_a_move_outside_the_corridor_is_refused(confirmed):
    workbench, revision_id = confirmed
    outcome = validate_operation(
        TranslateComponent(target_part_id="prt_battery", axis="x", delta_m=0.9),
        parts=workbench.get_parts(revision_id),
        features=workbench.get_features(revision_id),
        mission=workbench.repository.design_mission(DESIGN_ID),
        base_revision_id=revision_id,
        catalog=workbench.catalog,
    )
    assert not outcome.ok
    assert any("corridor" in reason or "harness allowance" in reason for reason in outcome.reasons)


def test_a_spar_resize_must_regenerate_its_mounts(confirmed):
    workbench, revision_id = confirmed
    outcome = validate_operation(
        ResizeSpar(
            target_part_id="prt_spar",
            outer_diameter_m=0.018,
            inner_diameter_m=0.016,
            regenerate_mount_part_ids=[],
        ),
        parts=workbench.get_parts(revision_id),
        features=workbench.get_features(revision_id),
        mission=workbench.repository.design_mission(DESIGN_ID),
        base_revision_id=revision_id,
        catalog=workbench.catalog,
    )
    assert not outcome.ok
    assert any("mounts bear on the spar" in reason for reason in outcome.reasons)


def test_an_edit_against_the_wrong_base_revision_is_refused(confirmed):
    workbench, revision_id = confirmed
    outcome = validate_operation(
        TranslateComponent(target_part_id="prt_battery", axis="x", delta_m=0.02),
        parts=workbench.get_parts(revision_id),
        features=workbench.get_features(revision_id),
        mission=workbench.repository.design_mission(DESIGN_ID),
        base_revision_id="rev_0000000000000000",
        catalog=workbench.catalog,
    )
    assert not outcome.ok
    assert any("stated base" in reason for reason in outcome.reasons)


# ---------------------------------------------------------------------------------------------
# Recommendation budgets and honesty
# ---------------------------------------------------------------------------------------------


def test_missing_evidence_takes_priority_over_edit_proposals(imported):
    """Section 7 step 2: ask for the missing mass before promising endurance."""
    workbench, revision_id = imported
    workbench.evaluate(revision_id)
    result = workbench.recommend(revision_id, preview_all=False)

    assert result.evidence_requests, "an unknown required check must surface a request"
    request = result.evidence_requests[0]
    assert request.quantity == "prt_harness.mass_kg"
    assert "mass_budget" in request.blocked_check_ids
    assert "inferred" not in request.suggested_source_kinds
    assert not result.generated, "no edit may be proposed while a required check is unknown"


def test_budgets_are_respected(reviewed):
    _, _, recommendations = reviewed
    assert len(recommendations.generated) <= MAX_CANDIDATES
    assert len(recommendations.displayed_proposal_ids) <= MAX_DISPLAYED
    assert recommendations.provider_calls_used <= 2


def test_a_proposal_that_recovers_feasibility_ranks_first(reviewed):
    _, _, recommendations = reviewed
    assert recommendations.displayed_proposal_ids[0] == "rec_battery-cg"


def test_the_spar_proposal_shows_both_sides_of_its_tradeoff(reviewed):
    """Section 10: more margin and more mass must both be visible."""
    _, _, recommendations = reviewed
    spar = next(r for r in recommendations.generated if r.proposal_id == "rec_spar-resize")
    improving = {t.metric for t in spar.tradeoffs if t.direction == "improves"}
    worsening = {t.metric for t in spar.tradeoffs if t.direction == "worsens"}
    assert "spar_safety_factor" in improving
    assert "mass_kg" in worsening
    assert "endurance_min" in worsening


def test_banded_metrics_take_their_direction_from_their_check(reviewed):
    _, _, recommendations = reviewed
    cg = next(r for r in recommendations.generated if r.proposal_id == "rec_battery-cg")
    station = next(t for t in cg.tradeoffs if t.metric == "cg_station_m")
    assert station.direction == "improves"
    assert "cg_envelope moved from fail to pass" in (station.basis or "")


def test_an_unevaluated_proposal_is_labelled(confirmed):
    workbench, revision_id = confirmed
    workbench.evaluate(revision_id)
    result = workbench.recommend(revision_id, preview_all=False)
    for proposal in result.generated:
        assert proposal.display_label == "unevaluated proposal"


def test_no_removal_proposals_are_generated(reviewed):
    """Section 3: missing redundancy or load-path knowledge prevents removal recommendations."""
    _, _, recommendations = reviewed
    for proposal in recommendations.generated:
        assert proposal.operation.operation in (
            "translate_component",
            "resize_spar",
            "set_wing_tip_extension",
            "replace_catalog_component",
        )


def test_every_proposal_states_its_prerequisites_and_evidence(reviewed):
    _, _, recommendations = reviewed
    for proposal in recommendations.generated:
        assert proposal.prerequisites
        assert proposal.rationale
        assert proposal.issue
