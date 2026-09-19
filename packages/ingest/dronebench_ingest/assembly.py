"""Turn manifest occurrences back into placed meshes in the canonical FRD frame (metres).

The definition of a mesh part is its source file scaled to metres; a mirrored part's definition is
that geometry reflected about the confirmed plane with its winding repaired, so the placement stays
a proper rotation. This module is the single place that applies the two steps in that order.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import trimesh

from dronebench_contracts.models import DesignManifest, PartOccurrence

from .frame import definition_scale_matrix, mirror_matrix
from .inspection import load_mesh


def definition_mesh(manifest: DesignManifest, part: PartOccurrence) -> trimesh.Trimesh:
    """A mesh part's definition geometry in metres, in its own (native-derived) axes."""
    if part.source is None:
        raise ValueError(f"{part.part_id}: not a mesh occurrence")
    root = Path(manifest.sources_root or ".")
    mesh = load_mesh(root / part.source).copy()
    mesh.apply_transform(definition_scale_matrix(manifest.frame))
    if part.mirror_of is not None:
        mesh.apply_transform(mirror_matrix(manifest.frame))
        # a reflection inverts every triangle; put the outward normals back
        mesh.invert()
        mesh.fix_normals()
    return mesh


def placed_mesh(manifest: DesignManifest, part: PartOccurrence) -> trimesh.Trimesh:
    """A mesh part in FRD metres, placement applied."""
    mesh = definition_mesh(manifest, part)
    mesh.apply_transform(np.array(part.T_parent_from_local, dtype=float))
    return mesh


def envelope_mesh(part: PartOccurrence) -> trimesh.Trimesh:
    """A bought component's box envelope in FRD metres (visualisation and clearance only)."""
    extents = [float(v) for v in part.labels["envelope_m"].split(",")]
    box = trimesh.creation.box(extents=extents)
    box.apply_transform(np.array(part.T_parent_from_local, dtype=float))
    return box


def part_meshes(manifest: DesignManifest, categories: tuple[str, ...] | None = None
                ) -> dict[str, trimesh.Trimesh]:
    """Every installed occurrence as a placed mesh in FRD metres, keyed by part_id."""
    out: dict[str, trimesh.Trimesh] = {}
    for part in manifest.parts:
        if categories is not None and part.category not in categories:
            continue
        out[part.part_id] = placed_mesh(manifest, part) if part.source else envelope_mesh(part)
    return out
