"""DroneBench ingest: stage a mesh archive, inspect it, confirm it, and measure it.

Public API (all coordinates FRD metres once confirmed; see ``frame.py``):

    stage_archive(zip_or_dir, out_dir) -> StagedArchive
    load_staged(design_dir) -> StagedArchive
    inspect_sources(staged) -> list[SourceFile]
    propose_frame(sources) -> FrameConfirmation          # always unconfirmed
    detect_variants(sources) -> list[VariantGroup]       # never auto-selected
    confirm(design_dir, units, frame=None, variants=..., mirror=..., mass_model=...) -> RevisionManifest
    build_manifest(design_id, revision_id, staged, sources, frame, variants, ...) -> DesignManifest
    geometry_features(manifest) -> GeometryFeatures | ErrorEnvelope
    export_reference_glb(manifest, out_path) -> Artifact | ErrorEnvelope

Nothing here fabricates mass, material or hardware: unknown stays unknown, and a metric asked of an
unconfirmed design comes back as an ErrorEnvelope rather than a number.
"""
from .assembly import definition_mesh, envelope_mesh, part_meshes, placed_mesh
from .bom import load_demo_bom
from .errors import IngestError
from .features import geometry_features
from .frame import categorize, placement_matrix, propose_frame, to_frd
from .glb import build_scene, export_reference_glb
from .inspection import inspect_sources, load_mesh, mesh_qa
from .manifest import build_manifest, stable_part_id
from .revisions import confirm, load_features, load_manifest, preview_manifest, revision_dir
from .staging import StagedArchive, StagedFile, load_staged, stage_archive
from .variants import detect_variants

__all__ = [
    "IngestError", "StagedArchive", "StagedFile", "build_manifest", "build_scene", "categorize",
    "confirm", "definition_mesh", "detect_variants", "envelope_mesh", "export_reference_glb",
    "geometry_features", "inspect_sources", "load_demo_bom", "load_features", "load_manifest",
    "load_mesh", "load_staged", "mesh_qa", "part_meshes", "placed_mesh", "placement_matrix",
    "preview_manifest", "propose_frame", "revision_dir", "stable_part_id", "stage_archive", "to_frd",
]
