from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts import validate_instance

REPO_ROOT = Path(__file__).resolve().parents[2]
CAD_DIR = REPO_ROOT / "fixtures" / "c" / "titan_avenger_cad"
GEOMETRY_PATH = CAD_DIR / "geometry_features.json"

SCHEMA_FILES = {
    "design_manifest.json": "design_manifest",
    "parts.json": "parts",
    "geometry_features.json": "geometry_features",
    "part_map.json": "part_map",
}

SYNTHETIC_CANT_RAD = 0.6981317007977318


@pytest.fixture(scope="module")
def cad_dir() -> Path:
    if not GEOMETRY_PATH.is_file():
        pytest.skip("fixtures/c/titan_avenger_cad/geometry_features.json not present yet")
    return CAD_DIR


def _load(cad_dir: Path, name: str) -> dict:
    return json.loads((cad_dir / name).read_text(encoding="utf-8"))


def test_archive_fixture_validates(cad_dir: Path) -> None:
    for filename, schema_name in SCHEMA_FILES.items():
        validate_instance(schema_name, _load(cad_dir, filename))


def test_archive_mass_kg_unknown_and_null(cad_dir: Path) -> None:
    parts = _load(cad_dir, "parts.json")
    for occ in parts["occurrences"]:
        mass = occ["mass_kg"]
        assert mass["status"] == "unknown", occ["part_id"]
        assert mass["value"] is None, occ["part_id"]


def test_archive_reference_span_area_and_cad_source(cad_dir: Path) -> None:
    geom = _load(cad_dir, "geometry_features.json")
    span = geom["reference"]["b_m"]
    area = geom["reference"]["S_m2"]
    do = geom["spar"]["Do_m"]
    assert span["value"] == pytest.approx(2.2245, abs=1e-4)
    assert area["value"] == pytest.approx(0.4199, abs=1e-4)
    assert span["source_kind"] == "cad"
    assert do["source_kind"] == "cad"


def test_archive_cant_is_vtail1_atan_not_synthetic_40deg(cad_dir: Path) -> None:
    geom = _load(cad_dir, "geometry_features.json")
    cant = geom["tail"]["cant_rad"]["value"]
    assert cant != pytest.approx(SYNTHETIC_CANT_RAD)
    assert 0.54 <= cant <= 0.56


def test_archive_spar_di_unknown_and_np_null(cad_dir: Path) -> None:
    geom = _load(cad_dir, "geometry_features.json")
    assert geom["spar"]["Do_m"]["value"] == pytest.approx(0.012)
    assert geom["spar"]["Di_m"]["value"] is None
    np_claim = geom["cg_inputs"]["np_x_m"]
    assert np_claim["status"] == "unknown"
    assert np_claim["value"] is None


def test_archive_aero_coefficients_assumed(cad_dir: Path) -> None:
    geom = _load(cad_dir, "geometry_features.json")
    for name, claim in geom["aero_assumptions"].items():
        assert claim["source_kind"] == "assumed", name


def test_archive_part_map_keys_match_thirty_occurrences(cad_dir: Path) -> None:
    parts = _load(cad_dir, "parts.json")
    part_map = _load(cad_dir, "part_map.json")
    ids = [occ["part_id"] for occ in parts["occurrences"]]
    assert len(ids) == 30
    assert len(set(ids)) == 30
    assert set(part_map) == set(ids)
    assert len(part_map) == 30


def test_archive_json_omits_avenger_and_falcon(cad_dir: Path) -> None:
    for filename in SCHEMA_FILES:
        blob = (cad_dir / filename).read_text(encoding="utf-8").lower()
        assert "avenger" not in blob, filename
        assert "falcon" not in blob, filename
