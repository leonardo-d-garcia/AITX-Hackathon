"""A3c: interference and propeller-clearance checks.

Every fixture here is synthetic and built in millimetres, the way `dronebench_cad` builds the
reconstruction — `collide` converts to metres itself. One test reaches for the real Avenger and
skips cleanly when the (git-ignored) vendor archive is not on this machine.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import cadquery as cq
import pytest

from dronebench_edits import collide


# ---------------------------------------------------------------- fixtures

@dataclass
class FakePart:
    part_id: str
    category: str = "other"
    solid: Optional[Any] = None
    parameters: dict = field(default_factory=dict)


@dataclass
class FakeModel:
    parts: list


def slab(part_id: str = "slab") -> FakePart:
    """A 100 x 100 x 10 mm plate centred on the origin."""
    return FakePart(part_id, "fuselage", cq.Solid.makeBox(100, 100, 10, cq.Vector(-50, -50, -5)))


def tube(part_id: str = "spar_1") -> FakePart:
    """A 12 mm tube on the z axis, passing clean through the slab."""
    return FakePart(part_id, "spar",
                    cq.Solid.makeCylinder(6, 60, cq.Vector(0, 0, -30), cq.Vector(0, 0, 1)))


def box(part_id: str, x0: float, dx: float, category: str = "other") -> FakePart:
    return FakePart(part_id, category,
                    cq.Solid.makeBox(dx, 40, 40, cq.Vector(x0, -20, -20)))


def manifest_of(*parts: dict) -> dict:
    return {"parts": list(parts)}


def occurrence(part_id: str, *, allowed: Optional[list[str]] = None, known: bool = False,
               category: str = "other") -> dict:
    """A manifest occurrence. `known=True` means mount, material and mass are all claimed."""
    status = "confirmed" if known else "unknown"
    return {
        "part_id": part_id,
        "category": category,
        "allowed_overlap_with": list(allowed or []),
        "labels": {"mount": "bolted M3x4" if known else "unknown"},
        "material": {"status": status, "value": "PLA" if known else None},
        "mass_kg": {"status": status, "value": 0.12 if known else None, "unit": "kg"},
        "function": {"status": status},
    }


def _shipped_policy() -> dict:
    """A3b's real policy file, or a close stand-in while it is still being written."""
    import pathlib

    policy_file = pathlib.Path(__file__).resolve().parents[2] / "packages" / "edits" / "edit_policy.yaml"
    try:
        import yaml

        return yaml.safe_load(policy_file.read_text())
    except Exception:
        return {"declared_overlap_pairs": [["recon_spar", "recon_wing*"]],
                "clearance": {"prop_clearance_min_m": 0.010}}


def named(checks, name: str):
    for c in checks:
        if c.name == name:
            return c
    raise AssertionError(f"no check named {name} in {[c.name for c in checks]}")


def mm_after(detail: str, part_id: str) -> float:
    """Pull the millimetre number reported next to a part id out of a check detail."""
    m = re.search(re.escape(part_id) + r"[^|;]*?(-?\d+\.\d+) mm", detail)
    assert m, f"no millimetre figure for {part_id} in: {detail}"
    return float(m.group(1))


@pytest.fixture(autouse=True)
def _fresh_cache():
    collide.clear_cache()
    yield
    collide.clear_cache()


PROP_PARAMS = SimpleNamespace(motor=SimpleNamespace(
    x_m=-0.95, z_m=0.0, length_m=0.040, prop_clearance_m=0.005,
    prop_diameter_m=0.305, prop_thickness_m=0.010,
))


# ---------------------------------------------------------------- declared vs undeclared

def test_declared_pair_passes_and_still_reports_engagement_depth():
    model = FakeModel([slab("fuse_1"), tube("spar_1")])
    man = manifest_of(occurrence("spar_1", allowed=["fuse_1"], known=True),
                      occurrence("fuse_1", allowed=["spar_1"], known=True))

    checks = collide.check(model, man, None, {})

    assert named(checks, "collision_undeclared_interference").passed
    engagement = named(checks, "collision_declared_engagement")
    assert engagement.passed
    assert "spar_1" in engagement.detail and "fuse_1" in engagement.detail
    # The tube really does pass through the 10 mm plate: the depth is evidence, not a verdict.
    assert mm_after(engagement.detail, "engagement") > 1.0


def test_undeclared_pair_fails_and_names_both_parts_and_the_depth():
    model = FakeModel([slab("fuse_1"), tube("spar_1")])
    man = manifest_of(occurrence("spar_1", known=True), occurrence("fuse_1", known=True))

    interference = named(collide.check(model, man, None, {}), "collision_undeclared_interference")

    assert not interference.passed
    assert "spar_1" in interference.detail and "fuse_1" in interference.detail
    assert mm_after(interference.detail, "interference") > 1.0


