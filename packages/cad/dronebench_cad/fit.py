"""How far the reconstruction is from the reference meshes.

Two independent numbers, both reported per part and overall:

* **station deviation** — slice both the reference group and the reconstructed solid at each
  parameter station and compare leading edge x, chord and mid-thickness z. This is the one
  that says whether the planform is right.
* **surface distance** — point-to-surface distance between deterministic samples of the
  reference mesh and the reconstructed surface, both directions. This is the sampled
  silhouette metric; a one-directional distance hides material the reconstruction invented.

There is deliberately **no pass/fail threshold**. `confirmed` is `false` until a human looks
at the overlay and records a decision; until then the reconstruction is not usable for
engineering comparison (architecture §6, step 8).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np
import trimesh

from .model import MM, CadModel, ReconPart

__all__ = [
    "fit_report",
    "CANDIDATE_FRAME",
    "REFERENCE_GROUPS",
    "to_frd_mesh",
    "projected_planform_area_m2",
]

# The candidate native -> FRD frame from tasks/a.md. Unconfirmed: a caller with a confirmed
# DesignManifest should pass it so this is not used.
CANDIDATE_FRAME = {
    "scale_to_m": 0.001,
    "nose_datum_native": [0.0, -403.0700988769531, 0.0],
    "source_side": "right",   # native +X is mapped to FRD +y here; a reflection, not a placement
    "confirmed": False,
}

# Which reference meshes stand behind each reconstructed part. Variant choices are the
# caller's; the defaults here match the fixture (wing3_16mm_hole, plain fuse3).
REFERENCE_GROUPS: dict[str, dict[str, Any]] = {
    "wing": {
        "files": ["Wings/wing1.stl", "Wings/wing2.stl", "Wings/wing3_16mm_hole.stl",
                  "Wings/wing4.stl", "Wings/wing5.stl", "Wings/aileron.stl"],
        "surface_id": "wing",
    },
    "vtail": {
        "files": ["Tail/vtail1.stl", "Tail/vtail2.stl", "Tail/taileron.stl"],
        "surface_id": "vtail_right",
    },
    "fuselage": {
        "files": ["Fuselage/fuse1.stl", "Fuselage/fuse2.stl", "Fuselage/fuse3.stl",
                  "Fuselage/fuse4.stl", "Fuselage/fuse5.stl", "Fuselage/canopy1.stl",
                  "Fuselage/canopy2.stl", "Fuselage/hatch1.stl", "Fuselage/hatch2.stl"],
        "surface_id": None,
    },
    "mount": {
        "files": ["High Temp PETG or ABS or ASA/motor_mount.stl"],
        "surface_id": None,
        "part_ids": ["recon_motor_mount"],
    },
    "plate": {
        "files": ["High Temp PETG or ABS or ASA/wing_bay_plate.stl"],
        "surface_id": None,
        "part_ids": ["recon_wing_bay_plate"],
    },
}

NO_REFERENCE = {
    "spar": "no spar exists in the source archive",
    "battery": "no battery exists in the source archive",
    "motor": "no motor exists in the source archive",
    "prop": "no propeller exists in the source archive",
}


# ---------------------------------------------------------------- reference meshes

def to_frd_mesh(mesh: trimesh.Trimesh, frame: dict[str, Any]) -> trimesh.Trimesh:
    """Native mesh -> FRD metres, source side mapped to +y."""
    s = float(frame.get("scale_to_m", 0.001))
    y_nose = float(frame.get("nose_datum_native", [0, 0, 0])[1])
    sign = 1.0 if frame.get("source_side", "right") == "right" else -1.0
    v = mesh.vertices
    out = mesh.copy()
    out.vertices = np.column_stack([-(v[:, 1] - y_nose) * s, sign * v[:, 0] * s, -v[:, 2] * s])
    out.invert()  # the y map is a reflection; repair the winding rather than leave it inside out
    return out


def _load_group(reference_dir: Path, files: Iterable[str], frame: dict[str, Any]):
    meshes = []
    missing = []
    for rel in files:
        path = reference_dir / rel
        if not path.exists():
            missing.append(rel)
            continue
        meshes.append(to_frd_mesh(trimesh.load(str(path), process=False), frame))
    if not meshes:
        return None, missing
    return trimesh.util.concatenate(meshes), missing


def _tessellate(part: ReconPart, tolerance_mm: float = 0.05) -> trimesh.Trimesh:
    verts, tris = part.solid.tessellate(tolerance_mm)
    v = np.array([[p.x / MM, p.y / MM, p.z / MM] for p in verts], dtype=float)
    return trimesh.Trimesh(vertices=v, faces=np.array(tris, dtype=np.int64), process=False)


def projected_planform_area_m2(part: ReconPart, tolerance_mm: float = 0.02) -> float:
    """Planform area of one solid, projected onto the x-y plane and counted once.

    Summing the signed x-y area of every triangle of a closed solid gives zero; summing only
    the positive ones gives the silhouette. That is what stops upper and lower skins (or
    a control surface lofted into its parent) being counted twice.
    """
    mesh = _tessellate(part, tolerance_mm)
    tri = mesh.triangles
    signed = 0.5 * (
        (tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1])
        - (tri[:, 2, 0] - tri[:, 0, 0]) * (tri[:, 1, 1] - tri[:, 0, 1])
    )
    return float(signed[signed > 0].sum())


# ---------------------------------------------------------------- metrics

def _slice_extents(mesh: trimesh.Trimesh, y: float) -> Optional[dict[str, float]]:
    sec = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
    if sec is None or len(sec.vertices) < 3:
        return None
    p = sec.vertices
    le, te = float(p[:, 0].max()), float(p[:, 0].min())
    return {
        "leading_edge_x_m": le,
        "chord_m": le - te,
        "z_m": float((p[:, 2].min() + p[:, 2].max()) / 2),
    }


def _rms(values: list[float]) -> Optional[float]:
    return float(np.sqrt(np.mean(np.square(values)))) if values else None


def _sample(mesh: trimesh.Trimesh, count: int, seed: int) -> np.ndarray:
    """Deterministic area-weighted surface sampling (no global RNG state)."""
    rng = np.random.default_rng(seed)
    areas = mesh.area_faces
    total = areas.sum()
    if total <= 0:
        return mesh.vertices[: min(count, len(mesh.vertices))]
    face_idx = rng.choice(len(areas), size=count, p=areas / total)
    tri = mesh.triangles[face_idx]
    u = rng.random((count, 1))
    v = rng.random((count, 1))
    flip = (u + v) > 1
    u[flip] = 1 - u[flip]
    v[flip] = 1 - v[flip]
    return tri[:, 0] + u * (tri[:, 1] - tri[:, 0]) + v * (tri[:, 2] - tri[:, 0])


def _distance_stats(source: trimesh.Trimesh, target: trimesh.Trimesh, n: int, seed: int):
    pts = _sample(source, n, seed)
    _, dist, _ = target.nearest.on_surface(pts)
    return {
        "n_samples": int(len(pts)),
        "rms_m": float(np.sqrt(np.mean(dist**2))),
        "mean_m": float(np.mean(dist)),
        "max_m": float(np.max(dist)),
        "p95_m": float(np.percentile(dist, 95)),
    }


# ---------------------------------------------------------------- entry point

def fit_report(
    model: CadModel,
    reference: str | Path | Any,
    frame: Optional[dict[str, Any]] = None,
    samples: int = 4000,
    seed: int = 20260919,
) -> dict[str, Any]:
    """Compare the reconstruction with the reference meshes. Numbers only, no verdict.

    `reference` is the directory holding the original STL tree, or a DesignManifest (object
    or dict) carrying a confirmed frame and source paths — in which case its frame is used
    and its `reference_dir` / the given directory supplies the files.
    """
    reference_dir, frame = _resolve_reference(reference, frame)

    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "design_id": model.design_id,
        "revision_id": model.revision_id,
        "confirmed": False,
        "confirmation_note": (
            "Fit numbers only. A human must record a 'reconstruction confirmed' decision "
            "before the reconstruction is used for engineering comparison."
        ),
        "frame": frame,
        "reference_dir": str(reference_dir) if reference_dir else None,
        "method": {
            "station_deviation": "axis-aligned y sections of both meshes at each parameter station",
            "surface_distance": "deterministic area-weighted sampling, point-to-surface both ways",
            "tessellation_tolerance_mm": 0.05,
            "samples_per_direction": samples,
            "seed": seed,
        },
        "parts": {},
        "surfaces": {},
        "overall": {},
        "notes": [],
        "warnings": list(model.warnings),
    }

    if reference_dir is None or not Path(reference_dir).exists():
        report["notes"].append(
            f"reference geometry not available at {reference_dir!r}; no fit computed"
        )
        return report

    if not frame.get("confirmed", False):
        report["notes"].append(
            "Frame is UNCONFIRMED. These deviations describe the reconstruction against a "
            "candidate alignment and must not be published as aircraft metrics."
        )

    group_meshes: dict[str, Optional[trimesh.Trimesh]] = {}
    for key, spec in REFERENCE_GROUPS.items():
        mesh, missing = _load_group(Path(reference_dir), spec["files"], frame)
        group_meshes[key] = mesh
        if missing:
            report["notes"].append(f"{key}: missing reference files {missing}")

    all_ref_d: list[float] = []
    all_recon_d: list[float] = []
    all_station_d: list[float] = []

    for part in model.parts:
        entry: dict[str, Any] = {
            "category": part.category,
            "representation": part.representation,
            "side": part.side,
        }
        if part.mirror_of:
            entry["skipped"] = (
                f"mirrored occurrence of {part.mirror_of}; the reference archive supplies one "
                "side only, so the fit of the parent applies"
            )
            report["parts"][part.part_id] = entry
            continue
        if part.category in NO_REFERENCE:
            entry["skipped"] = NO_REFERENCE[part.category]
            report["parts"][part.part_id] = entry
            report["parts"][part.part_id]["reference"] = None
            continue

        group_key = _group_for(part)
        ref = group_meshes.get(group_key) if group_key else None
        if ref is None:
            entry["skipped"] = f"no reference group for category {part.category!r}"
            report["parts"][part.part_id] = entry
            continue

        recon = _tessellate(part)
        entry["reference_group"] = group_key
        entry["reference_watertight"] = bool(ref.is_watertight)
        entry["reference_to_reconstruction"] = _distance_stats(ref, recon, samples, seed)
        entry["reconstruction_to_reference"] = _distance_stats(recon, ref, samples, seed + 1)
        entry["volume_m3"] = part.volume_m3()
        entry["bounds_m"] = part.bounds_m()
        entry["reference_bounds_m"] = [list(map(float, ref.bounds[0])), list(map(float, ref.bounds[1]))]

        d_ref = entry["reference_to_reconstruction"]
        d_rec = entry["reconstruction_to_reference"]
        all_ref_d.append(d_ref["rms_m"])
        all_recon_d.append(d_rec["rms_m"])

        # Station deviations for the lofted surfaces.
        surface = _surface_params(model, part)
        if surface is not None:
            rows = []
            devs: list[float] = []
            for st in surface.stations:
                got = _slice_extents(recon, st.span_y_m)
                want = _slice_extents(ref, st.span_y_m)
                if got is None or want is None:
                    rows.append({"span_y_m": st.span_y_m, "skipped": "no section in one mesh"})
                    continue
                row = {
                    "span_y_m": st.span_y_m,
                    "leading_edge_x_m": {"reference": want["leading_edge_x_m"],
                                         "reconstruction": got["leading_edge_x_m"],
                                         "deviation_m": got["leading_edge_x_m"] - want["leading_edge_x_m"]},
                    "chord_m": {"reference": want["chord_m"], "reconstruction": got["chord_m"],
                                "deviation_m": got["chord_m"] - want["chord_m"]},
                    "z_m": {"reference": want["z_m"], "reconstruction": got["z_m"],
                            "deviation_m": got["z_m"] - want["z_m"]},
                }
                rows.append(row)
                devs.extend(
                    abs(row[k]["deviation_m"]) for k in ("leading_edge_x_m", "chord_m", "z_m")
                )
            all_station_d.extend(devs)
            report["surfaces"][surface.surface_id] = {
                "part_id": part.part_id,
                "stations": rows,
                "station_deviation_rms_m": _rms(devs),
                "station_deviation_max_m": max(devs) if devs else None,
            }

        report["parts"][part.part_id] = entry

    report["overall"] = {
        "station_deviation_rms_m": _rms(all_station_d),
        "station_deviation_max_m": max(all_station_d) if all_station_d else None,
        "reference_to_reconstruction_rms_m": _rms(all_ref_d),
        "reconstruction_to_reference_rms_m": _rms(all_recon_d),
        "surface_distance_max_m": max(
            [
                v["reference_to_reconstruction"]["max_m"]
                for v in report["parts"].values()
                if "reference_to_reconstruction" in v
            ]
            + [
                v["reconstruction_to_reference"]["max_m"]
                for v in report["parts"].values()
                if "reconstruction_to_reference" in v
            ]
            or [0.0]
        )
        or None,
        "parts_compared": sum(1 for v in report["parts"].values() if "reference_group" in v),
        "parts_without_reference": sum(1 for v in report["parts"].values() if "skipped" in v),
    }
    report["notes"].append(
        "Several reference meshes are open shells (fuse2, fuse4, fuse5, hatch2, wing1, wing3*, "
        "motor_mount). Surface distance is still meaningful; any volume comparison is not."
    )
    return report


def _group_for(part: ReconPart) -> Optional[str]:
    for key, spec in REFERENCE_GROUPS.items():
        if "part_ids" in spec and part.part_id in spec["part_ids"]:
            return key
    return part.category if part.category in REFERENCE_GROUPS else None


def _surface_params(model: CadModel, part: ReconPart):
    sid = part.parameters.get("surface_id")
    if not sid:
        return None
    for s in model.params.surfaces:
        if s.surface_id == sid:
            return s
    return None


def _resolve_reference(reference: Any, frame: Optional[dict[str, Any]]):
    """Accept a directory, or a DesignManifest object/dict carrying a confirmed frame."""
    if isinstance(reference, (str, Path)):
        return Path(reference), dict(frame or CANDIDATE_FRAME)

    data = reference if isinstance(reference, dict) else getattr(reference, "model_dump", dict)()
    if callable(data):
        data = data()
    manifest_frame = data.get("frame") or {}
    resolved = dict(frame or {})
    if manifest_frame and not frame:
        resolved = {
            "scale_to_m": manifest_frame.get("scale_to_m", 0.001),
            "nose_datum_native": manifest_frame.get("nose_datum_native", [0, 0, 0]),
            "source_side": "right",
            "confirmed": bool(manifest_frame.get("confirmed", False)),
            "native_to_frd": manifest_frame.get("native_to_frd"),
            "from_manifest": True,
        }
    ref_dir = data.get("reference_dir") or data.get("staged_dir")
    return (Path(ref_dir) if ref_dir else None), (resolved or dict(CANDIDATE_FRAME))
