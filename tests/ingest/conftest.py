"""Shared fixtures for the ingest suite.

The vendor archive is git-ignored and unlicensed: tests read it in place, never copy it into the
repository tree, and skip cleanly when it is absent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for pkg in ("packages/ingest", "packages/contracts", "packages/viewer"):
    path = str(REPO / pkg)
    if path not in sys.path:
        sys.path.insert(0, path)

AVENGER = REPO / "vendor_assets" / "avenger"
WING3 = "Wings/wing3_12mm_hole.stl"
FUSE3 = "Fuselage/fuse3.stl"
SELECTION = {"wing3": WING3, "fuse3": FUSE3}


@pytest.fixture(scope="session")
def avenger_dir() -> Path:
    if not AVENGER.is_dir():
        pytest.skip(f"vendor archive not present at {AVENGER}")
    return AVENGER


@pytest.fixture(scope="session")
def staged(avenger_dir, tmp_path_factory):
    from dronebench_ingest import inspect_sources, stage_archive
    design_dir = tmp_path_factory.mktemp("design")
    archive = stage_archive(avenger_dir, design_dir)
    return design_dir, archive, inspect_sources(archive)


@pytest.fixture(scope="session")
def confirmed(staged):
    """A confirmed revision of the real archive: mm, mirrored about x=0, mass model 'none'."""
    from dronebench_ingest import confirm, load_features, load_manifest
    design_dir, _, _ = staged
    revision = confirm(design_dir, units="mm", variants=SELECTION, mirror="x=0", mass_model="none",
                       confirmed_by="pytest")
    return design_dir, revision, load_manifest(design_dir, revision.revision_id), \
        load_features(design_dir, revision.revision_id)