def test_the_shipped_edit_policy_is_read_as_written():
    """A3b's `edit_policy.yaml` nests the clearance and spells the pairs `declared_overlap_pairs`."""
    yaml = pytest.importorskip("yaml")
    policy_file = __import__("pathlib").Path(__file__).resolve().parents[2] / \
        "packages" / "edits" / "edit_policy.yaml"
    if not policy_file.exists():
        pytest.skip("edit_policy.yaml not written yet")
    policy = yaml.safe_load(policy_file.read_text())

    assert collide._policy_number(policy, "prop_clearance_min_m", 0.005) > 0
    pairs = collide._declared_pattern_pairs(policy)
    assert ("recon_spar", "recon_wing_right") in pairs or ("recon_wing_right", "recon_spar") in pairs
    assert not any("recon_prop" in p for p in pairs)   # the prop may never overlap anything


def test_policy_declared_overlaps_patterns_match_a_pair():
    model = FakeModel([slab("wing_bay"), tube("spar_1")])
    policy = {"declared_overlaps": [["spar*", "wing*"]]}

    checks = collide.check(model, manifest_of(), None, policy)

    assert named(checks, "collision_undeclared_interference").passed
    assert "declared_overlaps" in named(checks, "collision_declared_engagement").detail


def test_touching_but_not_overlapping_passes():
    model = FakeModel([box("left", -20, 20), box("right", 0, 20)])

    checks = collide.check(model, manifest_of(), None, {})

    assert named(checks, "collision_undeclared_interference").passed


# ---------------------------------------------------------------- propeller clearance

@pytest.mark.parametrize("boom_x0_mm, expect_pass", [(-987.0, False), (-970.0, True)])
def test_propeller_swept_volume_against_a_boom(boom_x0_mm, expect_pass):
    """The disc sits at x = -0.995 m (pusher: aft of the motor at -0.95). 3 mm fails, 20 mm passes."""
    model = FakeModel([box("boom", boom_x0_mm, 60, category="fuselage")])

    check = named(collide.check(model, manifest_of(), PROP_PARAMS, {"prop_clearance_min_m": 0.005}),
                  "propeller_clearance")

    assert check.passed is expect_pass
    assert "pusher" in check.detail
    measured = mm_after(check.detail, "minimum clearance")
    assert (measured >= 5.0) is expect_pass
    assert abs(measured - (boom_x0_mm + 990.0)) < 1.5   # the disc's forward face is at -0.990 m


def test_propeller_axis_follows_the_motor_rather_than_being_assumed():
    """Flip the envelope to a tractor and the reported axis flips with it."""
    tractor = SimpleNamespace(motor=SimpleNamespace(
        x_m=-0.95, z_m=0.0, length_m=-0.040, prop_clearance_m=-0.005,
        prop_diameter_m=0.305, prop_thickness_m=0.010,
    ))
    model = FakeModel([box("boom", -900.0, 60, category="fuselage")])

    detail = named(collide.check(model, manifest_of(), tractor, {}), "propeller_clearance").detail

    assert "tractor" in detail and "axis=(1.000" in detail


def test_no_propeller_envelope_makes_no_clearance_claim():
    model = FakeModel([box("boom", -900.0, 60)])

    check = named(collide.check(model, manifest_of(), None, {}), "propeller_clearance")

    assert check.passed and "not evaluated" in check.detail


# ---------------------------------------------------------------- scope and caching

def test_changed_part_ids_limits_the_pairs_tested():
    model = FakeModel([slab("fuse_1"), tube("spar_1"), box("tail", 400, 40)])
    man = manifest_of(occurrence("spar_1", known=True), occurrence("fuse_1", known=True),
                      occurrence("tail", allowed=["fuse_1"], known=True))

    everything = named(collide.check(model, man, None, {}), "collision_undeclared_interference")
    only_tail = named(collide.check(model, man, None, {}, changed_part_ids=["tail"]),
                      "collision_undeclared_interference")

    assert not everything.passed                    # spar through fuselage, undeclared
    assert only_tail.passed                         # that pair is not part of this edit
    assert "untouched by this edit were not retested" in only_tail.detail
    assert "changed parts ['tail']" in only_tail.detail


