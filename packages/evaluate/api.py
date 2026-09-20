"""Public evaluate_revision / compare_evaluations entry points."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from contracts import validate_instance

from .checks import run_checks
from .hashing import canonical_hash, geometry_hash, normalize_hash
from .models import (
    CHECK_CONTRACT_NAMES,
    Check,
    Claim,
    Evaluation,
    FidelityMismatch,
    make_claim,
    unknown_claim,
)
from .physics import (
    aero_metrics,
    as_float,
    battery_energy_claims,
    center_of_gravity,
    compute_tail,
    drag_force_n,
    extract_solver_cl_cdi,
    mission_float,
    performance,
    propulsion_level_flight,
    reference_sbc,
    spar_safety,
    static_margin,
    sum_mass,
    unique,
    usable_energy,
)

_CONTRACT_STATUSES = {"known", "estimated", "unknown", "conflicted", "not_applicable"}
_CONTRACT_SOURCE_KINDS = {"cad", "bom", "manual", "catalog", "computed", "inferred", "assumed"}
_NONE_HASH = "none"


def load_solver_result(path: str | Path, geometry: dict | None = None) -> dict:
    """Load a C4 VSPAERO sweep JSON for evaluate_revision(solver_result=...).

    If `geometry` is given, geometry_hash is taken from evaluate.hashing.geometry_hash
    of that dict so a sweep binds to the fixture it was generated from.
    """
    p = Path(path)
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise TypeError(f"{p} is not a JSON object")
    out = dict(data)
    if geometry is not None:
        out["geometry_hash"] = geometry_hash(geometry)
    return out


def evaluate_revision(
    geometry: dict,
    parts: list[dict] | dict,
    mission: dict | None = None,
    solver_result: dict | None = None,
    design_manifest: dict | None = None,
) -> dict:
    """Evaluate one revision. Returns an evaluation.json-shaped dict.

    Coefficients are read from geometry/parts. Missing data yields unknown, not zero.
    Inputs are never mutated.
    """
    if not isinstance(geometry, dict):
        raise TypeError("geometry must be a dict")
    parts_input: Any = parts
    if isinstance(parts, dict):
        if isinstance(parts.get("occurrences"), list):
            parts = parts["occurrences"]
        elif isinstance(parts.get("parts"), list):
            parts = parts["parts"]
        else:
            raise TypeError("parts dict must contain occurrences or parts list")
    if not isinstance(parts, list):
        raise TypeError("parts must be a list")
    mission_dict = mission if isinstance(mission, dict) else geometry.get("mission")
    assumptions: list[str] = [
        "Straight and level, no wind.",
        "Reference S, b, c taken exactly once from geometry.reference.",
        "CD = CD_profile + CD_fuselage + CD_interference + k*CL^2 with k=1/(pi*e*AR); induced stored separately.",
        "Root bending moment 3.5 g * W * (b/4) (simple elliptic/rect load assumption); 21 spanwise stations; spars share BM by stiffness.",
        "Assumption ranges are propagated input assumptions, not confidence intervals.",
        "V-tail cant is the panel angle from the horizontal; S_h_eff=2*A*cos(cant), S_v_eff=2*A*sin(cant).",
        "Static margin stays unknown without a known-status neutral point.",
        "VSPAERO linear lift does not establish CLmax.",
    ]
    missing: list[str] = []
    g_hash = geometry_hash(geometry)
    revision_id = str(
        geometry.get("revision_id")
        or (mission_dict or {}).get("revision_id")
        or (design_manifest or {}).get("revision_id")
        or "unspecified"
    )

    mass_claim, annotated = sum_mass(parts)
    cg_claim = center_of_gravity(annotated, mass_claim)
    energy_claim, _raw_energy, quarantined = battery_energy_claims(parts)

    rho, miss_rho = mission_float(mission_dict, geometry, "rho", "rho_kgm3", path="mission.rho")
    v_cruise, miss_v = mission_float(mission_dict, geometry, "cruise_mps", "V", "v_mps", path="mission.cruise_mps")
    g_acc, miss_g = mission_float(mission_dict, geometry, "g", "g_mps2", path="mission.g")
    reserve, miss_res = mission_float(
        mission_dict,
        geometry,
        "reserve_fraction",
        "reserve",
        "reserve_wh_fraction",
        path="mission.reserve_fraction",
    )
    missing.extend(miss_rho + miss_v + miss_g + miss_res)
    e_usable = usable_energy(energy_claim, reserve, miss_res)

    s, b, c, ref_missing = reference_sbc(geometry)
    missing.extend(ref_missing)

    solver_used = False
    solver_cl = None
    solver_cdi = None
    solver_versions: dict[str, Any] = {}
    if isinstance(solver_result, dict):
        solver_hash = normalize_hash(solver_result.get("geometry_hash"))
        if solver_hash is None:
            assumptions.append("solver_result missing geometry_hash; ignored, fidelity stays analytic.")
        elif solver_hash != normalize_hash(g_hash):
            assumptions.append("solver_result geometry_hash does not match; ignored, fidelity stays analytic.")
        else:
            # Analytic trim CL (if mass/q/S known) for polar interpolation.
            cl_trim = None
            if mass_claim.value is not None and g_acc is not None and rho is not None and v_cruise is not None and s:
                w = float(mass_claim.value) * g_acc
                q = 0.5 * rho * v_cruise * v_cruise
                if q * s != 0:
                    cl_trim = w / (q * s)
            solver_cl, solver_cdi = extract_solver_cl_cdi(solver_result, cl_trim)
            if solver_cl is None or solver_cdi is None or not math.isfinite(solver_cl) or not math.isfinite(solver_cdi):
                assumptions.append("solver_result lacked finite CL and CDi; ignored, fidelity stays analytic.")
                solver_cl, solver_cdi = None, None
            else:
                solver_used = True
                solver_versions = dict(
                    solver_result.get("solver_versions")
                    or solver_result.get("versions")
                    or {}
                )
                assumptions.append(
                    "Lift and induced drag replaced from VSPAERO; profile/fuselage/interference kept analytic."
                )
                assumptions.append(
                    "Static margin stays unknown: solver_result has no validated VSPAERO derivatives."
                )
                for i, text in enumerate(assumptions):
                    if text.startswith("CD = CD_profile"):
                        assumptions[i] = (
                            "CD = CD_profile + CD_fuselage + CD_interference + CDi(VSPAERO polar at trim CL); "
                            "analytic k*CL^2 is not added."
                        )
                        break

    fidelity = "vspaero" if solver_used else "analytic"
    aero = aero_metrics(
        geometry=geometry,
        mass_claim=mass_claim,
        rho=rho,
        v=v_cruise,
        g=g_acc,
        solver_cl=solver_cl,
        solver_cdi=solver_cdi,
        fidelity=fidelity,
    )
    tail = compute_tail(geometry)
    missing.extend(tail.get("missing") or [])

    w_claim = aero.get("W") or unknown_claim(unit="N")
    spar_claim = spar_safety(geometry, parts, w_claim)

    cd_claim = aero.get("CD") or unknown_claim()
    q_claim = aero.get("q") or unknown_claim()
    drag = drag_force_n(cd_claim, q_claim, s)
    propulsion = propulsion_level_flight(parts, drag_n=drag, v_mps=v_cruise, rho=rho)
    missing.extend(propulsion.get("missing") or [])

    p_elec = as_float(propulsion.get("P_elec"))
    perf = performance(
        p_elec=p_elec,
        v_mps=v_cruise,
        e_usable=e_usable,
        p_missing=list(propulsion.get("missing") or []),
    )

    sm_claim = static_margin(geometry, cg_claim, c, ref_missing)

    climb_claim = unknown_claim(
        unit="m/s",
        missing_fields=unique((propulsion.get("missing") or []) + (["mass"] if mass_claim.value is None else [])),
        notes="climb needs excess power from a propulsion solution",
    )
    if p_elec is not None and mass_claim.value is not None and g_acc is not None and drag is not None and v_cruise:
        # Without a max-power point, excess power is unknown; leave climb unknown.
        climb_claim = unknown_claim(
            unit="m/s",
            missing_fields=["propulsion.P_max"],
            notes="level-flight power is not excess power",
        )

    metrics: dict[str, Claim] = {
        "mass": mass_claim,
        "cg": cg_claim,
        "battery_energy_wh": energy_claim,
        "E_usable_wh": e_usable,
        "static_margin": sm_claim,
        "spar_sf": spar_claim,
        "climb": climb_claim,
        **aero,
        **perf,
    }
    if tail.get("V_h") is not None:
        metrics["tail_volume_h"] = make_claim(tail["V_h"], "known", source="computed")
    else:
        metrics["tail_volume_h"] = unknown_claim(missing_fields=list(tail.get("missing") or []))
    if tail.get("V_v") is not None:
        metrics["tail_volume_v"] = make_claim(tail["V_v"], "known", source="computed")
    else:
        metrics["tail_volume_v"] = unknown_claim(missing_fields=list(tail.get("missing") or []))

    if cg_claim.value is None:
        # Guarantee the JSON value is null, never 0 / [0,0,0].
        metrics["cg"] = cg_claim.model_copy(update={"value": None, "status": "unknown"})

    checks = run_checks(
        geometry=geometry,
        parts=parts,
        mission=mission_dict,
        metrics=metrics,
        tail=tail,
        propulsion=propulsion,
        missing_fields=missing,
    )

    input_hashes = {
        "design_manifest": (
            canonical_hash(design_manifest) if design_manifest is not None else _NONE_HASH
        ),
        "parts": canonical_hash(parts_input),
        "geometry_features": g_hash,
    }
    evaluation = Evaluation(
        revision_id=revision_id,
        geometry_hash=g_hash,
        fidelity_tier=fidelity,  # type: ignore[arg-type]
        metrics=metrics,
        checks=checks,
        assumptions=assumptions,
        solver_versions=solver_versions,
        input_hashes=input_hashes,
        missing_fields=unique(missing),
        quarantined=quarantined,
    )
    doc = _sanitize(_to_evaluation_document(evaluation))
    validate_instance("evaluation", doc)
    return doc


def compare_evaluations(a: dict, b: dict) -> dict:
    """Compare two evaluations of the same fidelity. Mixed tiers raise FidelityMismatch."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        raise TypeError("compare_evaluations expects evaluation dicts")
    ta = _fidelity_of(a)
    tb = _fidelity_of(b)
    if ta != tb:
        raise FidelityMismatch(
            f"cannot compare fidelity_tier {ta!r} against {tb!r}; recompute both sides at one tier"
        )
    metrics_a = a.get("metrics") or {}
    metrics_b = b.get("metrics") or {}
    names = sorted(set(metrics_a) | set(metrics_b))
    deltas: dict[str, Any] = {}
    for name in names:
        va = _claim_value(metrics_a.get(name))
        vb = _claim_value(metrics_b.get(name))
        delta = None
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = vb - va
        deltas[name] = {"a": va, "b": vb, "delta": delta}
    return {"fidelity_tier": ta, "metrics_delta": deltas}


