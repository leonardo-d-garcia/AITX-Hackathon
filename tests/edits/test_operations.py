"""A3b: the typed edit kernels, their bounds, and what the regenerated geometry actually does.

Most of these run on the parameter set alone (`reconstruct()` is ~0.7 s and needs no vendor
archive), so the suite is meaningful on a clean clone. The one end-to-end `apply_edit` test
uses a synthetic design directory plus a local fake store/collider until A3a's and A3c's land.

Every number checked here is measured from regenerated geometry, never from a published
metric, and nothing asserts a mass or a CG: both are unknown for this aircraft.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for _pkg in ("packages/cad", "packages/contracts", "packages/ingest", "packages/edits"):
    _path = str(REPO / _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from dronebench_cad import (DEFAULT_PARAMS_PATH, ReconParams, dump_params,  # noqa: E402
                            load_params, reconstruct)
from dronebench_contracts.models import (CadEditRequest, Claim, DesignManifest,  # noqa: E402
                                         EditCapability, EditOperation, ErrorCode,
                                         FrameConfirmation, PartOccurrence, RevisionManifest,
                                         RevisionState, RoundTripCheck, VariantGroup)
from dronebench_edits import operations, policy as policy_mod  # noqa: E402
from dronebench_edits.api import BuildResult, EditBlocked  # noqa: E402
from dronebench_edits.apply import PARAMS_NAME, apply_edit  # noqa: E402

IDENTITY = [[1.0, 0, 0, 0], [0, 1.0, 0, 0], [0, 0, 1.0, 0], [0, 0, 0, 1.0]]
BATTERY_PART_ID = "battery-main-c-000000"
LOCKED_PART_ID = "wing3-r-000000"


# ---------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def policy() -> dict:
    return policy_mod.load_policy()


@pytest.fixture(scope="module")
def base_params() -> ReconParams:
    """The baseline Avenger parameter set. Deep-copied per test by the kernels themselves."""
    return load_params(DEFAULT_PARAMS_PATH)


def _manifest(wing3: str | None = "Wings/wing3_16mm_hole.stl") -> DesignManifest:
    """A synthetic manifest: one confirmed wing3 variant, one movable battery, one locked mesh.

    Deliberately hand-built rather than ingested: the constraint under test is the *confirmed
    variant*, and a fixture that fabricates a confirmation is easier to read than one that
    hides it inside an archive.
    """
    return DesignManifest(
        design_id="titan_avenger", revision_id="rev-fixture", title="synthetic edit fixture",
        frame=FrameConfirmation(units="mm", native_to_frd=[[0, -1, 0], [-1, 0, 0], [0, 0, -1]],
                                scale_to_m=0.001, nose_datum_native=[0.0, -403.07, 0.0],
                                mirror_plane_native="x=0", confirmed=True),
        variants=[VariantGroup(group_id="wing3",
                               options=["Wings/wing3_12mm_hole.stl", "Wings/wing3_16mm_hole.stl",
                                        "Wings/wing3_no_hole.stl"],
                               selected=wing3)],
        parts=[
            PartOccurrence(
                part_id=BATTERY_PART_ID, definition_id="def-env-battery_main",
                name="Main flight battery (synthetic)", category="battery", side="center",
                representation="envelope", T_parent_from_local=IDENTITY,
                mass_kg=Claim.unknown("kg"), locked=False,
                edit_capabilities=[EditCapability.translate, EditCapability.replace_catalog],
            ),
            PartOccurrence(
                part_id=LOCKED_PART_ID, definition_id="def-wing3", name="wing3 (right)",
                category="wing", side="right", representation="reference_mesh",
                source="Wings/wing3_16mm_hole.stl", T_parent_from_local=IDENTITY,
                locked=True, edit_capabilities=[EditCapability.none],
            ),
        ],
    )


@pytest.fixture(scope="module")
def manifest() -> DesignManifest:
    return _manifest()


def _request(operation: EditOperation, targets: list[str], **parameters) -> CadEditRequest:
    return CadEditRequest(base_revision_id="rev-fixture", operation=operation,
                          target_part_ids=targets, parameters=parameters)


def _by_id(model) -> dict:
    return {p.part_id: p for p in model.parts}


# ---------------------------------------------------------------------------- translate

@pytest.mark.parametrize("delta_mm", [20.0])
def test_battery_move_changes_placement_only(base_params, delta_mm):
    """+20 mm forward moves the pack and nothing else, to 1e-9 in volume and centroid."""
    delta = [delta_mm / 1000.0, 0.0, 0.0]
    new, changes = operations.translate_component(base_params, "recon_battery", delta)

    before_model, after_model = reconstruct(params=base_params), reconstruct(params=new)
    before, after = _by_id(before_model), _by_id(after_model)
    assert set(before) == set(after)

    moved = after["recon_battery"].centroid_m()
    was = before["recon_battery"].centroid_m()
    assert moved[0] - was[0] == pytest.approx(delta[0], abs=1e-9)
    assert moved[1:] == pytest.approx(was[1:], abs=1e-9)
    # placement only: the envelope kept its shape
    assert after["recon_battery"].volume_m3() == pytest.approx(
        before["recon_battery"].volume_m3(), rel=1e-12)

    for part_id in before:
        if part_id == "recon_battery":
            continue
        assert after[part_id].volume_m3() == pytest.approx(
            before[part_id].volume_m3(), abs=1e-9, rel=0), part_id
        assert after[part_id].centroid_m() == pytest.approx(
            before[part_id].centroid_m(), abs=1e-9), part_id

    placement = next(c for c in changes if c["field"] == "center_m")
    assert placement["before"] == [-0.2, 0.0, -0.005]
    assert placement["after"] == pytest.approx([-0.18, 0.0, -0.005], abs=1e-12)
    assert placement["unit"] == "m"


def test_battery_move_reports_cg_as_unknown(base_params):
    """A move changes the CG, and this project does not know the CG. It says so."""
    _, changes = operations.translate_component(base_params, "recon_battery", [0.02, 0.0, 0.0])
    cg = next(c for c in changes if c["field"] == "cg_m")
    assert cg["before"] is None and cg["after"] is None
    assert cg["status"] == "unknown"
    assert "unknown" in cg["note"].lower()
    # and no change anywhere in the transaction invents a mass or a CG number
    for change in changes:
        if change["field"] in {"cg_m", "mass_kg"}:
            assert change["before"] is None and change["after"] is None


def test_translate_outside_the_declared_corridor_is_blocked(base_params, manifest, policy):
    request = _request(EditOperation.translate_component, [BATTERY_PART_ID],
                       delta_m=[0.028, 0.0, 0.0])  # -0.172 m: inside the corridor
    policy_mod.check_bounds(request, manifest, base_params, policy)

    far = _request(EditOperation.translate_component, [BATTERY_PART_ID],
                   delta_m=[0.200, 0.0, 0.0])
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(far, manifest, base_params, policy)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert "harness allowance" in envelope.message
    assert envelope.details["limit"] == "battery_corridor.harness_allowance_m"


# ---------------------------------------------------------------------------- spar

def test_spar_10_to_12_mm_changes_volume_per_the_tube_formula(base_params):
    """Wall thickness is preserved and the regenerated tube matches pi/4*(OD^2-ID^2)*L."""
    start = base_params.model_copy(deep=True)
    start.spar.outer_diameter_m, start.spar.inner_diameter_m = 0.010, 0.006
    length = start.spar.span_m

    new, changes = operations.resize_spar(start, outer_d_mm=12.0)
    assert new.spar.outer_diameter_m == pytest.approx(0.012)
    assert new.spar.inner_diameter_m == pytest.approx(0.008)   # 2 mm wall kept
    assert start.spar.outer_diameter_m == 0.010                # parent untouched

    before = _by_id(reconstruct(params=start))["recon_spar"].volume_m3()
    after = _by_id(reconstruct(params=new))["recon_spar"].volume_m3()

    def tube(od, idd):
        return math.pi / 4 * (od ** 2 - idd ** 2) * length

    assert before == pytest.approx(tube(0.010, 0.006), rel=1e-6)
    assert after == pytest.approx(tube(0.012, 0.008), rel=1e-6)
    assert after - before == pytest.approx(tube(0.012, 0.008) - tube(0.010, 0.006), rel=1e-6)

    mass = next(c for c in changes if c["field"] == "mass_kg")
    assert mass["before"] is None and mass["after"] is None and mass["status"] == "unknown"


def test_spar_17_mm_is_blocked_by_the_confirmed_16_mm_wing3_hole(base_params, manifest, policy):
    request = _request(EditOperation.resize_spar, ["recon_spar"], outer_d_mm=17.0)
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(request, manifest, base_params, policy)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert "17" in envelope.message and "16" in envelope.message
    assert "wing3_16mm_hole" in envelope.message
    assert envelope.details["limit_value"] == 16.0
    assert envelope.details["requested"] == 17.0
    assert "confirmed wing3 variant" in envelope.details["source"]

    # 16 mm exactly is allowed: the limit is the hole, not a margin on it
    policy_mod.check_bounds(_request(EditOperation.resize_spar, ["recon_spar"], outer_d_mm=16.0),
                            manifest, base_params, policy)


def test_twelve_mm_variant_lowers_the_ceiling(base_params, policy):
    twelve = _manifest("Wings/wing3_12mm_hole.stl")
    assert policy_mod.spar_hole_limit_mm(twelve, policy) == 12.0
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(
            _request(EditOperation.resize_spar, ["recon_spar"], outer_d_mm=14.0),
            twelve, base_params, policy)
    assert "wing3_12mm_hole" in excinfo.value.envelope.message


def test_no_hole_variant_blocks_any_through_spar_resize(base_params, policy):
    no_hole = _manifest("Wings/wing3_no_hole.stl")
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.spar_hole_limit_mm(no_hole, policy)
    assert "no through-spar passage" in excinfo.value.envelope.message

    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(
            _request(EditOperation.resize_spar, ["recon_spar"], outer_d_mm=8.0),
            no_hole, base_params, policy)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert "wing3_no_hole" in envelope.message


def test_unconfirmed_wing3_variant_blocks_the_resize(base_params, policy):
    unconfirmed = _manifest(None)
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(
            _request(EditOperation.resize_spar, ["recon_spar"], outer_d_mm=12.0),
            unconfirmed, base_params, policy)
    assert "no wing3 variant has been confirmed" in excinfo.value.envelope.message


def test_wall_thickness_floor_is_enforced(base_params, manifest, policy):
    floor = policy["spar"]["wall_thickness_floor_mm"]
    thin = _request(EditOperation.resize_spar, ["recon_spar"], outer_d_mm=12.0, inner_d_mm=11.5)
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(thin, manifest, base_params, policy)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert envelope.details["limit"] == "spar.wall_thickness_floor_mm"
    assert envelope.details["limit_value"] == floor
    assert envelope.details["requested"] == pytest.approx(0.25)

    # exactly at the floor passes
    policy_mod.check_bounds(
        _request(EditOperation.resize_spar, ["recon_spar"], outer_d_mm=12.0, inner_d_mm=11.0),
        manifest, base_params, policy)


# ---------------------------------------------------------------------------- tip extension

def test_tip_extension_adds_twice_the_extension_to_the_regenerated_span(base_params):
    extension = 0.1
    new, changes = operations.set_wing_tip_extension(base_params, extension)
    assert new.tip_extension_m == pytest.approx(extension)
    assert base_params.tip_extension_m == 0.0

    def span(model) -> tuple[float, float, float]:
        parts = _by_id(model)
        right, left = parts["recon_wing_right"], parts["recon_wing_left"]
        r_lo, r_hi = right.bounds_m()
        l_lo, l_hi = left.bounds_m()
        return (max(r_hi[1], l_hi[1]) - min(r_lo[1], l_lo[1]), r_hi[1], -l_lo[1])

    before_span, before_right, before_left = span(reconstruct(params=base_params))
    after_span, after_right, after_left = span(reconstruct(params=new))

    assert after_span - before_span == pytest.approx(2 * extension, abs=1e-6)
    # symmetric: both sides grew by the same amount, in one transaction
    assert after_right - before_right == pytest.approx(extension, abs=1e-6)
    assert after_left - before_left == pytest.approx(extension, abs=1e-6)
    assert after_right == pytest.approx(after_left, abs=1e-9)

    changed = {c["part_id"] for c in changes if c["field"] == "tip_extension_m"}
    assert changed == {"recon_wing_right", "recon_wing_left"}
    reported = next(c for c in changes if c["field"] == "wing_span_m")
    assert reported["after"] - reported["before"] == pytest.approx(2 * extension, abs=1e-9)
    # the spar is flagged as deliberately NOT extended with the tip
    spar = next(c for c in changes if c["part_id"] == "recon_spar")
    assert spar["before"] == spar["after"] and spar["status"] == "unchanged"


def test_tip_extension_beyond_the_declared_ceiling_is_blocked(base_params, manifest, policy):
    request = _request(EditOperation.set_wing_tip_extension,
                       ["recon_wing_right", "recon_wing_left"], extension_m=0.30)
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(request, manifest, base_params, policy)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.CONSTRAINT_FAILED
    assert envelope.details["limit"] == "wing_tip_extension"
    assert envelope.details["limit_value"] == [-0.05, 0.15]


# ---------------------------------------------------------------------------- refusals

def test_unknown_operation_is_unsupported(base_params, manifest, policy):
    """`replace_catalog_component` is in the contract's enum but not implemented here."""
    request = _request(EditOperation.replace_catalog_component, [BATTERY_PART_ID], catalog_id="x")
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(request, manifest, base_params, policy)
    assert excinfo.value.envelope.code is ErrorCode.UNSUPPORTED_EDIT
    assert "not implemented" in excinfo.value.envelope.message


