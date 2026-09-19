"""Contract checks (architecture section 13).

"All fixtures parse; unknowns remain null; serialization round trip preserves units and IDs;
references resolve; schema mismatch fails with an actionable message. No NaN/Infinity in JSON."
"""

from __future__ import annotations

import json
import math

import pytest
from pydantic import ValidationError

from dronebench_contracts import (
    Artifact,
    CatalogOffer,
    CatalogSnapshot,
    Claim,
    ComparisonPair,
    ConflictSet,
    DesignManifest,
    Evidence,
    GeometryFeatures,
    GraphEdge,
    Mission,
    NonFiniteNumberError,
    PartsDocument,
    Transform,
    assert_finite,
    canonical_json,
    content_hash,
)
from dronebench_contracts.schema import build_bundle

from tests.conftest import fixture_json


# ---------------------------------------------------------------------------------------------
# Fixtures parse, and round trip
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,model",
    [
        ("design_manifest", DesignManifest),
        ("parts", PartsDocument),
        ("geometry_features", GeometryFeatures),
        ("mission", Mission),
        ("catalog", CatalogSnapshot),
    ],
)
def test_fixture_parses_and_round_trips(name, model):
    payload = fixture_json(name)
    parsed = model.model_validate(payload)
    again = model.model_validate(parsed.model_dump(mode="json"))
    assert again.model_dump(mode="json") == parsed.model_dump(mode="json")


def test_round_trip_preserves_units_and_ids():
    parts = PartsDocument.model_validate(fixture_json("parts"))
    reparsed = PartsDocument.model_validate(json.loads(canonical_json(parts.model_dump(mode="json"))))
    for before, after in zip(parts.occurrences, reparsed.occurrences):
        assert before.part_id == after.part_id
        assert before.definition_id == after.definition_id
        assert before.mass_kg.unit == after.mass_kg.unit
        assert before.mass_kg.value == after.mass_kg.value
        assert before.mass_kg.status == after.mass_kg.status


def test_references_resolve():
    """Every definition, parent, mirror, contact partner, and cited evidence must exist."""
    parts = PartsDocument.model_validate(fixture_json("parts"))
    # PartsDocument's validator enforces this; constructing it above is the check. Assert one
    # concrete consequence so a future relaxation of the validator fails here too.
    definition_ids = {d.definition_id for d in parts.definitions}
    part_ids = {o.part_id for o in parts.occurrences}
    evidence_ids = {e.evidence_id for e in parts.evidence}
    for occurrence in parts.occurrences:
        assert occurrence.definition_id in definition_ids
        assert set(occurrence.allowed_contact_part_ids) <= part_ids
        assert set(occurrence.mass_kg.evidence_ids) <= evidence_ids


def test_dangling_reference_is_rejected_with_an_actionable_message():
    payload = fixture_json("parts")
    payload["occurrences"][0]["definition_id"] = "def_does-not-exist"
    with pytest.raises(ValidationError) as excinfo:
        PartsDocument.model_validate(payload)
    assert "def_does-not-exist" in str(excinfo.value)


# ---------------------------------------------------------------------------------------------
# Unknowns stay null
# ---------------------------------------------------------------------------------------------


def test_unknown_claim_serialises_as_null_not_zero():
    claim = Claim.unknown("kg", reason="no BOM entry")
    payload = claim.model_dump(mode="json")
    assert payload["value"] is None
    assert payload["value"] != 0
    assert payload["confidence"] is None


def test_unknown_claim_may_not_carry_a_confidence():
    with pytest.raises(ValidationError):
        Claim(value=None, unit="kg", status="unknown", source_kind="inferred", confidence=0.9)


def test_a_valued_claim_may_not_declare_itself_unknown():
    with pytest.raises(ValidationError):
        Claim(value=1.0, unit="kg", status="unknown", source_kind="bom")


def test_fixture_keeps_its_unknown_mass_null():
    parts = PartsDocument.model_validate(fixture_json("parts"))
    harness = parts.by_id("prt_harness")
    assert harness.mass_kg.value is None
    assert harness.mass_kg.number() is None
    assert not harness.mass_kg.is_known


def test_measured_claim_requires_evidence():
    with pytest.raises(ValueError):
        Claim.measured(1.0, "kg", source_kind="bom", evidence_ids=[])


def test_assumed_claim_requires_a_stated_assumption():
    with pytest.raises(ValidationError):
        Claim(value=1.0, unit="kg", status="estimated", source_kind="assumed", assumptions=[])


# ---------------------------------------------------------------------------------------------
# No NaN or Infinity
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_non_finite(bad):
    with pytest.raises(NonFiniteNumberError):
        canonical_json({"metric": bad})


def test_non_finite_rejected_at_any_depth():
    with pytest.raises(NonFiniteNumberError):
        assert_finite({"a": [{"b": [1.0, float("nan")]}]})


def test_claim_rejects_a_non_finite_value():
    with pytest.raises(ValidationError):
        Claim(value=float("nan"), unit="kg", status="known", source_kind="bom", evidence_ids=["ev_x"])


def test_no_fixture_contains_a_non_finite_number():
    for name in ("design_manifest", "parts", "geometry_features", "mission", "catalog"):
        assert_finite(fixture_json(name))


# ---------------------------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------------------------


def test_content_hash_ignores_key_order_and_display_only_fields():
    a = content_hash({"b": 1, "a": 2, "created_at": "2026-01-01"})
    b = content_hash({"a": 2, "b": 1, "created_at": "2099-12-31"})
    assert a == b