def _claim_value(claim: Any) -> Any:
    if claim is None:
        return None
    if isinstance(claim, dict):
        return claim.get("value")
    return getattr(claim, "value", None)


def _fidelity_of(doc: dict) -> Any:
    if "fidelity_tier" in doc:
        return doc.get("fidelity_tier")
    meta = doc.get("meta")
    if isinstance(meta, dict):
        return meta.get("fidelity_tier")
    return None


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return obj
    return obj


def _to_evaluation_document(evaluation: Evaluation) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "revision_id": evaluation.revision_id,
        "geometry_hash": evaluation.geometry_hash,
        "fidelity_tier": evaluation.fidelity_tier,
        "input_hashes": {
            "design_manifest": str(
                (evaluation.input_hashes or {}).get("design_manifest") or _NONE_HASH
            ),
            "parts": str((evaluation.input_hashes or {}).get("parts") or _NONE_HASH),
            "geometry_features": str(
                (evaluation.input_hashes or {}).get("geometry_features")
                or evaluation.geometry_hash
            ),
        },
        "assumptions": list(evaluation.assumptions or []),
    }
    solver_versions = _contract_solver_versions(evaluation.solver_versions)
    if solver_versions:
        meta["solver_versions"] = solver_versions
    doc: dict[str, Any] = {
        "schema_version": 1,
        "meta": meta,
        "metrics": {
            name: _dump_claim(claim) for name, claim in evaluation.metrics.items()
        },
        "checks": _dump_checks(evaluation.checks),
    }
    quarantine = _dump_quarantine(evaluation.quarantined)
    if quarantine:
        doc["quarantine"] = quarantine
    return doc