def test_a_locked_reference_mesh_cannot_be_translated(base_params, manifest, policy):
    request = _request(EditOperation.translate_component, [LOCKED_PART_ID], delta_m=[0.01, 0, 0])
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(request, manifest, base_params, policy)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.UNSUPPORTED_EDIT
    assert "locked" in envelope.message


def test_a_part_without_the_capability_cannot_be_extended(base_params, manifest, policy):
    request = _request(EditOperation.set_wing_tip_extension, [BATTERY_PART_ID], extension_m=0.05)
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(request, manifest, base_params, policy)
    envelope = excinfo.value.envelope
    assert envelope.code is ErrorCode.UNSUPPORTED_EDIT
    assert "does not allow set_wing_tip_extension" in envelope.message
    assert envelope.details["capabilities"] == ["translate_component", "replace_catalog_component"]


def test_an_unknown_target_is_unsupported(base_params, manifest, policy):
    request = _request(EditOperation.translate_component, ["no-such-part"], delta_m=[0.01, 0, 0])
    with pytest.raises(EditBlocked) as excinfo:
        policy_mod.check_bounds(request, manifest, base_params, policy)
    assert excinfo.value.envelope.code is ErrorCode.UNSUPPORTED_EDIT
    assert "unknown target part" in excinfo.value.envelope.message