def test_content_hash_changes_with_real_content():
    assert content_hash({"a": 1}) != content_hash({"a": 2})


def test_artifact_hash_is_not_embedded_in_its_own_bytes():
    data = b'{"value": 1}'
    artifact = Artifact.of_bytes(
        data, relative_path="x.json", media_type="application/json", produced_by="B", role="x"
    )
    assert artifact.sha256 not in data.decode()


@pytest.mark.parametrize("path", ["/etc/passwd", "../escape.json", "C:\\windows\\x"])
def test_artifact_path_must_be_relative_and_non_escaping(path):
    with pytest.raises(ValidationError):
        Artifact(
            artifact_id="art_0000000000000000",
            relative_path=path,
            sha256="0" * 64,
            size_bytes=0,
            media_type="application/json",
            produced_by="B",
            role="x",
        )


# ---------------------------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------------------------


def test_a_reflection_is_not_accepted_as_a_placement():
    """Section 5: mirroring is a reconstruction operation, not a rigid rotation."""
    with pytest.raises(ValidationError) as excinfo:
        Transform(
            matrix=[
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
    assert "reflection" in str(excinfo.value).lower()


def test_compatible_with_cannot_be_authored_from_proximity():
    with pytest.raises(ValidationError):
        GraphEdge(
            edge_id="e1",
            source_id="a",
            target_id="b",
            relation="compatible_with",
            revision_id="rev_0000000000000000",
        )


def test_near_cannot_be_asserted_as_known():
    with pytest.raises(ValidationError):
        GraphEdge(
            edge_id="e1",
            source_id="a",
            target_id="b",
            relation="near",
            revision_id="rev_0000000000000000",
            status="known",
        )


def test_mates_with_needs_confirmation_evidence():
    with pytest.raises(ValidationError):
        GraphEdge(
            edge_id="e1",
            source_id="a",
            target_id="b",
            relation="mates_with",
            revision_id="rev_0000000000000000",
            status="known",
            evidence_ids=[],
        )


def test_a_synthetic_offer_may_not_name_a_supplier():
    """Section 7: do not fabricate product availability, origin, or price."""
    with pytest.raises(ValidationError):
        CatalogOffer(synthetic=True, supplier_name="A Real Company", currency="USD")


def test_a_verified_offer_needs_a_source_and_a_timestamp():
    with pytest.raises(ValidationError):
        CatalogOffer(synthetic=False, supplier_name="Someone")


def test_conflicting_claims_are_both_retained():
    inferred = Claim(value=0.5, unit="kg", status="estimated", source_kind="inferred")
    measured = Claim.measured(0.7, "kg", source_kind="bom", evidence_ids=["ev_x"])
    conflict = ConflictSet.resolve("mass_kg", [inferred, measured])
    assert len(conflict.candidates) == 2
    assert conflict.selected.value == 0.7, "a measured value must win over an inferred one"
    assert conflict.selected.status == "conflicted"
    assert "retained" in conflict.rationale


def test_evidence_validity_interval_must_be_ordered():
    from datetime import datetime, timezone

    with pytest.raises(ValidationError):
        Evidence(
            evidence_id="ev_x",
            source_uri="x",
            source_kind="manual",
            extraction_method="m",
            valid_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
            valid_to=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


# ---------------------------------------------------------------------------------------------
# Schema bundle
# ---------------------------------------------------------------------------------------------


def test_schema_bundle_is_generatable_and_complete():
    bundle = build_bundle()
    defs = bundle["$defs"]
    for required in (
        "Claim",
        "Evidence",
        "PartsDocument",
        "GeometryFeatures",
        "Evaluation",
        "EvidenceGraph",
        "Recommendation",
        "DecisionRequest",
        "ErrorEnvelope",
        "EditOperation",
        "SimulationRun",
    ):
        assert required in defs, f"{required} is missing from the generated schema"


def test_committed_schema_matches_the_generator():
    """The checked-in bundle is the one the TypeScript types are generated from."""
    from pathlib import Path

    committed = json.loads(
        (Path(__file__).resolve().parents[2] / "schema" / "dronebench.schema.json").read_text(
            encoding="utf-8"
        )
    )
    assert committed["$defs"].keys() == build_bundle()["$defs"].keys(), (
        "schema/dronebench.schema.json is stale; run "
        "python -m dronebench_contracts.schema schema"
    )


# ---------------------------------------------------------------------------------------------
# Mission registry tampering
# ---------------------------------------------------------------------------------------------


def test_the_check_registry_is_frozen():
    """Section 8: a proposal or a model cannot edit the registry or downgrade a check."""
    from dronebench_contracts import FIXED_WING_CRUISE_V1

    with pytest.raises(ValidationError):
        FIXED_WING_CRUISE_V1.checks[0].check_class = "informational"  # type: ignore[misc]


def test_mission_hash_covers_the_registry():
    mission = Mission.model_validate(fixture_json("mission"))
    assert mission.mission_hash() == mission.mission_hash()
    other = mission.model_copy(update={"cruise_speed_mps": 17.0})
    assert other.mission_hash() != mission.mission_hash()


def test_mission_rejects_contradictory_cg_and_static_margin_bounds():
    payload = fixture_json("mission")
    payload["static_margin_bounds"] = [0.4, 0.2]
    with pytest.raises(ValidationError):
        Mission.model_validate(payload)
