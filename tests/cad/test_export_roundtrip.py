"""Export acceptance: the artifacts exist, the STEP survives a reimport, the GLB is loadable.

The round trip is compared semantically. STEP entity numbering and face ordering are not
required to be stable, so nothing here hashes STEP bytes.
"""
from __future__ import annotations

import json
import time

import pytest
import trimesh

from dronebench_cad import (
    BOM_NAME,
    CHANGES_NAME,
    GLB_NAME,
    PART_MAP_NAME,
    STEP_NAME,
    export,
    reconstruct,
    reimport_check,
    sha256_file,
)

ARTIFACT_NAMES = {STEP_NAME, GLB_NAME, PART_MAP_NAME, BOM_NAME, CHANGES_NAME}


def test_export_writes_every_artifact_with_a_hash(exported):
    out, artifacts = exported
    assert {a["path"] for a in artifacts} == ARTIFACT_NAMES
    for artifact in artifacts:
        path = out / artifact["path"]
        assert path.is_file() and path.stat().st_size > 0
        assert artifact["sha256"] == sha256_file(path)
        assert len(artifact["sha256"]) == 64


def test_part_map_covers_every_part_and_is_labelled(exported, model):
    out, _ = exported
    part_map = json.loads((out / PART_MAP_NAME).read_text())
    assert {p["part_id"] for p in part_map["parts"]} == {p.part_id for p in model.parts}
    assert "not the original" in part_map["label"].lower()
    assert part_map["units"] == "m" and part_map["frame"] == "FRD"


def test_bom_never_invents_a_mass_or_a_material(exported):
    out, _ = exported
    bom = json.loads((out / BOM_NAME).read_text())
    for item in bom["items"]:
        assert item["material"]["status"] == "unknown"
        if item["mass_kg"]["value"] is None:
            assert item["mass_kg"]["status"] == "unknown"


def test_changes_is_empty_for_a_baseline_and_records_what_it_is_given(model, tmp_path):
    change = {"part_id": "recon_spar", "field": "outer_diameter_m",
              "before": 0.016, "after": 0.020, "unit": "m"}
    artifacts = export(model, tmp_path, changes=[change], cause="edit:resize_spar")
    payload = json.loads((tmp_path / CHANGES_NAME).read_text())
    assert payload["changes"] == [change] and payload["cause"] == "edit:resize_spar"
    assert {a["path"] for a in artifacts} == ARTIFACT_NAMES


def test_step_reimports_and_passes_every_acceptance_check(exported, model):
    out, _ = exported
    checks = reimport_check(out / STEP_NAME, model)
    failed = [c for c in checks if not c["passed"]]
    assert not failed, failed
    names = {c["name"] for c in checks}
    assert {
        "step_readable", "solid_count", "part_map_id_coverage", "all_solids_valid",
        "finite_positive_volume", "bounds_within_tolerance", "placement_match",
        "volume_relative_difference",
    } <= names


def test_round_trip_accepts_a_part_map_file_as_the_expectation(exported):
    out, _ = exported
    checks = reimport_check(out / STEP_NAME, out / PART_MAP_NAME)
    assert all(c["passed"] for c in checks)


def test_round_trip_notices_an_edited_design_against_a_stale_part_map(exported, params, tmp_path):
    """A STEP built from changed parameters must not pass the old sidecar's checks."""
    out, _ = exported
    edited = params.model_copy(deep=True)
    edited.spar.outer_diameter_m = 0.024
    export(reconstruct(params=edited), tmp_path)
    checks = reimport_check(tmp_path / STEP_NAME, out / PART_MAP_NAME)
    failed = {c["name"] for c in checks if not c["passed"]}
    assert "volume_relative_difference" in failed or "bounds_within_tolerance" in failed


def test_glb_loads_with_a_node_for_every_part(exported, model):
    out, _ = exported
    scene = trimesh.load(str(out / GLB_NAME))
    nodes = set(scene.graph.nodes)
    missing = {p.part_id for p in model.parts} - nodes
    assert not missing, f"GLB is missing nodes for {sorted(missing)}"
    # The GLB is written in metres: a 2.2 m aircraft must not come back 2200 units long.
    extents = scene.bounds[1] - scene.bounds[0]
    assert 1.0 < float(max(extents)) < 4.0


# ---------------------------------------------------------------- failure containment

def test_a_corrupt_step_fails_fast_instead_of_taking_the_process_down(exported, tmp_path):
    out, _ = exported
    broken = tmp_path / "corrupt.step"
    broken.write_bytes(b"ISO-10303-21;\nHEADER;\n" + b"\x00\xff" * 5000 + b"\nnot a step file")
    started = time.perf_counter()
    checks = reimport_check(broken, out / PART_MAP_NAME, timeout_s=60)
    elapsed = time.perf_counter() - started
    assert elapsed < 60, "the worker should be bounded by its timeout"
    assert any(not c["passed"] for c in checks)


def test_a_truncated_step_fails_fast(exported, tmp_path):
    out, _ = exported
    good = (out / STEP_NAME).read_bytes()
    truncated = tmp_path / "truncated.step"
    truncated.write_bytes(good[: len(good) // 2])
    checks = reimport_check(truncated, out / PART_MAP_NAME, timeout_s=60)
    assert any(not c["passed"] for c in checks)


def test_a_missing_step_is_reported_not_raised(tmp_path, model):
    checks = reimport_check(tmp_path / "nope.step", model)
    assert checks and not checks[0]["passed"] and "no such file" in checks[0]["detail"]


def test_an_impossible_timeout_is_contained(exported, model):
    out, _ = exported
    checks = reimport_check(out / STEP_NAME, model, timeout_s=0.001)
    assert any(not c["passed"] for c in checks)
    assert any("timeout" in c["detail"] or "exceeded" in c["detail"] for c in checks)


def test_expectation_must_be_a_part_map(exported):
    out, _ = exported
    with pytest.raises(TypeError):
        reimport_check(out / STEP_NAME, {"not": "a part map"})
