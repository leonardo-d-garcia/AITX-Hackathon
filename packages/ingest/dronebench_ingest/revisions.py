"""Confirmation and the append-only revision store.

``confirm`` is the only way a design becomes measurable. It takes the user's explicit choices —
units, frame, one option per variant group, whether to mirror, which mass model — and writes an
immutable revision directory containing the manifest, the parts list, the measured features and the
reference GLB, each hashed in ``revision_manifest.json``.

The revision id is derived from the content of those choices plus the source hashes, so the same
inputs always name the same revision and re-confirming is idempotent rather than a silent mutation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from dronebench_contracts.models import (
    SCHEMA_VERSION, Artifact, DesignManifest, ErrorCode, ErrorEnvelope, FrameConfirmation,
    GeometryFeatures, RevisionManifest, RevisionState, SourceFile, VariantGroup,
)

from .bom import DEMO_BOM_PATH
from .errors import IngestError
from .features import geometry_features
from .frame import propose_frame
from .glb import GLB_NAME, export_reference_glb
from .inspection import inspect_sources
from .manifest import build_manifest, canonical_json
from .staging import StagedArchive, load_staged, sha256_file

MASS_MODELS = ("none", "shell_estimate")
# Bumped whenever the artifacts a revision contains change shape (not just the inputs), so a
# re-confirm produces a new revision instead of pointing at stale bytes. a1.2: GLB vertex normals.
# a1.3: fuselage stations reach the measured nose and tail extremes.
PIPELINE_VERSION = "a1.3"
MANIFEST_NAME = "design_manifest.json"
PARTS_NAME = "parts.json"
FEATURES_NAME = "geometry_features.json"
REVISION_NAME = "revision_manifest.json"


def _fail(code: ErrorCode, message: str, **details) -> IngestError:
    return IngestError(ErrorEnvelope(code=code, message=message, details=details))


def _apply_choices(proposal: FrameConfirmation, units: str, mirror, confirmed_by: str,
                   frame: Optional[FrameConfirmation]) -> FrameConfirmation:
    base = (frame or proposal).model_copy(deep=True)
    if units not in ("mm", "m", "in"):
        raise _fail(ErrorCode.INPUT_REJECTED, f"unsupported units {units!r}", units=units)
    base.units = units
    base.scale_to_m = {"mm": 0.001, "m": 1.0, "in": 0.0254}[units]
    if mirror is False or mirror is None:
        base.mirror_plane_native = None
    elif mirror is not True:
        base.mirror_plane_native = str(mirror)
    elif base.mirror_plane_native is None:
        raise _fail(ErrorCode.ASSEMBLY_UNCONFIRMED,
                    "mirroring was requested but no mirror plane was proposed or supplied")
    if units != proposal.units:
        base.notes = [*base.notes, f"units confirmed as {units!r}, overriding the proposed "
                                   f"{proposal.units!r}"]
    base.confirmed = True
    base.confirmed_by = confirmed_by
    base.notes = [*base.notes,
                  f"confirmed by {confirmed_by}: units, axes, nose datum and mirror plane "
                  f"({base.mirror_plane_native or 'no mirroring'})"]
    return base


def _apply_variants(groups: list[VariantGroup], choices: dict[str, str]) -> list[VariantGroup]:
    out = []
    for group in groups:
        selected = choices.get(group.group_id)
        if selected is None:
            raise _fail(ErrorCode.ASSEMBLY_UNCONFIRMED,
                        f"variant group {group.group_id!r} has no selection; one option must be "
                        "chosen explicitly", group_id=group.group_id, options=group.options)
        if selected not in group.options:
            raise _fail(ErrorCode.INPUT_REJECTED,
                        f"{selected!r} is not an option of variant group {group.group_id!r}",
                        group_id=group.group_id, options=group.options)
        out.append(group.model_copy(update={
            "selected": selected,
            "reason": f"selected at confirmation; the other {len(group.options) - 1} option(s) are "
                      "excluded and contribute no mass, area or geometry",
        }))
    unknown = sorted(set(choices) - {g.group_id for g in groups})
    if unknown:
        raise _fail(ErrorCode.INPUT_REJECTED, f"no such variant group(s): {', '.join(unknown)}",
                    groups=unknown)
    return out


def _content_hash(staged: StagedArchive, frame: FrameConfirmation, variants: list[VariantGroup],
                  mass_model: str) -> str:
    h = hashlib.sha256()
    h.update(staged.content_sha256.encode())
    h.update(canonical_json(frame).encode())
    for group in variants:
        h.update(f"{group.group_id}={group.selected}\0".encode())
    h.update(mass_model.encode())
    h.update(PIPELINE_VERSION.encode())
    h.update(sha256_file(DEMO_BOM_PATH).encode())
    return h.hexdigest()


def _write_json(path: Path, payload) -> Artifact:
    data = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")
    return Artifact(path=path.name, sha256=sha256_file(path), media_type="application/json")


def confirm(
    design_dir: str | Path,
    units: str,
    frame: Optional[FrameConfirmation] = None,
    variants: Optional[dict[str, str]] = None,
    mirror: bool | str = True,
    mass_model: str = "none",
    confirmed_by: str = "user",
    design_id: Optional[str] = None,
    title: str = "Titan Avenger (reference mesh import)",
) -> RevisionManifest:
    """Record the user's explicit choices and write an immutable revision.

    ``variants`` maps a group id to the source path of the chosen option; every detected group must
    appear. ``mirror`` is ``True`` (use the proposed plane), ``False`` (half model as supplied), or
    an explicit plane such as ``"x=0"``. ``mass_model`` is ``"none"`` (printed mass stays unknown)
    or ``"shell_estimate"`` (estimated, with assumptions recorded on every claim).
    """
    if mass_model not in MASS_MODELS:
        raise _fail(ErrorCode.INPUT_REJECTED, f"unsupported mass model {mass_model!r}",
                    supported=list(MASS_MODELS))
    design_dir = Path(design_dir)
    staged = load_staged(design_dir)
    sources: list[SourceFile] = inspect_sources(staged)
    proposal = propose_frame(sources)
    confirmed_frame = _apply_choices(proposal, units, mirror, confirmed_by, frame)

    from .variants import detect_variants
    groups = _apply_variants(detect_variants(sources), dict(variants or {}))

    content = _content_hash(staged, confirmed_frame, groups, mass_model)
    revision_id = f"rev-{content[:12]}"
    design_id = design_id or f"design-{staged.content_sha256[:12]}"
    rev_dir = design_dir / "revisions" / revision_id
    existing = rev_dir / REVISION_NAME
    if existing.is_file():
        return RevisionManifest.model_validate_json(existing.read_text())

    tmp_dir = design_dir / "revisions" / f".{revision_id}.partial"
    if tmp_dir.exists():
        raise _fail(ErrorCode.INPUT_REJECTED, "a partial revision directory is in the way",
                    path=str(tmp_dir))
    tmp_dir.mkdir(parents=True)
    try:
        manifest = build_manifest(design_id, revision_id, staged, sources, confirmed_frame, groups,
                                  mass_model=mass_model, title=title)
        artifacts = [_write_json(tmp_dir / MANIFEST_NAME, manifest),
                     _write_json(tmp_dir / PARTS_NAME, {
                         "schema_version": SCHEMA_VERSION, "design_id": design_id,
                         "revision_id": revision_id,
                         "parts": [p.model_dump(mode="json") for p in manifest.parts]})]
        features = geometry_features(manifest)
        if isinstance(features, ErrorEnvelope):
            raise IngestError(features)
        artifacts.append(_write_json(tmp_dir / FEATURES_NAME, features))
        glb = export_reference_glb(manifest, tmp_dir / GLB_NAME)
        if isinstance(glb, ErrorEnvelope):
            raise IngestError(glb)
        artifacts.append(glb)
        for a in artifacts[:3]:
            a.representation = "reference_mesh"
            a.part_ids = [p.part_id for p in manifest.parts]
        revision = RevisionManifest(
            schema_version=SCHEMA_VERSION, design_id=design_id, revision_id=revision_id,
            parent_revision_id=None, state=RevisionState.committed, content_sha256=content,
            cause="confirm", created_at=datetime.now(timezone.utc).isoformat(), artifacts=artifacts)
        (tmp_dir / REVISION_NAME).write_text(
            json.dumps(revision.model_dump(mode="json"), indent=2) + "\n")
        tmp_dir.rename(rev_dir)
    except BaseException:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return revision


# ------------------------------------------------------------------ reading a revision back

def revision_dir(design_dir: str | Path, revision_id: Optional[str] = None) -> Path:
    root = Path(design_dir) / "revisions"
    if revision_id:
        return root / revision_id
    candidates = sorted(p for p in root.glob("rev-*") if (p / REVISION_NAME).is_file())
    if not candidates:
        raise _fail(ErrorCode.MISSING_EVIDENCE, "no confirmed revision in this design",
                    design_dir=str(design_dir))
    return max(candidates, key=lambda p: (p / REVISION_NAME).stat().st_mtime)


def load_manifest(design_dir: str | Path, revision_id: Optional[str] = None) -> DesignManifest:
    return DesignManifest.model_validate_json(
        (revision_dir(design_dir, revision_id) / MANIFEST_NAME).read_text())


def load_features(design_dir: str | Path, revision_id: Optional[str] = None) -> GeometryFeatures:
    return GeometryFeatures.model_validate_json(
        (revision_dir(design_dir, revision_id) / FEATURES_NAME).read_text())


def preview_manifest(design_dir: str | Path, mass_model: str = "none") -> DesignManifest:
    """An unconfirmed manifest for the confirmation UI: proposals only, no metrics published."""
    staged = load_staged(design_dir)
    sources = inspect_sources(staged)
    from .variants import detect_variants
    return build_manifest("design-preview", "rev-preview", staged, sources, propose_frame(sources),
                          detect_variants(sources), mass_model=mass_model)


def artifact_paths(design_dir: str | Path, revision_id: Optional[str] = None) -> Iterable[Path]:
    d = revision_dir(design_dir, revision_id)
    return sorted(p for p in d.iterdir() if p.is_file())
