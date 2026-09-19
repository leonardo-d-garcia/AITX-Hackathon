"""C2: V-tail projections vs conventional volume heuristics."""

from __future__ import annotations

from evaluate import evaluate_revision

from tests.physics.aircraft import (
    all_missing_fields,
    check_by_id,
    conventional_geometry,
    default_mission,
    default_parts,
    vtail_geometry,
)


def test_vtail_reaches_verdict_without_conventional_heuristic_fail():
    result = evaluate_revision(vtail_geometry(), default_parts(), default_mission())
    assert result["revision_id"]
    assert len(result["checks"]) == 14
    h = check_by_id(result, "tail_volume_h")
    v = check_by_id(result, "tail_volume_v")
    assert h["status"] == "not_applicable"
    assert v["status"] == "not_applicable"
    for item in result["checks"]:
        if item["id"] in {"tail_volume_h", "tail_volume_v"}:
            assert item["status"] != "fail"


def test_conventional_tail_runs_volume_heuristics():
    result = evaluate_revision(conventional_geometry(), default_parts(), default_mission())
    h = check_by_id(result, "tail_volume_h")
    v = check_by_id(result, "tail_volume_v")
    assert h["status"] in {"pass", "fail"}
    assert v["status"] in {"pass", "fail"}
    assert h["status"] != "not_applicable"
    assert v["status"] != "not_applicable"


def test_vtail_missing_cant_rad_unknown():
    geo = vtail_geometry()
    del geo["vtail"]["cant_rad"]
    result = evaluate_revision(geo, default_parts(), default_mission())
    h = check_by_id(result, "tail_volume_h")
    v = check_by_id(result, "tail_volume_v")
    assert h["status"] == "unknown"
    assert v["status"] == "unknown"
    assert "vtail.cant_rad" in all_missing_fields(result)