def test_tessellation_is_cached_across_calls():
    model = FakeModel([slab("fuse_1"), tube("spar_1")])

    collide.check(model, manifest_of(), None, {})
    first = collide.cache_stats()
    collide.check(model, manifest_of(), None, {})
    second = collide.cache_stats()

    assert first["misses"] == 2 and first["hits"] == 0
    assert second["misses"] == 2 and second["hits"] == 2   # no re-tessellation


# ---------------------------------------------------------------- unknown interfaces

def test_unknown_retention_interface_blocks_a_verified_movement_claim():
    model = FakeModel([slab("fuse_1"), box("battery", 200, 40, category="battery")])
    man = manifest_of(occurrence("fuse_1", known=True), occurrence("battery"))

    checks = collide.check(model, man, None, {}, changed_part_ids=["battery"])

    gap = named(checks, "verified_movement_unknown")
    assert not gap.passed
    assert "battery" in gap.detail
    assert "evidence gap" in gap.detail                    # distinguishable from interference
    assert named(checks, "collision_undeclared_interference").passed


def test_a_fully_declared_moved_part_does_not_raise_the_evidence_gap():
    model = FakeModel([slab("fuse_1"), box("battery", 200, 40, category="battery")])
    man = manifest_of(occurrence("fuse_1", allowed=["battery"], known=True),
                      occurrence("battery", allowed=["fuse_1"], known=True))

    gap = named(collide.check(model, man, None, {}, changed_part_ids=["battery"]),
                "verified_movement_unknown")

    assert gap.passed


def test_no_movement_means_no_movement_claim():
    model = FakeModel([slab("fuse_1")])

    names = [c.name for c in collide.check(model, manifest_of(), None, {})]

    assert "verified_movement_unknown" not in names


# ---------------------------------------------------------------- odd input never raises

def test_degenerate_part_returns_a_failed_check_instead_of_raising():
    import trimesh

    empty = FakePart("ghost", "other", None)
    empty.mesh = trimesh.Trimesh()                          # no faces, no vertices
    model = FakeModel([slab("fuse_1"), empty])

    checks = collide.check(model, manifest_of(), None, {})

    unusable = named(checks, "collision_geometry_unusable")
    assert not unusable.passed
    assert "ghost" in unusable.detail
    assert named(checks, "collision_undeclared_interference").passed   # the rest still measured


def test_a_part_with_no_geometry_at_all_is_reported_not_raised():
    model = FakeModel([FakePart("nothing")])

    checks = collide.check(model, manifest_of(), None, {})

    assert not named(checks, "collision_geometry_unusable").passed


def test_empty_model_returns_a_failed_check():
    checks = collide.check(FakeModel([]), manifest_of(), None, {})

    assert [c.name for c in checks] == ["collision_check_error"]
    assert not checks[0].passed


def test_garbage_input_returns_a_failed_check():
    checks = collide.check(object(), manifest_of(), None, {})

    assert len(checks) == 1 and not checks[0].passed


# ---------------------------------------------------------------- the real aircraft

def test_avenger_end_to_end(request):
    """One realistic call: the reconstructed Avenger, its confirmed manifest, its real prop."""
    try:
        design_dir, _revision = request.getfixturevalue("avenger_design")
    except Exception as exc:                                 # fixture missing or archive absent
        pytest.skip(f"avenger_design not available: {exc}")

    features_files = sorted(design_dir.glob("revisions/*/geometry_features.json"))
    manifest_files = sorted(design_dir.glob("revisions/*/design_manifest.json"))
    if not features_files or not manifest_files:
        pytest.skip("the confirmed revision carries no geometry_features/design_manifest yet")

    from dronebench_cad import reconstruct

    model = reconstruct(json.loads(features_files[-1].read_text()))
    man = json.loads(manifest_files[-1].read_text())
    policy = _shipped_policy()

    started = time.time()
    checks = collide.check(model, man, model.params, policy)
    elapsed = time.time() - started

    names = {c.name for c in checks}
    assert {"collision_declared_engagement", "collision_undeclared_interference",
            "propeller_clearance"} <= names
    prop = named(checks, "propeller_clearance")
    assert "pusher" in prop.detail, prop.detail          # the Avenger's disc is aft of the motor

    if collide._declared_pattern_pairs(policy):
        # Unedited, every contact in the reconstruction is one the policy declared.
        interference = named(checks, "collision_undeclared_interference")
        assert interference.passed, interference.detail
        assert "recon_spar" in named(checks, "collision_declared_engagement").detail
    assert elapsed < 30.0, f"collision check took {elapsed:.1f}s"

    # A second call over the same model must reuse every tessellation.
    before = collide.cache_stats()["misses"]
    collide.check(model, man, model.params, policy, changed_part_ids=["recon_battery"])
    assert collide.cache_stats()["misses"] == before
