"""Fourteen gate checks. Null inputs yield unknown, never a substituted zero."""

from __future__ import annotations

from typing import Any

from .models import Check
from .physics import as_float, unique

CHECK_IDS = [
    "static_margin",
    "stall",
    "climb",
    "spar",
    "tail_volume_h",
    "tail_volume_v",
    "servos",
    "motor_current",
    "esc_current",
    "battery_current",
    "wiring_chains",
    "payload",
    "clearance",
    "vtail_or_tail_layout",
]

TAIL_H_LIMIT = [0.35, 0.7]
TAIL_V_LIMIT = [0.02, 0.06]
SM_LIMIT = [0.05, 0.20]
STALL_RATIO_MIN = 1.3
CLIMB_MIN_MPS = 2.0
SPAR_SF_MIN = 1.5
SERVO_RATIO_MIN = 1.5


def _check(
    check_id: str,
    status: str,
    *,
    value: Any = None,
    limit: list[Any] | None = None,
    missing_fields: list[str] | None = None,
    message: str | None = None,
) -> Check:
    return Check(
        id=check_id,
        status=status,  # type: ignore[arg-type]
        value=value,
        limit=limit,
        missing_fields=list(missing_fields or []),
        message=message,
    )


def _unknown(check_id: str, missing: list[str], *, value: Any = None, limit: list[Any] | None = None, message: str | None = None) -> Check:
    return _check(check_id, "unknown", value=value, limit=limit, missing_fields=unique(missing), message=message)