def test_the_manifest_battery_id_resolves_onto_the_reconstruction_envelope(manifest, policy):
    recon_id, capabilities = policy_mod.resolve_target(BATTERY_PART_ID, manifest, policy)
    assert recon_id == "recon_battery"
    assert EditCapability.translate in capabilities


# ---------------------------------------------------------------------------- end to end

class _FakeStore:
    """Stands in for A3a's store: runs the build in a directory and reports a preview."""

    def __init__(self, root: Path):
        self.root = root
        self.builds: list[BuildResult] = []

    def create_preview(self, design_dir, parent_revision_id, cause, build, idempotency_key=None):
        workdir = self.root / "preview-0001"
        workdir.mkdir(parents=True, exist_ok=True)
        result = build(workdir)
        self.builds.append(result)
        return RevisionManifest(
            design_id="titan_avenger", revision_id="preview-0001",
            parent_revision_id=parent_revision_id, state=RevisionState.preview,
            content_sha256="0" * 64, cause=cause, artifacts=result.artifacts)


class _FakeCollider:
    """Stands in for A3c's collider: declares that it checked and found nothing."""

    def __init__(self):
        self.calls: list[dict] = []

    def check(self, model, manifest, params, policy, changed_part_ids=None):
        self.calls.append({"changed": list(changed_part_ids or []), "parts": len(model.parts)})
        return [RoundTripCheck(name="no_undeclared_interference", passed=True,
                               detail="fake collider (A3c not landed yet)")]


