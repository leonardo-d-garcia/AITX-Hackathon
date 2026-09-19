"""Aero bookkeeping, JSON finiteness, fidelity comparison, hash stability."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from evaluate import FidelityMismatch, compare_evaluations, evaluate_revision, load_solver_result
from evaluate.hashing import geometry_hash
from evaluate.physics import extract_solver_cl_cdi
from tests.physics.aircraft import (
    check_by_id,
    default_mission,
    default_parts,
    fidelity_of,
    geometry_hash_of,
    metric,
    vtail_geometry,
)

ROOT = Path(__file__).resolve().parents[2]
C4_SWEEP = ROOT / "docs" / "openvsp-c4-sweep-summary.json"
C4_HASH = "f0d361e699ec0a56c4664ac82a5489be8708a0a6c52a2bdca77909690a25ce1c"
FIXTURE_GEO = ROOT / "fixtures" / "c" / "synthetic_vtail_demo" / "geometry_features.json"
FIXTURE_PARTS = ROOT / "fixtures" / "c" / "synthetic_vtail_demo" / "parts.json"


def _linear_at(xs: list[float], ys: list[float], x: float) -> float:
    pairs = sorted(zip(xs, ys, strict=True), key=lambda p: p[0])
    xs_s = [p[0] for p in pairs]
    ys_s = [p[1] for p in pairs]
    if x <= xs_s[0]:
        return ys_s[0]
    if x >= xs_s[-1]:
        return ys_s[-1]
    for i in range(1, len(xs_s)):
        if xs_s[i] >= x:
            span = xs_s[i] - xs_s[i - 1]
            if span == 0:
                return ys_s[i]
            t = (x - xs_s[i - 1]) / span
            return ys_s[i - 1] + t * (ys_s[i] - ys_s[i - 1])
    return ys_s[-1]


def _walk_numbers(obj, found: list) -> None:
    if isinstance(obj, dict):
        for v in obj.values():
            _walk_numbers(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk_numbers(v, found)
    elif isinstance(obj, float):
        found.append(obj)


def test_json_dump_has_no_nan_or_inf():
    result = evaluate_revision(vtail_geometry(), default_parts(), default_mission())
    dumped = json.dumps(result, allow_nan=False)
    assert "NaN" not in dumped
    assert "Infinity" not in dumped
    assert "-Infinity" not in dumped
    numbers: list[float] = []
    _walk_numbers(result, numbers)
    assert numbers
    assert all(math.isfinite(x) for x in numbers)


def test_induced_drag_not_double_counted():
    result = evaluate_revision(vtail_geometry(), default_parts(), default_mission())
    cl = metric(result, "CL")["value"]
    k = metric(result, "k")["value"]
    cdi = metric(result, "CD_induced")["value"]
    cdp = metric(result, "CD_profile")["value"]
    cdf = metric(result, "CD_fuselage")["value"]
    cdn = metric(result, "CD_interference")["value"]
    cd = metric(result, "CD")["value"]
    assert cl is not None and k is not None
    assert cdi == pytest.approx(k * cl * cl)
    assert cd == pytest.approx(cdp + cdf + cdn + cdi)
    assert cd != pytest.approx(cdp + cdf + cdn + 2.0 * cdi)


def test_compare_evaluations_raises_fidelity_mismatch():
    geo = vtail_geometry()
    parts = default_parts()
    mission = default_mission()
    analytic = evaluate_revision(geo, parts, mission)
    assert fidelity_of(analytic) == "analytic"
    solver = {
        "geometry_hash": geometry_hash_of(analytic),
        "CL": 0.50,
        "CDi": 0.010,
        "versions": {"vspaero": "test"},
    }
    vspaero = evaluate_revision(geo, parts, mission, solver_result=solver)
    assert fidelity_of(vspaero) == "vspaero"
    with pytest.raises(FidelityMismatch):
        compare_evaluations(analytic, vspaero)


def test_geometry_hash_stable():
    geo_a = vtail_geometry()
    geo_b = {
        "spar": geo_a["spar"],
        "aero": geo_a["aero"],
        "vtail": geo_a["vtail"],
        "reference": geo_a["reference"],
        "source_kind": geo_a["source_kind"],
        "revision_id": geo_a["revision_id"],
    }
    a = evaluate_revision(geo_a, default_parts(), default_mission())
    b = evaluate_revision(geo_b, default_parts(), default_mission())
    assert geometry_hash_of(a) == geometry_hash_of(b)
    assert len(geometry_hash_of(a) or "") == 64
    again = evaluate_revision(geo_a, default_parts(), default_mission())
    assert geometry_hash_of(again) == geometry_hash_of(a)


def test_solver_induced_drag_from_polar_not_double_counted():
    """Analytic CDi is k*CL^2; solver CDi is polar interpolation. Not a factor of two."""
    geo = vtail_geometry()
    parts = default_parts()
    mission = default_mission()
    analytic = evaluate_revision(geo, parts, mission)
    cl_a = metric(analytic, "CL")["value"]
    k = metric(analytic, "k")["value"]
    cdi_a = metric(analytic, "CD_induced")["value"]
    assert cl_a is not None and k is not None and cdi_a is not None
    assert cdi_a == pytest.approx(k * cl_a * cl_a)

    polar = [
        {"alpha_deg": 0.0, "alpha_rad": 0.0, "CL": 0.0, "CDi": 0.001},
        {"alpha_deg": 4.0, "alpha_rad": 0.06981317007977318, "CL": 0.40, "CDi": 0.020},
        {"alpha_deg": 8.0, "alpha_rad": 0.13962634015954636, "CL": 0.80, "CDi": 0.050},
    ]
    solver = {
        "geometry_hash": geometry_hash_of(analytic),
        "polar": polar,
        "versions": {"vspaero": "test"},
    }
    vsp = evaluate_revision(geo, parts, mission, solver_result=solver)
    assert fidelity_of(vsp) == "vspaero"
    cl_s = metric(vsp, "CL")["value"]
    cdi_s = metric(vsp, "CD_induced")["value"]
    k_s = metric(vsp, "k")["value"]
    cdp = metric(vsp, "CD_profile")["value"]
    cdf = metric(vsp, "CD_fuselage")["value"]
    cdn = metric(vsp, "CD_interference")["value"]
    cd = metric(vsp, "CD")["value"]
    assert cl_s is not None and cdi_s is not None and k_s is not None
    expected_cdi = _linear_at([p["CL"] for p in polar], [p["CDi"] for p in polar], cl_s)
    assert cdi_s == pytest.approx(expected_cdi)
    analytic_at_same_cl = k_s * cl_s * cl_s
    assert cdi_s != pytest.approx(analytic_at_same_cl)
    assert cdi_s != pytest.approx(2.0 * cdi_a)
    assert cdi_a != pytest.approx(2.0 * cdi_s)
    assert cd == pytest.approx(cdp + cdf + cdn + cdi_s)
    assert cd != pytest.approx(cdp + cdf + cdn + cdi_s + analytic_at_same_cl)
    assert cdp == pytest.approx(metric(analytic, "CD_profile")["value"])
    assert cdf == pytest.approx(metric(analytic, "CD_fuselage")["value"])
    assert cdn == pytest.approx(metric(analytic, "CD_interference")["value"])


def test_fidelity_vspaero_only_when_solver_hash_matches():
    geo = vtail_geometry()
    parts = default_parts()
    mission = default_mission()
    analytic = evaluate_revision(geo, parts, mission)
    assert fidelity_of(analytic) == "analytic"
    matched = {
        "geometry_hash": geometry_hash_of(analytic),
        "CL": 0.45,
        "CDi": 0.012,
        "versions": {"vspaero": "test"},
    }
    vsp = evaluate_revision(geo, parts, mission, solver_result=matched)
    assert fidelity_of(vsp) == "vspaero"


def test_mismatched_hash_stays_analytic():
    geo = vtail_geometry()
    parts = default_parts()
    mission = default_mission()
    analytic = evaluate_revision(geo, parts, mission)
    cl = metric(analytic, "CL")["value"]
    k = metric(analytic, "k")["value"]
    mismatched = {
        "geometry_hash": "deadbeef" * 8,
        "polar": [
            {"alpha_deg": 2.0, "CL": 0.2, "CDi": 0.02},
            {"alpha_deg": 4.0, "CL": 0.5, "CDi": 0.05},
        ],
        "versions": {"vspaero": "test"},
    }
    result = evaluate_revision(geo, parts, mission, solver_result=mismatched)
    assert fidelity_of(result) == "analytic"
    assert metric(result, "CD_induced")["value"] == pytest.approx(k * cl * cl)


def test_static_margin_unknown_with_solver_result():
    geo = vtail_geometry()
    parts = default_parts()
    mission = default_mission()
    analytic = evaluate_revision(geo, parts, mission)
    solver = {
        "geometry_hash": geometry_hash_of(analytic),
        "CL": 0.45,
        "CDi": 0.012,
        "versions": {"vspaero": "test"},
    }
    vsp = evaluate_revision(geo, parts, mission, solver_result=solver)
    assert fidelity_of(vsp) == "vspaero"
    sm = metric(vsp, "static_margin")
    assert sm["status"] == "unknown"
    assert sm["value"] is None
    assert check_by_id(vsp, "static_margin")["status"] == "unknown"


def test_c4_json_and_fixture_are_vspaero_with_finite_cdi():
    geo = json.loads(FIXTURE_GEO.read_text(encoding="utf-8"))
    parts = json.loads(FIXTURE_PARTS.read_text(encoding="utf-8"))
    assert geometry_hash(geo) == C4_HASH
    solver = load_solver_result(C4_SWEEP, geometry=geo)
    assert solver["geometry_hash"] == C4_HASH
    analytic = evaluate_revision(geo, parts)
    vsp = evaluate_revision(geo, parts, solver_result=solver)
    assert fidelity_of(analytic) == "analytic"
    assert fidelity_of(vsp) == "vspaero"
    assert geometry_hash_of(vsp) == C4_HASH
    cdi = metric(vsp, "CD_induced")
    assert cdi["value"] is not None
    assert math.isfinite(cdi["value"])
    cl = metric(vsp, "CL")["value"]
    k = metric(vsp, "k")["value"]
    cdp = metric(vsp, "CD_profile")["value"]
    cdf = metric(vsp, "CD_fuselage")["value"]
    cdn = metric(vsp, "CD_interference")["value"]
    cd = metric(vsp, "CD")["value"]
    assert cl is not None and k is not None
    polar_cls = [row["CL"] for row in solver["polar"]]
    polar_cdis = [row["CDi"] for row in solver["polar"]]
    polar_cdi = _linear_at(polar_cls, polar_cdis, cl)
    assert cdi["value"] == pytest.approx(polar_cdi)
    _, extracted_cdi = extract_solver_cl_cdi(solver, cl)
    assert extracted_cdi == pytest.approx(polar_cdi)
    assert cdi["value"] != pytest.approx(k * cl * cl)
    assert cdi["value"] != pytest.approx(2.0 * metric(analytic, "CD_induced")["value"])
    assert cd == pytest.approx(cdp + cdf + cdn + cdi["value"])
    assert cd != pytest.approx(cdp + cdf + cdn + cdi["value"] + k * cl * cl)
    sm = metric(vsp, "static_margin")
    assert sm["status"] == "unknown"
    assert sm["value"] is None
    assert check_by_id(vsp, "static_margin")["status"] == "unknown"
    with pytest.raises(FidelityMismatch):
        compare_evaluations(analytic, vsp)
    dumped = json.dumps(vsp, allow_nan=False)
    assert "NaN" not in dumped
    assert "Infinity" not in dumped
