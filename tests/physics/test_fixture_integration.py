from __future__ import annotations

import json
from pathlib import Path

from contracts import validate_instance
from evaluate import evaluate_revision

from tests.physics.aircraft import check_by_id, fidelity_of

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, folder: str) -> dict:
    path = ROOT / "fixtures" / "c" / folder / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_synthetic_vtail_fixture_evaluates():
    geometry = _load("geometry_features.json", "synthetic_vtail_demo")
    parts = _load("parts.json", "synthetic_vtail_demo")
    result = evaluate_revision(geometry, parts)
    assert fidelity_of(result) == "analytic" or result.get("meta", {}).get("fidelity_tier") == "analytic"
    mass = result["metrics"]["mass"]
    assert mass["value"] is not None and mass["value"] > 0
    cg = result["metrics"]["cg"]
    assert cg["status"] != "unknown"
    assert check_by_id(result, "tail_volume_h")["status"] == "not_applicable"
    assert check_by_id(result, "tail_volume_v")["status"] == "not_applicable"
    dumped = json.dumps(result)
    assert "NaN" not in dumped and "Infinity" not in dumped


def test_synthetic_vtail_evaluation_validates_against_contract():
    geometry = _load("geometry_features.json", "synthetic_vtail_demo")
    parts = _load("parts.json", "synthetic_vtail_demo")
    manifest = _load("design_manifest.json", "synthetic_vtail_demo")
    result = evaluate_revision(geometry, parts, design_manifest=manifest)
    validate_instance("evaluation", result)


def test_conventional_fixture_runs_tail_heuristics():
    geometry = _load("geometry_features.json", "conventional_tail_demo")
    parts = _load("parts.json", "conventional_tail_demo")
    result = evaluate_revision(geometry, parts)
    assert check_by_id(result, "tail_volume_h")["status"] != "not_applicable"
    assert check_by_id(result, "tail_volume_v")["status"] != "not_applicable"