@pytest.fixture
def synthetic_design(tmp_path) -> Path:
    """A design directory with one revision: a manifest and the baseline parameter set."""
    design = tmp_path / "design"
    revision = design / "revisions" / "rev-fixture"
    revision.mkdir(parents=True)
    (revision / "design_manifest.json").write_text(_manifest().model_dump_json(indent=2))
    (revision / "revision_manifest.json").write_text(RevisionManifest(
        design_id="titan_avenger", revision_id="rev-fixture", state=RevisionState.committed,
        content_sha256="0" * 64, cause="import").model_dump_json(indent=2))
    dump_params(load_params(DEFAULT_PARAMS_PATH), revision / PARAMS_NAME)
    return design


def test_apply_edit_end_to_end_moves_the_battery_and_verifies_the_export(synthetic_design,
                                                                         tmp_path):
    store, collider = _FakeStore(tmp_path / "revisions"), _FakeCollider()
    request = CadEditRequest(base_revision_id="rev-fixture",
                             operation=EditOperation.translate_component,
                             target_part_ids=[BATTERY_PART_ID],
                             parameters={"delta_m": [0.02, 0.0, 0.0]})

    result = apply_edit(synthetic_design, request, store=store, collider=collider)

    assert result.status == "ok", result.error
    assert result.preview_revision_id == "preview-0001"
    assert result.affected_part_ids == ["recon_battery"]
    names = {c.name for c in result.checks}
    assert {"requested_placement_applied", "unchanged_parts_unchanged", "solids_valid",
            "no_undeclared_interference"} <= names
    assert all(c.passed for c in result.checks)
    # both ids travel to the collider: the one it can measure, and the one it can read claims on
    assert collider.calls == [{"changed": ["recon_battery", BATTERY_PART_ID], "parts": 11}]

    written = {a.path for a in result.artifacts}
    assert {"updated_reconstruction.step", "part_map.json", "bom.json", "changes.json",
            PARAMS_NAME} <= written
    # the preview carries its own parameter set, so the next edit chains off this one
    child = load_params(tmp_path / "revisions" / "preview-0001" / PARAMS_NAME)
    assert child.battery.center_m == pytest.approx([-0.18, 0.0, -0.005])

    cg = next(c for c in result.changes if c["field"] == "cg_m")
    assert cg["before"] is None and cg["after"] is None

    # the preview carries the design's identity forward, or the edited design is unloadable
    preview = tmp_path / "revisions" / "preview-0001"
    for name in ("design_manifest.json", "parts.json"):
        assert (preview / name).is_file(), name
    moved = next(p for p in DesignManifest.model_validate_json(
        (preview / "design_manifest.json").read_text()).parts if p.part_id == BATTERY_PART_ID)
    assert [row[3] for row in moved.T_parent_from_local[:3]] == pytest.approx([0.02, 0.0, 0.0])

    content = store.builds[0].content
    assert content["operation"] == "translate_component"
    assert content["policy_sha256"] and content["params_sha256"]
    assert content["parent_revision_id"] == "rev-fixture"

    # changes.json records the same typed changes the caller got back
    recorded = json.loads((tmp_path / "revisions" / "preview-0001" / "changes.json").read_text())
    assert recorded["cause"] == "edit:translate_component"
    assert any(c["field"] == "center_m" for c in recorded["changes"])


