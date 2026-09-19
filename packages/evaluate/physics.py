"""Analytic mass, aero, tail, structure, and propulsion. Coefficients come from inputs."""

from __future__ import annotations

import math
from typing import Any

from .models import Claim, assumption_band, make_claim, unknown_claim
from .quarantine import (
    chemistry_wh_per_kg_limit,
    quarantine_input,
    specific_energy_wh_kg,
)

ASSUMPTION_FRAC = 0.15
SPAR_STATIONS = 21
LOAD_FACTOR_G = 3.5


def dig(obj: Any, *keys: str, default: Any = None) -> Any:
    cur = obj
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def is_claim(value: Any) -> bool:
    return isinstance(value, dict) and "value" in value and "status" in value


def as_float(value: Any) -> float | None:
    if is_claim(value):
        return as_float(value.get("value"))
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def explicit_null(value: Any) -> bool:
    if value is None:
        return True
    if is_claim(value):
        return value.get("value") is None
    return False


def finite(value: Any) -> bool:
    return as_float(value) is not None


def first_present(obj: dict | None, *keys: str) -> Any:
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if key in obj:
            return obj[key]
    return None


def unique(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in seq:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def part_specs(part: dict) -> dict:
    specs = part.get("specs")
    return specs if isinstance(specs, dict) else {}


def part_id_of(part: dict) -> str:
    return str(part.get("id") or part.get("part_id") or part.get("type") or "part")


def part_mass_kg(part: dict) -> tuple[float | None, str | None, bool]:
    """Return (mass, field_path, explicit_null)."""
    pid = part_id_of(part)
    specs = part_specs(part)
    if "mass_kg" in part:
        val = as_float(part.get("mass_kg"))
        return val, f"parts.{pid}.mass_kg", explicit_null(part.get("mass_kg"))
    if "mass" in part:
        val = as_float(part.get("mass"))
        return val, f"parts.{pid}.mass", explicit_null(part.get("mass"))
    if "mass_g" in part:
        raw = part.get("mass_g")
        val = as_float(raw)
        return (val / 1000.0 if val is not None else None, f"parts.{pid}.mass_g", raw is None)
    if "mass_kg" in specs:
        val = as_float(specs.get("mass_kg"))
        return val, f"parts.{pid}.specs.mass_kg", specs.get("mass_kg") is None
    if "mass_g" in specs:
        raw = specs.get("mass_g")
        val = as_float(raw)
        return (val / 1000.0 if val is not None else None, f"parts.{pid}.specs.mass_g", raw is None)
    return None, f"parts.{pid}.mass_kg", False


def part_xyz(part: dict) -> tuple[list[float] | None, list[str]]:
    pid = part_id_of(part)
    missing: list[str] = []
    frd = part.get("position_frd_m")
    if isinstance(frd, dict):
        comps = [as_float(frd.get("x_m")), as_float(frd.get("y_m")), as_float(frd.get("z_m"))]
        if any(c is None for c in comps):
            return None, [f"parts.{pid}.position_frd_m"]
        return [float(comps[0]), float(comps[1]), float(comps[2])], []
    for key in ("cg_m", "r_m", "position_m", "xyz"):
        if key in part:
            vec = part.get(key)
            if vec is None:
                return None, [f"parts.{pid}.{key}"]
            if isinstance(vec, (list, tuple)) and len(vec) >= 3:
                comps = [as_float(vec[0]), as_float(vec[1]), as_float(vec[2])]
                if any(c is None for c in comps):
                    return None, [f"parts.{pid}.{key}"]
                return [float(comps[0]), float(comps[1]), float(comps[2])], []
            return None, [f"parts.{pid}.{key}"]
    if any(k in part for k in ("x", "y", "z")):
        comps = [as_float(part.get("x")), as_float(part.get("y")), as_float(part.get("z"))]
        for axis, val in zip(("x", "y", "z"), comps, strict=True):
            if val is None:
                missing.append(f"parts.{pid}.{axis}")
        if missing:
            return None, missing
        return [float(comps[0]), float(comps[1]), float(comps[2])], []
    return None, [f"parts.{pid}.cg_m"]


def reference_sbc(geometry: dict) -> tuple[float | None, float | None, float | None, list[str]]:
    ref = geometry.get("reference")
    missing: list[str] = []
    if not isinstance(ref, dict):
        return None, None, None, ["geometry.reference"]
    s = as_float(first_present(ref, "S_m2", "S", "area_m2", "area"))
    b = as_float(first_present(ref, "b_m", "b", "span_m", "span"))
    c = as_float(first_present(ref, "c_m", "c", "mac_m", "chord", "c_ref"))
    if s is None:
        missing.append("geometry.reference.S")
    if b is None:
        missing.append("geometry.reference.b")
    if c is None:
        missing.append("geometry.reference.c")
    return s, b, c, missing


def mission_float(mission: dict | None, geometry: dict, *keys: str, path: str) -> tuple[float | None, list[str]]:
    src = mission if isinstance(mission, dict) else {}
    geo_mission = geometry.get("mission") if isinstance(geometry.get("mission"), dict) else {}
    env = geometry.get("environment") if isinstance(geometry.get("environment"), dict) else {}
    for key in keys:
        if key in src:
            val = as_float(src.get(key))
            return val, ([] if val is not None else [f"mission.{key}"])
        if key in geo_mission:
            val = as_float(geo_mission.get(key))
            return val, ([] if val is not None else [f"geometry.mission.{key}"])
        if key in env:
            val = as_float(env.get(key))
            return val, ([] if val is not None else [f"geometry.environment.{key}"])
    return None, [path]


def aero_coeff(geometry: dict, name: str, *alts: str) -> tuple[float | None, list[str]]:
    aero = geometry.get("aero") if isinstance(geometry.get("aero"), dict) else {}
    assumed = geometry.get("aero_assumptions") if isinstance(geometry.get("aero_assumptions"), dict) else {}
    keys = (name, *alts)
    for key in keys:
        if key in aero:
            val = as_float(aero.get(key))
            return val, ([] if val is not None else [f"geometry.aero.{key}"])
        if key in assumed:
            val = as_float(assumed.get(key))
            return val, ([] if val is not None else [f"geometry.aero_assumptions.{key}"])
        if key in geometry:
            val = as_float(geometry.get(key))
            return val, ([] if val is not None else [f"geometry.{key}"])
    return None, [f"geometry.aero.{name}"]


def sum_mass(parts: list[dict]) -> tuple[Claim, list[dict]]:
    total = 0.0
    missing: list[str] = []
    complete = True
    annotated: list[dict] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        mass, field, explicit_null = part_mass_kg(part)
        row = dict(part)
        row["_mass_kg"] = mass
        row["_mass_field"] = field
        annotated.append(row)
        if mass is None:
            complete = False
            missing.append(field)
            if explicit_null:
                missing.append(field)
            continue
        total += mass
    if not complete:
        return unknown_claim(unit="kg", missing_fields=unique(missing), source="parts"), annotated
    return make_claim(
        total,
        "known",
        unit="kg",
        source="parts",
        assumption_range=assumption_band(total, ASSUMPTION_FRAC),
        notes="assumption range replaces the former flat ±15% band; not a CI",
    ), annotated


def center_of_gravity(annotated_parts: list[dict], mass_claim: Claim) -> Claim:
    if mass_claim.status == "unknown" or mass_claim.value is None:
        missing = list(mass_claim.missing_fields)
        missing.append("mass")
        return unknown_claim(
            unit="m",
            missing_fields=unique(missing),
            source="parts",
            notes="CG is unknown when any required mass is null; not zero",
        )
    m_total = float(mass_claim.value)
    if m_total == 0:
        return unknown_claim(unit="m", missing_fields=["mass"], notes="zero mass")
    acc = [0.0, 0.0, 0.0]
    missing: list[str] = []
    for part in annotated_parts:
        mass = part.get("_mass_kg")
        if mass is None:
            missing.append(part.get("_mass_field") or "mass")
            continue
        xyz, miss = part_xyz(part)
        if xyz is None:
            missing.extend(miss)
            continue
        acc[0] += mass * xyz[0]
        acc[1] += mass * xyz[1]
        acc[2] += mass * xyz[2]
    if missing:
        return unknown_claim(unit="m", missing_fields=unique(missing), source="parts")
    return make_claim(
        [acc[0] / m_total, acc[1] / m_total, acc[2] / m_total],
        "known",
        unit="m",
        source="parts",
    )


def battery_energy_claims(parts: list[dict]) -> tuple[Claim, Claim, list[Claim]]:
    energy_total = 0.0
    have = False
    missing: list[str] = []
    quarantined: list[Claim] = []
    conflicted = False
    raw_kept: float | None = None
    for part in parts:
        if not isinstance(part, dict):
            continue
        if str(part.get("type") or "").lower() != "battery":
            continue
        pid = part_id_of(part)
        specs = part_specs(part)
        raw = first_present(specs, "energy_wh", "energy_Wh", "wh")
        if raw is None:
            raw = first_present(part, "energy_wh", "energy_Wh", "wh")
        if raw is None:
            missing.append(f"parts.{pid}.specs.energy_wh")
            continue
        energy = as_float(raw)
        if energy is None:
            missing.append(f"parts.{pid}.specs.energy_wh")
            continue
        have = True
        energy_total += energy
        raw_kept = energy if raw_kept is None else raw_kept
        mass, mass_field, _ = part_mass_kg(part)
        chem = first_present(specs, "chemistry", "cell", "cell_chemistry")
        if chem is None:
            chem = first_present(part, "chemistry", "cell")
        if mass is None:
            missing.append(mass_field or f"parts.{pid}.mass_kg")
            continue
        spec_e = specific_energy_wh_kg(energy, mass)
        limit = chemistry_wh_per_kg_limit(str(chem) if chem is not None else None)
        if spec_e is not None and spec_e > limit:
            conflicted = True
            quarantined.append(
                quarantine_input(
                    energy,
                    field=f"parts.{pid}.specs.energy_wh",
                    reason=(
                        f"specific energy {spec_e:.4g} Wh/kg exceeds {limit:g} Wh/kg "
                        f"({'Li-ion' if limit >= 270 else 'LiPo'}); raw value retained"
                    ),
                    unit="Wh",
                )
            )
    if not have:
        return (
            unknown_claim(unit="Wh", missing_fields=unique(missing) or ["parts.battery.specs.energy_wh"]),
            unknown_claim(unit="Wh"),
            quarantined,
        )
    status = "conflicted" if conflicted else "known"
    notes = None
    if conflicted:
        notes = "raw battery energy retained; not clamped"
        raw_kept = energy_total
    energy_claim = make_claim(
        energy_total,
        status,
        unit="Wh",
        source="parts",
        notes=notes,
        missing_fields=unique(missing),
    )
    return energy_claim, make_claim(energy_total, status, unit="Wh"), quarantined


def usable_energy(energy_claim: Claim, reserve: float | None, reserve_missing: list[str]) -> Claim:
    if energy_claim.value is None or reserve is None:
        miss = list(energy_claim.missing_fields) + list(reserve_missing)
        if energy_claim.value is None and not energy_claim.missing_fields:
            miss.append("battery.energy_wh")
        if reserve is None:
            miss.append("mission.reserve_fraction")
        return unknown_claim(unit="Wh", missing_fields=unique(miss))
    usable = float(energy_claim.value) * (1.0 - reserve)
    status = energy_claim.status if energy_claim.status in {"conflicted", "assumed"} else "known"
    return make_claim(
        usable,
        status,
        unit="Wh",
        source="computed",
        assumption_range=assumption_band(usable, ASSUMPTION_FRAC),
        notes="E_usable = energy_wh * (1 - reserve_fraction); assumption range, not a CI",
    )


def layout_of(geometry: dict) -> tuple[str | None, list[str]]:
    vtail = geometry.get("vtail") if isinstance(geometry.get("vtail"), dict) else {}
    tail = geometry.get("tail") if isinstance(geometry.get("tail"), dict) else {}
    if "layout" in vtail:
        layout = vtail.get("layout")
        if layout is None:
            return None, ["vtail.layout"]
        return str(layout).lower(), []
    if "layout" in tail:
        layout = tail.get("layout")
        if layout is None:
            return None, ["tail.layout"]
        return str(layout).lower(), []
    return None, ["vtail.layout"]


def compute_tail(geometry: dict) -> dict[str, Any]:
    """Horizontal/vertical tail volumes. V-tail cant is from the HORIZONTAL."""
    s, b, c, ref_missing = reference_sbc(geometry)
    layout, layout_missing = layout_of(geometry)
    vtail = geometry.get("vtail") if isinstance(geometry.get("vtail"), dict) else {}
    tail = geometry.get("tail") if isinstance(geometry.get("tail"), dict) else {}
    src = vtail or tail
    htail = geometry.get("htail") if isinstance(geometry.get("htail"), dict) else {}
    vfin = geometry.get("vfin") if isinstance(geometry.get("vfin"), dict) else {}
    missing: list[str] = list(layout_missing)
    info: dict[str, Any] = {
        "layout": layout,
        "V_h": None,
        "V_v": None,
        "S_h_eff": None,
        "S_v_eff": None,
        "missing": missing,
        "heuristic": "conventional",
    }
    if layout is None:
        info["heuristic"] = "unknown"
        return info
    if layout in {"vtail", "v-tail", "v_tail"}:
        info["layout"] = "vtail"
        info["heuristic"] = "not_applicable"
        # Cant is the panel angle from HORIZONTAL (40 deg V-tail => each panel 40 deg
        # from horizontal). Then S_h_eff = 2*A*cos(cant), S_v_eff = 2*A*sin(cant).
        if "cant_rad" not in src:
            missing.append("vtail.cant_rad")
            info["missing"] = unique(missing)
            return info
        cant = as_float(src.get("cant_rad"))
        if cant is None:
            missing.append("vtail.cant_rad")
            info["missing"] = unique(missing)
            return info
        panel_area = as_float(first_present(src, "panel_area", "panel_area_m2", "area_each"))
        if panel_area is None and isinstance(src.get("panels"), list):
            areas = [as_float(p.get("area") if isinstance(p, dict) else p) for p in src["panels"]]
            if areas and all(a is not None for a in areas):
                s_h = 0.0
                s_v = 0.0
                for area in areas:
                    s_h += float(area) * math.cos(cant)
                    s_v += float(area) * math.sin(cant)
                panel_area = None
                info["S_h_eff"] = s_h
                info["S_v_eff"] = s_v
        if info["S_h_eff"] is None:
            if panel_area is None:
                missing.append("vtail.panel_area")
            else:
                info["S_h_eff"] = 2.0 * panel_area * math.cos(cant)
                info["S_v_eff"] = 2.0 * panel_area * math.sin(cant)
        arm = as_float(first_present(src, "tail_arm", "tail_arm_m", "arm", "l_t", "lv"))
        if arm is None:
            arm = as_float(first_present(tail, "tail_arm", "tail_arm_m", "arm", "l_h", "l_v"))
        if arm is None:
            missing.append("vtail.tail_arm")
        missing.extend(ref_missing)
        if missing:
            info["missing"] = unique(missing)
            return info
        assert s is not None and b is not None and c is not None
        info["V_h"] = info["S_h_eff"] * arm / (s * c)
        info["V_v"] = info["S_v_eff"] * arm / (s * b)
        info["missing"] = []
        return info

    info["layout"] = "conventional"
    info["heuristic"] = "conventional"
    s_h = as_float(first_present(htail, "S", "area", "area_m2"))
    s_v = as_float(first_present(vfin, "S", "area", "area_m2"))
    if s_h is None:
        s_h = as_float(first_present(tail, "S_h", "sh", "horizontal_area", "horizontal_area_m2"))
    if s_v is None:
        s_v = as_float(first_present(tail, "S_v", "sv", "vertical_area", "vertical_area_m2"))
    l_h = as_float(first_present(htail, "arm", "l_h", "tail_arm", "tail_arm_m"))
    l_v = as_float(first_present(vfin, "arm", "l_v", "tail_arm", "tail_arm_m"))
    if l_h is None:
        l_h = as_float(first_present(tail, "l_h", "arm", "tail_arm", "tail_arm_m"))
    if l_v is None:
        l_v = as_float(first_present(tail, "l_v", "arm", "tail_arm", "tail_arm_m"))
    if s_h is None:
        missing.append("tail.S_h")
    if s_v is None:
        missing.append("tail.S_v")
    if l_h is None:
        missing.append("tail.l_h")
    if l_v is None:
        missing.append("tail.l_v")
    missing.extend(ref_missing)
    if missing:
        info["missing"] = unique(missing)
        return info
    assert s is not None and b is not None and c is not None
    info["S_h_eff"] = s_h
    info["S_v_eff"] = s_v
    info["V_h"] = s_h * l_h / (s * c)
    info["V_v"] = s_v * l_v / (s * b)
    info["missing"] = []
    return info


def _row_alpha_rad(row: dict) -> float | None:
    rad = as_float(row.get("alpha_rad"))
    if rad is not None:
        return rad
    deg = as_float(row.get("alpha_deg"))
    if deg is not None:
        return math.radians(deg)
    return as_float(first_present(row, "alpha", "a"))


def _interp_at(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if xs[i] >= x:
            span = xs[i] - xs[i - 1]
            if span == 0:
                return ys[i]
            t = (x - xs[i - 1]) / span
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def _solver_polar_points(solver_result: dict) -> list[tuple[float, float, float]]:
    """(alpha_rad, CL, CDi) from a C4 polar or parallel CL/CDi arrays."""
    pts: list[tuple[float, float, float]] = []
    polar = solver_result.get("polar")
    if not isinstance(polar, list) or not polar:
        polar = solver_result.get("CL_alpha")
    if isinstance(polar, list):
        for row in polar:
            if not isinstance(row, dict):
                continue
            pcl = as_float(row.get("CL"))
            pcdi = as_float(first_present(row, "CDi", "CD_induced"))
            if pcl is None or pcdi is None:
                continue
            alpha = _row_alpha_rad(row)
            pts.append((0.0 if alpha is None else alpha, pcl, pcdi))
    if pts:
        return pts
    cls = solver_result.get("CL")
    cdis = first_present(solver_result, "CDi", "CD_induced")
    if not isinstance(cls, (list, tuple)) or not isinstance(cdis, (list, tuple)):
        return []
    if len(cls) == 0 or len(cls) != len(cdis):
        return []
    alphas_rad = solver_result.get("alphas_rad")
    if not isinstance(alphas_rad, list):
        alphas_deg = solver_result.get("alphas_deg")
        alphas_rad = []
        if isinstance(alphas_deg, list):
            for raw in alphas_deg:
                deg = as_float(raw)
                alphas_rad.append(math.radians(deg) if deg is not None else None)
    for i, (cl_raw, cdi_raw) in enumerate(zip(cls, cdis, strict=True)):
        pcl = as_float(cl_raw)
        pcdi = as_float(cdi_raw)
        if pcl is None or pcdi is None:
            continue
        alpha = as_float(alphas_rad[i]) if i < len(alphas_rad) else None
        pts.append((0.0 if alpha is None else alpha, pcl, pcdi))
    return pts


def extract_solver_cl_cdi(solver_result: dict, cl_trim: float | None) -> tuple[float | None, float | None]:
    """Lift and induced drag from a solver result.

    Polar path: CDi is linearly interpolated vs CL at trim CL (W/qS). Level-flight
    CL stays the trim value; analytic k*CL^2 is not used. Scalar CL/CDi are a
    fallback when no polar is present.
    """
    pts = _solver_polar_points(solver_result)
    if pts:
        if cl_trim is not None:
            ordered = sorted(pts, key=lambda p: p[1])
            cdi = _interp_at([p[1] for p in ordered], [p[2] for p in ordered], cl_trim)
            return cl_trim, cdi
        nearest = min(pts, key=lambda p: abs(p[0]))
        return nearest[1], nearest[2]
    cl = as_float(solver_result.get("CL"))
    cdi = as_float(first_present(solver_result, "CDi", "CD_induced", "CDi_CL"))
    if cl is not None and cdi is not None:
        return cl, cdi
    if cdi is not None:
        return cl, cdi
    return None, None


def aero_metrics(
    *,
    geometry: dict,
    mass_claim: Claim,
    rho: float | None,
    v: float | None,
    g: float | None,
    solver_cl: float | None,
    solver_cdi: float | None,
    fidelity: str,
) -> dict[str, Claim]:
    s, b, c, ref_missing = reference_sbc(geometry)
    cd_profile, miss_p = aero_coeff(geometry, "CD_profile", "cd_profile", "CD0_profile")
    cd_fuse, miss_f = aero_coeff(geometry, "CD_fuselage", "cd_fuselage", "CD0_fuselage")
    cd_int, miss_i = aero_coeff(geometry, "CD_interference", "cd_interference", "CD0_interference")
    e, miss_e = aero_coeff(geometry, "e", "oswald_e")
    out: dict[str, Claim] = {}
    src = "vspaero" if fidelity == "vspaero" else "analytic"

    def assumed_coeff(val: float | None, miss: list[str], name: str, status_if_ok: str = "assumed") -> Claim:
        if val is None:
            return unknown_claim(missing_fields=miss, source="geometry")
        rng = assumption_band(val, ASSUMPTION_FRAC) if name in {"e", "CD_profile", "CD_fuselage", "CD_interference"} else None
        return make_claim(val, status_if_ok, source="geometry.aero", assumption_range=rng)

    out["CD_profile"] = assumed_coeff(cd_profile, miss_p, "CD_profile")
    out["CD_fuselage"] = assumed_coeff(cd_fuse, miss_f, "CD_fuselage")
    out["CD_interference"] = assumed_coeff(cd_int, miss_i, "CD_interference")
    out["e"] = assumed_coeff(e, miss_e, "e")
    if out["e"].value is not None:
        out["e"] = out["e"].model_copy(update={"assumption_range": assumption_band(float(out["e"].value))})

    parasite_ok = all(out[k].value is not None for k in ("CD_profile", "CD_fuselage", "CD_interference"))
    cd0 = None
    if parasite_ok:
        cd0 = float(out["CD_profile"].value) + float(out["CD_fuselage"].value) + float(out["CD_interference"].value)
        out["CD0"] = make_claim(
            cd0,
            "assumed",
            source="geometry.aero",
            assumption_range=assumption_band(cd0, ASSUMPTION_FRAC),
            notes="CD0 = CD_profile + CD_fuselage + CD_interference (induced stored separately)",
        )
    else:
        miss = unique(miss_p + miss_f + miss_i)
        out["CD0"] = unknown_claim(missing_fields=miss)

    if s is None or b is None:
        out["AR"] = unknown_claim(missing_fields=ref_missing)
    else:
        out["AR"] = make_claim(b * b / s, "known", source="geometry.reference")

    k = None
    if out["AR"].value is not None and e is not None and float(out["AR"].value) != 0:
        k = 1.0 / (math.pi * e * float(out["AR"].value))
        out["k"] = make_claim(k, "known", source="analytic", notes="k = 1/(pi*e*AR)")
    else:
        out["k"] = unknown_claim(missing_fields=unique(ref_missing + miss_e))

    weight_missing: list[str] = []
    m = as_float(mass_claim.value) if mass_claim.status != "unknown" else None
    if m is None:
        weight_missing.extend(mass_claim.missing_fields or ["mass"])
    if g is None:
        weight_missing.append("mission.g")
    if m is None or g is None:
        out["W"] = unknown_claim(unit="N", missing_fields=unique(weight_missing))
    else:
        out["W"] = make_claim(m * g, "known", unit="N", source="computed")

    q_missing: list[str] = []
    if rho is None:
        q_missing.append("mission.rho")
    if v is None:
        q_missing.append("mission.cruise_mps")
    if rho is None or v is None:
        out["q"] = unknown_claim(unit="Pa", missing_fields=q_missing)
    else:
        out["q"] = make_claim(0.5 * rho * v * v, "known", unit="Pa", source="computed")

    cl_analytic = None
    cl_miss: list[str] = []
    w = as_float(out["W"].value)
    q = as_float(out["q"].value)
    if w is None:
        cl_miss.extend(out["W"].missing_fields)
    if q is None:
        cl_miss.extend(out["q"].missing_fields)
    if s is None:
        cl_miss.extend(ref_missing)
    if w is not None and q is not None and s is not None and q * s != 0:
        cl_analytic = w / (q * s)
    cl_use = solver_cl if solver_cl is not None else cl_analytic
    if cl_use is None:
        out["CL"] = unknown_claim(missing_fields=unique(cl_miss), source=src)
    else:
        cl_notes = None
        if solver_cl is not None:
            cl_notes = "solver-informed CL; CDi is solver CDi, not k*CL^2"
        out["CL"] = make_claim(cl_use, "known", source=src, notes=cl_notes)

    cdi = None
    if solver_cdi is not None:
        cdi = solver_cdi
        out["CD_induced"] = make_claim(
            cdi,
            "known",
            source="vspaero",
            notes="induced drag replaced from solver CDi; analytic k*CL^2 is not added",
        )
    elif k is not None and cl_use is not None:
        cdi = k * cl_use * cl_use
        out["CD_induced"] = make_claim(
            cdi,
            "known",
            source="analytic",
            notes="CD_induced = k*CL^2; not included in CD0",
        )
    else:
        out["CD_induced"] = unknown_claim(
            missing_fields=unique(out["k"].missing_fields + out["CL"].missing_fields)
        )

    if cd0 is not None and cdi is not None:
        cd = cd0 + cdi
        out["CD"] = make_claim(
            cd,
            "known",
            source=src,
            notes="CD = CD_profile + CD_fuselage + CD_interference + CD_induced",
        )
    else:
        miss = unique(out["CD0"].missing_fields + out["CD_induced"].missing_fields)
        out["CD"] = unknown_claim(missing_fields=miss)

    cl_v = as_float(out["CL"].value)
    cd_v = as_float(out["CD"].value)
    if cl_v is None or cd_v is None or cd_v == 0:
        out["L/D"] = unknown_claim(missing_fields=unique(out["CL"].missing_fields + out["CD"].missing_fields))
    else:
        out["L/D"] = make_claim(cl_v / cd_v, "known", source=src)

    clmax, miss_clmax = aero_coeff(geometry, "CLmax", "cl_max", "CL_max")
    if clmax is None or w is None or rho is None or s is None or rho <= 0 or s <= 0 or clmax <= 0:
        miss = unique((miss_clmax if clmax is None else []) + (out["W"].missing_fields if w is None else []) + (["mission.rho"] if rho is None else []) + (ref_missing if s is None else []))
        out["stall"] = unknown_claim(unit="m/s", missing_fields=miss, notes="VSPAERO linear lift does not establish CLmax")
    else:
        v_stall = math.sqrt(2.0 * w / (rho * s * clmax))
        out["stall"] = make_claim(v_stall, "known", unit="m/s", source="analytic", notes="V_stall = sqrt(2W/(rho*S*CLmax))")
    return out


def spar_parts(parts: list[dict], geometry: dict) -> list[dict]:
    found = [p for p in parts if isinstance(p, dict) and str(p.get("type") or "").lower() == "spar"]
    geo = geometry.get("spar") if isinstance(geometry.get("spar"), dict) else {}
    if found:
        return found
    count = as_float(geo.get("count"))
    n = int(count) if count is not None and count > 0 else 0
    if n <= 0:
        return []
    return [{"id": f"spar_{i}", "type": "spar", "specs": dict(geo)} for i in range(n)]


def _spar_dim(part: dict, geometry: dict, *keys: str) -> float | None:
    specs = part_specs(part)
    geo = geometry.get("spar") if isinstance(geometry.get("spar"), dict) else {}
    for src in (specs, part, geo):
        val = as_float(first_present(src, *keys))
        if val is not None:
            return val
    return None


def spar_safety(geometry: dict, parts: list[dict], w_claim: Claim) -> Claim:
    """Cantilever spars, 21 stations, BM shared by stiffness.

    Root moment is 3.5 g * W * (b/4): a simple elliptic/rect load assumption,
    not a FEM result. Equal spars (equal I, same E) share the moment equally.
    """
    if w_claim.value is None:
        return unknown_claim(
            missing_fields=unique(w_claim.missing_fields + ["W"]),
            notes="weight-dependent spar check",
        )
    w = float(w_claim.value)
    s, b, c, ref_missing = reference_sbc(geometry)
    if b is None or b <= 0:
        return unknown_claim(missing_fields=unique(ref_missing or ["geometry.reference.b"]))
    spars = spar_parts(parts, geometry)
    if not spars:
        return unknown_claim(missing_fields=["parts.spar", "geometry.spar"])
    items: list[dict[str, float]] = []
    missing: list[str] = []
    for part in spars:
        pid = str(part.get("id") or "spar")
        do = _spar_dim(part, geometry, "Do", "do", "od", "outer_d", "outer_diameter")
        di = _spar_dim(part, geometry, "Di", "di", "id", "inner_d", "inner_diameter")
        allow = _spar_dim(part, geometry, "allow_pa", "allow", "sigma_allow_pa")
        if allow is None:
            allow_mpa = _spar_dim(part, geometry, "allow_mpa", "sigma_allow_mpa")
            if allow_mpa is not None:
                allow = allow_mpa * 1e6
        e_mod = _spar_dim(part, geometry, "E", "e_pa", "modulus_pa")
        if do is None:
            missing.append(f"parts.{pid}.specs.Do")
        if di is None:
            missing.append(f"parts.{pid}.specs.Di")
        if allow is None:
            missing.append(f"parts.{pid}.specs.allow_pa")
        if do is None or di is None or allow is None:
            continue
        inertia = math.pi * (do**4 - di**4) / 64.0
        if inertia <= 0:
            missing.append(f"parts.{pid}.specs.I")
            continue
        stiffness = (e_mod if e_mod is not None else 1.0) * inertia
        items.append({"Do": do, "Di": di, "I": inertia, "allow": allow, "stiff": stiffness})
    if missing or not items:
        return unknown_claim(missing_fields=unique(missing or ["geometry.spar"]))
    ksum = sum(item["stiff"] for item in items)
    if ksum <= 0:
        return unknown_claim(missing_fields=["spar.stiffness"])
    # Root BM = n W (b/4). Spanwise shape is rectangular-load (1-y/L)^2 scaled to that root.
    m_root = LOAD_FACTOR_G * w * (b / 4.0)
    sigma_max = 0.0
    for i in range(SPAR_STATIONS):
        y = (b / 2.0) * (i / (SPAR_STATIONS - 1))
        span_frac = 1.0 - (y / (b / 2.0))
        m_total = m_root * span_frac * span_frac
        for item in items:
            m_share = m_total * (item["stiff"] / ksum)
            sigma = m_share * (item["Do"] / 2.0) / item["I"]
            if sigma > sigma_max:
                sigma_max = sigma
    if sigma_max <= 0:
        return unknown_claim(notes="zero bending stress")
    allow_min = min(item["allow"] for item in items)
    sf = allow_min / sigma_max
    return make_claim(
        sf,
        "known",
        source="analytic",
        notes="3.5 g * W * (b/4) root BM, elliptic/rect assumption; 21 stations; BM shared by I",
    )


def _motor_prop_battery(parts: list[dict]) -> dict[str, Any]:
    motor = next((p for p in parts if str(p.get("type") or "").lower() == "motor"), None)
    prop = next((p for p in parts if str(p.get("type") or "").lower() in {"prop", "propeller"}), None)
    esc = next((p for p in parts if str(p.get("type") or "").lower() == "esc"), None)
    batt = next((p for p in parts if str(p.get("type") or "").lower() == "battery"), None)
    return {"motor": motor, "prop": prop, "esc": esc, "battery": batt}


def propulsion_level_flight(
    parts: list[dict],
    *,
    drag_n: float | None,
    v_mps: float | None,
    rho: float | None,
) -> dict[str, Any]:
    """Solve throttle for T=D when motor + prop aero + battery voltage are present."""
    result: dict[str, Any] = {
        "I_a": None,
        "throttle": None,
        "P_elec": None,
        "T": None,
        "missing": [],
        "motor_imax": None,
        "esc_imax": None,
        "batt_imax": None,
    }
    bits = _motor_prop_battery(parts)
    motor, prop, esc, batt = bits["motor"], bits["prop"], bits["esc"], bits["battery"]
    missing: list[str] = []
    if motor is None:
        missing.append("parts.motor")
    if prop is None:
        missing.append("parts.prop")
    if batt is None:
        missing.append("parts.battery")
    mspec = part_specs(motor) if motor else {}
    pspec = part_specs(prop) if prop else {}
    espec = part_specs(esc) if esc else {}
    bspec = part_specs(batt) if batt else {}
    kv = as_float(first_present(mspec, "kv", "KV", "kv_rpm_v"))
    rm = as_float(first_present(mspec, "rm", "Rm", "rm_ohm"))
    i0 = as_float(first_present(mspec, "i0", "I0", "i0_a"))
    imax = as_float(first_present(mspec, "imax", "Imax", "imax_a"))
    result["motor_imax"] = imax
    result["esc_imax"] = as_float(first_present(espec, "imax", "Imax", "imax_a"))
    ct = as_float(first_present(pspec, "Ct", "ct", "thrust_coeff"))
    cp = as_float(first_present(pspec, "Cp", "cp", "power_coeff"))
    d_prop = as_float(first_present(pspec, "D", "diameter_m", "diameter"))
    v_batt = as_float(first_present(bspec, "V", "voltage_v", "v", "nominal_v"))
    ir = as_float(first_present(bspec, "ir_ohm", "IR", "ir", "internal_resistance_ohm"))
    c_rate = as_float(first_present(bspec, "c_rate", "C", "c_rating"))
    if kv is None:
        missing.append("parts.motor.specs.kv")
    if rm is None:
        missing.append("parts.motor.specs.rm")
    if i0 is None:
        missing.append("parts.motor.specs.i0")
    if ct is None:
        missing.append("parts.prop.specs.Ct")
    if cp is None:
        missing.append("parts.prop.specs.Cp")
    if d_prop is None:
        missing.append("parts.prop.specs.D")
    if v_batt is None:
        missing.append("parts.battery.specs.V")
    if drag_n is None:
        missing.append("drag")
    if v_mps is None:
        missing.append("mission.cruise_mps")
    if rho is None:
        missing.append("mission.rho")
    if ir is None:
        ir = 0.0
    if c_rate is not None and v_batt is not None:
        energy = as_float(first_present(bspec, "energy_wh", "energy_Wh"))
        if energy is not None and v_batt != 0:
            result["batt_imax"] = c_rate * (energy / v_batt)
    result["missing"] = unique(missing)
    if missing:
        return result
    assert drag_n is not None and ct is not None and rho is not None and d_prop is not None
    if ct <= 0 or rho <= 0 or d_prop <= 0 or drag_n < 0:
        result["missing"] = unique(missing + ["propulsion.domain"])
        return result
    n_rps = math.sqrt(drag_n / (ct * rho * d_prop**4))
    omega = 2.0 * math.pi * n_rps
    p_shaft = cp * rho * (n_rps**3) * (d_prop**5)
    kt = 60.0 / (2.0 * math.pi * kv) if kv else None
    if kt is None or omega <= 0:
        result["missing"] = unique(missing + ["parts.motor.specs.kv"])
        return result
    i_a = i0 + p_shaft / (omega * kt)
    rpm = n_rps * 60.0
    v_back = rpm / kv
    v_motor = v_back + i_a * rm
    v_pack = v_motor + i_a * ir
    throttle = v_pack / v_batt if v_batt else None
    result["I_a"] = i_a
    result["throttle"] = throttle
    result["P_elec"] = v_pack * i_a
    result["T"] = drag_n
    result["missing"] = []
    return result


def performance(
    *,
    p_elec: float | None,
    v_mps: float | None,
    e_usable: Claim,
    p_missing: list[str],
) -> dict[str, Claim]:
    out: dict[str, Claim] = {}
    if p_elec is None or v_mps is None or v_mps == 0:
        miss = unique(p_missing + (["mission.cruise_mps"] if v_mps is None else []))
        out["Wh/km"] = unknown_claim(unit="Wh/km", missing_fields=miss)
    else:
        wh_per_km = p_elec / (3.6 * v_mps)
        out["Wh/km"] = make_claim(wh_per_km, "known", unit="Wh/km", source="computed")
    if p_elec is None or p_elec == 0 or e_usable.value is None:
        miss = unique(list(e_usable.missing_fields) + p_missing)
        out["endurance"] = unknown_claim(unit="min", missing_fields=miss)
        out["range"] = unknown_claim(unit="km", missing_fields=miss)
        return out
    e_wh = float(e_usable.value)
    endurance_min = 60.0 * e_wh / p_elec
    out["endurance"] = make_claim(
        endurance_min,
        e_usable.status if e_usable.status == "conflicted" else "known",
        unit="min",
        source="computed",
        assumption_range=assumption_band(endurance_min, ASSUMPTION_FRAC),
        notes="endurance_min = 60 * E_usable_Wh / P_elec; assumption range, not a CI",
    )
    wh_per_km = as_float(out["Wh/km"].value)
    if wh_per_km is None or wh_per_km == 0:
        out["range"] = unknown_claim(unit="km", missing_fields=out["Wh/km"].missing_fields)
    else:
        out["range"] = make_claim(e_wh / wh_per_km, "known", unit="km", source="computed")
    return out


def static_margin(geometry: dict, cg: Claim, mac: float | None, mac_missing: list[str]) -> Claim:
    """SM = (x_CG - x_NP)/MAC in FRD. Prefer unknown unless NP status is known."""
    np_obj = None
    for key in ("neutral_point", "np", "x_np"):
        if key in geometry:
            np_obj = geometry.get(key)
            break
    stab = geometry.get("stability") if isinstance(geometry.get("stability"), dict) else {}
    if np_obj is None and "x_np" in stab:
        np_obj = stab.get("x_np")
    if np_obj is None:
        return unknown_claim(
            missing_fields=["geometry.neutral_point"],
            notes="static margin stays unknown without a provided NP",
        )
    np_status = "known"
    x_np = None
    if isinstance(np_obj, dict):
        x_np = as_float(first_present(np_obj, "x", "x_m", "value"))
        np_status = str(np_obj.get("status") or "assumed").lower()
    else:
        x_np = as_float(np_obj)
        np_status = "assumed"
    if x_np is None:
        return unknown_claim(missing_fields=["geometry.neutral_point.x"])
    if cg.value is None:
        return unknown_claim(missing_fields=unique(cg.missing_fields + ["cg"]))
    cg_x = None
    if isinstance(cg.value, (list, tuple)) and cg.value:
        cg_x = as_float(cg.value[0])
    else:
        cg_x = as_float(cg.value)
    if cg_x is None or mac is None or mac == 0:
        miss = unique(cg.missing_fields + (mac_missing if mac is None else []))
        return unknown_claim(missing_fields=miss)
    sm = (cg_x - x_np) / mac
    if np_status != "known":
        return make_claim(
            sm,
            "estimated" if np_status in {"assumed", "estimated"} else "unknown",
            source="geometry.neutral_point",
            notes="NP is not a validated derivative; check stays unknown",
        )
    return make_claim(sm, "known", source="geometry.neutral_point")


def drag_force_n(cd: Claim, q: Claim, s: float | None) -> float | None:
    if cd.value is None or q.value is None or s is None:
        return None
    return float(cd.value) * float(q.value) * s
