"""Mock Titan-Avenger-shaped artifacts so the inspector is demonstrable before A1/A2 land.

Nothing here is evidence about the real aircraft: every claim in the mock manifest is labelled
with the status and source kind it would carry in the real pipeline, and the frame is left
*unconfirmed* on purpose so the "metrics are hypotheses" path is exercised. Swap these files for
A1's `design_manifest.json` / `reference.glb` and A2's `reconstruction.glb` when they exist.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import trimesh

from .inspector import FRD_TO_GLTF

__all__ = ["build_mock_artifacts", "MOCK_DIR"]

MOCK_DIR = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "features" / "cad" / "mock"

_R = np.array(FRD_TO_GLTF, dtype=float)


def _to_gltf(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Rotate FRD-metre geometry into glTF's Y-up metre frame (proper rotation, det +1)."""
    m = mesh.copy()
    m.vertices = m.vertices @ _R.T
    m.fix_normals()
    return m


def _box(center: tuple[float, float, float], size: tuple[float, float, float]) -> trimesh.Trimesh:
    m = trimesh.creation.box(extents=size)
    m.apply_translation(center)
    return m


def _tapered_panel(
    root_le: tuple[float, float, float],
    root_chord: float,
    tip_le: tuple[float, float, float],
    tip_chord: float,
    thickness_ratio: float = 0.12,
    cant_rad: float = 0.0,
) -> trimesh.Trimesh:
    """A convex tapered slab standing in for a lofted airfoil panel (FRD metres).

    The panel runs root -> tip; `cant_rad` rotates it about the aircraft x axis so the V-tail
    panels sit at their measured cant instead of flat.
    """
    pts = []
    for le, chord in ((root_le, root_chord), (tip_le, tip_chord)):
        x, y, z = le
        half_t = 0.5 * thickness_ratio * chord
        for dx in (0.0, chord):
            for dz in (-half_t, half_t):
                pts.append((x + dx, y, z + dz))
    pts = np.asarray(pts, dtype=float)
    if cant_rad:
        c, s = np.cos(cant_rad), np.sin(cant_rad)
        rot = np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)
        pivot = np.array(root_le, dtype=float)
        pts = (pts - pivot) @ rot.T + pivot
    return trimesh.convex.convex_hull(pts)