def test_an_operation_with_no_named_target_resolves_by_role(synthetic_design, tmp_path):
    """The archive has no spar, so `resize_spar` has exactly one possible target: declare it.

    The request below names nothing and still reaches the wing3 bound, which proves the
    default target was resolved and went through the capability check.
    """
    store, collider = _FakeStore(tmp_path / "revisions"), _FakeCollider()
    result = apply_edit(synthetic_design,
                        CadEditRequest(base_revision_id="rev-fixture",
                                       operation=EditOperation.resize_spar, target_part_ids=[],
                                       parameters={"outer_d_mm": 17.0}),
                        store=store, collider=collider)
    assert result.status == "blocked"
    assert "wing3_16mm_hole" in result.error.message
    assert result.affected_part_ids == ["recon_spar"]

    # translate_component has no default: which component moves *is* the request
    ambiguous = apply_edit(synthetic_design,
                           CadEditRequest(base_revision_id="rev-fixture",
                                          operation=EditOperation.translate_component,
                                          target_part_ids=[],
                                          parameters={"delta_m": [0.02, 0.0, 0.0]}),
                           store=store, collider=collider)
    assert ambiguous.status == "blocked"
    assert ambiguous.error.code is ErrorCode.UNSUPPORTED_EDIT
    assert "names no target" in ambiguous.error.message
    assert store.builds == []


