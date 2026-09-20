"""Titan print-archive CAD: STL -> named GLB, native mm -> glTF / FRD.

The zip is pre-assembled in a shared millimetre frame. Do not centre parts.
Do not fuse meshes. Do not invent mass or material.
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from typing import Any, Sequence

import numpy as np

MappingLike = dict[str, Any]

Y_DATUM_MM = 55.0  # wing quarter-chord at centreline, native Y
SPAN_TIP_MM = 1112.25
FUSE_NOSE_MM = -403.07
FUSE_TAIL_MM = 598.27

# Runbook 2.8. Excluded alternates must not appear in the installed scene.
BASELINE_WING3 = "wing3_12mm_hole"
BASELINE_FUSE3 = "fuse3_clean"
WING3_16MM = "wing3_16mm_hole"
EXCLUDED = ("wing3_16mm_hole", "wing3_no_hole", "fuse3", "fuse3_belly_cam")

CENTRELINE: tuple[tuple[str, str], ...] = (
    ("Fuselage/fuse1.stl", "fuse_1"),
    ("Fuselage/fuse2.stl", "fuse_2"),
    ("Fuselage/fuse3_clean.stl", "fuse_3"),
    ("Fuselage/fuse4.stl", "fuse_4"),
    ("Fuselage/fuse5.stl", "fuse_5"),
    ("Fuselage/canopy1.stl", "canopy_1"),
    ("Fuselage/canopy2.stl", "canopy_2"),
    ("Fuselage/hatch1.stl", "hatch_1"),
    ("Fuselage/hatch2.stl", "hatch_2"),
    ("High Temp PETG or ABS or ASA/motor_mount.stl", "motor_mount"),
)

# Native +X is the aircraft left. Unmirrored occurrence is *_L.
HALFSPAN: tuple[tuple[str, str], ...] = (
    ("Wings/wing1.stl", "wing_1"),
    ("Wings/wing2.stl", "wing_2"),
    ("Wings/wing3_12mm_hole.stl", "wing_3"),
    ("Wings/wing4.stl", "wing_4"),
    ("Wings/wing5.stl", "wing_5"),
    ("Wings/aileron.stl", "aileron"),
    ("High Temp PETG or ABS or ASA/wing_bay_plate.stl", "wing_bay_plate"),
    ("Tail/vtail1.stl", "vtail_1"),
    ("Tail/vtail2.stl", "vtail_2"),
    ("Tail/taileron.stl", "taileron"),
)

PART_TYPES: dict[str, str] = {
    "fuse_1": "fuselage",
    "fuse_2": "fuselage",
    "fuse_3": "fuselage",
    "fuse_4": "fuselage",
    "fuse_5": "fuselage",
    "canopy_1": "fuselage",
    "canopy_2": "fuselage",
    "hatch_1": "fuselage",
    "hatch_2": "fuselage",
    "motor_mount": "other",
    "wing_1": "wing",
    "wing_2": "wing",
    "wing_3": "wing",
    "wing_4": "wing",
    "wing_5": "wing",
    "aileron": "surface",
    "wing_bay_plate": "other",
    "vtail_1": "tail",
    "vtail_2": "tail",
    "taileron": "surface",
}

# Projected planform, both sides, no carry-through. Measured from this archive
# (runbook 2.4 segment table). Not a wetted-area guess.
EXPOSED_PLANFORM_M2 = 0.4199

REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = REPO_ROOT / "titan_avenger_inventory.json"
CAD_FIXTURE_DIR = REPO_ROOT / "fixtures" / "c" / "titan_avenger_cad"


def find_archive_zip(root: Path | None = None) -> Path:
    root = root or REPO_ROOT
    hits = sorted(root.glob("*.zip"))
    for path in hits:
        name = path.name.lower()
        if "titan" in name or "avenger" in name:
            return path
    raise FileNotFoundError(f"no Titan print archive zip under {root}")


def load_inventory(path: Path | None = None) -> dict[str, Any]:
    target = path or INVENTORY_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def inventory_by_path(inventory: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    inv = inventory or load_inventory()
    return {str(part["path"]).replace("\\", "/"): part for part in inv["parts"]}


def native_mm_to_gltf_m(vertices_mm: np.ndarray) -> np.ndarray:
    """native mm (X left, Y aft, Z up) -> glTF m (X right, Y up, Z back)."""
    v = np.asarray(vertices_mm, dtype=np.float64)
    return np.column_stack(
        [
            -v[:, 0] / 1000.0,
            v[:, 2] / 1000.0,
            (v[:, 1] - Y_DATUM_MM) / 1000.0,
        ]
    )


def native_mm_to_frd_m(x_mm: float, y_mm: float, z_mm: float) -> tuple[float, float, float]:
    """native mm (X left, Y aft, Z up) -> FRD m (X forward, Y right, Z down)."""
    return (
        -(y_mm - Y_DATUM_MM) / 1000.0,
        -x_mm / 1000.0,
        -z_mm / 1000.0,
    )


def occurrence_plan(*, wing3: str = BASELINE_WING3) -> list[tuple[str, str, bool]]:
    """Yield (stl_path, part_id, mirror_for_right). 30 occurrences."""
    rows: list[tuple[str, str, bool]] = []
    for stl, part_id in CENTRELINE:
        rows.append((stl, part_id, False))
    for stl, base in HALFSPAN:
        path = f"Wings/{wing3}.stl" if base == "wing_3" else stl
        rows.append((path, f"{base}_L", False))
        rows.append((path, f"{base}_R", True))
    return rows


def extract_zip(zip_path: Path, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(dest)
    return dest


def convert_archive(
    zip_path: Path | None = None,
    *,
    dest_glb: Path | None = None,
    wing3: str = BASELINE_WING3,
    stl_root: Path | None = None,
) -> dict[str, Any]:
    """Build a 30-node GLB. Returns a JSON-serialisable report."""
    import trimesh

    zip_path = zip_path or find_archive_zip()
    stl_dir = stl_root or (REPO_ROOT / "artifacts" / "titan_stl")
    if stl_root is None:
        extract_zip(zip_path, stl_dir)
    dest = dest_glb or (CAD_FIXTURE_DIR / "meshes" / "titan_avenger.glb")
    dest.parent.mkdir(parents=True, exist_ok=True)

    scene = trimesh.Scene()
    report_parts: list[dict[str, Any]] = []
    total_tris = 0
    for stl_rel, part_id, mirror in occurrence_plan(wing3=wing3):
        path = _resolve_stl(stl_dir, stl_rel)
        mesh = trimesh.load(path, force="mesh", process=False)
        if not isinstance(mesh, trimesh.Trimesh):
            raise TypeError(f"{path} did not load as a triangle mesh")
        mesh = mesh.copy()
        mesh.vertices = native_mm_to_gltf_m(np.asarray(mesh.vertices))
        if mirror:
            mesh.vertices[:, 0] *= -1.0
            mesh.invert()
        n_tris = int(len(mesh.faces))
        total_tris += n_tris
        scene.add_geometry(mesh, node_name=part_id, geom_name=part_id)
        bounds = np.asarray(mesh.bounds)
        report_parts.append(
            {
                "part_id": part_id,
                "stl": stl_rel,
                "mirror": mirror,
                "triangles": n_tris,
                "bounds_m": bounds.tolist(),
            }
        )

    scene.export(dest)
    bounds = np.asarray(scene.bounds)
    span_m = float(bounds[1, 0] - bounds[0, 0])
    length_m = float(bounds[1, 2] - bounds[0, 2])
    height_m = float(bounds[1, 1] - bounds[0, 1])
    node_names = _scene_node_names(scene)
    report = {
        "glb": str(dest),
        "wing3": wing3,
        "node_count": len(node_names),
        "node_names": node_names,
        "triangles": total_tris,
        "span_m": span_m,
        "length_m": length_m,
        "height_m": height_m,
        "bounds_m": bounds.tolist(),
        "parts": report_parts,
    }
    return report


def _scene_node_names(scene: Any) -> list[str]:
    names = [name for name in scene.graph.nodes_geometry if name]
    return sorted(names)


def _resolve_stl(root: Path, rel: str) -> Path:
    direct = root / rel
    if direct.is_file():
        return direct
    matches = list(root.rglob(Path(rel).name))
    if len(matches) == 1:
        return matches[0]
    raise FileNotFoundError(f"STL {rel} not found under {root}")


def bbox_center_native_mm(part: MappingLike) -> tuple[float, float, float]:
    lo = part["min"]
    hi = part["max"]
    return (
        0.5 * (float(lo[0]) + float(hi[0])),
        0.5 * (float(lo[1]) + float(hi[1])),
        0.5 * (float(lo[2]) + float(hi[2])),
    )


def wing_stations_from_inventory(by_path: dict[str, dict[str, Any]]) -> list[dict[str, float]]:
    """Right-wing FRD stations at panel inboard edges plus tip. Lengths in metres."""
    wing3 = by_path["Wings/wing3_12mm_hole.stl"]
    aileron = by_path["Wings/aileron.stl"]
    panels = [
        by_path["Wings/wing1.stl"],
        by_path["Wings/wing2.stl"],
        {
            "min": [
                wing3["min"][0],
                min(float(wing3["min"][1]), float(aileron["min"][1])),
                min(float(wing3["min"][2]), float(aileron["min"][2])),
            ],
            "max": [
                wing3["max"][0],
                max(float(wing3["max"][1]), float(aileron["max"][1])),
                max(float(wing3["max"][2]), float(aileron["max"][2])),
            ],
        },
        by_path["Wings/wing4.stl"],
        by_path["Wings/wing5.stl"],
    ]
    stations: list[dict[str, float]] = []
    chords: list[tuple[float, float]] = []
    for panel in panels:
        x_in_mm = float(panel["min"][0])
        le_mm = float(panel["min"][1])
        te_mm = float(panel["max"][1])
        z_mm = 0.5 * (float(panel["min"][2]) + float(panel["max"][2]))
        chord_mm = te_mm - le_mm
        chords.append((x_in_mm, chord_mm))
        frd = native_mm_to_frd_m(x_in_mm, le_mm, z_mm)
        stations.append(
            {
                "span_y_m": x_in_mm / 1000.0,
                "leading_edge_x_m": frd[0],
                "chord_m": chord_mm / 1000.0,
                "z_m": frd[2],
            }
        )
    tip = by_path["Wings/wing5.stl"]
    x_tip_mm = float(tip["max"][0])
    # Linear chord law from the five inboard measurements; tip is not a printed seam.
    slope = (chords[-1][1] - chords[-2][1]) / (chords[-1][0] - chords[-2][0])
    chord_tip_mm = chords[-1][1] + slope * (x_tip_mm - chords[-1][0])
    le_slope = (float(tip["min"][1]) - float(by_path["Wings/wing4.stl"]["min"][1])) / (
        float(tip["min"][0]) - float(by_path["Wings/wing4.stl"]["min"][0])
    )
    le_tip_mm = float(tip["min"][1]) + le_slope * (x_tip_mm - float(tip["min"][0]))
    z_tip_mm = 0.5 * (float(tip["min"][2]) + float(tip["max"][2]))
    frd_tip = native_mm_to_frd_m(x_tip_mm, le_tip_mm, z_tip_mm)
    stations.append(
        {
            "span_y_m": x_tip_mm / 1000.0,
            "leading_edge_x_m": frd_tip[0],
            "chord_m": chord_tip_mm / 1000.0,
            "z_m": frd_tip[2],
        }
    )
    return stations


def mac_from_stations(stations: Sequence[MappingLike], s_m2: float) -> float:
    """Mean aerodynamic chord from piecewise-linear planform, both-sides S."""
    s_one = s_m2 / 2.0
    acc = 0.0
    for a, b in zip(stations, stations[1:]):
        y1, y2 = float(a["span_y_m"]), float(b["span_y_m"])
        c1, c2 = float(a["chord_m"]), float(b["chord_m"])
        acc += (y2 - y1) / 3.0 * (c1 * c1 + c1 * c2 + c2 * c2)
    if s_one <= 0.0:
        raise ValueError("S must be positive")
    return (2.0 / s_one) * acc


def vtail_metrics(by_path: dict[str, dict[str, Any]]) -> dict[str, float]:
    v1 = by_path["Tail/vtail1.stl"]
    dx = float(v1["max"][0]) - float(v1["min"][0])
    dz = float(v1["max"][2]) - float(v1["min"][2])
    cant_rad = math.atan2(dz, dx)
    le_mm = float(v1["min"][1])
    chord_mm = float(v1["max"][1]) - float(v1["min"][1])
    qc_mm = le_mm + 0.25 * chord_mm
    tail_arm_m = abs(qc_mm - Y_DATUM_MM) / 1000.0
    return {
        "cant_rad": cant_rad,
        "panel_span_m": dx / 1000.0,
        "tail_arm_m": tail_arm_m,
    }


def expected_triangle_count(by_path: dict[str, dict[str, Any]], *, wing3: str = BASELINE_WING3) -> int:
    total = 0
    for stl, _part_id in CENTRELINE:
        total += int(by_path[stl]["tris"])
    for stl, base in HALFSPAN:
        path = f"Wings/{wing3}.stl" if base == "wing_3" else stl
        total += 2 * int(by_path[path]["tris"])
    return total


def installed_part_ids(*, wing3: str = BASELINE_WING3) -> list[str]:
    return [part_id for _stl, part_id, _mirror in occurrence_plan(wing3=wing3)]
