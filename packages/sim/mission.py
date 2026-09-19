"""Prescribed-route mission model. Not a plant: no forces, no 6DOF."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .attitude import quat_from_euler_321
from .validate import validate_simulation_run

_ASSUMPTIONS = [
    "straight and level segments at constant Va",
    "prescribed coordinated-turn load factor; not a tested turning envelope",
    "no wind",
    "energy_wh_remaining is usable energy after mission reserve withheld",
    "pos_ned is FRD/NED metres",
    "quat is scalar-first",
    "spar_L sigma_mpa is an assumed analytic beam estimate, not FEA",
    "right-wing-down is positive roll about FRD +x; quat is 3-2-1 yaw-pitch-roll",
    "coordinated-turn heading rate is a kinematic constraint from n=1/cos(phi), not a 6DOF solution",
    "power_w is a prescribed operating-point draw, not from a propulsion solve",
]


def simulate_mission(
    geometry: Mapping[str, Any] | None,
    parts: Any,
    evaluation: Mapping[str, Any] | None = None,
    route: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Integrate usable energy along a prescribed route and emit simulation_run."""
    ref = _reference_geometry(geometry)
    params = _mission_params(route, evaluation)
    spar_id = _spar_part_id(parts)
    semispan_m = 0.5 * ref["b"]
    stations = _spar_stations(semispan_m)

    t_straight_end = params["t_straight_end"]
    t_climb_end = params["t_climb_end"]
    t_turn_end = params["t_turn_end"]
    duration_s = params["duration_s"]
    dt_s = params["dt_s"]
    origins = _segment_origins(params)

    n_steps = int(round(duration_s / dt_s))
    usable_wh = params["pack_wh"] * (1.0 - params["reserve_fraction"])
    energy = usable_wh
    frames: list[dict[str, Any]] = []
    stress_samples: list[dict[str, Any]] = []
    prev_power = 0.0
    stress_stride = max(1, int(round(params["stress_dt_s"] / dt_s)))

    for i in range(n_steps + 1):
        t = i * dt_s
        if t > duration_s + 1e-12:
            break
        state = _state_at(t, params, origins)
        if i > 0:
            energy -= prev_power * dt_s / 3600.0
            if energy < 0.0:
                energy = 0.0
                frame = _frame(t, state, energy)
                frames.append(frame)
                _extend_stress(
                    stress_samples,
                    t,
                    state["load_factor_n"],
                    stations,
                    semispan_m,
                    params["sigma_root_mpa_n1"],
                )
                break
        frame = _frame(t, state, energy)
        frames.append(frame)
        if i % stress_stride == 0 or i == n_steps or energy == 0.0:
            _extend_stress(
                stress_samples,
                t,
                state["load_factor_n"],
                stations,
                semispan_m,
                params["sigma_root_mpa_n1"],
            )
        prev_power = state["power_w"]
        if energy == 0.0:
            break

    run = {
        "meta": {
            "revision_id": params["revision_id"],
            "geometry_hash": _geometry_hash(ref),
            "fidelity_tier": params["fidelity_tier"],
            "solver_versions": {
                "openvsp": params["openvsp_version"],
                "vspaero": params["vspaero_version"],
            },
            "assumptions": list(_ASSUMPTIONS),
            "dt_s": dt_s,
        },
        "frames": frames,
        "part_stress": {spar_id: stress_samples},
    }
    validate_simulation_run(run)
    return run


def _reference_geometry(
    geometry: Mapping[str, Any] | None,
    *,
    S: float = 0.4,
    b: float = 2.2,
    c: float = 0.2,
    cant: float = 0.6981317007977318,
) -> dict[str, float]:
    """Read reference quantities from the geometry dict. Defaults are parameters, not module constants."""
    return {
        "S": _dig(geometry, ("S",), ("area_m2",), ("reference", "S"), default=S),
        "b": _dig(geometry, ("b",), ("span_m",), ("reference", "b"), default=b),
        "c": _dig(geometry, ("c",), ("chord_m",), ("reference", "c"), default=c),
        "cant": _dig(
            geometry,
            ("cant",),
            ("cant_rad",),
            ("vtail_cant_rad",),
            ("reference", "cant"),
            default=cant,
        ),
    }