def _contract_solver_versions(raw: Any) -> dict[str, str | None] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, str | None] = {}
    for key in ("openvsp", "vspaero"):
        if key not in raw:
            continue
        val = raw[key]
        out[key] = None if val is None else str(val)
    return out or None


def _scalar_value(value: Any) -> float | None:
    if isinstance(value, (list, tuple)):
        return as_float(value[0]) if value else None
    return as_float(value)


def _dump_claim(claim: Claim, *, default_unit: str = "1") -> dict[str, Any]:
    value = _scalar_value(claim.value)
    unit = claim.unit if isinstance(claim.unit, str) and claim.unit.strip() else default_unit
    status, source_kind = _contract_status_and_source(claim, value)
    if status == "unknown":
        value = None
    if status in {"known", "estimated"} and value is None:
        status = "unknown"
    assumptions: list[str] = []
    if claim.notes:
        assumptions.append(claim.notes)
    for field in claim.missing_fields or []:
        if field not in assumptions:
            assumptions.append(field)
    dumped: dict[str, Any] = {
        "value": value,
        "unit": unit,
        "status": status,
        "source_kind": source_kind,
        "evidence_ids": [],
        "assumptions": assumptions,
    }
    if value is not None and claim.assumption_range is not None:
        dumped["assumption_range"] = {
            "low": claim.assumption_range.low,
            "nominal": claim.assumption_range.nominal,
            "high": claim.assumption_range.high,
        }
    return dumped