def _in_band(value: float, lo: float | None, hi: float | None) -> bool:
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def run_checks(
    *,
    geometry: dict,
    parts: list[dict],
    mission: dict | None,
    metrics: dict,
    tail: dict,
    propulsion: dict,
    missing_fields: list[str],
) -> list[Check]:
    checks: list[Check] = []
    mass_unknown = metrics.get("mass") is None or metrics["mass"].value is None
    weight_missing = unique(
        list(getattr(metrics.get("mass"), "missing_fields", None) or [])
        + list(getattr(metrics.get("W"), "missing_fields", None) or [])
        + (["mass"] if mass_unknown else [])
    )

    sm = metrics.get("static_margin")
    sm_val = as_float(sm.value) if sm is not None else None
    if sm is None or sm.value is None or sm.status in {"unknown", "estimated"}:
        miss = list(sm.missing_fields) if sm is not None else ["geometry.neutral_point"]
        if sm is not None and sm.status == "estimated" and sm_val is not None:
            checks.append(
                _unknown(
                    "static_margin",
                    miss or ["geometry.neutral_point"],
                    value=sm_val,
                    limit=SM_LIMIT,
                    message="NP not validated; check remains unknown",
                )
            )
        else:
            checks.append(_unknown("static_margin", miss, limit=SM_LIMIT))
    else:
        ok = _in_band(sm_val, SM_LIMIT[0], SM_LIMIT[1])
        checks.append(_check("static_margin", "pass" if ok else "fail", value=sm_val, limit=SM_LIMIT))

    stall = metrics.get("stall")
    v_stall = as_float(stall.value) if stall is not None else None
    cruise = as_float((mission or {}).get("cruise_mps")) if mission else as_float((geometry.get("mission") or {}).get("cruise_mps") if isinstance(geometry.get("mission"), dict) else None)
    if cruise is None:
        geo_m = geometry.get("mission") if isinstance(geometry.get("mission"), dict) else {}
        cruise = as_float(geo_m.get("cruise_mps"))
    if mass_unknown or v_stall is None:
        miss = unique(weight_missing + (list(stall.missing_fields) if stall is not None else ["stall"]))
        checks.append(_unknown("stall", miss, limit=[STALL_RATIO_MIN, None], message="weight-dependent"))
    elif cruise is None:
        checks.append(_unknown("stall", ["mission.cruise_mps"], value=v_stall, limit=[STALL_RATIO_MIN, None]))
    else:
        ratio = cruise / v_stall if v_stall else None
        ok = ratio is not None and ratio >= STALL_RATIO_MIN
        checks.append(
            _check(
                "stall",
                "pass" if ok else "fail",
                value=ratio,
                limit=[STALL_RATIO_MIN, None],
                message="cruise >= 1.3 * V_stall",
            )
        )

    climb = metrics.get("climb")
    climb_v = as_float(climb.value) if climb is not None else None
    if mass_unknown or climb is None or climb.value is None:
        miss = unique(weight_missing + (list(climb.missing_fields) if climb is not None else ["climb"]))
        checks.append(_unknown("climb", miss, limit=[CLIMB_MIN_MPS, None], message="weight-dependent; unknown without excess power"))
    else:
        ok = climb_v >= CLIMB_MIN_MPS
        checks.append(_check("climb", "pass" if ok else "fail", value=climb_v, limit=[CLIMB_MIN_MPS, None]))

    spar = metrics.get("spar_sf")
    spar_v = as_float(spar.value) if spar is not None else None
    if mass_unknown or spar is None or spar.value is None:
        miss = unique(weight_missing + (list(spar.missing_fields) if spar is not None else ["spar"]))
        checks.append(_unknown("spar", miss, limit=[SPAR_SF_MIN, None], message="weight-dependent"))
    else:
        ok = spar_v >= SPAR_SF_MIN
        checks.append(_check("spar", "pass" if ok else "fail", value=spar_v, limit=[SPAR_SF_MIN, None]))

    layout = tail.get("layout")
    heuristic = tail.get("heuristic")
    v_h = as_float(tail.get("V_h"))
    v_v = as_float(tail.get("V_v"))
    tail_missing = list(tail.get("missing") or [])
    if layout == "vtail":
        # Conventional volume-coefficient bands do not apply to a V-tail.
        checks.append(
            _check(
                "tail_volume_h",
                "not_applicable" if "vtail.cant_rad" not in tail_missing else "unknown",
                value=v_h,
                limit=TAIL_H_LIMIT,
                missing_fields=tail_missing if v_h is None else [],
                message="V-tail projected horizontal volume; conventional 0.35–0.7 heuristic is not_applicable",
            )
        )
        checks.append(
            _check(
                "tail_volume_v",
                "not_applicable" if "vtail.cant_rad" not in tail_missing else "unknown",
                value=v_v,
                limit=TAIL_V_LIMIT,
                missing_fields=tail_missing if v_v is None else [],
                message="V-tail projected vertical volume; conventional 0.02–0.06 heuristic is not_applicable",
            )
        )
    elif heuristic == "conventional" and layout is not None:
        if v_h is None:
            checks.append(_unknown("tail_volume_h", tail_missing or ["tail.S_h"], limit=TAIL_H_LIMIT))
        else:
            ok = _in_band(v_h, TAIL_H_LIMIT[0], TAIL_H_LIMIT[1])
            checks.append(_check("tail_volume_h", "pass" if ok else "fail", value=v_h, limit=TAIL_H_LIMIT))
        if v_v is None:
            checks.append(_unknown("tail_volume_v", tail_missing or ["tail.S_v"], limit=TAIL_V_LIMIT))
        else:
            ok = _in_band(v_v, TAIL_V_LIMIT[0], TAIL_V_LIMIT[1])
            checks.append(_check("tail_volume_v", "pass" if ok else "fail", value=v_v, limit=TAIL_V_LIMIT))
    else:
        checks.append(_unknown("tail_volume_h", tail_missing or ["vtail.layout"], limit=TAIL_H_LIMIT))
        checks.append(_unknown("tail_volume_v", tail_missing or ["vtail.layout"], limit=TAIL_V_LIMIT))

    servo_ratio = as_float((metrics.get("servo_torque_ratio").value if metrics.get("servo_torque_ratio") else None))
    if servo_ratio is None:
        checks.append(_unknown("servos", ["parts.servo.specs.torque", "hinge_moment"], limit=[SERVO_RATIO_MIN, None]))
    else:
        checks.append(_check("servos", "pass" if servo_ratio >= SERVO_RATIO_MIN else "fail", value=servo_ratio, limit=[SERVO_RATIO_MIN, None]))

    def current_check(check_id: str, current: Any, limit_a: Any, missing: list[str]) -> Check:
        i = as_float(current)
        lim = as_float(limit_a)
        if i is None or lim is None:
            return _unknown(check_id, missing, limit=[None, lim])
        ok = i <= lim
        return _check(check_id, "pass" if ok else "fail", value=i, limit=[None, lim])

    prop_missing = list(propulsion.get("missing") or ["parts.motor", "parts.prop"])
    checks.append(current_check("motor_current", propulsion.get("I_a"), propulsion.get("motor_imax"), unique(prop_missing + ["parts.motor.specs.imax"])))
    checks.append(current_check("esc_current", propulsion.get("I_a"), propulsion.get("esc_imax"), unique(prop_missing + ["parts.esc.specs.imax"])))
    checks.append(current_check("battery_current", propulsion.get("I_a"), propulsion.get("batt_imax"), unique(prop_missing + ["parts.battery.specs.c_rate"])))

    if propulsion.get("I_a") is None:
        # wiring topology is not in the parts list for this analytic path
        pass
    chain_types = {str(p.get("type") or "").lower() for p in parts if isinstance(p, dict)}
    electrical = geometry.get("electrical") if isinstance(geometry.get("electrical"), dict) else {}
    chains = electrical.get("chains") or (mission or {}).get("electrical_chains")
    if chains:
        checks.append(_check("wiring_chains", "pass", message="caller-provided electrical chains"))
    else:
        checks.append(
            _unknown(
                "wiring_chains",
                ["geometry.electrical.chains"],
                message="no electrical chain graph; types present: " + ",".join(sorted(t for t in chain_types if t)),
            )
        )

    locked_ids = []
    if isinstance(mission, dict):
        locked_ids = list(mission.get("locked_part_ids") or mission.get("locked") or [])
    present = {str(p.get("id")) for p in parts if isinstance(p, dict)}
    locked_in_parts = [str(p.get("id")) for p in parts if isinstance(p, dict) and p.get("locked")]
    required = [str(x) for x in locked_ids] if locked_ids else locked_in_parts
    missing_payload = [pid for pid in required if pid not in present]
    if missing_payload:
        checks.append(_check("payload", "fail", missing_fields=[f"parts.{pid}" for pid in missing_payload], message="locked payload missing"))
    else:
        checks.append(_check("payload", "pass", message="locked parts present"))

    if geometry.get("clearance") is None and not isinstance(geometry.get("intersections"), list):
        checks.append(_unknown("clearance", ["geometry.clearance"], message="no mesh interference data"))
    else:
        ok = bool(geometry.get("clearance", {}).get("pass")) if isinstance(geometry.get("clearance"), dict) else False
        checks.append(_check("clearance", "pass" if ok else "fail"))

    if layout in {"vtail", "conventional"}:
        checks.append(
            _check(
                "vtail_or_tail_layout",
                "pass",
                message=f"layout={layout}",
            )
        )
    else:
        checks.append(_unknown("vtail_or_tail_layout", tail_missing or ["vtail.layout"]))

    by_id = {c.id: c for c in checks}
    return [by_id[i] for i in CHECK_IDS]
