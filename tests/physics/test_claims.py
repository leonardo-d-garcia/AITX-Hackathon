"""C1: unknown, quarantine, assumption ranges."""

from __future__ import annotations

from evaluate import evaluate_revision, quarantine_input

from tests.physics.aircraft import (
    check_by_id,
    default_mission,
    default_parts,
    metric,
    vtail_geometry,
)


def test_null_battery_mass_cg_unknown_not_zero():
    parts = default_parts(battery_mass_kg=None)
    result = evaluate_revision(vtail_geometry(), parts, default_mission())
    cg = metric(result, "cg")
    assert cg["status"] == "unknown"
    assert cg["value"] is None
    assert cg["value"] != 0
    assert cg["value"] != 0.0
    assert cg["value"] != [0, 0, 0]
    for check_id in ("stall", "climb", "spar"):
        assert check_by_id(result, check_id)["status"] == "unknown"
    endurance = metric(result, "endurance")
    assert endurance["status"] == "unknown"


def test_battery_energy_quarantined_not_clamped():
    parts = default_parts(battery_energy_wh=500.0)
    energy_before = parts[7]["specs"]["energy_wh"]
    result = evaluate_revision(vtail_geometry(), parts, default_mission())
    assert parts[7]["specs"]["energy_wh"] == energy_before == 500.0
    energy = metric(result, "battery_energy_wh")
    assert energy["value"] == 500.0
    assert energy["status"] == "conflicted"
    assert energy["value"] != 200
    quarantined_values = [q.get("value") for q in result.get("quarantined") or []]
    quarantined_values.extend(q.get("raw") for q in result.get("quarantine") or [])
    assert 500.0 in quarantined_values or energy["value"] == 500.0
    q = quarantine_input(500.0, field="parts.battery.specs.energy_wh", reason="over limit", unit="Wh")
    assert q.status == "conflicted"
    assert q.value == 500.0


def test_assumption_range_ordered():
    result = evaluate_revision(vtail_geometry(), default_parts(), default_mission())
    mass = metric(result, "mass")
    endurance = metric(result, "endurance")
    rng = mass.get("assumption_range") or endurance.get("assumption_range")
    assert rng is not None
    assert rng["low"] <= rng["nominal"] <= rng["high"]