def _geometry_hash(ref: Mapping[str, float]) -> str:
    payload = {"S": ref["S"], "b": ref["b"], "c": ref["c"], "cant": ref["cant"]}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _mission_params(
    route: Mapping[str, Any] | None,
    evaluation: Mapping[str, Any] | None,
    *,
    dt_s: float = 0.02,
    duration_s: float = 60.0,
    Va: float = 15.0,
    alt_m: float = 120.0,
    climb_vz_up_mps: float = 2.0,
    climb_load_factor_n: float = 1.05,
    bank_rad: float = math.radians(30.0),
    alpha_rad: float = 0.043,
    pack_wh: float = 88.0,
    reserve_fraction: float = 0.2,
    power_level_w: float = 150.0,
    power_climb_w: float = 175.0,
    power_turn_w: float = 162.0,
    sigma_root_mpa_n1: float = 41.2,
    t_straight_end: float = 20.0,
    t_climb_end: float = 30.0,
    t_turn_end: float = 50.0,
    g_mps2: float = 9.80665,
    stress_dt_s: float = 0.2,
    revision_id: str = "rev_synthetic_vtail_001",
    fidelity_tier: str = "analytic",
) -> dict[str, Any]:
    route = route or {}
    evaluation = evaluation or {}
    meta = evaluation.get("meta") if isinstance(evaluation.get("meta"), Mapping) else {}
    solvers = evaluation.get("solver_versions")
    if not isinstance(solvers, Mapping):
        solvers = meta.get("solver_versions") if isinstance(meta.get("solver_versions"), Mapping) else {}
    level_power = float(route.get("power_level_w", evaluation.get("power_w", power_level_w)))
    return {
        "dt_s": float(route.get("dt_s", dt_s)),
        "duration_s": float(route.get("duration_s", duration_s)),
        "Va": float(route.get("Va", Va)),
        "alt_m": float(route.get("alt_m", alt_m)),
        "climb_vz_up_mps": float(route.get("climb_vz_up_mps", climb_vz_up_mps)),
        "climb_load_factor_n": float(route.get("climb_load_factor_n", climb_load_factor_n)),
        "bank_rad": float(route.get("bank_rad", bank_rad)),
        "alpha_rad": float(route.get("alpha_rad", alpha_rad)),
        "pack_wh": float(route.get("pack_wh", pack_wh)),
        "reserve_fraction": float(route.get("reserve_fraction", reserve_fraction)),
        "power_level_w": level_power,
        "power_climb_w": float(route.get("power_climb_w", power_climb_w)),
        "power_turn_w": float(route.get("power_turn_w", power_turn_w)),
        "sigma_root_mpa_n1": float(route.get("sigma_root_mpa_n1", sigma_root_mpa_n1)),
        "t_straight_end": float(route.get("t_straight_end", t_straight_end)),
        "t_climb_end": float(route.get("t_climb_end", t_climb_end)),
        "t_turn_end": float(route.get("t_turn_end", t_turn_end)),
        "g_mps2": float(route.get("g_mps2", g_mps2)),
        "stress_dt_s": float(route.get("stress_dt_s", stress_dt_s)),
        "revision_id": str(
            route.get(
                "revision_id",
                evaluation.get("revision_id", meta.get("revision_id", revision_id)),
            )
        ),
        "fidelity_tier": str(
            evaluation.get(
                "fidelity_tier",
                meta.get("fidelity_tier", route.get("fidelity_tier", fidelity_tier)),
            )
        ),
        "openvsp_version": solvers.get("openvsp"),
        "vspaero_version": solvers.get("vspaero"),
    }


def _segment_origins(params: Mapping[str, Any]) -> dict[str, float]:
    Va = params["Va"]
    alt_m = params["alt_m"]
    t_straight_end = params["t_straight_end"]
    t_climb_end = params["t_climb_end"]
    t_turn_end = params["t_turn_end"]
    vz = params["climb_vz_up_mps"]
    gamma = math.asin(max(-1.0, min(1.0, vz / Va))) if Va else 0.0
    vh = Va * math.cos(gamma)
    x_climb0 = Va * t_straight_end
    z_climb0 = -alt_m
    climb_dt = t_climb_end - t_straight_end
    x_turn0 = x_climb0 + vh * climb_dt
    y_turn0 = 0.0
    z_turn0 = z_climb0 - vz * climb_dt
    phi = params["bank_rad"]
    omega = params["g_mps2"] * math.tan(phi) / Va
    turn_dt = t_turn_end - t_climb_end
    psi_end = omega * turn_dt
    radius = Va / omega
    x_s2 = x_turn0 + radius * math.sin(psi_end)
    y_s2 = y_turn0 + radius * (1.0 - math.cos(psi_end))
    return {
        "gamma": gamma,
        "vh": vh,
        "x_climb0": x_climb0,
        "z_climb0": z_climb0,
        "x_turn0": x_turn0,
        "y_turn0": y_turn0,
        "z_turn0": z_turn0,
        "omega": omega,
        "radius": radius,
        "psi_end": psi_end,
        "x_s2": x_s2,
        "y_s2": y_s2,
        "z_s2": z_turn0,
    }


