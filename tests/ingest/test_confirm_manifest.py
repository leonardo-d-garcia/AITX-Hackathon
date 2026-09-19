"""Confirmation, the revision store, identity, mirroring and the mass rules."""
from __future__ import annotations

import json

import numpy as np
import pytest

from dronebench_ingest import confirm, load_manifest, placed_mesh, stable_part_id
from dronebench_ingest.errors import IngestError

from conftest import FUSE3, SELECTION, WING3


def test_confirm_requires_explicit_variant_choices(staged):
    design_dir, _, _ = staged
    with pytest.raises(IngestError) as exc:
        confirm(design_dir, units="mm", variants={"wing3": WING3}, mirror="x=0")
    assert exc.value.envelope.code.value == "ASSEMBLY_UNCONFIRMED"
    assert "fuse3" in exc.value.envelope.message


def test_confirm_rejects_an_option_that_is_not_in_the_group(staged):
    design_dir, _, _ = staged
    with pytest.raises(IngestError) as exc:
        confirm(design_dir, units="mm", mirror="x=0",
                variants={"wing3": "Wings/wing2.stl", "fuse3": FUSE3})
    assert exc.value.envelope.code.value == "INPUT_REJECTED"


def test_revision_is_deterministic_and_append_only(confirmed):
    design_dir, revision, manifest, _ = confirmed
    again = confirm(design_dir, units="mm", variants=SELECTION, mirror="x=0", mass_model="none",
                    confirmed_by="pytest")
    assert again.revision_id == revision.revision_id
    assert again.content_sha256 == revision.content_sha256
    assert again.created_at == revision.created_at          # re-read, not rewritten
    assert {a.path for a in revision.artifacts} == {
        "design_manifest.json", "parts.json", "geometry_features.json", "reference_meshes.glb"}
    for artifact in revision.artifacts:
        assert len(artifact.sha256) == 64
    assert revision.state.value == "committed" and revision.cause == "confirm"


def test_only_selected_variants_are_installed(confirmed):
    _, _, manifest, _ = confirmed
    installed = {p.source for p in manifest.parts if p.source}
    assert WING3 in installed and FUSE3 in installed
    assert manifest.excluded_sources == sorted([
        "Fuselage/fuse3_belly_cam.stl", "Fuselage/fuse3_clean.stl",
        "Wings/wing3_16mm_hole.stl", "Wings/wing3_no_hole.stl"])
    for excluded in manifest.excluded_sources:
        assert excluded not in installed
    assert all(g.selected is not None for g in manifest.variants)


def test_mirrored_occurrences_have_their_own_identity(confirmed):
    _, _, manifest, _ = confirmed
    ids = [p.part_id for p in manifest.parts]
    assert len(ids) == len(set(ids))
    mirrored = [p for p in manifest.parts if p.mirror_of is not None]
    assert len(mirrored) == 10                      # 5 wing sections, aileron, 3 tail bodies, bay plate
    by_id = {p.part_id: p for p in manifest.parts}
    for part in mirrored:
        parent = by_id[part.mirror_of]
        assert parent.mirror_of is None
        assert parent.part_id != part.part_id
        assert parent.source == part.source         # same asset, different occurrence
        assert part.definition_id != parent.definition_id
        assert {parent.side, part.side} == {"left", "right"}
    assert all(p.side == "center" for p in manifest.parts
               if p.source and p.mirror_of is None and p.part_id not in
               {m.mirror_of for m in mirrored})


def test_part_ids_are_stable_across_runs(confirmed):
    _, _, manifest, _ = confirmed
    for part in manifest.parts:
        if part.source and part.mirror_of is None:
            assert part.part_id == stable_part_id("mesh", part.source, 0, part.side)


def test_placements_are_proper_rotations_without_reflection(confirmed):
    _, _, manifest, _ = confirmed
    for part in manifest.parts:
        T = np.array(part.T_parent_from_local, dtype=float)
        assert T.shape == (4, 4)
        assert np.allclose(T[3], [0, 0, 0, 1])
        R = T[:3, :3]
        assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-9)
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-9)


def test_mirrored_meshes_land_on_the_other_side_with_outward_normals(confirmed):
    _, _, manifest, _ = confirmed
    by_id = {p.part_id: p for p in manifest.parts}
    for part in [p for p in manifest.parts if p.mirror_of is not None]:
        mesh = placed_mesh(manifest, part)
        parent = placed_mesh(manifest, by_id[part.mirror_of])
        assert mesh.is_winding_consistent
        if mesh.is_watertight:
            assert mesh.volume > 0                       # normals point out, not in
            assert mesh.volume == pytest.approx(parent.volume, rel=1e-9)
        assert mesh.bounds[0][1] == pytest.approx(-parent.bounds[1][1], abs=1e-9)
        assert mesh.bounds[1][1] == pytest.approx(-parent.bounds[0][1], abs=1e-9)
        assert np.allclose(mesh.bounds[:, 0], parent.bounds[:, 0], atol=1e-9)   # same x
        assert np.allclose(mesh.bounds[:, 2], parent.bounds[:, 2], atol=1e-9)   # same z


