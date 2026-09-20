"""C4 geometry unwrap. No live OpenVSP import required."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from evaluate.hashing import geometry_hash as evaluate_geometry_hash
from openvsp_worker import generate_and_sweep
from openvsp_worker.geometry import (
    ALPHAS_DEG,
    GeometryError,
    claim_value,
    frd_xyz_to_openvsp,
    geometry_hash,
    load_spec,
    require_float,
)
from openvsp_worker.report import format_validation_markdown

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "c"
    / "synthetic_vtail_demo"
    / "geometry_features.json"
)


def _geometry() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_unwrap_claim_value() -> None:
    claim = {
        "value": 0.4,
        "unit": "m2",
        "status": "known",
        "source_kind": "assumed",
        "evidence_ids": [],
        "assumptions": [],
    }
    assert claim_value(claim, "reference.S_m2") == 0.4
    assert require_float(claim, "reference.S_m2") == pytest.approx(0.4)
    with pytest.raises(GeometryError, match="unknown"):
        claim_value(
            {
                "value": None,
                "unit": "m",
                "status": "unknown",
                "source_kind": "assumed",
                "evidence_ids": [],
                "assumptions": ["missing"],
            },
            "np_x_m",
        )


def test_fixture_spec_does_not_invent_reference_or_cant() -> None:
    spec = load_spec(_geometry())
    assert spec.sref_m2 == pytest.approx(0.40)
    assert spec.bref_m == pytest.approx(2.20)
    assert spec.cref_m == pytest.approx(0.20)
    assert spec.cant_rad == pytest.approx(0.6981317007977318)
    assert spec.cant_deg == pytest.approx(math.degrees(0.6981317007977318))
    assert spec.panel_area_m2 == pytest.approx(0.05)
    assert spec.panel_span_m == pytest.approx(0.35)
    assert spec.panel_chord_m == pytest.approx(0.05 / 0.35)
    assert spec.tail_arm_m == pytest.approx(0.85)
    assert spec.vinf_mps == pytest.approx(15.0)
    assert spec.rho_kgm3 == pytest.approx(1.225)
    assert spec.altitude_m == pytest.approx(120.0)
    assert spec.alphas_deg == ALPHAS_DEG
    assert spec.symmetry == "openvsp_SYM_XZ"
    assert spec.stations[0].y_m == pytest.approx(0.0)
    assert spec.stations[-1].y_m == pytest.approx(1.1)
    assert spec.stations[0].x_le_frd_m == pytest.approx(-0.15)
    assert spec.stations[0].x_le_vsp_m == pytest.approx(0.15)
    assert spec.stations[-1].twist_rad == pytest.approx(-0.04)
    assert spec.sections[0].root_chord_m == pytest.approx(0.28)
    assert spec.sections[-1].tip_chord_m == pytest.approx(0.14)


def test_frd_to_openvsp_axes() -> None:
    x, y, z = frd_xyz_to_openvsp(-0.15, 0.3, 0.01)
    assert x == pytest.approx(0.15)
    assert y == pytest.approx(0.3)
    assert z == pytest.approx(-0.01)


def test_missing_cant_fails(tmp_path: Path) -> None:
    geo = _geometry()
    geo["tail"]["cant_rad"] = {
        "value": None,
        "unit": "rad",
        "status": "unknown",
        "source_kind": "assumed",
        "evidence_ids": [],
        "assumptions": ["missing"],
    }
    with pytest.raises(GeometryError, match="cant_rad"):
        load_spec(geo)
    geo_path = tmp_path / "geometry_features.json"
    geo_path.write_text(json.dumps(geo), encoding="utf-8")
    result = generate_and_sweep(geo_path, tmp_path / "out", write_docs=False)
    assert result["CL"] == []
    assert result["CDi"] == []
    assert result["validation"]["all_passed"] is False
    assert "cant_rad" in str(result.get("error"))


def test_geometry_hash_matches_evaluate() -> None:
    geo = _geometry()
    assert geometry_hash(geo) == evaluate_geometry_hash(geo)
    assert len(geometry_hash(geo)) == 64


def test_committed_c4_summary_has_finite_polar() -> None:
    summary_path = Path(__file__).resolve().parents[1] / "docs" / "openvsp-c4-sweep-summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    geo = _geometry()
    assert summary["geometry_hash"] == evaluate_geometry_hash(geo)
    assert summary["Sref"] == pytest.approx(0.40)
    assert summary["bref"] == pytest.approx(2.20)
    assert summary["cref"] == pytest.approx(0.20)
    assert summary["alphas_deg"] == [-2.0, 0.0, 2.0, 4.0, 6.0]
    assert len(summary["CL"]) == 5
    assert len(summary["CDi"]) == 5
    assert all(math.isfinite(x) for x in summary["CL"])
    assert all(math.isfinite(x) for x in summary["CDi"])
    slopes = [
        (summary["CL"][i + 1] - summary["CL"][i])
        / (summary["alphas_deg"][i + 1] - summary["alphas_deg"][i])
        for i in range(4)
    ]
    assert all(s > 0 for s in slopes)
    assert summary["validation"]["all_passed"] is True
    from evaluate.physics import extract_solver_cl_cdi

    cl, cdi = extract_solver_cl_cdi(summary, 0.20)
    assert cl is not None and cdi is not None
    assert math.isfinite(cl) and math.isfinite(cdi)


def test_validation_markdown_table_contains_fail_on_generate_error() -> None:
    md = format_validation_markdown(
        {
            "error": "boom",
            "versions": {"openvsp": "OpenVSP 3.51.3"},
            "validation": {
                "all_passed": False,
                "checks": [{"name": "generate", "pass": False, "numbers": "boom"}],
            },
        }
    )
    assert "| check | result | numbers |" in md
    assert "| generate | FAIL | boom |" in md
