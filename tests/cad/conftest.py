"""Shared fixtures for the CAD suite.

The vendor archive is git-ignored and unlicensed: tests that need it read it in place, never
copy it into the repository tree, and skip cleanly when it is absent. Everything else runs
from the checked-in GeometryFeatures fixture, so the suite is meaningful on a clean clone.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for pkg in ("packages/cad", "packages/contracts"):
    path = str(REPO / pkg)
    if path not in sys.path:
        sys.path.insert(0, path)

FIXTURE = Path(__file__).parent / "fixtures" / "avenger_features.json"
AVENGER = REPO / "vendor_assets" / "avenger"


@pytest.fixture(scope="session")
def features() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="session")
def params(features):
    from dronebench_cad import ReconParams

    return ReconParams.from_features(features)


@pytest.fixture(scope="session")
def model(params):
    from dronebench_cad import reconstruct

    return reconstruct(params=params)


@pytest.fixture(scope="session")
def exported(model, tmp_path_factory):
    from dronebench_cad import export

    out = tmp_path_factory.mktemp("recon_export")
    artifacts = export(model, out)
    return out, artifacts


@pytest.fixture(scope="session")
def avenger_dir() -> Path:
    if not AVENGER.is_dir():
        pytest.skip(f"vendor archive not present at {AVENGER}")
    return AVENGER