def _contract_status_and_source(claim: Claim, value: float | None) -> tuple[str, str]:
    status = str(claim.status or "unknown")
    source = str(claim.source or "")
    if status == "assumed":
        mapped_status = "estimated" if value is not None else "unknown"
        return mapped_status, "assumed"
    if status not in _CONTRACT_STATUSES:
        mapped_status = "unknown" if value is None else "estimated"
    else:
        mapped_status = status
    if source in _CONTRACT_SOURCE_KINDS:
        return mapped_status, source
    if source in {"analytic", "vspaero"}:
        return mapped_status, "computed"
    if source.startswith("parts"):
        return mapped_status, "computed"
    if "geometry" in source:
        return mapped_status, "inferred" if mapped_status in {"known", "estimated", "conflicted"} else "assumed"
    if mapped_status in {"known", "estimated", "conflicted"}:
        return mapped_status, "computed"
    return mapped_status, "assumed"


def _dump_checks(checks: list[Check]) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = []
    for check in checks:
        mapped = CHECK_CONTRACT_NAMES.get(check.id, check.id)
        names = mapped if isinstance(mapped, tuple) else (mapped,)
        for name in names:
            dumped.append(_dump_check(check, name))
    return dumped


def _dump_check(check: Check, name: str) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "status": check.status}
    metric = _dump_check_metric(check)
    if metric is not None:
        item["metric"] = metric
    if check.limit is not None and len(check.limit) >= 1:
        item["limit_low"] = check.limit[0]
    if check.limit is not None and len(check.limit) >= 2:
        item["limit_high"] = check.limit[1]
    detail_parts: list[str] = []
    if check.message:
        detail_parts.append(check.message)
    if check.missing_fields:
        detail_parts.append("missing: " + ", ".join(check.missing_fields))
    if detail_parts:
        item["detail"] = "; ".join(detail_parts)
    return item


def _dump_check_metric(check: Check) -> dict[str, Any] | None:
    value = _scalar_value(check.value)
    if value is None and not check.missing_fields:
        return None
    if value is None:
        return {
            "value": None,
            "unit": "1",
            "status": "unknown",
            "source_kind": "computed",
            "evidence_ids": [],
            "assumptions": list(check.missing_fields or []),
        }
    return {
        "value": value,
        "unit": "1",
        "status": "known",
        "source_kind": "computed",
        "evidence_ids": [],
        "assumptions": list(check.missing_fields or []),
    }


def _dump_quarantine(items: list[Claim]) -> list[dict[str, Any]]:
    dumped: list[dict[str, Any]] = []
    for item in items:
        path = item.source or "quarantine"
        reason = item.notes or "quarantined"
        dumped.append({"path": path, "reason": reason, "raw": item.value})
    return dumped
