from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import Draft202012Validator

from contracts import (
    SCHEMA_FILES,
    Claim,
    get_validator,
    iter_claims,
    load_schema,
    make_claim,
    validate_instance,
)
from contracts.claim import is_claim

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_C = REPO_ROOT / "fixtures" / "c"
FIXTURE_SCHEMA = {
    "design_manifest.json": "design_manifest",
    "parts.json": "parts",
    "parts_conflicted.json": "parts",
    "geometry_features.json": "geometry_features",
    "part_map.json": "part_map",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_key_paths(obj, key: str, prefix=()):
    paths = []
    if isinstance(obj, dict):
        for child_key, value in obj.items():
            here = prefix + (child_key,)
            if child_key == key:
                paths.append(here)
            paths.extend(_walk_key_paths(value, key, here))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            paths.extend(_walk_key_paths(value, key, prefix + (i,)))
    return paths


def _has_key(obj, key: str) -> bool:
    return bool(_walk_key_paths(obj, key))


def _collect_numbers(obj, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _collect_numbers(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from _collect_numbers(value, f"{path}[{i}]")
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        yield path, obj


def test_schemas_are_valid_draft_2020_12():
    for name in SCHEMA_FILES:
        schema = load_schema(name)
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("path", sorted(FIXTURES_C.glob("*/*.json")), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_fixture_files_parse_and_validate(path: Path):
    schema_name = FIXTURE_SCHEMA.get(path.name)
    assert schema_name, f"unexpected fixture file {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_instance(schema_name, payload)


def test_unknown_null_survives_json_round_trip():
    claim = make_claim(
        None,
        "kg",
        status="unknown",
        source_kind="assumed",
        assumptions=["null mass must stay null"],
    )
    dumped = json.dumps(claim)
    loaded = json.loads(dumped)
    assert loaded["value"] is None
    assert "assumption_range" not in loaded
    validate_instance("claim", loaded)
    model = Claim.model_validate(loaded)
    assert model.value is None
    again = json.loads(json.dumps(model.model_dump(mode="json")))
    assert again["value"] is None


def test_geometry_np_unknown_stays_null(vtail_dir: Path, conventional_dir: Path):
    for folder in (vtail_dir, conventional_dir):
        geom = load_json(folder / "geometry_features.json")
        np_claim = geom["cg_inputs"]["np_x_m"]
        assert np_claim["status"] == "unknown"
        assert np_claim["value"] is None
        round_tripped = json.loads(json.dumps(geom))
        assert round_tripped["cg_inputs"]["np_x_m"]["value"] is None


@pytest.mark.parametrize("path", sorted(FIXTURES_C.glob("*/*.json")), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_nan_or_infinity(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    for number_path, value in _collect_numbers(payload):
        assert math.isfinite(value), number_path


@pytest.mark.parametrize("path", sorted(FIXTURES_C.glob("*/*.json")), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_assumption_range_ordered_when_present(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    for claim_path, claim in iter_claims(payload):
        rng = claim.get("assumption_range")
        if rng is None:
            continue
        assert rng["low"] <= rng["nominal"] <= rng["high"], claim_path


def test_assumption_range_rejected_when_unordered():
    claim = make_claim(1.0, "1", assumption_range=(1.2, 1.0, 0.8))
    with pytest.raises(ValidationError, match="low <= nominal <= high"):
        validate_instance("claim", claim)
    with pytest.raises(Exception):
        Claim.model_validate(claim)


def test_assumption_range_omitted_when_value_null():
    claim = make_claim(None, "m", status="unknown")
    claim["assumption_range"] = {"low": 0.0, "nominal": 0.1, "high": 0.2}
    with pytest.raises(ValidationError):
        validate_instance("claim", claim)


def test_vtail_has_cant_rad_conventional_does_not(vtail_dir: Path, conventional_dir: Path):
    vtail = load_json(vtail_dir / "geometry_features.json")
    conventional = load_json(conventional_dir / "geometry_features.json")
    assert vtail["tail"]["layout"] == "vtail"
    assert "cant_rad" in vtail["tail"]
    assert vtail["tail"]["cant_rad"]["value"] == pytest.approx(0.6981317007977318)
    assert conventional["tail"]["layout"] == "conventional"
    assert "cant_rad" not in conventional["tail"]
    assert not _has_key(conventional, "cant_rad")
    assert _has_key(vtail, "cant_rad")


def test_geometry_reference_s_b_c_appear_exactly_once(vtail_dir: Path, conventional_dir: Path):
    for folder in (vtail_dir, conventional_dir):
        geom = load_json(folder / "geometry_features.json")
        for key, expected in (("S_m2", 0.40), ("b_m", 2.20), ("c_m", 0.20)):
            paths = _walk_key_paths(geom, key)
            assert paths == [("reference", key)], (folder.name, key, paths)
            assert geom["reference"][key]["value"] == pytest.approx(expected)


def test_vtail_schema_requires_cant_rad(vtail_dir: Path):
    geom = load_json(vtail_dir / "geometry_features.json")
    del geom["tail"]["cant_rad"]
    with pytest.raises(ValidationError):
        validate_instance("geometry_features", geom)


def test_conventional_schema_rejects_cant_rad(conventional_dir: Path):
    geom = load_json(conventional_dir / "geometry_features.json")
    geom["tail"]["cant_rad"] = make_claim(0.6981317007977318, "rad", assumptions=["should be rejected"])
    with pytest.raises(ValidationError):
        validate_instance("geometry_features", geom)


def test_known_fixture_claims_are_assumed(vtail_dir: Path, conventional_dir: Path):
    for folder in (vtail_dir, conventional_dir):
        for json_path in sorted(folder.glob("*.json")):
            payload = load_json(json_path)
            for claim_path, claim in iter_claims(payload):
                assert claim["source_kind"] == "assumed", claim_path
                if claim["value"] is None:
                    assert claim["status"] == "unknown", claim_path
                else:
                    assert claim["status"] == "known", claim_path


def test_fixtures_are_not_labeled_avenger_or_falcon():
    blob = ""
    for path in FIXTURES_C.glob("*/*.json"):
        blob += path.read_text(encoding="utf-8").lower()
    assert "avenger" not in blob
    assert "falcon" not in blob


def test_right_wing_stations_have_nonnegative_y(vtail_dir: Path):
    geom = load_json(vtail_dir / "geometry_features.json")
    ys = [station["span_y_m"]["value"] for station in geom["wing_stations"]]
    assert ys == [0.00, 0.30, 0.60, 0.90, 1.10]
    assert all(y >= 0.0 for y in ys)


def test_part_map_keys_match_part_ids(vtail_dir: Path, conventional_dir: Path):
    for folder in (vtail_dir, conventional_dir):
        parts = load_json(folder / "parts.json")
        part_map = load_json(folder / "part_map.json")
        ids = [occ["part_id"] for occ in parts["occurrences"]]
        assert len(ids) == len(set(ids))
        assert set(part_map) == set(ids)


def test_conflicted_battery_energy_is_raw_500(vtail_dir: Path):
    payload = load_json(vtail_dir / "parts_conflicted.json")
    battery = next(occ for occ in payload["occurrences"] if occ["part_id"] == "battery")
    assert battery["specs"]["energy_wh"]["value"] == 500
    assert battery["mass_kg"]["value"] == pytest.approx(0.60)
    validate_instance("parts", payload)


def test_vtail_and_conventional_share_reference_and_wing(vtail_dir: Path, conventional_dir: Path):
    left = load_json(vtail_dir / "geometry_features.json")
    right = load_json(conventional_dir / "geometry_features.json")
    assert left["reference"] == right["reference"]
    assert left["wing_stations"] == right["wing_stations"]
    assert left["mission"] == right["mission"]
    assert left["aero_assumptions"] == right["aero_assumptions"]
    assert left["spar"] == right["spar"]


def test_conventional_uses_hstab_vstab_not_vtail_parts(conventional_dir: Path, vtail_dir: Path):
    conv_ids = {occ["part_id"] for occ in load_json(conventional_dir / "parts.json")["occurrences"]}
    vtail_ids = {occ["part_id"] for occ in load_json(vtail_dir / "parts.json")["occurrences"]}
    assert "hstab" in conv_ids and "vstab" in conv_ids
    assert "vtail_L" not in conv_ids and "vtail_R" not in conv_ids
    assert "vtail_L" in vtail_ids and "vtail_R" in vtail_ids
    assert "hstab" not in vtail_ids


def test_payload_is_locked(vtail_dir: Path, conventional_dir: Path):
    for folder in (vtail_dir, conventional_dir):
        payload = next(
            occ
            for occ in load_json(folder / "parts.json")["occurrences"]
            if occ["part_id"] == "payload"
        )
        assert payload["locked"] is True
        assert payload["mass_kg"]["value"] == pytest.approx(0.20)


def test_known_status_rejects_null_value():
    claim = make_claim(1.0, "kg")
    claim["value"] = None
    with pytest.raises(ValidationError):
        validate_instance("claim", claim)


def test_unknown_status_rejects_numeric_value():
    claim = make_claim(None, "kg", status="unknown")
    claim["value"] = 0.0
    with pytest.raises(ValidationError):
        validate_instance("claim", claim)


def test_evaluation_schema_accepts_unknown_metrics():
    doc = {
        "schema_version": 1,
        "meta": {
            "revision_id": "rev_synthetic_vtail_001",
            "geometry_hash": "sha256:" + "0" * 64,
            "fidelity_tier": "analytic",
            "input_hashes": {
                "design_manifest": "sha256:" + "1" * 64,
                "parts": "sha256:" + "2" * 64,
                "geometry_features": "sha256:" + "3" * 64,
            },
            "assumptions": ["analytic tier; no VSPAERO run for this geometry_hash"],
        },
        "metrics": {
            "mass_kg": make_claim(2.67, "kg", source_kind="computed"),
            "np_x_m": make_claim(
                None,
                "m",
                status="unknown",
                source_kind="computed",
                assumptions=["no validated derivatives"],
            ),
            "static_margin": make_claim(
                None,
                "1",
                status="unknown",
                source_kind="computed",
                assumptions=["np_x_m unknown"],
            ),
        },
        "checks": [
            {
                "name": "static_margin",
                "status": "unknown",
                "metric": make_claim(
                    None,
                    "1",
                    status="unknown",
                    source_kind="computed",
                    assumptions=["np_x_m unknown"],
                ),
                "detail": "neutral point unknown; no derivatives",
            },
            {
                "name": "tail_volume_horizontal",
                "status": "not_applicable",
                "detail": "conventional-tail heuristic; layout is vtail",
            },
            {"name": "payload", "status": "pass"},
        ],
        "quarantine": [
            {
                "path": "occurrences[battery].specs.energy_wh",
                "reason": "implausible Wh/kg",
                "raw": 500,
            }
        ],
    }
    validate_instance("evaluation", doc)
    round_tripped = json.loads(json.dumps(doc))
    assert round_tripped["metrics"]["np_x_m"]["value"] is None
    assert round_tripped["metrics"]["static_margin"]["value"] is None
    assert round_tripped["quarantine"][0]["raw"] == 500


def test_simulation_run_schema_example_is_finite_and_monotonic():
    run = {
        "schema_version": 1,
        "meta": {
            "revision_id": "rev_synthetic_vtail_001",
            "geometry_hash": "sha256:" + "0" * 64,
            "fidelity_tier": "analytic",
            "assumptions": ["straight and level", "no wind"],
            "dt_s": 0.02,
        },
        "frames": [
            {
                "t": 0.00,
                "pos_ned": [0.0, 0.0, -120.0],
                "quat": [1.0, 0.0, 0.0, 0.0],
                "Va": 15.0,
                "alpha": 0.043,
                "beta": 0.0,
                "load_factor_n": 1.0,
                "power_w": 142.0,
                "energy_wh_remaining": 70.4,
            },
            {
                "t": 0.02,
                "pos_ned": [0.3, 0.0, -120.0],
                "quat": [1.0, 0.0, 0.0, 0.0],
                "Va": 15.0,
                "alpha": 0.043,
                "beta": 0.0,
                "load_factor_n": 1.0,
                "power_w": 142.0,
                "energy_wh_remaining": 70.39,
            },
        ],
        "part_stress": {
            "spar_L": [{"t": 0.0, "sigma_mpa": 41.2, "station_m": 0.0}]
        },
    }
    validate_instance("simulation_run", run)
    times = [frame["t"] for frame in run["frames"]]
    assert times == sorted(times)
    assert all(frame["energy_wh_remaining"] >= 0 for frame in run["frames"])
    for _, value in _collect_numbers(run):
        assert math.isfinite(value)


def test_vspaero_simulation_run_requires_solver_versions():
    run = {
        "meta": {
            "revision_id": "rev_x",
            "geometry_hash": "sha256:" + "0" * 64,
            "fidelity_tier": "vspaero",
            "assumptions": [],
            "dt_s": 0.02,
        },
        "frames": [
            {
                "t": 0.0,
                "pos_ned": [0.0, 0.0, -120.0],
                "quat": [1.0, 0.0, 0.0, 0.0],
                "Va": 15.0,
                "alpha": 0.0,
                "beta": 0.0,
                "load_factor_n": 1.0,
                "power_w": 0.0,
                "energy_wh_remaining": 1.0,
            }
        ],
        "part_stress": {},
    }
    with pytest.raises(ValidationError):
        validate_instance("simulation_run", run)
    run["meta"]["solver_versions"] = {"openvsp": "3.x", "vspaero": "3.x"}
    validate_instance("simulation_run", run)


def test_reference_duplication_is_detectable(vtail_dir: Path):
    geom = load_json(vtail_dir / "geometry_features.json")
    sneaky = copy.deepcopy(geom)
    sneaky["mission"]["S_m2"] = make_claim(0.41, "m2")
    paths = _walk_key_paths(sneaky, "S_m2")
    assert len(paths) == 2
    with pytest.raises(ValidationError):
        validate_instance("geometry_features", sneaky)


def test_is_claim_does_not_treat_material_as_claim(vtail_dir: Path):
    part_map = load_json(vtail_dir / "part_map.json")
    material = part_map["spar_L"]["material"]
    assert not is_claim(material)
    assert material["source_kind"] == "assumed"


def test_make_claim_refuses_range_on_null():
    with pytest.raises(ValueError, match="assumption_range"):
        make_claim(None, "m", status="unknown", assumption_range=(0.0, 0.1, 0.2))


def test_get_validator_round_trips_claim_with_range():
    claim = make_claim(0.80, "1", assumption_range=(0.70, 0.80, 0.85))
    get_validator("claim").validate(claim)
    validate_instance("claim", claim)
    model = Claim.model_validate(claim)
    assert model.assumption_range is not None
    assert model.assumption_range.low == pytest.approx(0.70)
