"""Titan print-archive CAD: occurrence plan, frames, inventory triangle count."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from cad.titan_archive import (
    EXCLUDED,
    convert_archive,
    expected_triangle_count,
    extract_zip,
    find_archive_zip,
    inventory_by_path,
    native_mm_to_frd_m,
    native_mm_to_gltf_m,
    occurrence_plan,
)


def _require_trimesh_and_zip() -> Path:
    pytest.importorskip("trimesh")
    try:
        return find_archive_zip()
    except FileNotFoundError:
        pytest.skip("Titan print-archive zip missing")


def test_occurrence_plan_yields_30_unique_part_ids() -> None:
    rows = occurrence_plan()
    part_ids = [part_id for _stl, part_id, _mirror in rows]
    assert len(rows) == 30
    assert len(set(part_ids)) == 30
    assert len(part_ids) == 30


def test_expected_triangle_count_from_inventory_baseline() -> None:
    """Baseline is fuse3_clean + wing3_12mm_hole, not the runbook's 607558 (fuse3)."""
    by_path = inventory_by_path()
    computed = 0
    stems: list[str] = []
    for stl, _part_id, _mirror in occurrence_plan():
        computed += int(by_path[stl]["tris"])
        stems.append(Path(stl).stem)

    assert "fuse3_clean" in stems
    assert "wing3_12mm_hole" in stems
    assert "fuse3" not in stems
    assert computed == expected_triangle_count(by_path)
    assert computed != 607558

    fuse3_tris = int(by_path["Fuselage/fuse3.stl"]["tris"])
    fuse3_clean_tris = int(by_path["Fuselage/fuse3_clean.stl"]["tris"])
    runbook_accidental = computed - fuse3_clean_tris + fuse3_tris
    assert runbook_accidental == 607558


def test_native_mm_to_gltf_m_datum_point() -> None:
    out = native_mm_to_gltf_m(np.array([[1000.0, 55.0, 0.0]], dtype=np.float64))
    assert out[0, 0] == pytest.approx(-1.0)
    assert out[0, 1] == pytest.approx(0.0)
    assert out[0, 2] == pytest.approx(0.0)


def test_native_mm_to_frd_m_left_wing_is_negative_y() -> None:
    # +native X is left; FRD Y is right, so native (1000, 55, 0) -> FRD (0, -1, 0).
    assert native_mm_to_frd_m(1000.0, 55.0, 0.0) == pytest.approx((0.0, -1.0, 0.0))


def test_excluded_variants_not_in_baseline_occurrence_plan() -> None:
    stems = {Path(stl).stem for stl, _part_id, _mirror in occurrence_plan()}
    for name in EXCLUDED:
        assert name not in stems


def test_convert_archive_baseline_scene(tmp_path: Path) -> None:
    zip_path = _require_trimesh_and_zip()
    stl_root = tmp_path / "stl"
    extract_zip(zip_path, stl_root)
    dest = tmp_path / "titan.glb"
    report = convert_archive(zip_path, dest_glb=dest, stl_root=stl_root)

    assert report["node_count"] == 30
    assert report["span_m"] == pytest.approx(2.2245, abs=0.05)
    assert report["length_m"] == pytest.approx(0.9913, abs=0.08)

    canopy = [p for p in report["parts"] if str(p["part_id"]).startswith("canopy")]
    fuse = [p for p in report["parts"] if str(p["part_id"]).startswith("fuse_")]
    assert canopy and fuse
    canopy_y_max = max(float(p["bounds_m"][1][1]) for p in canopy)
    fuse_y_min = min(float(p["bounds_m"][0][1]) for p in fuse)
    fuse_y_max = max(float(p["bounds_m"][1][1]) for p in fuse)
    fuse_y_mid = 0.5 * (fuse_y_min + fuse_y_max)
    assert canopy_y_max > fuse_y_mid