def test_printed_mass_is_unknown_without_an_explicit_mass_model(confirmed):
    _, _, manifest, _ = confirmed
    assert manifest.mass_model == "none"
    printed = [p for p in manifest.parts if p.representation == "reference_mesh"]
    assert printed
    for part in printed:
        assert part.mass_kg.value is None
        assert part.mass_kg.status.value == "unknown"
        assert any("not mass" in a for a in part.mass_kg.assumptions)
        assert part.material.value is None               # geometry never determines material
        assert part.edit_capabilities == ["none"] and part.locked


def test_not_watertight_parts_have_no_centroid(confirmed):
    _, _, manifest, _ = confirmed
    open_parts = [p for p in manifest.parts if p.labels.get("watertight") == "false"]
    assert {p.name.split(" ")[0] for p in open_parts} == {
        "fuse2", "fuse4", "fuse5", "hatch2", "motor_mount", "wing1", "wing3_12mm_hole"}
    for part in open_parts:
        assert part.local_com_m.value is None
    assert any("not watertight" in w for w in manifest.warnings)


def test_shell_estimate_is_opt_in_and_carries_its_assumptions(staged):
    design_dir, _, _ = staged
    revision = confirm(design_dir, units="mm", variants=SELECTION, mirror="x=0",
                       mass_model="shell_estimate", confirmed_by="pytest")
    manifest = load_manifest(design_dir, revision.revision_id)
    assert manifest.mass_model == "shell_estimate"
    printed = [p for p in manifest.parts if p.representation == "reference_mesh"]
    for part in printed:
        assert part.mass_kg.status.value == "estimated"
        assert part.mass_kg.value > 0
        assert any("wall" in a for a in part.mass_kg.assumptions)
        assert any("explicitly selected" in a for a in part.mass_kg.assumptions)
    open_part = next(p for p in printed if p.labels["watertight"] == "false")
    assert any("not watertight" in a for a in open_part.mass_kg.assumptions)


def test_demo_bom_parts_are_labelled_synthetic_and_carry_no_supplier(confirmed):
    _, _, manifest, _ = confirmed
    bought = [p for p in manifest.parts if p.representation == "envelope"]
    assert {p.category for p in bought} == {
        "motor", "prop", "esc", "battery", "fc", "rx", "gps", "payload", "servo"}
    assert len([p for p in bought if p.category == "motor"]) == 1        # one pusher mount, one motor
    assert len([p for p in bought if p.category == "servo"]) == 4
    text = json.dumps([p.model_dump(mode="json") for p in bought]).lower()
    for forbidden in ("supplier", "price", "usd", "$", "in stock", "sku", "part number"):
        assert forbidden not in text
    for part in bought:
        assert part.labels["synthetic"] == "true"
        assert part.mass_kg.status.value == "estimated"
        assert part.mass_kg.source_kind.value == "catalog"
        assert any("synthetic" in a for a in part.mass_kg.assumptions)
    battery = next(p for p in bought if p.category == "battery")
    assert "translate_component" in [c.value for c in battery.edit_capabilities]


def test_declared_mating_pairs_exist_and_are_symmetric(confirmed):
    _, _, manifest, _ = confirmed
    by_id = {p.part_id: p for p in manifest.parts}
    for part in manifest.parts:
        for other in part.allowed_overlap_with:
            assert other in by_id
            assert part.part_id in by_id[other].allowed_overlap_with
        assert part.part_id not in part.allowed_overlap_with
    wing1 = next(p for p in manifest.parts if p.name == "wing1 (left)")
    neighbours = {by_id[i].name for i in wing1.allowed_overlap_with}
    assert "wing2 (left)" in neighbours
    assert "wing2 (right)" not in neighbours


def test_a_failed_confirm_leaves_no_partial_revision(staged, monkeypatch):
    design_dir, _, _ = staged
    import dronebench_ingest.revisions as revisions
    monkeypatch.setattr(revisions, "build_manifest",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    before = {p.name for p in (design_dir / "revisions").iterdir()}
    with pytest.raises(RuntimeError):
        revisions.confirm(design_dir, units="in", variants=SELECTION, mirror="x=0")
    after = {p.name for p in (design_dir / "revisions").iterdir()}
    assert after == before
