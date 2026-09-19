from __future__ import annotations

import json
from pathlib import Path

from evaluate import evaluate_revision

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, folder: str) -> dict:
    path = ROOT / "fixtures" / "c" / folder / name
    return json.loads(path.read_text(encoding="utf-8"))


def test_synthetic_vtail_fixture_evaluates():
    geometry = _load("geometry_features.json", "synthetic_vtail_demo")
    parts = _load("parts.json", "synthetic_vtail_demo")
    result = evaluate_revision(geometry, parts)
    assert result["fidelity_tier"] == "analytic"
    mass = result["metrics"]["mass"]
    assert mass["value"] is not None and mass["value"] > 0
    cg = result["metrics"]["cg"]
    assert cg["status"] != "unknown"
    checks = {c["id"]: c["status"] for c in result["checks"]}
    assert checks["tail_volume_h"] == "not_applicable"
    assert checks["tail_volume_v"] == "not_applicable"
    dumped = json.dumps(result)
    assert "NaN" not in dumped and "Infinity" not in dumped


def test_conventional_fixture_runs_tail_heuristics():
    geometry = _load("geometry_features.json", "conventional_tail_demo")
    parts = _load("parts.json", "conventional_tail_demo")
    result = evaluate_revision(geometry, parts)
    checks = {c["id"]: c["status"] for c in result["checks"]}
    assert checks["tail_volume_h"] != "not_applicable"
    assert checks["tail_volume_v"] != "not_applicable"
