"""The reference GLB and the CLI surface."""
from __future__ import annotations

import json

import numpy as np
import pytest
import trimesh

from dronebench_contracts.models import ErrorEnvelope
from dronebench_ingest import export_reference_glb, preview_manifest
from dronebench_ingest.cli import main
from dronebench_ingest.glb import FRD_TO_GLTF, GLB_NAME

from .conftest import SELECTION


def test_glb_round_trips_with_every_part_node(confirmed, tmp_path):
    design_dir, revision, manifest, _ = confirmed
    artifact = export_reference_glb(manifest, tmp_path / "out.glb")
    assert not isinstance(artifact, ErrorEnvelope)
    assert artifact.media_type == "model/gltf-binary"
    assert artifact.representation == "reference_mesh"
    assert sorted(artifact.part_ids) == sorted(p.part_id for p in manifest.parts)

    scene = trimesh.load(tmp_path / "out.glb", file_type="glb")
    assert set(scene.geometry) == {p.part_id for p in manifest.parts}
    for mesh in scene.geometry.values():
        assert len(mesh.faces) > 0
        assert np.isfinite(mesh.vertices).all()
    # metres, Y-up: the aircraft is about 2.2 m across and about 1 m long
    extents = scene.bounds[1] - scene.bounds[0]
    assert extents.max() == pytest.approx(2.2245, abs=0.01)
    assert sorted(extents)[-2] == pytest.approx(0.99, abs=0.05)


def test_the_glb_of_the_committed_revision_is_the_hashed_artifact(confirmed):
    design_dir, revision, _, _ = confirmed
    from dronebench_ingest.revisions import revision_dir
    from dronebench_ingest.staging import sha256_file
    entry = next(a for a in revision.artifacts if a.path == GLB_NAME)
    path = revision_dir(design_dir, revision.revision_id) / GLB_NAME
    assert sha256_file(path) == entry.sha256


def test_display_adapter_maps_frd_to_gltf(confirmed):
    _, _, manifest, _ = confirmed
    adapter = np.array(FRD_TO_GLTF)[:3, :3]
    assert np.linalg.det(adapter) == pytest.approx(1.0)
    assert np.allclose(adapter @ np.array([1.0, 0.0, 0.0]), [0.0, 0.0, -1.0])   # forward -> -z
    assert np.allclose(adapter @ np.array([0.0, 0.0, 1.0]), [0.0, -1.0, 0.0])   # down -> -y


def test_export_is_refused_for_an_unconfirmed_design(staged, tmp_path):
    design_dir, _, _ = staged
    result = export_reference_glb(preview_manifest(design_dir), tmp_path / "no.glb")
    assert isinstance(result, ErrorEnvelope)
    assert result.code.value == "UNITS_UNCONFIRMED"
    assert not (tmp_path / "no.glb").exists()


def test_cli_inspect_reports_without_confirming(staged, capsys):
    design_dir, _, _ = staged
    assert main(["inspect", "--design-dir", str(design_dir)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["sources"]) == 24
    assert payload["frame_proposal"]["confirmed"] is False
    assert {g["group_id"] for g in payload["variants"]} == {"wing3", "fuse3"}
    assert all(g["selected"] is None for g in payload["variants"])
    assert len(payload["not_watertight"]) == 9


def test_cli_features_on_an_unconfirmed_design_is_a_report_not_a_failure(tmp_path, avenger_dir,
                                                                        capsys):
    design_dir = tmp_path / "fresh"
    assert main(["ingest", str(avenger_dir), "--design-dir", str(design_dir)]) == 0
    capsys.readouterr()
    assert main(["features", "--design-dir", str(design_dir)]) == 0      # exit 0, not a crash
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "UNITS_UNCONFIRMED"


def test_cli_confirm_then_features_and_parts(tmp_path, avenger_dir, capsys):
    design_dir = tmp_path / "cli"
    assert main(["ingest", str(avenger_dir), "--design-dir", str(design_dir)]) == 0
    capsys.readouterr()
    argv = ["confirm", "--design-dir", str(design_dir), "--units", "mm", "--mirror", "x=0"]
    for group, option in SELECTION.items():
        argv += ["--select", f"{group}={option}"]
    assert main(argv) == 0
    revision = json.loads(capsys.readouterr().out)
    assert revision["state"] == "committed"

    assert main(["features", "--design-dir", str(design_dir)]) == 0
    features = json.loads(capsys.readouterr().out)
    assert features["reference_span_m"]["value"] == pytest.approx(2.2245, abs=0.002)

    assert main(["parts", "--design-dir", str(design_dir)]) == 0
    parts = json.loads(capsys.readouterr().out)
    assert parts["confirmed"] is True
    assert len(parts["parts"]) == 42
    assert len(parts["excluded_sources"]) == 4


def test_cli_confirm_without_a_selection_exits_non_zero(tmp_path, avenger_dir, capsys):
    design_dir = tmp_path / "cli2"
    assert main(["ingest", str(avenger_dir), "--design-dir", str(design_dir)]) == 0
    capsys.readouterr()
    code = main(["confirm", "--design-dir", str(design_dir), "--units", "mm"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "ASSEMBLY_UNCONFIRMED"
