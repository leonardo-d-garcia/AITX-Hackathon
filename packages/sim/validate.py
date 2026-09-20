"""Schema / monotonic / energy checks for simulation_run.json."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

_TOP_KEYS = ("meta", "frames", "part_stress")
_META_KEYS = (
    "revision_id",
    "geometry_hash",
    "fidelity_tier",
    "solver_versions",
    "assumptions",
    "dt_s",
)
_FRAME_KEYS = (
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
_STRESS_KEYS = ("t", "sigma_mpa", "station_m")
_FIDELITY = {"analytic", "vspaero"}
_DT_TOL = 1e-9
_QUAT_UNIT_TOL = 1e-6


class SimulationRunError(ValueError):
    """Invalid simulation_run payload."""


def validate_simulation_run(run: Mapping[str, Any]) -> None:
    if not isinstance(run, Mapping):
        raise SimulationRunError("simulation_run must be an object")
    for key in _TOP_KEYS:
        if key not in run:
            raise SimulationRunError(f"missing required key {key!r}")

    meta = run["meta"]
    frames = run["frames"]
    part_stress = run["part_stress"]
    if not isinstance(meta, Mapping):
        raise SimulationRunError("meta must be an object")
    for key in _META_KEYS:
        if key not in meta:
            raise SimulationRunError(f"meta missing {key!r}")
    if meta["fidelity_tier"] not in _FIDELITY:
        raise SimulationRunError("meta.fidelity_tier must be analytic or vspaero")
    geometry_hash = meta["geometry_hash"]
    if not isinstance(geometry_hash, str) or not geometry_hash.startswith("sha256:"):
        raise SimulationRunError("meta.geometry_hash must be a sha256:... string")
    if not isinstance(meta["assumptions"], list) or not meta["assumptions"]:
        raise SimulationRunError("meta.assumptions must be a non-empty list")
    solvers = meta["solver_versions"]
    if not isinstance(solvers, Mapping) or "openvsp" not in solvers or "vspaero" not in solvers:
        raise SimulationRunError("meta.solver_versions must include openvsp and vspaero")
    dt_s = _finite_number(meta["dt_s"], "meta.dt_s")
    if dt_s <= 0.0:
        raise SimulationRunError("meta.dt_s must be positive")

    if not isinstance(frames, list) or not frames:
        raise SimulationRunError("frames must be a non-empty list")

    prev_t: float | None = None
    prev_energy: float | None = None
    prev_power: float | None = None
    n_frames = len(frames)
    for i, frame in enumerate(frames):
        if not isinstance(frame, Mapping):
            raise SimulationRunError(f"frames[{i}] must be an object")
        for key in _FRAME_KEYS:
            if key not in frame:
                raise SimulationRunError(f"frames[{i}] missing {key!r}")
        t = _finite_number(frame["t"], f"frames[{i}].t")
        _check_vec(frame["pos_ned"], 3, f"frames[{i}].pos_ned")
        quat = _check_vec(frame["quat"], 4, f"frames[{i}].quat")
        _finite_number(frame["Va"], f"frames[{i}].Va")
        _finite_number(frame["alpha"], f"frames[{i}].alpha")
        _finite_number(frame["beta"], f"frames[{i}].beta")
        _finite_number(frame["load_factor_n"], f"frames[{i}].load_factor_n")
        power = _finite_number(frame["power_w"], f"frames[{i}].power_w")
        energy = _finite_number(
            frame["energy_wh_remaining"], f"frames[{i}].energy_wh_remaining"
        )
        if energy < 0.0:
            raise SimulationRunError(
                f"frames[{i}].energy_wh_remaining is negative ({energy})"
            )
        qn2 = quat[0] ** 2 + quat[1] ** 2 + quat[2] ** 2 + quat[3] ** 2
        if abs(qn2 - 1.0) > _QUAT_UNIT_TOL:
            raise SimulationRunError(f"frames[{i}].quat is not unit length ({qn2})")
        if prev_t is not None:
            if t < prev_t:
                raise SimulationRunError(
                    f"time is not monotonic at frames[{i}]: {t} < {prev_t}"
                )
            step = t - prev_t
            last_depleted = i == n_frames - 1 and energy == 0.0
            if last_depleted:
                if step <= 0.0 or step - dt_s > _DT_TOL:
                    raise SimulationRunError(
                        f"frames[{i}] depleted-energy step {step} is not in (0, dt_s]"
                    )
            elif abs(step - dt_s) > _DT_TOL:
                raise SimulationRunError(
                    f"frames[{i}] dt {step} != meta.dt_s {dt_s}"
                )
        if prev_energy is not None and prev_power is not None:
            if energy > prev_energy:
                raise SimulationRunError(
                    f"energy increased at frames[{i}]: {prev_energy} -> {energy}"
                )
            if prev_power > 0.0 and not (energy < prev_energy):
                raise SimulationRunError(
                    f"energy did not strictly decrease at frames[{i}] while power>0"
                )
        prev_t = t
        prev_energy = energy
        prev_power = power

    if not isinstance(part_stress, Mapping):
        raise SimulationRunError("part_stress must be an object")
    for part_id, samples in part_stress.items():
        if not isinstance(samples, list) or not samples:
            raise SimulationRunError(f"part_stress.{part_id} must be a non-empty list")
        for j, sample in enumerate(samples):
            if not isinstance(sample, Mapping):
                raise SimulationRunError(f"part_stress.{part_id}[{j}] must be an object")
            for key in _STRESS_KEYS:
                if key not in sample:
                    raise SimulationRunError(
                        f"part_stress.{part_id}[{j}] missing {key!r}"
                    )
                _finite_number(sample[key], f"part_stress.{part_id}[{j}].{key}")

    _reject_nan_inf(run, "simulation_run")


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimulationRunError(f"{label} must be a number")
    if not math.isfinite(value):
        raise SimulationRunError(f"{label} is not finite")
    return float(value)


def _check_vec(value: Any, n: int, label: str) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SimulationRunError(f"{label} must be a length-{n} array")
    if len(value) != n:
        raise SimulationRunError(f"{label} must have length {n}")
    return [_finite_number(v, f"{label}[{i}]") for i, v in enumerate(value)]


def _reject_nan_inf(value: Any, label: str) -> None:
    if isinstance(value, Mapping):
        for k, v in value.items():
            _reject_nan_inf(v, f"{label}.{k}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for i, v in enumerate(value):
            _reject_nan_inf(v, f"{label}[{i}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise SimulationRunError(f"{label} is not finite")
