"""Generate aircraft.vsp3 and run VSPAEROSweep. Import openvsp only in the ABI-matched interpreter."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import traceback
from pathlib import Path
from typing import Any

_PACKAGES = Path(__file__).resolve().parent.parent
if str(_PACKAGES) not in sys.path:
    sys.path.insert(0, str(_PACKAGES))

from openvsp_worker.geometry import GeometrySpec, load_spec  # noqa: E402

TESS_U_BASE = 8
TESS_W_BASE = 17
TESS_U_FINE = 16
TESS_W_FINE = 33
WAKE_NUM_ITER = 3
MESH_ALPHA_DEG = 2.0
SYM_CY_TOL = 5.0e-3
SYM_CL_ROLL_TOL = 5.0e-3

# This 3.51.3 VSPAEROSweep AlphaStart/AlphaEnd are degrees.
# Evidence: GetAnalysisInputDoc defaults AlphaStart=0, AlphaEnd=10 (10 rad would be 573 deg);
# shipped SweptTest.py / HersheyTest.py pass 1.0 and convert CL_alpha with pi/180.
ALPHA_UNIT = "deg"
ALPHA_UNIT_EVIDENCE = (
    "OpenVSP 3.51.3 VSPAEROSweep AlphaStart/AlphaEnd are degrees. "
    "GetAnalysisInputDoc: defaults AlphaStart=0.0, AlphaEnd=10.0, AlphaNpts=3. "
    "Shipped /opt/OpenVSP/scripts/python_scripts/SweptTest.py and HersheyTest.py "
    "set AlphaStart=[1.0] and treat CL_alpha as per-degree (multiply theoretical per-rad by pi/180). "
    "Adapter does not convert to radians."
)


def run(geometry_path: str | Path, out_dir: str | Path, geometry_hash: str | None = None) -> dict[str, Any]:
    import openvsp as vsp  # type: ignore

    geometry_path = Path(geometry_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(out_dir)

    geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
    spec = load_spec(geometry)
    if not geometry_hash:
        from openvsp_worker.geometry import geometry_hash as _hash

        geometry_hash = _hash(geometry)

    versions = {
        "openvsp": vsp.GetVSPVersion(),
        "vspaero": None,
        "interpreter": sys.executable,
        "python_version": sys.version,
        "abi": "cp314",
    }
    try:
        versions["vspaero_path"] = vsp.GetVSPAEROPath()
    except Exception as exc:  # noqa: BLE001
        versions["vspaero_path_error"] = repr(exc)
    try:
        import subprocess

        bin_path = "/opt/OpenVSP/vspaero"
        if os.path.isfile(bin_path):
            proc = subprocess.run(
                [bin_path],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
                stdin=subprocess.DEVNULL,
            )
            text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
            versions["vspaero"] = text.splitlines()[0].strip() if text else None
    except Exception as exc:  # noqa: BLE001
        versions["vspaero_error"] = repr(exc)

    result: dict[str, Any] = {
        "geometry_hash": geometry_hash,
        "alphas_deg": list(spec.alphas_deg),
        "CL": [],
        "CDi": [],
        "Sref": spec.sref_m2,
        "bref": spec.bref_m,
        "cref": spec.cref_m,
        "Vinf": spec.vinf_mps,
        "Rho": spec.rho_kgm3,
        "altitude_m": spec.altitude_m,
        "mesh_delta": {},
        "polar": [],
        "raw": {},
        "versions": versions,
        "solver_versions": versions,
        "notes": list(spec.notes),
        "alpha_unit": ALPHA_UNIT,
        "alpha_unit_evidence": ALPHA_UNIT_EVIDENCE,
        "spec": spec.to_dict(),
        "error": None,
        "validation": {"all_passed": False, "checks": []},
    }

    vsp3_path = out_dir / "aircraft.vsp3"
    log_path = out_dir / "vspaero.log"
    inputs_path = out_dir / "solver_inputs.json"
    raw_path = out_dir / "raw_outputs.json"
    csv_path = out_dir / "vspaero_results.csv"
    result_path = out_dir / "sweep_result.json"

    try:
        _build_model(vsp, spec, tess_u=TESS_U_BASE, tess_w=TESS_W_BASE)
        geom_info = _geom_info(vsp, spec)
        result["geometry_info"] = geom_info
        vsp.WriteVSPFile(str(vsp3_path), vsp.SET_ALL)
        _drain(vsp)
        vsp.ClearVSPModel()
        vsp.ReadVSPFile(str(vsp3_path))
        vsp.Update()
        _drain(vsp)

        ncpu = max(1, min(int(os.cpu_count() or 4), 8))
        compute_set = {
            "GeomSet": int(vsp.SET_NONE),
            "ThinGeomSet": int(vsp.SET_ALL),
            "NRef": 0,
            "Symmetry": 0,
        }
        _run_compute_geometry(vsp, compute_set)

        sweep_set = {
            "GeomSet": int(vsp.SET_NONE),
            "ThinGeomSet": int(vsp.SET_ALL),
            "RefFlag": int(vsp.MANUAL_REF),
            "Symmetry": 0,
            "Sref": float(spec.sref_m2),
            "bref": float(spec.bref_m),
            "cref": float(spec.cref_m),
            "Rho": float(spec.rho_kgm3),
            "Vinf": float(spec.vinf_mps),
            "Vref": float(spec.vinf_mps),
            "ManualVrefFlag": 1,
            "MachStart": 0.0,
            "MachEnd": 0.0,
            "MachNpts": 1,
            "AlphaStart": float(spec.alphas_deg[0]),
            "AlphaEnd": float(spec.alphas_deg[-1]),
            "AlphaNpts": int(len(spec.alphas_deg)),
            "BetaStart": 0.0,
            "BetaEnd": 0.0,
            "BetaNpts": 1,
            "WakeNumIter": WAKE_NUM_ITER,
            "NCPU": ncpu,
            "RedirectFile": str(log_path),
            "StallModel": 0,
        }
        rid, sweep_readback = _run_sweep(vsp, sweep_set)
        try:
            vsp.WriteResultsCSVFile(rid, str(csv_path))
        except Exception as exc:  # noqa: BLE001
            result.setdefault("warnings", []).append(f"WriteResultsCSVFile: {exc!r}")

        polar, raw_cases = _extract_polar(vsp, rid, spec)
        result["polar"] = polar
        result["CL"] = [row.get("CL") for row in polar]
        result["CDi"] = [row.get("CDi") for row in polar]
        result["alphas_deg_result"] = [row.get("alpha_deg") for row in polar]

        compute_readback = _read_inputs(vsp, "VSPAEROComputeGeometry")
        solver_inputs = {
            "alpha_unit": ALPHA_UNIT,
            "alpha_unit_evidence": ALPHA_UNIT_EVIDENCE,
            "VSPAEROComputeGeometry_set": compute_set,
            "VSPAEROComputeGeometry_readback": compute_readback,
            "VSPAEROSweep_set": sweep_set,
            "VSPAEROSweep_readback": sweep_readback,
            "enumerated_VSPAEROSweep": list(vsp.GetAnalysisInputNames("VSPAEROSweep")),
            "enumerated_VSPAEROComputeGeometry": list(
                vsp.GetAnalysisInputNames("VSPAEROComputeGeometry")
            ),
        }
        inputs_path.write_text(json.dumps(_jsonable(solver_inputs), indent=2) + "\n", encoding="utf-8")

        raw = {
            "sweep_parent": _dump_result(vsp, rid, cap_len=80),
            "cases": raw_cases,
            "geometry_info": geom_info,
        }
        raw_path.write_text(json.dumps(_jsonable(raw), indent=2) + "\n", encoding="utf-8")

        mesh_delta = _refined_mesh_point(vsp, spec, polar, ncpu, log_path)
        result["mesh_delta"] = mesh_delta
        solver_inputs["refined_mesh"] = mesh_delta.get("solver_inputs")
        inputs_path.write_text(json.dumps(_jsonable(solver_inputs), indent=2) + "\n", encoding="utf-8")

        checks = _validate(spec, polar, sweep_readback, mesh_delta, geom_info)
        result["validation"] = {
            "all_passed": all(bool(c.get("pass")) for c in checks) and bool(checks),
            "checks": checks,
        }
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        if not result["validation"]["checks"]:
            result["validation"]["checks"] = [
                {
                    "name": "generate",
                    "pass": False,
                    "numbers": result["error"].splitlines()[0],
                }
            ]
            result["validation"]["all_passed"] = False

    result["raw"] = {
        "vsp3": str(vsp3_path),
        "solver_inputs": str(inputs_path),
        "outputs": str(raw_path),
        "csv": str(csv_path),
        "logs": str(log_path),
        "sweep_result": str(result_path),
    }
    result["paths"] = result["raw"]
    payload = _jsonable(result)
    result_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _build_model(vsp: Any, spec: GeometrySpec, *, tess_u: int, tess_w: int) -> None:
    vsp.ClearVSPModel()
    _drain(vsp)
    _add_main_wing(vsp, spec, tess_u=tess_u, tess_w=tess_w)
    _add_vtail(vsp, spec, tess_u=tess_u, tess_w=tess_w)
    vsp.Update()
    errors = _drain(vsp)
    if errors:
        raise RuntimeError("OpenVSP errors while building geometry: " + " | ".join(errors))


def _add_main_wing(vsp: Any, spec: GeometrySpec, *, tess_u: int, tess_w: int) -> str:
    wid = vsp.AddGeom("WING", "")
    vsp.SetGeomName(wid, "MainWing")
    _setp(vsp, wid, "Sym_Planar_Flag", "Sym", float(vsp.SYM_XZ))
    _setp(vsp, wid, "Tess_W", "Shape", tess_w)
    _setp(vsp, wid, "RotateAirfoilMatchDideralFlag", "WingGeom", 1.0)
    _setp(vsp, wid, "RelativeTwistFlag", "WingGeom", 0.0)
    _setp(vsp, wid, "RelativeDihedralFlag", "WingGeom", 0.0)
    n_needed = len(spec.sections)
    for _ in range(n_needed - 1):
        vsp.InsertXSec(wid, 1, vsp.XS_FOUR_SERIES)
    vsp.Update()
    for sec in spec.sections:
        i = sec.index
        group = f"XSec_{i}"
        vsp.SetDriverGroup(
            wid, i, vsp.SPAN_WSECT_DRIVER, vsp.ROOTC_WSECT_DRIVER, vsp.TIPC_WSECT_DRIVER
        )
        _setp(vsp, wid, "Span", group, sec.span_m)
        _setp(vsp, wid, "Sweep", group, sec.sweep_deg)
        _setp(vsp, wid, "Sweep_Location", group, 0.0)
        _setp(vsp, wid, "Dihedral", group, sec.dihedral_deg)
        _setp(vsp, wid, "Twist", group, sec.twist_out_deg)
        _setp(vsp, wid, "Tip_Chord", group, sec.tip_chord_m)
        if i == 1:
            _setp(vsp, wid, "Root_Chord", group, sec.root_chord_m)
        _setp(vsp, wid, "SectTess_U", group, tess_u)
        vsp.Update()
    _setp(vsp, wid, "X_Rel_Location", "XForm", spec.wing_x_rel_m)
    _setp(vsp, wid, "Y_Rel_Location", "XForm", 0.0)
    _setp(vsp, wid, "Z_Rel_Location", "XForm", spec.wing_z_rel_m)
    vsp.Update()
    return wid


def _add_vtail(vsp: Any, spec: GeometrySpec, *, tess_u: int, tess_w: int) -> str:
    wid = vsp.AddGeom("WING", "")
    vsp.SetGeomName(wid, "VTail")
    _setp(vsp, wid, "Sym_Planar_Flag", "Sym", float(vsp.SYM_XZ))
    _setp(vsp, wid, "Tess_W", "Shape", tess_w)
    _setp(vsp, wid, "RotateAirfoilMatchDideralFlag", "WingGeom", 1.0)
    vsp.SetDriverGroup(
        wid, 1, vsp.SPAN_WSECT_DRIVER, vsp.ROOTC_WSECT_DRIVER, vsp.TIPC_WSECT_DRIVER
    )
    # Sweep/twist are not in the fixture; zero avoids the WING default of 30 deg sweep.
    _setp(vsp, wid, "Span", "XSec_1", spec.panel_span_m)
    _setp(vsp, wid, "Root_Chord", "XSec_1", spec.panel_chord_m)
    _setp(vsp, wid, "Tip_Chord", "XSec_1", spec.panel_chord_m)
    _setp(vsp, wid, "Dihedral", "XSec_1", spec.cant_deg)
    _setp(vsp, wid, "Sweep", "XSec_1", 0.0)
    _setp(vsp, wid, "Sweep_Location", "XSec_1", 0.0)
    _setp(vsp, wid, "Twist", "XSec_1", 0.0)
    _setp(vsp, wid, "SectTess_U", "XSec_1", tess_u)
    _setp(vsp, wid, "X_Rel_Location", "XForm", spec.tail_x_rel_m)
    _setp(vsp, wid, "Y_Rel_Location", "XForm", 0.0)
    _setp(vsp, wid, "Z_Rel_Location", "XForm", 0.0)
    vsp.Update()
    return wid


def _set_tess(vsp: Any, geom_id: str, tess_u: int, tess_w: int, n_sections: int) -> None:
    _setp(vsp, geom_id, "Tess_W", "Shape", tess_w)
    for i in range(1, n_sections + 1):
        _setp(vsp, geom_id, "SectTess_U", f"XSec_{i}", tess_u)
    vsp.Update()


def _geom_info(vsp: Any, spec: GeometrySpec) -> dict[str, Any]:
    info: dict[str, Any] = {"geoms": []}
    for name in ("MainWing", "VTail"):
        ids = list(vsp.FindGeomsWithName(name))
        for gid in ids:
            item: dict[str, Any] = {
                "name": name,
                "id": gid,
                "sym": vsp.GetParmVal(gid, "Sym_Planar_Flag", "Sym"),
                "tess_w": vsp.GetParmVal(gid, "Tess_W", "Shape"),
                "total_span": vsp.GetParmVal(gid, "TotalSpan", "WingGeom"),
                "total_projected_span": vsp.GetParmVal(gid, "TotalProjectedSpan", "WingGeom"),
                "total_area": vsp.GetParmVal(gid, "TotalArea", "WingGeom"),
                "total_chord": vsp.GetParmVal(gid, "TotalChord", "WingGeom"),
            }
            try:
                item["bbox_min"] = _vec3(vsp.GetGeomBBoxMin(gid, 0, True))
                item["bbox_max"] = _vec3(vsp.GetGeomBBoxMax(gid, 0, True))
            except Exception as exc:  # noqa: BLE001
                item["bbox_error"] = repr(exc)
            info["geoms"].append(item)
    info["expected_half_span_m"] = spec.stations[-1].y_m
    info["expected_bref_m"] = spec.bref_m
    return info


def _run_compute_geometry(vsp: Any, values: dict[str, Any]) -> str:
    name = "VSPAEROComputeGeometry"
    vsp.SetAnalysisInputDefaults(name)
    for key, val in values.items():
        _set_input(vsp, name, key, val)
    rid = vsp.ExecAnalysis(name)
    errors = _drain(vsp)
    if not rid:
        raise RuntimeError("VSPAEROComputeGeometry returned no result id: " + " | ".join(errors))
    return rid


def _run_sweep(vsp: Any, values: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    name = "VSPAEROSweep"
    vsp.SetAnalysisInputDefaults(name)
    for key, val in values.items():
        _set_input(vsp, name, key, val)
    vsp.Update()
    readback = _read_inputs(vsp, name)
    rid = vsp.ExecAnalysis(name)
    errors = _drain(vsp)
    if not rid:
        raise RuntimeError("VSPAEROSweep returned no result id: " + " | ".join(errors))
    if errors:
        readback["openvsp_errors"] = errors
    return rid, readback


def _refined_mesh_point(
    vsp: Any,
    spec: GeometrySpec,
    polar: list[dict[str, Any]],
    ncpu: int,
    log_path: Path,
) -> dict[str, Any]:
    base = next((row for row in polar if _near(row.get("alpha_deg"), MESH_ALPHA_DEG)), None)
    if base is None and polar:
        base = min(polar, key=lambda r: abs((r.get("alpha_deg") or 0.0) - MESH_ALPHA_DEG))
    if base is None or base.get("CL") is None or base.get("CDi") is None:
        return {
            "error": "baseline polar missing CL/CDi at refined-mesh alpha",
            "alpha_deg": MESH_ALPHA_DEG,
        }

    wing_ids = list(vsp.FindGeomsWithName("MainWing"))
    tail_ids = list(vsp.FindGeomsWithName("VTail"))
    if not wing_ids or not tail_ids:
        return {"error": "MainWing/VTail not found for refined tessellation"}
    _set_tess(vsp, wing_ids[0], TESS_U_FINE, TESS_W_FINE, n_sections=len(spec.sections))
    _set_tess(vsp, tail_ids[0], TESS_U_FINE, TESS_W_FINE, n_sections=1)

    compute_set = {
        "GeomSet": int(vsp.SET_NONE),
        "ThinGeomSet": int(vsp.SET_ALL),
        "NRef": 0,
        "Symmetry": 0,
    }
    _run_compute_geometry(vsp, compute_set)
    alpha = float(base["alpha_deg"])
    sweep_set = {
        "GeomSet": int(vsp.SET_NONE),
        "ThinGeomSet": int(vsp.SET_ALL),
        "RefFlag": int(vsp.MANUAL_REF),
        "Symmetry": 0,
        "Sref": float(spec.sref_m2),
        "bref": float(spec.bref_m),
        "cref": float(spec.cref_m),
        "Rho": float(spec.rho_kgm3),
        "Vinf": float(spec.vinf_mps),
        "Vref": float(spec.vinf_mps),
        "ManualVrefFlag": 1,
        "MachStart": 0.0,
        "MachEnd": 0.0,
        "MachNpts": 1,
        "AlphaStart": alpha,
        "AlphaEnd": alpha,
        "AlphaNpts": 1,
        "WakeNumIter": WAKE_NUM_ITER,
        "NCPU": ncpu,
        "RedirectFile": str(log_path),
        "StallModel": 0,
    }
    rid, readback = _run_sweep(vsp, sweep_set)
    refined_polar, _raw = _extract_polar(vsp, rid, spec, npts=1)
    if not refined_polar:
        return {
            "error": "refined sweep returned no polar",
            "alpha_deg": alpha,
            "solver_inputs": sweep_set,
        }
    ref = refined_polar[0]
    dcl = float(ref["CL"]) - float(base["CL"])
    dcdi = float(ref["CDi"]) - float(base["CDi"])
    return {
        "alpha_deg": alpha,
        "tess_u_baseline": TESS_U_BASE,
        "tess_w_baseline": TESS_W_BASE,
        "tess_u_refined": TESS_U_FINE,
        "tess_w_refined": TESS_W_FINE,
        "nref_baseline": 0,
        "nref_refined": 0,
        "CL_baseline": float(base["CL"]),
        "CL_refined": float(ref["CL"]),
        "CDi_baseline": float(base["CDi"]),
        "CDi_refined": float(ref["CDi"]),
        "dCL": dcl,
        "dCDi": dcdi,
        "note": "Single refined-mesh point (SectTess_U and Tess_W doubled). Not a convergence study.",
        "solver_inputs": {"VSPAEROSweep_set": sweep_set, "VSPAEROSweep_readback": readback},
    }


def _extract_polar(
    vsp: Any, rid: str, spec: GeometrySpec, npts: int | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    npts = int(npts or len(spec.alphas_deg))
    names = set(vsp.GetAllDataNames(rid))
    children: list[str] = []
    if "ResultsVec" in names:
        children = [str(x) for x in vsp.GetStringResults(rid, "ResultsVec")]
    cases: list[str] = []
    raw_cases: list[dict[str, Any]] = []
    for child in children:
        dumped = _dump_result(vsp, child, cap_len=40)
        raw_cases.append(dumped)
        data_names = set(dumped.get("data_names") or [])
        if "CLtot" in data_names or "CL" in data_names:
            cases.append(child)
        if len(cases) >= npts:
            break
    if len(cases) < npts:
        # Fall back to latest history if ResultsVec was short.
        hist = vsp.FindLatestResultsID("VSPAERO_History")
        if hist and hist not in cases:
            cases.append(hist)
            raw_cases.append(_dump_result(vsp, hist, cap_len=40))

    polar: list[dict[str, Any]] = []
    for i, child in enumerate(cases[:npts]):
        alpha_name, alpha, _ = _last_double(vsp, child, "Alpha", "alpha", "Alpha_deg")
        cl_name, cl, _ = _last_double(vsp, child, "CLtot", "CL", "CLtot_avg")
        cdi_name, cdi, _ = _last_double(
            vsp, child, "CDi", "CDitot", "CDiTot", "CDind", "CDi_tot", "CDiTot_avg"
        )
        cy_name, cy, _ = _last_double(
            vsp, child, "CStot", "CYtot", "CY", "CFytot", "CYtot_avg"
        )
        cll_name, cll, _ = _last_double(
            vsp, child, "CMxtot", "Cltot", "Clltot", "CMx", "Cl_tot"
        )
        s_name, sref, _ = _last_double(vsp, child, "FC_Sref_", "Sref", "SREF")
        b_name, bref, _ = _last_double(vsp, child, "FC_Bref_", "bref", "Bref", "b_ref")
        c_name, cref, _ = _last_double(vsp, child, "FC_Cref_", "cref", "Cref", "c_ref")
        alpha_deg = float(alpha) if alpha is not None else float(spec.alphas_deg[min(i, len(spec.alphas_deg) - 1)])
        polar.append(
            {
                "alpha_deg": alpha_deg,
                "alpha_rad": math.radians(alpha_deg),
                "CL": cl,
                "CDi": cdi,
                "CY": cy,
                "Cl_rolling": cll,
                "Sref": sref,
                "bref": bref,
                "cref": cref,
                "fields": {
                    "alpha": alpha_name,
                    "CL": cl_name,
                    "CDi": cdi_name,
                    "CY": cy_name,
                    "Cl_rolling": cll_name,
                    "Sref": s_name,
                    "bref": b_name,
                    "cref": c_name,
                },
                "result_id": child,
            }
        )
    return polar, raw_cases


def _validate(
    spec: GeometrySpec,
    polar: list[dict[str, Any]],
    readback: dict[str, Any],
    mesh_delta: dict[str, Any],
    geom_info: dict[str, Any],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, numbers: Any) -> None:
        checks.append({"name": name, "pass": bool(passed), "numbers": numbers})

    collected: list[float] = []
    nonfinite: list[str] = []

    def take(label: str, value: Any) -> None:
        if value is None:
            return
        try:
            num = float(value)
        except (TypeError, ValueError):
            nonfinite.append(f"{label}={value!r}")
            return
        if not math.isfinite(num):
            nonfinite.append(f"{label}={num}")
            return
        collected.append(num)

    for i, row in enumerate(polar):
        for key in ("alpha_deg", "CL", "CDi", "CY", "Cl_rolling", "Sref", "bref", "cref"):
            take(f"polar[{i}].{key}", row.get(key))
    for key in ("Sref", "bref", "cref", "Rho", "Vinf", "AlphaStart", "AlphaEnd"):
        val = readback.get(key)
        if isinstance(val, list) and val:
            take(f"readback.{key}", val[0])
        else:
            take(f"readback.{key}", val)
    for key in ("CL_baseline", "CL_refined", "CDi_baseline", "CDi_refined", "dCL", "dCDi"):
        take(f"mesh.{key}", mesh_delta.get(key))

    add(
        "every returned number finite",
        (not nonfinite) and bool(collected),
        {"count": len(collected), "nonfinite": nonfinite, "min": min(collected) if collected else None, "max": max(collected) if collected else None},
    )

    s_rb = _first_num(readback.get("Sref"))
    b_rb = _first_num(readback.get("bref"))
    c_rb = _first_num(readback.get("cref"))
    s_hist = next((row.get("Sref") for row in polar if row.get("Sref") is not None), None)
    b_hist = next((row.get("bref") for row in polar if row.get("bref") is not None), None)
    c_hist = next((row.get("cref") for row in polar if row.get("cref") is not None), None)
    ref_ok = (
        s_rb is not None
        and b_rb is not None
        and c_rb is not None
        and abs(s_rb - spec.sref_m2) <= 1e-9
        and abs(b_rb - spec.bref_m) <= 1e-9
        and abs(c_rb - spec.cref_m) <= 1e-9
    )
    hist_ok = True
    if s_hist is not None:
        hist_ok = hist_ok and abs(float(s_hist) - spec.sref_m2) <= 1e-6
    if b_hist is not None:
        hist_ok = hist_ok and abs(float(b_hist) - spec.bref_m) <= 1e-6
    if c_hist is not None:
        hist_ok = hist_ok and abs(float(c_hist) - spec.cref_m) <= 1e-6
    add(
        "reference S/b/c come back as set",
        ref_ok and hist_ok,
        {
            "set_Sref": spec.sref_m2,
            "set_bref": spec.bref_m,
            "set_cref": spec.cref_m,
            "readback_Sref": s_rb,
            "readback_bref": b_rb,
            "readback_cref": c_rb,
            "history_Sref": s_hist,
            "history_bref": b_hist,
            "history_cref": c_hist,
        },
    )

    slopes: list[float | None] = []
    slope_ok = len(polar) >= 2
    for i in range(len(polar) - 1):
        a0 = polar[i].get("alpha_deg")
        a1 = polar[i + 1].get("alpha_deg")
        cl0 = polar[i].get("CL")
        cl1 = polar[i + 1].get("CL")
        if None in (a0, a1, cl0, cl1) or float(a1) == float(a0):
            slopes.append(None)
            slope_ok = False
            continue
        sl = (float(cl1) - float(cl0)) / (float(a1) - float(a0))
        slopes.append(sl)
        if not math.isfinite(sl) or sl <= 0.0:
            slope_ok = False
    add(
        "lift slope dCL/dalpha > 0 from -2 to 6 deg",
        slope_ok and len(polar) == len(spec.alphas_deg),
        {
            "alphas_deg": [row.get("alpha_deg") for row in polar],
            "CL": [row.get("CL") for row in polar],
            "dCL_dalpha_per_deg": slopes,
        },
    )

    cy_vals = [row.get("CY") for row in polar]
    cll_vals = [row.get("Cl_rolling") for row in polar]
    cy_ok = bool(cy_vals) and all(v is not None and abs(float(v)) <= SYM_CY_TOL for v in cy_vals)
    cll_ok = bool(cll_vals) and all(
        v is not None and abs(float(v)) <= SYM_CL_ROLL_TOL for v in cll_vals
    )
    add(
        "left/right symmetry (CStot side force, CMxtot rolling)",
        cy_ok and cll_ok,
        {
            "tolerance_abs_CStot": SYM_CY_TOL,
            "tolerance_abs_CMxtot": SYM_CL_ROLL_TOL,
            "CStot": cy_vals,
            "CMxtot": cll_vals,
            "max_abs_CStot": max((abs(float(v)) for v in cy_vals if v is not None), default=None),
            "max_abs_CMxtot": max((abs(float(v)) for v in cll_vals if v is not None), default=None),
            "method": "full-span model via OpenVSP SYM_XZ; VSPAEROSweep Symmetry=0; this 3.51.3 history names CStot (side) and CMxtot (roll)",
        },
    )

    dcl = mesh_delta.get("dCL")
    dcdi = mesh_delta.get("dCDi")
    mesh_ok = (
        dcl is not None
        and dcdi is not None
        and math.isfinite(float(dcl))
        and math.isfinite(float(dcdi))
        and mesh_delta.get("error") is None
    )
    add(
        "one refined-mesh point (not a convergence study)",
        mesh_ok,
        {
            "alpha_deg": mesh_delta.get("alpha_deg"),
            "CL_baseline": mesh_delta.get("CL_baseline"),
            "CL_refined": mesh_delta.get("CL_refined"),
            "dCL": dcl,
            "CDi_baseline": mesh_delta.get("CDi_baseline"),
            "CDi_refined": mesh_delta.get("CDi_refined"),
            "dCDi": dcdi,
            "tess_u": f"{mesh_delta.get('tess_u_baseline')} -> {mesh_delta.get('tess_u_refined')}",
            "tess_w": f"{mesh_delta.get('tess_w_baseline')} -> {mesh_delta.get('tess_w_refined')}",
            "note": mesh_delta.get("note") or mesh_delta.get("error"),
        },
    )

    wing = next((g for g in geom_info.get("geoms") or [] if g.get("name") == "MainWing"), None)
    if wing:
        proj = wing.get("total_projected_span")
        span_ok = proj is not None and abs(float(proj) - spec.bref_m) <= 0.05
        add(
            "MainWing TotalProjectedSpan near reference.b_m (geometry check, not Sref)",
            span_ok,
            {
                "TotalProjectedSpan": proj,
                "TotalSpan": wing.get("total_span"),
                "TotalArea": wing.get("total_area"),
                "reference_b_m": spec.bref_m,
                "tol_m": 0.05,
            },
        )
    return checks


def _set_input(vsp: Any, analysis: str, name: str, value: Any) -> None:
    names = list(vsp.GetAnalysisInputNames(analysis))
    if name not in names:
        raise RuntimeError(f"{analysis} has no input {name}. Runtime names: {names}")
    t = vsp.GetAnalysisInputType(analysis, name)
    vec = value if isinstance(value, list) else [value]
    if t == vsp.INT_DATA:
        vsp.SetIntAnalysisInput(analysis, name, [int(x) for x in vec], 0)
    elif t == vsp.DOUBLE_DATA:
        vsp.SetDoubleAnalysisInput(analysis, name, [float(x) for x in vec], 0)
    elif t == vsp.STRING_DATA:
        vsp.SetStringAnalysisInput(analysis, name, [str(x) for x in vec], 0)
    else:
        raise RuntimeError(f"unsupported type {t} for {analysis}.{name}")


def _read_inputs(vsp: Any, analysis: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in vsp.GetAnalysisInputNames(analysis):
        t = vsp.GetAnalysisInputType(analysis, name)
        if t == vsp.INT_DATA:
            out[name] = [int(x) for x in vsp.GetIntAnalysisInput(analysis, name)]
        elif t == vsp.DOUBLE_DATA:
            out[name] = [float(x) for x in vsp.GetDoubleAnalysisInput(analysis, name)]
        elif t == vsp.STRING_DATA:
            out[name] = [str(x) for x in vsp.GetStringAnalysisInput(analysis, name)]
        else:
            out[name] = f"type={t}"
    return out


def _last_double(vsp: Any, resid: str, *candidates: str) -> tuple[str | None, float | None, list[float]]:
    try:
        names = set(vsp.GetAllDataNames(resid))
    except Exception:  # noqa: BLE001
        return None, None, []
    for cand in candidates:
        if cand not in names:
            continue
        try:
            vec = [float(x) for x in vsp.GetDoubleResults(resid, cand)]
        except Exception:  # noqa: BLE001
            continue
        if vec:
            return cand, float(vec[-1]), vec
    return None, None, []


def _dump_result(vsp: Any, resid: str, *, cap_len: int) -> dict[str, Any]:
    out: dict[str, Any] = {"id": resid, "data": {}}
    try:
        out["name"] = vsp.GetResultsName(resid)
    except Exception:  # noqa: BLE001
        out["name"] = None
    try:
        names = list(vsp.GetAllDataNames(resid))
    except Exception as exc:  # noqa: BLE001
        out["error"] = repr(exc)
        return out
    out["data_names"] = names
    for n in names:
        try:
            typ = vsp.GetResultsType(resid, n)
        except Exception:  # noqa: BLE001
            continue
        try:
            if typ == vsp.DOUBLE_DATA:
                vec = [float(x) for x in vsp.GetDoubleResults(resid, n)]
                out["data"][n] = vec if len(vec) <= cap_len else {"n": len(vec), "head": vec[:10], "tail": vec[-5:]}
            elif typ == vsp.INT_DATA:
                vec = [int(x) for x in vsp.GetIntResults(resid, n)]
                out["data"][n] = vec[:cap_len]
            elif typ == vsp.STRING_DATA:
                vec = [str(x) for x in vsp.GetStringResults(resid, n)]
                out["data"][n] = vec[: min(len(vec), cap_len)]
        except Exception as exc:  # noqa: BLE001
            out["data"][n] = repr(exc)
    return out


def _vec3(value: Any) -> list[float] | str:
    if hasattr(value, "x") and callable(value.x):
        return [float(value.x()), float(value.y()), float(value.z())]
    if hasattr(value, "x"):
        return [float(value.x), float(value.y), float(value.z)]
    try:
        return [float(value[0]), float(value[1]), float(value[2])]
    except Exception:
        return str(value)


def _setp(vsp: Any, geom_id: str, name: str, group: str, value: float) -> None:
    vsp.SetParmVal(geom_id, name, group, float(value))


def _drain(vsp: Any) -> list[str]:
    err_mgr = vsp.ErrorMgrSingleton.getInstance()
    errors: list[str] = []
    while err_mgr.GetNumTotalErrors() > 0:
        err = err_mgr.PopLastError()
        errors.append(err.GetErrorString())
    return errors


def _first_num(value: Any) -> float | None:
    if isinstance(value, list) and value:
        value = value[0]
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return num


def _near(value: Any, target: float, tol: float = 1e-6) -> bool:
    try:
        return abs(float(value) - target) <= tol
    except (TypeError, ValueError):
        return False


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        return obj
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    return str(obj)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="C4 OpenVSP generate and VSPAEROSweep")
    parser.add_argument("--geometry", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--hash", dest="geometry_hash", default=None)
    args = parser.parse_args(argv)
    try:
        result = run(args.geometry, args.out, args.geometry_hash)
    except Exception as exc:  # noqa: BLE001
        result = {
            "error": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
            "geometry_hash": args.geometry_hash,
            "CL": [],
            "CDi": [],
            "validation": {
                "all_passed": False,
                "checks": [{"name": "generate", "pass": False, "numbers": str(exc)}],
            },
        }
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "sweep_result.json").write_text(json.dumps(_jsonable(result), indent=2) + "\n", encoding="utf-8")
    sys.stdout.write("C4_RESULT_BEGIN\n")
    json.dump(_jsonable(result), sys.stdout)
    sys.stdout.write("\nC4_RESULT_END\n")
    sys.stdout.flush()
    if result.get("error") and not result.get("CL"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
