"""Per-mesh QA on staged sources. Reports what the file is, never what it means.

Watertightness is judged after merging coincident vertices (a binary STL stores every triangle
independently, so an unmerged mesh is never watertight and the answer would be meaningless).
The folder name is carried through as a hint: it is evidence about the author's intent, not proof.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import trimesh

from dronebench_contracts.models import MeshQA, SourceFile

from .staging import StagedArchive, StagedFile

DEGENERATE_AREA = 1e-12       # native units squared


@lru_cache(maxsize=64)
def _load_cached(path: str, mtime: float, size: int) -> trimesh.Trimesh:
    mesh = trimesh.load(path, process=True, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"{Path(path).name}: no triangle mesh")
    return mesh


def load_mesh(path: str | Path) -> trimesh.Trimesh:
    """Load a mesh in its native file units, with coincident vertices merged. Cached per file."""
    p = Path(path)
    st = p.stat()
    return _load_cached(str(p), st.st_mtime, st.st_size)


def mesh_qa(mesh: trimesh.Trimesh) -> MeshQA:
    areas = trimesh.triangles.area(mesh.triangles) if len(mesh.faces) else np.zeros(0)
    finite = bool(np.isfinite(mesh.vertices).all())
    bounds = mesh.bounds if finite and len(mesh.vertices) else np.zeros((2, 3))
    return MeshQA(
        triangles=int(len(mesh.faces)),
        finite=finite,
        watertight=bool(mesh.is_watertight),
        components=int(mesh.body_count),
        degenerate_faces=int((areas <= DEGENERATE_AREA).sum()),
        consistent_winding=bool(mesh.is_winding_consistent),
        bounds_native=[[float(v) for v in bounds[0]], [float(v) for v in bounds[1]]],
    )


def inspect_source(staged: StagedFile) -> SourceFile:
    return SourceFile(
        source_path=staged.source_path,
        sha256=staged.sha256,
        size_bytes=staged.size_bytes,
        qa=mesh_qa(load_mesh(staged.staged_path)),
        folder_hint=staged.folder_hint,
    )


def inspect_sources(staged: StagedArchive) -> list[SourceFile]:
    """QA every mesh in the staged archive, in source-path order. Non-mesh files are skipped."""
    return [inspect_source(f) for f in staged.meshes]
