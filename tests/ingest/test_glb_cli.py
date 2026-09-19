"""The reference GLB and the CLI surface."""
from __future__ import annotations

import json
import struct

import numpy as np
import pytest
import trimesh

from dronebench_contracts.models import ErrorEnvelope
from dronebench_ingest import export_reference_glb, preview_manifest
from dronebench_ingest.cli import main
from dronebench_ingest.glb import FRD_TO_GLTF, GLB_NAME



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


def _gltf_attributes(glb: bytes) -> set[str]:
    """Attribute names of every primitive in a GLB, read from its JSON chunk."""
    length = struct.unpack("<I", glb[12:16])[0]
    doc = json.loads(glb[20:20 + length])
    return {name for mesh in doc["meshes"] for prim in mesh["primitives"]
            for name in prim["attributes"]}


def test_glb_primitives_carry_vertex_normals(confirmed, tmp_path):
    """glTF never computes normals: a primitive without NORMAL renders black in three.js."""
    _, _, manifest, _ = confirmed
    out = tmp_path / "normals.glb"
    export_reference_glb(manifest, out)
    assert _gltf_attributes(out.read_bytes()) >= {"POSITION", "NORMAL"}

    scene = trimesh.load(out, file_type="glb")
    for part_id, mesh in scene.geometry.items():
        normals = mesh.vertex_normals
        assert len(normals) == len(mesh.vertices), part_id
        assert np.isfinite(normals).all(), part_id
        assert np.allclose(np.linalg.norm(normals, axis=1), 1.0, atol=1e-3), part_id


def test_hard_edges_are_not_smoothed_away(confirmed):
    """A crease angle splits vertices at sharp edges instead of averaging across them."""
    from dronebench_ingest.glb import shade
    from dronebench_ingest import placed_mesh
    _, _, manifest, _ = confirmed
    part = next(p for p in manifest.parts if p.name.startswith("wing2"))
    raw = placed_mesh(manifest, part)
    shaded = shade(raw)
    assert len(shaded.vertices) > len(raw.vertices)          # creases duplicated
    assert len(shaded.faces) == len(raw.faces)               # geometry unchanged
    assert np.allclose(shaded.bounds, raw.bounds, atol=1e-9)


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


def test_cli_confirm_then_features_and_parts(tmp_path, avenger_dir, selection, capsys):
    design_dir = tmp_path / "cli"
    assert main(["ingest", str(avenger_dir), "--design-dir", str(design_dir)]) == 0
    capsys.readouterr()
    argv = ["confirm", "--design-dir", str(design_dir), "--units", "mm", "--mirror", "x=0"]
    for group, option in selection.items():
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


def test_cli_viewer_renders_the_standalone_inspector(confirmed, tmp_path, capsys):
    pytest.importorskip("dronebench_viewer")
    design_dir, revision, manifest, _ = confirmed
    out = tmp_path / "inspector.html"
    assert main(["viewer", "--design-dir", str(design_dir), "--revision", revision.revision_id,
                 "--out", str(out)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["inspector_html"] == str(out)
    assert payload["revision_id"] == revision.revision_id
    html = out.read_text()
    assert "<html" in html.lower()
    assert manifest.parts[0].part_id in html               # the manifest reached the page


def test_cli_confirm_without_a_selection_exits_non_zero(tmp_path, avenger_dir, capsys):
    design_dir = tmp_path / "cli2"
    assert main(["ingest", str(avenger_dir), "--design-dir", str(design_dir)]) == 0
    capsys.readouterr()
    code = main(["confirm", "--design-dir", str(design_dir), "--units", "mm"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["code"] == "ASSEMBLY_UNCONFIRMED"
