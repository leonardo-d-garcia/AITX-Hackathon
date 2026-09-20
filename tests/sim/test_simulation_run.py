"""U0 telemetry contract tests for simulation_run.json."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

import pytest

from sim import (
    SimulationRunError,
    simulate_mission,
    validate_simulation_run,
    write_simulation_run,
)

SYNTHETIC_GEOMETRY = {
    "S": 0.4,
    "b": 2.2,
    "c": 0.2,
    "cant": 0.6981317007977318,
}
SYNTHETIC_PARTS = [{"id": "spar_L", "type": "spar"}]

FRAME_KEYS = (
    "t",
    "pos_ned",
    "quat",
    "Va",
    "alpha",
    "beta",
    "load_factor_n",
    "power_w",
    "energy_wh_remaining",
)
DT_TOL = 1e-9
QUAT_UNIT_TOL = 1e-6
PACK_WH = 88.0
RESERVE_FRACTION = 0.2
USABLE_WH = PACK_WH * (1.0 - RESERVE_FRACTION)


def _finite_walk(value: object) -> None:
    if isinstance(value, dict):
        for item in value.values():
            _finite_walk(item)
        return
    if isinstance(value, list):
        for item in value:
            _finite_walk(item)
        return
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        assert math.isfinite(value)


def _roll_from_quat(quat: list[float]) -> float:
    """3-2-1 roll. Positive about FRD +x is right-wing-down."""
    w, x, y, z = quat
    return math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))


def test_fallback_file_exists(fallback_path: Path) -> None:
    assert fallback_path.is_file()


@pytest.mark.parametrize("run_name", ["fallback_run", "live_run"])
def test_schema_required_keys(run_name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(run_name)
    assert set(run) >= {"meta", "frames", "part_stress"}
    meta = run["meta"]
    for key in (
        "revision_id",
        "geometry_hash",
        "fidelity_tier",
        "solver_versions",
        "assumptions",
        "dt_s",
    ):
        assert key in meta
    assert run["frames"], "frames must be non-empty"
    for frame in run["frames"]:
        for key in FRAME_KEYS:
            assert key in frame
    assert "spar_L" in run["part_stress"]
    samples = run["part_stress"]["spar_L"]
    assert samples
    stations = {sample["station_m"] for sample in samples}
    assert 0.0 in stations
    assert len(stations) >= 2
    for sample in samples:
        assert {"t", "sigma_mpa", "station_m"} <= set(sample)


@pytest.mark.parametrize("run_name", ["fallback_run", "live_run"])
def test_time_monotonic_and_dt(run_name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(run_name)
    dt_s = run["meta"]["dt_s"]
    times = [frame["t"] for frame in run["frames"]]
    assert times[0] == pytest.approx(0.0, abs=DT_TOL)
    for prev, curr in zip(times, times[1:]):
        assert curr >= prev
        assert abs((curr - prev) - dt_s) <= DT_TOL


@pytest.mark.parametrize("run_name", ["fallback_run", "live_run"])
def test_energy_never_below_zero(run_name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(run_name)
    energies = [frame["energy_wh_remaining"] for frame in run["frames"]]
    assert all(energy >= 0.0 for energy in energies)
    for prev, curr, prev_frame in zip(energies, energies[1:], run["frames"]):
        if prev_frame["power_w"] > 0.0:
            assert curr < prev


@pytest.mark.parametrize("run_name", ["fallback_run", "live_run"])
def test_energy_is_net_of_reserve(run_name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(run_name)
    first = run["frames"][0]["energy_wh_remaining"]
    assert first == pytest.approx(USABLE_WH)
    assert first < PACK_WH
    assert first == pytest.approx(PACK_WH * (1.0 - RESERVE_FRACTION))


def test_fallback_duration_and_load_factor(fallback_run: dict) -> None:
    dt_s = fallback_run["meta"]["dt_s"]
    last_t = fallback_run["frames"][-1]["t"]
    assert last_t >= 60.0 - dt_s
    assert any(frame["load_factor_n"] > 1.0 for frame in fallback_run["frames"])


def test_right_turn_banks_right(fallback_run: dict) -> None:
    """Commanded right turn must bank right-wing-down.

    Encoding: NED world, FRD body, scalar-first quat (w, x, y, z), 3-2-1
    yaw-pitch-roll. Positive roll about FRD +x is right-wing-down. A
    coordinated right turn therefore has phi>0, quat x>0 at heading north,
    increasing yaw (north toward east), and pos_ned east (index 1) > 0.
    """
    turn = [frame for frame in fallback_run["frames"] if 30.0 <= frame["t"] < 50.0]
    assert turn, "expected a 30-50 s right-turn segment"
    first = turn[0]
    rolls = [_roll_from_quat(frame["quat"]) for frame in turn]
    assert first["quat"][1] > 0.0
    assert all(phi > 0.2 for phi in rolls)
    assert abs(sum(rolls) / len(rolls) - math.radians(30.0)) < 0.05
    assert all(frame["load_factor_n"] > 1.0 for frame in turn)
    expected_n = 1.0 / math.cos(math.radians(30.0))
    assert abs(turn[len(turn) // 2]["load_factor_n"] - expected_n) < 1e-6
    assert turn[-1]["pos_ned"][1] > 1.0
    dn = turn[1]["pos_ned"][0] - turn[0]["pos_ned"][0]
    de = turn[1]["pos_ned"][1] - turn[0]["pos_ned"][1]
    heading_rate_sign = math.atan2(de, dn)
    assert heading_rate_sign > 0.0


@pytest.mark.parametrize("run_name", ["fallback_run", "live_run"])
def test_quat_nearly_unit_length(run_name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(run_name)
    for frame in run["frames"]:
        w, x, y, z = frame["quat"]
        assert abs(w * w + x * x + y * y + z * z - 1.0) < QUAT_UNIT_TOL


@pytest.mark.parametrize("run_name", ["fallback_run", "live_run"])
def test_no_nan_inf(run_name: str, request: pytest.FixtureRequest) -> None:
    run = request.getfixturevalue(run_name)
    _finite_walk(run)


def test_validate_simulation_run_on_committed_file(fallback_run: dict) -> None:
    validate_simulation_run(fallback_run)


def test_validate_rejects_negative_energy(fallback_run: dict) -> None:
    bad = copy.deepcopy(fallback_run)
    bad["frames"][10]["energy_wh_remaining"] = -0.1
    with pytest.raises(SimulationRunError, match="negative"):
        validate_simulation_run(bad)


def test_validate_rejects_time_regression(fallback_run: dict) -> None:
    bad = copy.deepcopy(fallback_run)
    bad["frames"][3]["t"] = bad["frames"][2]["t"] - 0.01
    with pytest.raises(SimulationRunError, match="monotonic"):
        validate_simulation_run(bad)


def test_geometry_hash_is_canonical_synthetic_reference(fallback_run: dict) -> None:
    canonical = json.dumps(
        {"S": 0.4, "b": 2.2, "c": 0.2, "cant": 0.6981317007977318},
        sort_keys=True,
        separators=(",", ":"),
    )
    expected = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert fallback_run["meta"]["geometry_hash"] == expected
    assert fallback_run["meta"]["fidelity_tier"] == "analytic"
    assert fallback_run["meta"]["solver_versions"]["openvsp"] is None
    assert fallback_run["meta"]["solver_versions"]["vspaero"] is None
    assert fallback_run["meta"]["dt_s"] == pytest.approx(0.02)


def test_fallback_matches_simulate_mission(fallback_run: dict, live_run: dict) -> None:
    assert len(fallback_run["frames"]) == len(live_run["frames"])
    assert fallback_run["meta"]["geometry_hash"] == live_run["meta"]["geometry_hash"]
    assert fallback_run["frames"][0]["energy_wh_remaining"] == pytest.approx(
        live_run["frames"][0]["energy_wh_remaining"]
    )


def test_energy_halt_does_not_clamp_and_continue() -> None:
    run = simulate_mission(
        SYNTHETIC_GEOMETRY,
        SYNTHETIC_PARTS,
        route={"pack_wh": 0.05, "reserve_fraction": 0.0, "duration_s": 60.0},
    )
    energies = [frame["energy_wh_remaining"] for frame in run["frames"]]
    assert energies[-1] == 0.0
    assert all(energy > 0.0 for energy in energies[:-1])
    assert run["frames"][-1]["t"] < 60.0 - 1e-9
    validate_simulation_run(run)


def test_write_simulation_run_roundtrip(tmp_path: Path, live_run: dict) -> None:
    path = tmp_path / "simulation_run.json"
    write_simulation_run(path, live_run)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    validate_simulation_run(loaded)


def test_sim_has_no_module_level_wing_constants() -> None:
    import sim.mission as mission

    for name in ("S", "b", "c", "SPAN", "WING_S", "WING_B"):
        assert not hasattr(mission, name)
