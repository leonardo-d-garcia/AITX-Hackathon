"""DroneBench Studio — Team A, deliverable A2: the editable CAD representation.

Public API:

    reconstruct(features=None, params=None, part_ids=None) -> CadModel
    export(model, out_dir, changes=None, cause="reconstruct") -> list[Artifact dict]
    reimport_check(step_path, expected, tolerances=None, timeout_s=120) -> list[check dict]
    fit_report(model, reference, frame=None, samples=4000, seed=...) -> dict
    ReconParams / load_params(path) / dump_params(params, path)

Everything this package produces is an **engineering reconstruction** of the Avenger
reference meshes: assumed airfoil, simplified fuselage envelope, and synthetic hardware
envelopes that do not exist in the source archive. It is never the manufacturer's CAD, and
the label travels with every part, artifact and filename.
"""
from __future__ import annotations

from .airfoil import naca4_points
from .exporter import (
    BOM_NAME,
    CHANGES_NAME,
    GLB_NAME,
    PART_MAP_NAME,
    STEP_NAME,
    export,
    sha256_file,
)
from .fit import fit_report, projected_planform_area_m2
from .model import CadModel, ReconPart
from .params import (
    DEFAULT_PARAMS_PATH,
    BoxParams,
    FuselageStationParams,
    MotorParams,
    ReconParams,
    SparParams,
    StationParams,
    SurfaceParams,
    dump_params,
    load_params,
)
from .reconstruct import DEFAULT_PART_IDS, reconstruct
from .roundtrip import DEFAULT_TOLERANCES, reimport_check

__version__ = "0.1.0"
REPRESENTATION_LABEL = "Editable reconstruction — not the original Titan CAD"

__all__ = [
    "BOM_NAME",
    "BoxParams",
    "CHANGES_NAME",
    "CadModel",
    "DEFAULT_PARAMS_PATH",
    "DEFAULT_PART_IDS",
    "DEFAULT_TOLERANCES",
    "FuselageStationParams",
    "GLB_NAME",
    "MotorParams",
    "PART_MAP_NAME",
    "REPRESENTATION_LABEL",
    "ReconParams",
    "ReconPart",
    "SparParams",
    "STEP_NAME",
    "StationParams",
    "SurfaceParams",
    "dump_params",
    "export",
    "fit_report",
    "load_params",
    "naca4_points",
    "projected_planform_area_m2",
    "reconstruct",
    "reimport_check",
    "sha256_file",
    "__version__",
]
