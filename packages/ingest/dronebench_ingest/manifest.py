"""Build the design manifest and write confirmed revisions.

One ``PartOccurrence`` per *installed* part. Unselected variants never become occurrences; they are
listed in ``excluded_sources``. A mirrored occurrence gets its own ``part_id``, an explicit
``mirror_of``, a mirrored definition (winding repaired in ``assembly.py``) and the same rigid
placement — no reflection ever enters a transform.

Mass rules (architecture §3, §5): geometry is not mass. A printed part's mass is ``unknown`` unless
``mass_model="shell_estimate"`` was explicitly selected at confirm, and then it is ``estimated``
with its assumptions attached. Bought components come from the synthetic demo BOM as envelopes.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np

from dronebench_contracts.models import (
    SCHEMA_VERSION, Claim, DesignManifest, EditCapability, Evidence, FrameConfirmation,
    PartOccurrence, SourceFile, SourceKind, Status, VariantGroup,
)

from . import bom as demo_bom
from .frame import (AERO_CATEGORIES, FUSELAGE_CATEGORIES, categorize, mirror_matrix,
                    placement_matrix, to_frd)
from .inspection import load_mesh
from .staging import StagedArchive

# shell mass model (only used when explicitly selected)
SHELL_THICKNESS_M = 0.0012        # ~3 perimeters of a 0.4 mm nozzle
SHELL_DENSITY_KG_M3 = 1240.0      # PLA-class; PETG/ABS/ASA differ by up to ~15 %
SHELL_ASSUMPTIONS = [
    f"uniform shell of {SHELL_THICKNESS_M * 1000:.1f} mm wall on the mesh surface",
    f"density {SHELL_DENSITY_KG_M3:.0f} kg/m^3 (PLA-class); the folder hint names PETG/ABS/ASA, "
    "whose densities differ — material is still unknown",
    "every mesh facet counted once: a mesh that already models an inner wall is over-estimated",
    "ignores infill, ribs, hardware, adhesive and paint",
    "explicitly selected mass model, not a measurement",
]
UNKNOWN_MASS_ASSUMPTIONS = [
    "no measured mass, slicer report or BOM entry for this printed part",
    "mesh volume is not mass: a filled bounding envelope is never plastic volume",
]

# Declared mating/nesting stem pairs: these parts are meant to touch or interpenetrate, so their
# contact is not interference. Proximity here is a *declaration*, never an inferred fastening.
MATING_STEMS: tuple[tuple[str, str], ...] = (
    ("fuse1", "fuse2"), ("fuse2", "fuse3"), ("fuse3", "fuse4"), ("fuse4", "fuse5"),
    ("fuse5", "motor_mount"), ("canopy1", "canopy2"), ("canopy1", "fuse1"), ("canopy1", "fuse2"),
    ("canopy2", "fuse2"), ("canopy2", "fuse3"), ("hatch1", "hatch2"), ("hatch1", "fuse3"),
    ("hatch2", "fuse4"), ("wing1", "wing2"), ("wing2", "wing3"), ("wing3", "wing4"),
    ("wing4", "wing5"), ("wing3", "aileron"), ("wing3", "wing_bay_plate"),
    ("wing1", "fuse2"), ("wing1", "fuse3"), ("vtail1", "vtail2"), ("vtail1", "taileron"),
    ("vtail1", "fuse4"), ("vtail1", "fuse5"),
)
SERVO_HOSTS = AERO_CATEGORIES + FUSELAGE_CATEGORIES


def stem_of(source_path: str) -> str:
    return re.split(r"[/\\]", source_path)[-1].rsplit(".", 1)[0]


def variant_head(stem: str) -> str:
    """``wing3_12mm_hole`` -> ``wing3``: the stem without its variant suffix, for mating lookups."""
    m = re.match(r"^([A-Za-z]+\d*)(?:[_\-].*)?$", stem)
    return m.group(1) if m else stem


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "part"


def stable_part_id(kind: str, key: str, occurrence: int, side: str) -> str:
    """Deterministic installed-occurrence id: readable stem + side + a hash of its provenance.

    The hash covers the source path (or BOM id), the occurrence index and the side, so the same
    inputs always produce the same id and two files with the same basename cannot collide.
    """
    digest = hashlib.sha1(f"{kind}|{key}|{occurrence}|{side}".encode()).hexdigest()[:6]
    return f"{_slug(stem_of(key))}-{side[0]}-{digest}"


# ------------------------------------------------------------------ claims

def _mass_claim(mesh_area_m2: float, watertight: bool, mass_model: str, evidence_id: str) -> Claim:
    if mass_model != "shell_estimate":
        return Claim(value=None, unit="kg", status=Status.unknown,
                     assumptions=list(UNKNOWN_MASS_ASSUMPTIONS))
    assumptions = list(SHELL_ASSUMPTIONS)
    if not watertight:
        assumptions.append("source mesh is not watertight; its surface area — and therefore this "
                           "estimate — is only as good as the open shell")
    return Claim(value=float(mesh_area_m2 * SHELL_THICKNESS_M * SHELL_DENSITY_KG_M3), unit="kg",
                 status=Status.estimated, source_kind=SourceKind.computed,
                 evidence_ids=[evidence_id], assumptions=assumptions)


def _com_claim(mesh, watertight: bool, evidence_id: str) -> Claim:
    if not watertight:
        return Claim.unknown("m", "mesh is not watertight; no centroid is defined for it")
    return Claim(value=[float(v) for v in mesh.center_mass], unit="m", status=Status.estimated,
                 source_kind=SourceKind.computed, evidence_ids=[evidence_id],
                 assumptions=["geometric centroid of the closed mesh under a uniform-density "
                              "assumption; this is not a measured centre of mass",
                              "expressed in the part's own definition axes (metres)"])


def _mirror_com(parent: Claim, frame: FrameConfirmation) -> Claim:
    """The mirrored definition's centroid: the parent's, reflected in the same plane."""
    if parent.value is None:
        return parent.model_copy(deep=True)
    point = np.array(parent.value, dtype=float)
    reflected = (mirror_matrix(frame)[:3, :3] @ point).tolist()
    return parent.model_copy(deep=True, update={
        "value": [float(v) for v in reflected],
        "assumptions": [*parent.assumptions, "reflected from the parent occurrence's centroid in "
                        f"the confirmed mirror plane {frame.mirror_plane_native}"],
    })


def _material_claim(folder_hint: Optional[str], evidence_id: str) -> Claim:
    if not folder_hint:
        return Claim.unknown(None, "no material evidence in the archive")
    return Claim(value=None, status=Status.unknown, source_kind=SourceKind.inferred,
                 evidence_ids=[evidence_id],
                 assumptions=[f"folder name {folder_hint!r} is evidence of a suggested choice, not "
                              "proof of the material used; geometry cannot determine chemistry"])


def _function_claim(category: str, evidence_id: str) -> Claim:
    if category == "other":
        return Claim.unknown(None, "filename gives no function hint")
    return Claim(value=category, status=Status.estimated, source_kind=SourceKind.inferred,
                 evidence_ids=[evidence_id],
                 assumptions=["function read from the filename and folder; filenames are evidence, "
                              "not a specification"])


# ------------------------------------------------------------------ manifest

def _installed_sources(sources: list[SourceFile], variants: list[VariantGroup]) -> list[SourceFile]:
    excluded = {o for v in variants for o in v.options if o != v.selected}
    return [s for s in sources if s.source_path not in excluded]


OFF_CENTRE_TOLERANCE = 1e-3       # native units


def _off_centre(src: SourceFile) -> bool:
    """True when the body lies wholly on one side of the mirror plane, so it has a counterpart.

    Purely geometric: a body that straddles the plane (fuselage, canopy, motor mount) is a single
    centre occurrence. The side name still depends on the confirmed rotation.
    """
    lo, hi = src.qa.bounds_native[0][0], src.qa.bounds_native[1][0]
    return lo > OFF_CENTRE_TOLERANCE or hi < -OFF_CENTRE_TOLERANCE


def _side_from_frame(src: SourceFile, frame: FrameConfirmation) -> str:
    """Which side of the aircraft the body lands on under the *confirmed* rotation."""
    centre = (np.array(src.qa.bounds_native[0]) + np.array(src.qa.bounds_native[1])) / 2
    return "right" if to_frd(centre.reshape(1, 3), frame)[0][1] > 0 else "left"


def _mating(parts: list[PartOccurrence]) -> None:
    """Fill ``allowed_overlap_with`` from the declared stem pairs and the BOM nesting rules."""
    by_stem: dict[str, list[PartOccurrence]] = {}
    for p in parts:
        if p.source:
            by_stem.setdefault(variant_head(stem_of(p.source)), []).append(p)
    allow: dict[str, set[str]] = {p.part_id: set() for p in parts}

    def pair(a: PartOccurrence, b: PartOccurrence) -> None:
        allow[a.part_id].add(b.part_id)
        allow[b.part_id].add(a.part_id)

    for left, right in MATING_STEMS:
        for a in by_stem.get(left, []):
            for b in by_stem.get(right, []):
                if a.side == b.side or "center" in (a.side, b.side):
                    pair(a, b)
    # a mesh part and its own mirror never touch, so nothing is declared between them
    hosts = [p for p in parts if p.source and p.category in FUSELAGE_CATEGORIES]
    aero = [p for p in parts if p.source and p.category in SERVO_HOSTS]
    for env in [p for p in parts if p.representation == "envelope"]:
        targets = aero if env.category == "servo" else hosts
        for host in targets:
            pair(env, host)
    for env in [p for p in parts if p.category in ("motor", "prop")]:
        for host in [p for p in parts if p.category in ("motor", "prop", "mount")]:
            if host.part_id != env.part_id:
                pair(env, host)
    for p in parts:
        p.allowed_overlap_with = sorted(allow[p.part_id])


def build_manifest(
    design_id: str,
    revision_id: str,
    staged: StagedArchive,
    sources: list[SourceFile],
    frame: FrameConfirmation,
    variants: list[VariantGroup],
    mass_model: str = "none",
    title: str = "Titan Avenger (reference mesh import)",
    demo_bom_path: str | Path | None = None,
) -> DesignManifest:
    """One occurrence per installed part, plus the synthetic demo BOM envelopes.

    ``frame`` must already be confirmed for the result to be usable for metrics; an unconfirmed
    frame still builds a manifest (so the viewer can show a preview) and is flagged in ``warnings``.
    """
    evidence: list[Evidence] = []
    parts: list[PartOccurrence] = []
    warnings: list[str] = []
    placement = placement_matrix(frame).tolist()
    mirror_on = frame.mirror_plane_native is not None

    for src in _installed_sources(sources, variants):
        category = categorize(src.source_path)
        ev_id = f"ev-{src.sha256[:12]}"
        evidence.append(Evidence(
            evidence_id=ev_id, uri=src.source_path, sha256=src.sha256,
            locator="whole_body", method="stl_bounds+mesh_qa",
            note=f"{src.qa.triangles} triangles, watertight={src.qa.watertight}, "
                 f"components={src.qa.components}, folder hint={src.folder_hint!r}",
        ))
        mesh = load_mesh(staged.by_source(src.source_path).staged_path)
        area_m2 = float(mesh.area) * frame.scale_to_m ** 2
        definition_id = f"def-{src.sha256[:12]}"
        base_side = _side_from_frame(src, frame) if (mirror_on and _off_centre(src)) else "center"
        sides: list[tuple[str, Optional[str]]] = [(base_side, None)]
        if base_side != "center":
            sides.append(("left" if base_side == "right" else "right", "mirror"))

        first_id = None
        for occurrence, (side, kind) in enumerate(sides):
            pid = stable_part_id("mesh", src.source_path, occurrence, side)
            if kind is None:
                first_id = pid
            parts.append(PartOccurrence(
                part_id=pid,
                definition_id=definition_id if kind is None else f"{definition_id}-mirrored",
                name=f"{stem_of(src.source_path)}" + ("" if side == "center" else f" ({side})"),
                category=category,
                side=side,
                mirror_of=None if kind is None else first_id,
                representation="reference_mesh",
                source=src.source_path,
                T_parent_from_local=placement,
                mass_kg=_mass_claim(area_m2, src.qa.watertight, mass_model, ev_id),
                local_com_m=(_com_claim(mesh, src.qa.watertight, ev_id) if kind is None
                             else _mirror_com(_com_claim(mesh, src.qa.watertight, ev_id), frame)),
                material=_material_claim(src.folder_hint, ev_id),
                function=_function_claim(category, ev_id),
                edit_capabilities=[EditCapability.none],
                locked=True,
                labels={
                    "source_sha256": src.sha256,
                    "watertight": str(src.qa.watertight).lower(),
                    "representation_note": "original vendor mesh, byte-identical; not editable topology",
                    **({"mirrored_from_plane": frame.mirror_plane_native or ""} if kind else {}),
                },
            ))
        if not src.qa.watertight:
            warnings.append(f"{src.source_path}: mesh is not watertight — no volume, no centroid, "
                            "mass stays unknown")

    # bought components: synthetic demo BOM
    bom_data = demo_bom.load_demo_bom(demo_bom_path)
    evidence.append(demo_bom.bom_evidence(demo_bom_path))
    for entry in bom_data["components"]:
        for occurrence, (side, position) in enumerate(demo_bom.instances(entry)):
            T = np.eye(4)
            T[:3, 3] = position
            caps = [EditCapability.replace_catalog]
            if entry["category"] == "battery":
                caps = [EditCapability.translate, EditCapability.replace_catalog]
            parts.append(PartOccurrence(
                part_id=stable_part_id("bom", entry["id"], occurrence, side),
                definition_id=f"def-env-{entry['id']}",
                name=entry["name"] + ("" if side == "center" else f" ({side})"),
                category=entry["category"],
                side=side,
                representation="envelope",
                source=None,
                T_parent_from_local=T.tolist(),
                mass_kg=demo_bom.mass_claim(entry),
                local_com_m=demo_bom.com_claim(entry),
                material=Claim.unknown(None, demo_bom.SYNTHETIC_NOTE,
                                       "no material claim is made for a placeholder component"),
                function=demo_bom.function_claim(entry),
                edit_capabilities=caps,
                locked=False,
                labels={
                    "synthetic": "true",
                    "bom_id": entry["id"],
                    "envelope_m": ",".join(f"{float(v):.6g}" for v in entry["envelope_m"]),
                    "placement_note": "assumed position in the confirmed FRD frame, not measured",
                    **({"energy_wh": f"{entry['energy_wh']:g}"} if entry.get("energy_wh") else {}),
                },
            ))
    warnings.append(f"bought components come from the synthetic demo BOM ({bom_data['title']}); "
                    "no supplier, price or stock claim is made and none of it is Titan data")
    if not frame.confirmed:
        warnings.append("frame is NOT confirmed: this manifest is a preview and no metric may be "
                        "published from it")
    if mass_model == "shell_estimate":
        warnings.append("printed-part masses are shell estimates from an explicitly selected model, "
                        "not measurements")

    _mating(parts)
    return DesignManifest(
        schema_version=SCHEMA_VERSION,
        design_id=design_id,
        revision_id=revision_id,
        title=title,
        frame=frame,
        sources_root=staged.root,
        mass_model="shell_estimate" if mass_model == "shell_estimate" else "none",
        sources=sources,
        variants=variants,
        excluded_sources=sorted(o for v in variants for o in v.options if o != v.selected),
        parts=parts,
        evidence=evidence,
        warnings=warnings,
    )


def canonical_json(model: Any) -> str:
    """Stable JSON for hashing: sorted keys, no timestamps."""
    if hasattr(model, "model_dump"):
        data = model.model_dump(mode="json")
    else:
        data = model
    return json.dumps(_strip_times(data), sort_keys=True, separators=(",", ":"))


def _strip_times(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_times(v) for k, v in obj.items() if k not in ("accessed_at", "created_at")}
    if isinstance(obj, list):
        return [_strip_times(v) for v in obj]
    return obj
