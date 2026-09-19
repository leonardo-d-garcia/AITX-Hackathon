"""Stored paths must not depend on anyone's working directory.

The manifest is a wire artifact: A2's fit report and A4's viewer read it in their own processes,
from their own directories. A path recorded relative to whatever cwd `stage_archive` happened to be
called from breaks all of them, so paths are stored absolute and relocated against the design
directory when that fails.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from dronebench_contracts.models import ErrorEnvelope
from dronebench_ingest import (confirm, export_reference_glb, geometry_features, load_manifest,
                               part_meshes, placed_mesh, stage_archive)
from dronebench_ingest.assembly import sources_root
from dronebench_ingest.errors import IngestError

from conftest import SELECTION


@pytest.fixture(scope="module")
def relative_design(avenger_dir, tmp_path_factory):
    """A design staged and confirmed with a RELATIVE design dir, as the end-to-end script does."""
    work = tmp_path_factory.mktemp("relative")
    previous = Path.cwd()
    os.chdir(work)
    try:
        stage_archive(avenger_dir, "design")             # relative, exactly like the failing run
        revision = confirm("design", units="mm", variants=SELECTION, mirror="x=0",
                           confirmed_by="pytest")
    finally:
        os.chdir(previous)
    return work, revision


def test_staged_paths_are_absolute(relative_design):
    work, revision = relative_design
    manifest = load_manifest(work / "design", revision.revision_id)
    assert Path(manifest.sources_root).is_absolute()
    assert Path(manifest.sources_root) == (work / "design" / "sources").resolve()
    for source in manifest.sources:
        assert not Path(source.source_path).is_absolute()     # inside the archive, stays relative


def test_meshes_load_from_an_unrelated_working_directory(relative_design, tmp_path, monkeypatch):
    """The original failure: cwd elsewhere, design dir passed relative."""
    work, revision = relative_design
    monkeypatch.chdir(tmp_path)                                # nowhere near the design
    manifest = load_manifest(work / "design", revision.revision_id)
    assert sources_root(manifest).is_dir()

    part = next(p for p in manifest.parts if p.source and p.source.endswith("aileron.stl"))
    mesh = placed_mesh(manifest, part)                         # used to raise FileNotFoundError
    assert len(mesh.faces) > 0

    features = geometry_features(manifest)
    assert not isinstance(features, ErrorEnvelope)
    assert features.reference_span_m.value == pytest.approx(2.2245, abs=0.002)

    artifact = export_reference_glb(manifest, tmp_path / "ref.glb")
    assert not isinstance(artifact, ErrorEnvelope)
    assert (tmp_path / "ref.glb").is_file()
    assert len(part_meshes(manifest)) == len(manifest.parts)


def test_a_moved_design_directory_relocates_its_sources(relative_design, tmp_path, monkeypatch):
    """Copy a design elsewhere: the sources sit next to the revision, so that wins over the record."""
    import shutil
    work, revision = relative_design
    moved = tmp_path / "somewhere_else"
    shutil.copytree(work / "design", moved)
    monkeypatch.chdir(tmp_path)

    manifest = load_manifest(moved, revision.revision_id)
    assert Path(manifest.sources_root) == (moved / "sources").resolve()
    assert any("relocated" in w for w in manifest.warnings)
    assert len(placed_mesh(manifest, manifest.parts[0]).faces) > 0


def test_missing_sources_fail_with_a_typed_error_naming_the_paths(confirmed, monkeypatch):
    _, _, manifest, _ = confirmed
    broken = manifest.model_copy(deep=True, update={"sources_root": "/nonexistent/design/sources"})
    with pytest.raises(IngestError) as exc:
        placed_mesh(broken, next(p for p in broken.parts if p.source))
    envelope = exc.value.envelope
    assert envelope.code.value == "MISSING_EVIDENCE"
    assert envelope.revision_id == manifest.revision_id
    assert "/nonexistent/design/sources" in envelope.details["recorded"]
    assert envelope.details["tried"] and envelope.details["fix"]


def test_revision_artifact_paths_stay_relative_to_their_revision(confirmed):
    """Artifacts are addressed relative to the revision dir by contract; the dir supplies the rest."""
    design_dir, revision, _, _ = confirmed
    from dronebench_ingest.revisions import revision_dir
    directory = revision_dir(design_dir, revision.revision_id)
    for artifact in revision.artifacts:
        assert not Path(artifact.path).is_absolute()
        assert (directory / artifact.path).is_file()
