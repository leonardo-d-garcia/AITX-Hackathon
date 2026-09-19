"""Write the revision artifacts: STEP assembly, GLB, part_map, BOM, changes.

Export acceptance (architecture §6) is the caller's next step: `reimport_check()` reads the
STEP back in a fresh process and compares semantics. Nothing here compares STEP bytes —
entity numbering and face ordering are not required to be stable.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Optional

from cadquery.occ_impl.exporters.assembly import exportAssembly, exportGLTF

from .model import CadModel

__all__ = [
    "export",
    "STEP_NAME",
    "GLB_NAME",
    "PART_MAP_NAME",
    "BOM_NAME",
    "CHANGES_NAME",
    "sha256_file",
]

STEP_NAME = "updated_reconstruction.step"
GLB_NAME = "reconstruction.glb"
PART_MAP_NAME = "part_map.json"
BOM_NAME = "bom.json"
CHANGES_NAME = "changes.json"

_LABEL = "Editable reconstruction — not the original Titan CAD"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _bom(model: CadModel) -> dict[str, Any]:
    """One row per reconstructed part.

    Mass is a claim, not a number we are willing to invent: printed-shell volume is not
    mass, and no motor, battery or spar exists in the source archive. A mass only appears
    when a curated (synthetic) demo BOM put it in the parameters.
    """
    rows = []
    for p in model.parts:
        mass = p.parameters.get("mass_kg")
        rows.append(
            {
                "part_id": p.part_id,
                "name": p.name,
                "category": p.category,
                "representation": p.representation,
                "side": p.side,
                "quantity": 1,
                "volume_m3": p.volume_m3(),
                "mass_kg": {
                    "value": mass,
                    "unit": "kg",
                    "status": "estimated" if mass is not None else "unknown",
                    "source_kind": "catalog" if mass is not None else None,
                    "assumptions": (
                        ["synthetic demo BOM entry, labelled as such; not measured"]
                        if mass is not None
                        else ["no mass evidence; geometric volume is not mass"]
                    ),
                },
                "material": {
                    "value": None,
                    "status": "unknown",
                    "assumptions": ["geometry does not determine material"],
                },
                "notes": p.notes,
            }
        )
    return {
        "schema_version": "0.1.0",
        "design_id": model.design_id,
        "revision_id": model.revision_id,
        "label": _LABEL,
        "items": rows,
    }


def export(
    model: CadModel,
    out_dir: str | Path,
    changes: Optional[Iterable[dict[str, Any]]] = None,
    cause: str = "reconstruct",
) -> list[dict[str, Any]]:
    """Write every artifact for one revision and return Artifact dicts with hashes.

    The returned dicts validate against `dronebench_contracts.models.Artifact`; this package
    does not import the contracts so that A2 stays usable while B reshapes them.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    part_ids = [p.part_id for p in model.parts]

    step_path = out / STEP_NAME
    # mode="default" keeps the parts as separate, named solids; "fused" would destroy them.
    exportAssembly(model.assembly(), str(step_path), mode="default", unit="MM", outputUnit="MM")

    glb_path = out / GLB_NAME
    # GLB is written in metres (glTF's unit), so the geometry is scaled, not placed.
    exportGLTF(model.assembly(scale=0.001), str(glb_path), binary=True, tolerance=1e-4,
               angularTolerance=0.1)

    part_map = model.part_map()
    part_map["cause"] = cause
    _write_json(out / PART_MAP_NAME, part_map)
    _write_json(out / BOM_NAME, _bom(model))
    _write_json(
        out / CHANGES_NAME,
        {
            "schema_version": "0.1.0",
            "design_id": model.design_id,
            "revision_id": model.revision_id,
            "cause": cause,
            "changes": list(changes or []),
        },
    )

    specs = [
        (step_path, "application/step", "reconstruction", part_ids),
        (glb_path, "model/gltf-binary", "reconstruction", part_ids),
        (out / PART_MAP_NAME, "application/json", None, part_ids),
        (out / BOM_NAME, "application/json", None, part_ids),
        (out / CHANGES_NAME, "application/json", None, []),
    ]
    return [
        {
            "path": path.name,
            "sha256": sha256_file(path),
            "media_type": media,
            "representation": representation,
            "part_ids": ids,
        }
        for path, media, representation, ids in specs
    ]