def _mirror_y(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Mirrored *definition* (winding repaired), never a reflecting placement — see §5."""
    m = mesh.copy()
    m.vertices = m.vertices * np.array([1.0, -1.0, 1.0])
    m.invert()
    m.fix_normals()
    return m


def _cyl(p0: tuple[float, float, float], p1: tuple[float, float, float], r: float) -> trimesh.Trimesh:
    return trimesh.creation.cylinder(radius=r, segment=np.array([p0, p1], dtype=float), sections=24)


# --------------------------------------------------------------------------- claims

def _claim(value: Any, unit: Optional[str], status: str, source_kind: Optional[str],
           evidence: Optional[list[str]] = None, assumptions: Optional[list[str]] = None,
           confidence: Optional[float] = None) -> dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "status": status,
        "source_kind": source_kind,
        "evidence_ids": evidence or [],
        "confidence": confidence,
        "assumptions": assumptions or [],
    }


def _unknown(unit: Optional[str] = None, *assumptions: str) -> dict[str, Any]:
    return _claim(None, unit, "unknown", None, assumptions=list(assumptions))


def _identity() -> list[list[float]]:
    return [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]


def _placement(dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> list[list[float]]:
    t = _identity()
    t[0][3], t[1][3], t[2][3] = dx, dy, dz
    return t


# --------------------------------------------------------------------------- geometry

_ROOT_LE_X = 0.330
_ROOT_CHORD = 0.214
_TIP_CHORD = 0.130
_SEMI_SPAN = 1.112
_VTAIL_CANT = 0.5585   # ~32 deg from horizontal, per the archive measurement


def _reference_parts() -> dict[str, trimesh.Trimesh]:
    """Reference-mesh stand-ins, FRD metres, nose datum at x=0."""
    wing_r = _tapered_panel(
        root_le=(_ROOT_LE_X, 0.082, -0.010), root_chord=_ROOT_CHORD,
        tip_le=(_ROOT_LE_X + 0.055, _SEMI_SPAN, -0.034), tip_chord=_TIP_CHORD,
    )
    aileron_r = _tapered_panel(
        root_le=(_ROOT_LE_X + 0.125, 0.70, -0.026), root_chord=0.052,
        tip_le=(_ROOT_LE_X + 0.150, 1.05, -0.033), tip_chord=0.040,
    )
    vtail_r = _tapered_panel(
        root_le=(0.840, 0.040, -0.030), root_chord=0.150,
        tip_le=(0.905, 0.290, -0.030), tip_chord=0.090,
        thickness_ratio=0.10, cant_rad=_VTAIL_CANT,
    )
    return {
        "fuse_nose": _box((0.120, 0.0, 0.000), (0.240, 0.140, 0.110)),
        "fuse_mid": _box((0.380, 0.0, 0.000), (0.280, 0.165, 0.120)),
        "fuse_tail": _box((0.720, 0.0, -0.010), (0.410, 0.100, 0.085)),
        "canopy_1": _box((0.250, 0.0, -0.075), (0.190, 0.110, 0.045)),
        "hatch_1": _box((0.470, 0.0, 0.062), (0.150, 0.120, 0.012)),
        "wing_right": wing_r,
        "wing_left": _mirror_y(wing_r),
        "aileron_right": aileron_r,
        "aileron_left": _mirror_y(aileron_r),
        "vtail_right": vtail_r,
        "vtail_left": _mirror_y(vtail_r),
        "motor_mount": _box((0.960, 0.0, -0.005), (0.060, 0.070, 0.070)),
        "wing_bay_plate": _box((0.400, 0.0, 0.055), (0.200, 0.150, 0.010)),
    }


def _bought_parts() -> dict[str, trimesh.Trimesh]:
    """Synthetic demo-BOM envelopes: never inferred from the archive."""
    return {
        "battery_pack": _box((0.300, 0.0, 0.020), (0.150, 0.060, 0.055)),
        "spar_main": _cyl((0.395, -_SEMI_SPAN, -0.012), (0.395, _SEMI_SPAN, -0.012), 0.008),
        "motor_pusher": _cyl((0.990, 0.0, -0.005), (1.030, 0.0, -0.005), 0.021),
        "prop_pusher": _cyl((1.032, 0.0, -0.005), (1.040, 0.0, -0.005), 0.165),
    }


def _reconstruction_parts() -> dict[str, trimesh.Trimesh]:
    """A deliberately *slightly different* rebuild, so the overlay shows real deviation."""
    ref = _reference_parts()
    recon = {}
    wing_r = _tapered_panel(
        root_le=(_ROOT_LE_X + 0.004, 0.082, -0.012), root_chord=_ROOT_CHORD * 1.02,
        tip_le=(_ROOT_LE_X + 0.050, _SEMI_SPAN * 0.985, -0.030), tip_chord=_TIP_CHORD * 0.97,
    )
    vtail_r = _tapered_panel(
        root_le=(0.836, 0.040, -0.030), root_chord=0.156,
        tip_le=(0.900, 0.283, -0.030), tip_chord=0.086,
        thickness_ratio=0.10, cant_rad=_VTAIL_CANT - 0.035,
    )
    recon["wing_right"] = wing_r
    recon["wing_left"] = _mirror_y(wing_r)
    recon["vtail_right"] = vtail_r
    recon["vtail_left"] = _mirror_y(vtail_r)
    # fuselage rebuilt from station envelopes: fatter and a touch shorter
    recon["fuse_nose"] = _box((0.122, 0.0, 0.0), (0.244, 0.150, 0.118))
    recon["fuse_mid"] = _box((0.378, 0.0, 0.0), (0.272, 0.172, 0.126))
    recon["fuse_tail"] = _box((0.716, 0.0, -0.010), (0.400, 0.108, 0.090))
    recon["motor_mount"] = ref["motor_mount"]
    recon.update(_bought_parts())
    return recon


def _export_scene(parts: dict[str, trimesh.Trimesh], out: Path) -> Path:
    scene = trimesh.Scene()
    for part_id, mesh in parts.items():
        m = _to_gltf(mesh)
        m.metadata["name"] = part_id
        scene.add_geometry(m, node_name=part_id, geom_name=part_id)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(scene.export(file_type="glb", include_normals=True))
    return out


# --------------------------------------------------------------------------- manifest

def _mock_manifest() -> dict[str, Any]:
    ev = [
        {"evidence_id": "ev_bounds_wing", "uri": "sources/wing/wing1.stl",
         "sha256": "0" * 64, "locator": "bounds", "method": "stl_bounds",
         "note": "native X 70.0 -> 1112.2 mm, one side only"},
        {"evidence_id": "ev_slice_wing", "uri": "artifacts/wing_stations.json",
         "locator": "stations[0..7]", "method": "slice_fit",
         "note": "chord fit residual reported in geometry_features.quality"},
        {"evidence_id": "ev_folder_material", "uri": "sources/High Temp PETG or ABS or ASA/",
         "locator": "folder", "method": "folder_hint",
         "note": "folder name is a suggestion, not proof: </script> characters kept verbatim"},
        {"evidence_id": "ev_bom_battery", "uri": "demo_bom.yaml", "locator": "items[battery]",
         "method": "catalog_lookup", "note": "SYNTHETIC demo BOM, not shipped with the archive"},
        {"evidence_id": "ev_cant_vtail", "uri": "sources/tail/vtail1.stl", "locator": "principal_axes",
         "method": "panel_normal_fit", "note": "panel canted about 32 deg from horizontal"},
    ]

    def printed(part_id, name, category, side, source, mirror_of=None, dx=0.0,
                material_status="estimated", caps=None, labels=None):
        return {
            "part_id": part_id,
            "definition_id": f"def_{part_id}",
            "name": name,
            "category": category,
            "side": side,
            "mirror_of": mirror_of,
            "representation": "reference_mesh",
            "source": source,
            "T_parent_from_local": _placement(dx),
            # printed parts: mass is unknown unless a shell estimate was explicitly selected
            "mass_kg": _unknown("kg", "no mass model selected at confirm"),
            "local_com_m": _unknown("m", "mesh is not watertight; centroid would be invalid"),
            "material": (_claim("High Temp PETG / ABS / ASA (folder hint)", None, "estimated",
                                "inferred", ["ev_folder_material"],
                                ["folder name is evidence of a suggestion, not of what was printed"], 0.4)
                         if material_status == "estimated" else _unknown()),
            "function": _claim(name, None, "known", "cad", ["ev_bounds_wing"]),
            "edit_capabilities": caps or ["none"],
            "allowed_overlap_with": [],
            "locked": False,
            "labels": labels or {},
        }

    parts: list[dict[str, Any]] = [
        printed("fuse_nose", "Fuselage nose", "fuselage", "center", "fuse1.stl"),
        printed("fuse_mid", "Fuselage mid (fuse3 clean variant)", "fuselage", "center", "fuse3_clean.stl",
                labels={"variant_group": "fuse3", "selected": "fuse3_clean"}),
        printed("fuse_tail", "Fuselage tail boom", "fuselage", "center", "fuse5.stl"),
        printed("canopy_1", "Canopy", "canopy", "center", "canopy1.stl"),
        printed("hatch_1", "Wing bay hatch", "hatch", "center", "hatch1.stl"),
        printed("wing_right", "Wing (right)", "wing", "right", "wing1.stl",
                caps=["set_wing_tip_extension"]),
        printed("wing_left", "Wing (left, mirrored)", "wing", "left", "wing1.stl",
                mirror_of="wing_right", caps=["set_wing_tip_extension"]),
        printed("aileron_right", "Aileron (right)", "aileron", "right", "aileron.stl"),
        printed("aileron_left", "Aileron (left, mirrored)", "aileron", "left", "aileron.stl",
                mirror_of="aileron_right"),
        printed("vtail_right", "V-tail panel (right)", "vtail", "right", "vtail1.stl"),
        printed("vtail_left", "V-tail panel (left, mirrored)", "vtail", "left", "vtail1.stl",
                mirror_of="vtail_right"),
        printed("motor_mount", "Motor mount (pusher)", "mount", "center", "motor_mount.stl"),
        printed("wing_bay_plate", "Wing bay plate", "mount", "center", "wing_bay_plate.stl",
                material_status="unknown"),
    ]

    # V-tail material conflicts: two sources disagree, which is a first-class state.
    parts[9]["material"] = _claim("ASA", None, "conflicted", "inferred",
                                  ["ev_folder_material", "ev_cant_vtail"],
                                  ["folder hint says PETG/ABS/ASA; the tail folder note says ASA only"])
    parts[10]["material"] = parts[9]["material"]

    bought = [
        {
            "part_id": "battery_pack", "definition_id": "def_battery_6s5000",
            "name": "Battery 6S 5000 mAh (synthetic demo BOM)", "category": "battery",
            "side": "center", "mirror_of": None, "representation": "envelope",
            "source": None, "T_parent_from_local": _placement(),
            "mass_kg": _claim(0.72, "kg", "estimated", "catalog", ["ev_bom_battery"],
                              ["catalog mass for a generic 6S 5000 mAh pack; not weighed"], 0.6),
            "local_com_m": _claim([0.0, 0.0, 0.0], "m", "estimated", "assumed", [],
                                  ["uniform density inside the declared envelope"]),
            "material": _claim("LiPo (catalog)", None, "estimated", "catalog", ["ev_bom_battery"]),
            "function": _claim("Main flight battery", None, "known", "bom", ["ev_bom_battery"]),
            "edit_capabilities": ["translate_component", "replace_catalog_component"],
            "allowed_overlap_with": ["fuse_mid", "wing_bay_plate"], "locked": False,
            "labels": {"synthetic": "true", "corridor_m": "x 0.24 -> 0.42"},
        },
        {
            "part_id": "spar_main", "definition_id": "def_spar_tube",
            "name": "Main spar tube (synthetic demo BOM)", "category": "spar",
            "side": "center", "mirror_of": None, "representation": "reconstruction",
            "source": None, "T_parent_from_local": _placement(),
            "mass_kg": _claim(0.104, "kg", "estimated", "computed", [],
                              ["carbon tube 16 mm OD / 14 mm ID at 1600 kg/m^3"], 0.5),
            "local_com_m": _claim([0.0, 0.0, 0.0], "m", "estimated", "computed", []),
            "material": _claim("Carbon fibre tube", None, "estimated", "catalog", ["ev_bom_battery"]),
            "function": _claim("Wing bending spar through both wing roots", None, "known", "bom", []),
            "edit_capabilities": ["resize_spar"],
            "allowed_overlap_with": ["wing_left", "wing_right", "fuse_mid"], "locked": False,
            "labels": {"synthetic": "true", "hole_limit_mm": "16 (wing3_16mm_hole selected)"},
        },
        {
            "part_id": "motor_pusher", "definition_id": "def_motor_env",
            "name": "Pusher motor envelope (synthetic demo BOM)", "category": "motor",
            "side": "center", "mirror_of": None, "representation": "envelope",
            "source": None, "T_parent_from_local": _placement(),
            "mass_kg": _claim(0.195, "kg", "estimated", "catalog", ["ev_bom_battery"],
                              ["catalog mass for a generic 42 mm outrunner"], 0.5),
            "local_com_m": _unknown("m"),
            "material": _unknown(),
            "function": _claim("Pusher propulsion", None, "estimated", "inferred", ["ev_bounds_wing"],
                               ["motor_mount sits at the tail (native Y 588-598), so pusher"]),
            "edit_capabilities": ["replace_catalog_component"],
            "allowed_overlap_with": ["motor_mount"], "locked": False,
            "labels": {"synthetic": "true"},
        },
        {
            "part_id": "prop_pusher", "definition_id": "def_prop_env",
            "name": "Propeller swept volume (synthetic demo BOM)", "category": "prop",
            "side": "center", "mirror_of": None, "representation": "envelope",
            "source": None, "T_parent_from_local": _placement(),
            "mass_kg": _unknown("kg", "no propeller is specified anywhere in the archive"),
            "local_com_m": _unknown("m"),
            "material": _unknown(),
            "function": _claim("Swept volume used for the airframe clearance check", None,
                               "estimated", "assumed", [], ["13 inch diameter assumed for the demo"]),
            "edit_capabilities": ["replace_catalog_component"],
            "allowed_overlap_with": [], "locked": True,
            "labels": {"synthetic": "true"},
        },
    ]

    return {
        "schema_version": "0.1.0",
        "design_id": "titan_avenger_mock",
        "revision_id": "rev_mock_0001",
        "title": "Titan Avenger (mock artifacts — not the real archive)",
        "frame": {
            "units": "mm",
            "native_to_frd": [[0, -1, 0], [-1, 0, 0], [0, 0, -1]],
            "scale_to_m": 0.001,
            "nose_datum_native": [0.0, -403.07, 0.0],
            "mirror_plane_native": "x=0",
            "confirmed": False,
            "confirmed_by": None,
            "notes": [
                "Units and axes are a hypothesis until a human confirms them in this viewer.",
                "Positive native X is treated as the left side; confirm before publishing any metric.",
            ],
        },
        "sources": [],
        "variants": [
            {"group_id": "wing3", "options": ["wing3_12mm_hole.stl", "wing3_16mm_hole.stl", "wing3_no_hole.stl"],
             "selected": "wing3_16mm_hole.stl", "reason": "mock selection for the demo"},
            {"group_id": "fuse3", "options": ["fuse3.stl", "fuse3_belly_cam.stl", "fuse3_clean.stl"],
             "selected": "fuse3_clean.stl", "reason": "mock selection for the demo"},
        ],
        "excluded_sources": ["wing3_12mm_hole.stl", "wing3_no_hole.stl", "fuse3.stl", "fuse3_belly_cam.stl"],
        "parts": parts + bought,
        "evidence": ev,
        "warnings": [
            "MOCK DATA: geometry and claims are stand-ins for A1/A2 output, not measurements of the archive.",
            "Frame is unconfirmed, so no metric on this page may be published.",
        ],
    }


def _mock_features() -> dict[str, Any]:
    stations = []
    for i in range(8):
        f = i / 7.0
        stations.append({
            "span_y_m": round(0.082 + f * (_SEMI_SPAN - 0.082), 4),
            "leading_edge_x_m": round(_ROOT_LE_X + f * 0.055, 4),
            "chord_m": round(_ROOT_CHORD + f * (_TIP_CHORD - _ROOT_CHORD), 4),
            "z_m": round(-0.010 - f * 0.024, 4),
            "twist_rad": round(-f * 0.0175, 5),
            "thickness_ratio": 0.12,
        })
    wing = {
        "surface_id": "wing",
        "part_ids": ["wing_left", "wing_right", "aileron_left", "aileron_right"],
        "stations": stations,
        "symmetric": True,
        "cant_rad": None,
        "span_m": _claim(2.2245, "m", "estimated", "computed", ["ev_bounds_wing"],
                         ["mm units and mirroring about native x=0, both unconfirmed"], 0.7),
        "area_m2": _claim(0.3742, "m2", "estimated", "computed", ["ev_slice_wing"],
                          ["projected planform counted once; aileron mapped to its parent"], 0.6),
        "mac_m": _claim(0.1755, "m", "estimated", "computed", ["ev_slice_wing"]),
        "x_mac_le_m": _claim(0.3541, "m", "estimated", "computed", ["ev_slice_wing"]),
        "aspect_ratio": _claim(13.22, None, "estimated", "computed", ["ev_slice_wing"]),
        "sweep_le_rad": _claim(0.0494, "rad", "estimated", "computed", ["ev_slice_wing"]),
        "dihedral_rad": _claim(0.0233, "rad", "estimated", "computed", ["ev_slice_wing"]),
        "airfoil": _claim("NACA 4412 (assumed)", None, "estimated", "assumed", [],
                          ["declared assumption for the reconstruction; no airfoil match was claimed"], 0.2),
        "control_surfaces": ["aileron_left", "aileron_right"],
        "fit_rms_m": 0.0031,
    }
    vtail = {
        "surface_id": "vtail_right",
        "part_ids": ["vtail_right"],
        "stations": [
            {"span_y_m": 0.040, "leading_edge_x_m": 0.840, "chord_m": 0.150, "z_m": -0.030,
             "twist_rad": 0.0, "thickness_ratio": 0.10},
            {"span_y_m": 0.290, "leading_edge_x_m": 0.905, "chord_m": 0.090, "z_m": -0.030,
             "twist_rad": 0.0, "thickness_ratio": 0.10},
        ],
        "symmetric": False,
        "cant_rad": _VTAIL_CANT,
        "span_m": _claim(0.2544, "m", "estimated", "computed", ["ev_cant_vtail"],
                         ["panel length along the canted axis, not a projected span"]),
        "area_m2": _claim(0.0305, "m2", "estimated", "computed", ["ev_cant_vtail"]),
        "mac_m": _claim(0.1224, "m", "estimated", "computed", ["ev_cant_vtail"]),
        "x_mac_le_m": _claim(0.8654, "m", "estimated", "computed", ["ev_cant_vtail"]),
        "aspect_ratio": _claim(2.12, None, "estimated", "computed", ["ev_cant_vtail"]),
        "sweep_le_rad": _claim(0.2554, "rad", "estimated", "computed", ["ev_cant_vtail"]),
        "dihedral_rad": _claim(_VTAIL_CANT, "rad", "estimated", "computed", ["ev_cant_vtail"]),
        "airfoil": _unknown(None, "no tail airfoil was fitted"),
        "control_surfaces": ["taileron_right"],
        "fit_rms_m": 0.0047,
    }
    return {
        "schema_version": "0.1.0",
        "design_id": "titan_avenger_mock",
        "revision_id": "rev_mock_0001",
        "frame": "FRD",
        "reference_area_m2": wing["area_m2"],
        "reference_span_m": wing["span_m"],
        "reference_chord_m": wing["mac_m"],
        "surfaces": [wing, vtail],
        "fuselage": [
            {"x_m": 0.00, "width_m": 0.052, "height_m": 0.048, "z_center_m": 0.0},
            {"x_m": 0.24, "width_m": 0.140, "height_m": 0.110, "z_center_m": 0.0},
            {"x_m": 0.38, "width_m": 0.165, "height_m": 0.120, "z_center_m": 0.0},
            {"x_m": 0.62, "width_m": 0.118, "height_m": 0.098, "z_center_m": -0.006},
            {"x_m": 0.99, "width_m": 0.060, "height_m": 0.058, "z_center_m": -0.010},
        ],
        "fuselage_length_m": _claim(0.9913, "m", "estimated", "computed", ["ev_bounds_wing"],
                                    ["mm units unconfirmed"], 0.7),
        "mass_kg": _unknown("kg", "printed-part masses are unknown, so the total cannot be summed"),
        "cg_m": _unknown("m", "depends on the unknown printed-part masses"),
        "quality": {
            "station_fit_rms_m": 0.0031,
            "warnings": ["wing1/wing3 are not watertight, so volume-based mass is invalid"],
        },
    }


def _mock_fit_report() -> dict[str, Any]:
    return {
        "rms_m": 0.0038,
        "max_m": 0.0142,
        "method": "per-station chord/LE/z deviation plus sampled silhouette distance",
        "per_part": [
            {"part_id": "wing_right", "rms_m": 0.0031, "max_m": 0.0098, "note": "tip chord 3% under the reference"},
            {"part_id": "wing_left", "rms_m": 0.0031, "max_m": 0.0098, "note": "mirrored instance of wing_right"},
            {"part_id": "vtail_right", "rms_m": 0.0047, "max_m": 0.0142, "note": "cant 2 deg shallower than measured"},
            {"part_id": "vtail_left", "rms_m": 0.0047, "max_m": 0.0142},
            {"part_id": "fuse_mid", "rms_m": 0.0044, "max_m": 0.0121, "note": "station envelope is a convex box"},
        ],
        "note": "Not usable for engineering comparison until a human confirms the reconstruction.",
    }


def _mock_edit_result() -> dict[str, Any]:
    return {
        "schema_version": "0.1.0",
        "base_revision_id": "rev_mock_0001",
        "preview_revision_id": "rev_mock_0002_preview",
        "operation": "translate_component",
        "status": "ok",
        "affected_part_ids": ["battery_pack"],
        "changes": [
            {"part_id": "battery_pack", "field": "T_parent_from_local.translation",
             "before": [0.0, 0.0, 0.0], "after": [0.025, 0.0, 0.0], "unit": "m"},
            {"part_id": "battery_pack", "field": "cg_contribution_x_m",
             "before": 0.300, "after": 0.325, "unit": "m"},
        ],
        "checks": [
            {"name": "battery stays inside the declared corridor", "passed": True,
             "detail": "x 0.325 m within 0.24 -> 0.42 m"},
            {"name": "no undeclared interference", "passed": True,
             "detail": "overlap only with fuse_mid and wing_bay_plate, both declared"},
            {"name": "retention hardware verified", "passed": False,
             "detail": "retention and harness are unknown, so no verified-movement claim is made"},
        ],
        "artifacts": [],
        "error": None,
    }


# --------------------------------------------------------------------------- entry point

def build_mock_artifacts(out_dir: Path | str = MOCK_DIR) -> dict[str, Path]:
    """Write the mock GLBs and JSON documents; returns a map of artifact name -> path."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    reference = {**_reference_parts(), **_bought_parts()}
    written = {
        "reference_glb": _export_scene(reference, out / "reference.glb"),
        "reconstruction_glb": _export_scene(_reconstruction_parts(), out / "reconstruction.glb"),
    }
    for name, doc in (
        ("design_manifest", _mock_manifest()),
        ("geometry_features", _mock_features()),
        ("fit_report", _mock_fit_report()),
        ("cad_edit_result", _mock_edit_result()),
    ):
        p = out / f"{name}.json"
        p.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        written[name] = p
    return written


if __name__ == "__main__":  # pragma: no cover - convenience
    for k, v in build_mock_artifacts().items():
        print(f"{k}: {v}")
