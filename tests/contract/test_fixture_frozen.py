"""The fixture is frozen (architecture section 11).

"B freezes the contract baseline with A/C during the first 45 minutes, commits generated types and
fixture hashes, then all three branch from it."

This test is the freeze. If it fails, the fixture changed - which is allowed, but it is a contract
change: update the hash here, note it in ``docs/decisions/``, and tell A and C, because their
branches are built against these bytes.
"""

from __future__ import annotations

from pathlib import Path

from dronebench_contracts import content_hash

from tests.conftest import fixture_json

ROOT = Path(__file__).resolve().parents[2]

#: Regenerate with ``python fixtures/b/build_fixture.py``, which prints this value.
EXPECTED_FIXTURE_HASH = (ROOT / "fixtures" / "b" / "FIXTURE_HASH").read_text().strip()

#: The design the whole of Team B is built against.
EXPECTED_REVISION_ID_PREFIX = "rev_"


def test_fixture_hash_is_frozen():
    documents = {
        "fixtures/b/design_manifest.json": content_hash(fixture_json("design_manifest")),
        "fixtures/b/geometry_features.json": content_hash(fixture_json("geometry_features")),
        "fixtures/b/mission.json": content_hash(fixture_json("mission")),
        "fixtures/b/parts.json": content_hash(fixture_json("parts")),
        "fixtures/common/catalog.json": content_hash(fixture_json("catalog")),
    }
    assert content_hash(dict(sorted(documents.items()))) == EXPECTED_FIXTURE_HASH, (
        "the frozen fixture changed. That is a contract change: regenerate with "
        "`python fixtures/b/build_fixture.py`, record it in docs/decisions/, and tell A and C."
    )


def test_the_fixture_is_labelled_synthetic():
    """It must never read as a reconstruction of the supplied Titan archive."""
    manifest = fixture_json("design_manifest")
    blob = (manifest["display_name"] + " " + " ".join(manifest["notes"])).lower()
    assert "synthetic" in blob
    assert "not the titan" in blob or "not derived from the titan" in blob


def test_every_catalog_offer_is_labelled_synthetic():
    catalog = fixture_json("catalog")
    assert catalog["all_synthetic"] is True
    for item in catalog["items"]:
        for offer in item["offers"]:
            assert offer["synthetic"] is True
            assert offer["supplier_name"] is None
            assert offer["product_url"] is None


def test_catalog_is_within_the_section_7_size_band():
    assert 6 <= len(fixture_json("catalog")["items"]) <= 12


def test_the_neutral_point_is_recorded_as_an_assumption():
    """Section 8 permits a synthetic fixture to assume one, provided it says so."""
    features = fixture_json("geometry_features")
    neutral_point = features["neutral_point_station_m"]
    assert neutral_point is not None
    assert neutral_point["source_kind"] == "assumed"
    assert neutral_point["assumptions"], "an assumed neutral point must state its assumption"