def _state_at(
    t: float, params: Mapping[str, Any], origins: Mapping[str, float]
) -> dict[str, float]:
    Va = params["Va"]
    alpha = params["alpha_rad"]
    t_straight_end = params["t_straight_end"]
    t_climb_end = params["t_climb_end"]
    t_turn_end = params["t_turn_end"]

    if t < t_straight_end:
        return {
            "pos_n": Va * t,
            "pos_e": 0.0,
            "pos_d": -params["alt_m"],
            "phi": 0.0,
            "theta": 0.0,
            "psi": 0.0,
            "Va": Va,
            "alpha": alpha,
            "beta": 0.0,
            "load_factor_n": 1.0,
            "power_w": params["power_level_w"],
        }
    if t < t_climb_end:
        tau = t - t_straight_end
        return {
            "pos_n": origins["x_climb0"] + origins["vh"] * tau,
            "pos_e": 0.0,
            "pos_d": origins["z_climb0"] - params["climb_vz_up_mps"] * tau,
            "phi": 0.0,
            "theta": origins["gamma"],
            "psi": 0.0,
            "Va": Va,
            "alpha": alpha,
            "beta": 0.0,
            "load_factor_n": params["climb_load_factor_n"],
            "power_w": params["power_climb_w"],
        }
    if t < t_turn_end:
        tau = t - t_climb_end
        psi = origins["omega"] * tau
        phi = params["bank_rad"]
        return {
            "pos_n": origins["x_turn0"] + origins["radius"] * math.sin(psi),
            "pos_e": origins["y_turn0"] + origins["radius"] * (1.0 - math.cos(psi)),
            "pos_d": origins["z_turn0"],
            "phi": phi,
            "theta": 0.0,
            "psi": psi,
            "Va": Va,
            "alpha": alpha,
            "beta": 0.0,
            "load_factor_n": 1.0 / math.cos(phi),
            "power_w": params["power_turn_w"],
        }
    tau = t - t_turn_end
    psi = origins["psi_end"]
    return {
        "pos_n": origins["x_s2"] + Va * math.cos(psi) * tau,
        "pos_e": origins["y_s2"] + Va * math.sin(psi) * tau,
        "pos_d": origins["z_s2"],
        "phi": 0.0,
        "theta": 0.0,
        "psi": psi,
        "Va": Va,
        "alpha": alpha,
        "beta": 0.0,
        "load_factor_n": 1.0,
        "power_w": params["power_level_w"],
    }


def _frame(t: float, state: Mapping[str, float], energy: float) -> dict[str, Any]:
    return {
        "t": t,
        "pos_ned": [state["pos_n"], state["pos_e"], state["pos_d"]],
        "quat": quat_from_euler_321(state["phi"], state["theta"], state["psi"]),
        "Va": state["Va"],
        "alpha": state["alpha"],
        "beta": state["beta"],
        "load_factor_n": state["load_factor_n"],
        "power_w": state["power_w"],
        "energy_wh_remaining": energy,
    }


def _spar_stations(semispan_m: float, *, n_stations: int = 5) -> list[float]:
    if semispan_m <= 0.0:
        return [0.0]
    # Root plus inboard stations; omit the free tip where the beam estimate is zero.
    return [semispan_m * (i / n_stations) for i in range(n_stations)]


def _extend_stress(
    samples: list[dict[str, Any]],
    t: float,
    load_factor_n: float,
    stations: Sequence[float],
    semispan_m: float,
    baseline_mpa: float,
) -> None:
    for station_m in stations:
        if semispan_m <= 0.0:
            span_factor = 1.0
        else:
            eta = max(0.0, min(1.0, station_m / semispan_m))
            span_factor = (1.0 - eta) ** 2
        samples.append(
            {
                "t": t,
                "sigma_mpa": baseline_mpa * load_factor_n * span_factor,
                "station_m": station_m,
            }
        )


def _spar_part_id(parts: Any, *, default: str = "spar_L") -> str:
    if parts is None:
        return default
    seq: Any
    if isinstance(parts, Mapping):
        if "id" in parts:
            seq = [parts]
        elif "parts" in parts:
            seq = parts["parts"]
        else:
            for key, value in parts.items():
                if isinstance(value, Mapping):
                    typ = str(value.get("type", "")).lower()
                    if typ == "spar" or "spar" in str(key).lower():
                        return str(value.get("id", key))
                if "spar" in str(key).lower():
                    return str(key)
            return default
    else:
        seq = parts
    if not isinstance(seq, Sequence) or isinstance(seq, (str, bytes)):
        return default
    for part in seq:
        if not isinstance(part, Mapping):
            continue
        pid = str(part.get("id", ""))
        typ = str(part.get("type", "")).lower()
        if typ == "spar" or pid.startswith("spar"):
            return pid or default
    return default


def _dig(
    geometry: Mapping[str, Any] | None,
    *paths: tuple[str, ...],
    default: float,
) -> float:
    if not geometry:
        return default
    for path in paths:
        cur: Any = geometry
        found = True
        for key in path:
            if isinstance(cur, Mapping) and key in cur and cur[key] is not None:
                cur = cur[key]
            else:
                found = False
                break
        if found:
            return float(cur)
    return default
