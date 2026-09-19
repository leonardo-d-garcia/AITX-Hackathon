"""Reference GLB export: one node per part_id, metres, ready for the viewer.

glTF is Y-up and right-handed, so the FRD assembly is rotated at the scene root with the adapter
the architecture fixes: ``(x, y, z)_FRD -> (y, -z, -x)``. Part geometry itself is untouched, so a
consumer can read a node's world transform and map it straight back to FRD.

The GLB is a *reference* artifact: it renders the original vendor meshes. It is not a
reconstruction and must be labelled as such wherever it is shown or downloaded.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from dronebench_contracts.models import Artifact, DesignManifest, ErrorEnvelope

from .assembly import envelope_mesh, placed_mesh
from .errors import assembly_unconfirmed, units_unconfirmed
from .staging import sha256_file
from .variants import selection_errors

# (x, y, z)_FRD -> (y, -z, -x): FRD to the glTF right-handed Y-up display frame.
FRD_TO_GLTF: list[list[float]] = [
    [0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, -1.0, 0.0],
    [-1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0],
]
GLB_NAME = "reference_meshes.glb"
CREASE_ANGLE_RAD = np.radians(30.0)


def shade(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Split vertices across sharp edges so the GLB can carry usable per-vertex normals.

    glTF has no "compute the normals for me": a primitive without a NORMAL accessor is shaded flat
    black by most renderers, so normals are written explicitly. Averaging them over every incident
    face would smear a printed part's hard edges, so vertices are duplicated where the dihedral
    angle exceeds the crease angle and averaged only within a smooth patch.
    """
    shaded = trimesh.graph.smooth_shade(mesh, angle=CREASE_ANGLE_RAD)
    shaded.vertex_normals  # noqa: B018 - force the accessor so the exporter finds them
    return shaded


def build_scene(manifest: DesignManifest) -> trimesh.Scene:
    """Scene with one node named after each part_id, in the glTF display frame, metres."""
    scene = trimesh.Scene()
    adapter = np.array(FRD_TO_GLTF, dtype=float)
    for part in manifest.parts:
        mesh = placed_mesh(manifest, part) if part.source else envelope_mesh(part)
        mesh.apply_transform(adapter)
        mesh = shade(mesh)
        mesh.metadata["name"] = part.part_id
        scene.add_geometry(mesh, node_name=part.part_id, geom_name=part.part_id)
    scene.metadata["dronebench"] = {
        "frame": "gltf Y-up; FRD -> glTF is (x,y,z) -> (y,-z,-x)",
        "units": "m",
        "representation": "reference_mesh",
        "revision_id": manifest.revision_id,
        "label": "Original mesh reference — not a reconstruction, not Titan's CAD",
    }
    return scene


def export_reference_glb(manifest: DesignManifest, out_path: str | Path | None = None
                         ) -> Artifact | ErrorEnvelope:
    """Write one GLB containing every installed occurrence. Requires a confirmed design."""
    if not manifest.frame.confirmed:
        return units_unconfirmed("frame is not confirmed; the assembly may not be exported",
                                 design_id=manifest.design_id, revision_id=manifest.revision_id)
    unresolved = selection_errors(manifest.variants)
    if unresolved:
        return assembly_unconfirmed(f"variant groups without a selection: {', '.join(unresolved)}",
                                    design_id=manifest.design_id, revision_id=manifest.revision_id,
                                    groups=unresolved)
    path = Path(out_path) if out_path is not None else Path.cwd() / GLB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_scene(manifest).export(file_type="glb", include_normals=True))
    return Artifact(
        path=path.name,
        sha256=sha256_file(path),
        media_type="model/gltf-binary",
        representation="reference_mesh",
        part_ids=[p.part_id for p in manifest.parts],
    )
