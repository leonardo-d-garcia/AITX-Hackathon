"""Aero bookkeeping, JSON finiteness, fidelity comparison, hash stability."""

from __future__ import annotations

import json
import math

import pytest

from evaluate import FidelityMismatch, compare_evaluations, evaluate_revision

from tests.physics.aircraft import (
    default_mission,
    default_parts,
    fidelity_of,
    geometry_hash_of,
    metric,
    vtail_geometry,
)


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