def test_a_refusal_always_carries_a_reason(synthetic_design, tmp_path):
    """No result may come back non-`ok` with an empty envelope: a silent refusal is useless."""
    store, collider = _FakeStore(tmp_path / "revisions"), _FakeCollider()
    for parameters, operation in (({"outer_d_mm": 17.0}, EditOperation.resize_spar),
                                  ({"outer_d_mm": 3.0}, EditOperation.resize_spar),
                                  ({"extension_m": 9.0}, EditOperation.set_wing_tip_extension),
                                  ({}, EditOperation.set_wing_tip_extension)):
        result = apply_edit(synthetic_design,
                            CadEditRequest(base_revision_id="rev-fixture", operation=operation,
                                           target_part_ids=[], parameters=parameters),
                            store=store, collider=collider)
        assert result.status != "ok"
        assert result.error is not None and result.error.message
        assert result.error.code in (ErrorCode.CONSTRAINT_FAILED, ErrorCode.UNSUPPORTED_EDIT)


def test_apply_edit_with_the_real_store_and_collider(synthetic_design):
    """The defaults: A3a's RevisionStore and A3c's collider, no fakes anywhere.

    The battery move is geometrically clean, so it is `ok`. The retention strap and power
    harness are not in the archive, so A3c will not call the movement verified: that blocks
    the *claim*, not the operation (architecture 6). The result says so with `verified: false`
    and the reasons, and A3c's check stays in `checks` with `passed=False`.
    """
    request = CadEditRequest(base_revision_id="rev-fixture",
                             operation=EditOperation.translate_component,
                             target_part_ids=[BATTERY_PART_ID],
                             parameters={"delta_m": [0.02, 0.0, 0.0]})

    result = apply_edit(synthetic_design, request)

    by_name = {c.name: c for c in result.checks}
    for name in ("requested_placement_applied", "unchanged_parts_unchanged",
                 "placement_match", "volume_relative_difference", "part_map_id_coverage",
                 "collision_undeclared_interference", "propeller_clearance"):
        assert by_name[name].passed, (name, by_name[name].detail)

    assert result.status == "ok"
    assert result.error.code is ErrorCode.MISSING_EVIDENCE
    assert result.error.details["verified"] is False
    assert result.error.details["advisory_checks"] == ["verified_movement_unknown"]
    assert result.error.details["unverified_reasons"]
    assert not by_name["verified_movement_unknown"].passed
    assert result.preview_revision_id
    preview = synthetic_design / "revisions" / result.preview_revision_id
    assert (preview / "updated_reconstruction.step").is_file()
    assert (preview / PARAMS_NAME).is_file()
    assert (synthetic_design / "revisions" / "rev-fixture" / PARAMS_NAME).is_file()  # parent kept


def test_apply_edit_returns_blocked_without_building_anything(synthetic_design, tmp_path):
    store, collider = _FakeStore(tmp_path / "revisions"), _FakeCollider()
    request = CadEditRequest(base_revision_id="rev-fixture", operation=EditOperation.resize_spar,
                             target_part_ids=["recon_spar"],
                             parameters={"outer_d_mm": 17.0})

    result = apply_edit(synthetic_design, request, store=store, collider=collider)

    assert result.status == "blocked"
    assert result.error.code is ErrorCode.CONSTRAINT_FAILED
    assert "wing3_16mm_hole" in result.error.message
    assert result.preview_revision_id is None
    assert store.builds == [] and collider.calls == []
    assert not (tmp_path / "revisions").exists()
