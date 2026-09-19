"""A1 -> A2: real ingest output drives the reconstruction, export and round trip.

Skipped when `packages/ingest` or the vendor archive is not there, so a clean clone and a
half-finished lane both stay green.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "packages" / "ingest"))

from dronebench_cad import STEP_NAME, export, fit_report, reconstruct, reimport_check  # noqa: E402

VARIANTS = {"wing3": "Wings/wing3_16mm_hole.stl", "fuse3": "Fuselage/fuse3.stl"}


@pytest.fixture(scope="module")
def ingested(avenger_dir, tmp_path_factory):
    ingest = pytest.importorskip("dronebench_ingest", reason="packages/ingest not available yet")
    design_dir = tmp_path_factory.mktemp("design")
    archive = ingest.stage_archive(avenger_dir, design_dir)
    ingest.inspect_sources(archive)
    revision = ingest.confirm(
        design_dir, units="mm", variants=VARIANTS, mirror="x=0", mass_model="none",
        confirmed_by="tests/cad",
    )
    return (
        ingest.load_manifest(design_dir, revision.revision_id),
        ingest.load_features(design_dir, revision.revision_id),
    )


def test_reconstructs_from_real_ingest_features(ingested):
    _, features = ingested
    model = reconstruct(features)
    assert model.source_features_revision_id == features.revision_id
    assert len(model.parts) >= 10
    for part in model.parts:
        assert part.is_valid() and part.volume_m3() > 0
    # A1 hands over an explicit V-tail pair; neither panel may be duplicated.
    vtail = [p for p in model.parts if p.category == "vtail"]
    assert len(vtail) == 2 and {p.side for p in vtail} == {"left", "right"}


def test_exports_and_round_trips_real_ingest_geometry(ingested, tmp_path):
    _, features = ingested
    model = reconstruct(features)
    export(model, tmp_path)
    checks = reimport_check(tmp_path / STEP_NAME, model)
    assert not [c for c in checks if not c["passed"]], checks


def test_fit_report_uses_the_confirmed_manifest_frame(ingested):
    manifest, features = ingested
    model = reconstruct(features)
    report = fit_report(model, manifest, samples=500, features=features)
    assert report["frame"]["confirmed"] is True
    assert report["reference_dir"] is not None
    assert report["confirmed"] is False, "geometry fit is never self-confirming"
    assert report["overall"]["parts_compared"] >= 4
    # Areas are only comparable once the carry-through is accounted for.
    assert abs(report["area"]["relative_difference_vs_gross"]) < 0.05
