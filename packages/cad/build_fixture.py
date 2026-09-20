"""Write fixtures/c/titan_avenger_cad JSON from the measured inventory.

JSON must not contain the words 'avenger' or 'falcon' (contract test).
Mass, material, inner diameter, allowables: unknown. Null is not zero.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from contracts.claim import make_claim

from .titan_archive import (
    BASELINE_WING3,
    CAD_FIXTURE_DIR,
    EXPOSED_PLANFORM_M2,
    PART_TYPES,
    SPAN_TIP_MM,
    bbox_center_native_mm,
    inventory_by_path,
    load_inventory,
    mac_from_stations,
    native_mm_to_frd_m,
    occurrence_plan,
    vtail_metrics,
    wing_stations_from_inventory,
)

MISSING_ARCHIVE = "not present in the print archive"
NOT_A_MEASUREMENT = "assumed mission-model input; not a measurement"
CAD_NOTE = "measured from print-archive STL bounds"

ASSUMED_AERO = {
    "CD0_profile": (0.015, "1"),
    "CD0_fuselage": (0.008, "1"),
    "CD0_interference": (0.002, "1"),
    "oswald_e": (0.8, "1"),
    "CLmax": (1.3, "1"),
}
ASSUMED_MISSION = {
    "cruise_mps": (15.0, "m/s"),
    "altitude_m": (120.0, "m"),
    "rho_kgm3": (1.225, "kg/m3"),
    "g_mps2": (9.80665, "m/s2"),
    "reserve_wh_fraction": (0.2, "1"),
    "load_factor_limit": (3.5, "1"),
}


def _cad(value: float, unit: str, *extra: str) -> dict[str, Any]:
    return make_claim(
        value,
        unit,
        status="known",
        source_kind="cad",
        assumptions=[CAD_NOTE, *extra],
    )


def _computed(value: float, unit: str, *extra: str) -> dict[str, Any]:
    return make_claim(
        value,
        unit,
        status="known",
        source_kind="computed",
        assumptions=list(extra) or ["computed from measured stations"],
    )


def _inferred(value: float, unit: str, *extra: str) -> dict[str, Any]:
    return make_claim(
        value,
        unit,
        status="known",
        source_kind="inferred",
        assumptions=list(extra) or ["linear extrapolation of measured taper"],
    )


def _assumed(value: float, unit: str) -> dict[str, Any]:
    return make_claim(
        value,
        unit,
        status="known",
        source_kind="assumed",
        assumptions=[NOT_A_MEASUREMENT, MISSING_ARCHIVE],
    )


def _unknown(unit: str, *extra: str) -> dict[str, Any]:
    return make_claim(
        None,
        unit,
        status="unknown",
        source_kind="assumed",
        assumptions=[MISSING_ARCHIVE, *extra],
    )


def build_design_manifest() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "design_id": "archive_fw_print",
        "revision_id": "rev_archive_fw_001",
        "representation": "as_measured",
        "frame": "FRD",
        "units": "SI",
        "notes": (
            "Print-archive fixed-wing pusher. Geometry from STL bounds. "
            "No mass, material, propulsion, or rotor hardware in the archive. "
            "Filename VTOL claim is not supported by the parts."
        ),
        "assumptions": [
            "Right-wing stations only; left wing is the implied mirror.",
            "FRD: X forward, Y right, Z down. Lengths in metres, angles in radians.",
            "Reference S is exposed planform, both sides, no carry-through.",
            MISSING_ARCHIVE,
        ],
    }


def build_geometry_features(by_path: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    by_path = by_path or inventory_by_path()
    stations_raw = wing_stations_from_inventory(by_path)
    b_m = 2.0 * (SPAN_TIP_MM / 1000.0)
    s_m2 = EXPOSED_PLANFORM_M2
    c_m = mac_from_stations(stations_raw, s_m2)
    tail = vtail_metrics(by_path)
    stations = []
    last_i = len(stations_raw) - 1
    for i, st in enumerate(stations_raw):
        kind = _inferred if i == last_i else _cad
        twist = _unknown("rad", "twist not extracted from the hollow printed section")
        stations.append(
            {
                "span_y_m": _cad(st["span_y_m"], "m") if i != last_i else _inferred(st["span_y_m"], "m", "tip station"),
                "leading_edge_x_m": kind(st["leading_edge_x_m"], "m"),
                "chord_m": kind(st["chord_m"], "m"),
                "z_m": kind(st["z_m"], "m"),
                "twist_rad": twist,
            }
        )
    return {
        "schema_version": 1,
        "frame": "FRD",
        "units": "m",
        "reference": {
            "S_m2": _cad(
                s_m2,
                "m2",
                "exposed planform both sides, no carry-through; set once",
            ),
            "b_m": _cad(b_m, "m", "twice the measured half-span tip"),
            "c_m": _computed(c_m, "m", "MAC from piecewise-linear measured stations"),
        },
        "wing_stations": stations,
        "tail": {
            "layout": "vtail",
            "cant_rad": _cad(tail["cant_rad"], "rad", "atan2(dZ, dX) of vtail1 AABB"),
            "panel_count": _cad(2.0, "1", "two canted panels after mirror"),
            "panel_area_m2": _unknown("m2", "planform not in the inventory; wetted area is not planform"),
            "panel_span_m": _cad(tail["panel_span_m"], "m"),
            "tail_arm_m": _computed(
                tail["tail_arm_m"],
                "m",
                "wing quarter-chord datum to vtail1 quarter-chord",
            ),
        },
        "mission": {key: _assumed(val, unit) for key, (val, unit) in ASSUMED_MISSION.items()},
        "aero_assumptions": {
            key: _assumed(val, unit) for key, (val, unit) in ASSUMED_AERO.items()
        },
        "spar": {
            "Do_m": _cad(0.012, "m", "pass-through hole in wing3_12mm_hole"),
            "Di_m": _unknown("m", "tube wall is not in the archive"),
            "sigma_allow_mpa": _unknown("MPa"),
            "stations": _assumed(21.0, "1"),
        },
        "cg_inputs": {
            "np_x_m": _unknown(
                "m",
                "neutral point not provided; do not substitute a quarter-chord guess",
            ),
        },
    }


def build_parts_and_map(
    by_path: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_path = by_path or inventory_by_path()
    occurrences: list[dict[str, Any]] = []
    part_map: dict[str, Any] = {}
    for stl_rel, part_id, mirror in occurrence_plan(wing3=BASELINE_WING3):
        rec = by_path[stl_rel]
        cx, cy, cz = bbox_center_native_mm(rec)
        if mirror:
            cx = -cx
        x_m, y_m, z_m = native_mm_to_frd_m(cx, cy, cz)
        base = part_id.rsplit("_", 1)[0] if part_id[-1] in "LR" and part_id[-2] == "_" else part_id
        # wing_1_L -> wing_1; fuse_1 stays fuse_1
        if part_id.endswith("_L") or part_id.endswith("_R"):
            base = part_id[:-2]
        ptype = PART_TYPES.get(base, PART_TYPES.get(part_id, "other"))
        occurrences.append(
            {
                "part_id": part_id,
                "type": ptype,
                "mass_kg": _unknown("kg", "volume is not mass"),
                "position_frd_m": {
                    "x_m": _cad(x_m, "m"),
                    "y_m": _cad(y_m, "m"),
                    "z_m": _cad(z_m, "m"),
                },
            }
        )
        part_map[part_id] = {
            "name": part_id,
            "mesh_node": part_id,
            "material": {
                "name": "unspecified",
                "status": "unknown",
                "source_kind": "assumed",
                "evidence_ids": [],
                "assumptions": [
                    MISSING_ARCHIVE,
                    "folder name High Temp PETG or ABS or ASA is not a material cert",
                ],
            },
        }
    return {
        "schema_version": 1,
        "frame": "FRD",
        "occurrences": occurrences,
    }, part_map


def write_fixture(dest: Path | None = None) -> Path:
    dest = dest or CAD_FIXTURE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    load_inventory()
    by_path = inventory_by_path()
    files = {
        "design_manifest.json": build_design_manifest(),
        "geometry_features.json": build_geometry_features(by_path),
    }
    parts, part_map = build_parts_and_map(by_path)
    files["parts.json"] = parts
    files["part_map.json"] = part_map
    for name, payload in files.items():
        path = dest / name
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return dest
