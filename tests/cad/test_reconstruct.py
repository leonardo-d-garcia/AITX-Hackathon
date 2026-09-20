"""The reconstruction is buildable, solid, faithful to its stations, and deterministic."""
from __future__ import annotations

import math

import numpy as np
import pytest
import trimesh

from dronebench_cad import ReconParams, projected_planform_area_m2, reconstruct

EXPECTED_PARTS = {
    "recon_wing_right", "recon_wing_left", "recon_vtail_right", "recon_vtail_left",
    "recon_fuselage", "recon_spar", "recon_battery", "recon_motor", "recon_motor_mount",
    "recon_prop", "recon_wing_bay_plate",
}


def _mesh(part, tolerance_mm: float = 0.05) -> trimesh.Trimesh:
    verts, tris = part.solid.tessellate(tolerance_mm)
    mesh = trimesh.Trimesh(
        vertices=np.array([[v.x, v.y, v.z] for v in verts]),
        faces=np.array(tris, dtype=np.int64),
        process=False,
    )
    mesh.merge_vertices()
    return mesh


def _chord_at(part, y_m: float, tolerance_mm: float = 0.02):
    """Chord, leading edge x and mid-thickness z of a tessellated part at span station y."""
    mesh = _mesh(part, tolerance_mm)
    sec = mesh.section(plane_origin=[0, y_m * 1000, 0], plane_normal=[0, 1, 0])
    assert sec is not None, f"no section at y={y_m}"
    p = sec.vertices / 1000.0
    le, te = float(p[:, 0].max()), float(p[:, 0].min())
    return le - te, le, float((p[:, 2].min() + p[:, 2].max()) / 2)


def test_every_expected_part_is_built(model):
    assert {p.part_id for p in model.parts} == EXPECTED_PARTS
    assert all(p.representation in ("reconstruction", "envelope") for p in model.parts)
    assert any("not the original" in w.lower() for w in model.warnings)


def test_every_solid_is_valid_closed_and_watertight(model):
    for part in model.parts:
        assert part.is_valid(), f"{part.part_id} failed isValid()"
        assert len(part.solid.Shells()) == 1, f"{part.part_id} is not a single shell"
        assert part.volume_m3() > 0, f"{part.part_id} has non-positive volume"
        assert math.isfinite(part.volume_m3())
        assert _mesh(part).is_watertight, f"{part.part_id} tessellates to an open mesh"


def test_mirrored_occurrences_are_geometry_not_placements(model):
    right = model.part("recon_wing_right")
    left = model.part("recon_wing_left")
    assert left.mirror_of == right.part_id
    assert left.volume_m3() == pytest.approx(right.volume_m3(), rel=1e-9)
    lo, hi = left.bounds_m()
    ro, rh = right.bounds_m()
    assert lo[1] == pytest.approx(-rh[1], abs=1e-9) and hi[1] == pytest.approx(-ro[1], abs=1e-9)
    assert lo[0] == pytest.approx(ro[0], abs=1e-9) and hi[0] == pytest.approx(rh[0], abs=1e-9)


def test_wing_area_matches_the_features_reference_area(model, features):
    exposed = sum(
        projected_planform_area_m2(p) for p in model.parts if p.category == "wing"
    )
    claimed = features["reference_area_m2"]["value"]
    assert exposed == pytest.approx(claimed, rel=0.03), (
        f"reconstructed exposed planform {exposed:.6f} m2 vs features {claimed:.6f} m2"
    )


def test_stations_are_reproduced_in_the_geometry(model, params):
    wing = next(s for s in params.surfaces if s.category == "wing")
    for station in (wing.stations[0], wing.stations[len(wing.stations) // 2]):
        chord, le, z = _chord_at(model.part("recon_wing_right"), station.span_y_m)
        assert chord == pytest.approx(station.chord_m, abs=2e-4)
        assert le == pytest.approx(station.leading_edge_x_m, abs=2e-4)
        assert z == pytest.approx(station.z_m, abs=2e-4)


def test_vtail_is_two_canted_panels(model, params):
    vtail = next(s for s in params.surfaces if s.category == "vtail")
    assert math.degrees(vtail.cant_rad) == pytest.approx(30.0, abs=1.0)
    right, left = model.part("recon_vtail_right"), model.part("recon_vtail_left")
    for panel in (right, left):
        lo, hi = panel.bounds_m()
        assert lo[2] < -0.10, "the panel should rise well above the tail boom (z is down)"
    assert right.bounds_m()[1][1] > 0 > left.bounds_m()[0][1]


def test_pusher_motor_and_prop_sit_behind_the_fuselage(model):
    fuse_aft = model.part("recon_fuselage").bounds_m()[0][0]
    assert model.part("recon_motor").bounds_m()[1][0] <= fuse_aft + 1e-9
    assert model.part("recon_prop").bounds_m()[1][0] < model.part("recon_motor").bounds_m()[0][0]


# ---------------------------------------------------------------- parameter response

def test_scaling_every_chord_scales_the_wing_volume_by_the_square(params):
    k = 1.10
    base = reconstruct(params=params).part("recon_wing_right").volume_m3()
    scaled = params.model_copy(deep=True)
    for surface in scaled.surfaces:
        if surface.category == "wing":
            for station in surface.stations:
                station.chord_m *= k
    got = reconstruct(params=scaled).part("recon_wing_right").volume_m3()
    assert got == pytest.approx(base * k**2, rel=1e-6)


def test_changing_one_station_chord_shows_up_at_that_station(params):
    edited = params.model_copy(deep=True)
    wing = next(s for s in edited.surfaces if s.category == "wing")
    index = 3
    station = wing.stations[index]
    untouched_y = wing.stations[0].span_y_m
    station.chord_m += 0.030

    before = reconstruct(params=params)
    after = reconstruct(params=edited)
    chord_after, _, _ = _chord_at(after.part("recon_wing_right"), station.span_y_m)
    chord_root_before, _, _ = _chord_at(before.part("recon_wing_right"), untouched_y)
    chord_root_after, _, _ = _chord_at(after.part("recon_wing_right"), untouched_y)

    assert chord_after == pytest.approx(station.chord_m, abs=2e-4)
    assert chord_root_after == pytest.approx(chord_root_before, abs=1e-6)
    assert after.part("recon_wing_right").volume_m3() > before.part("recon_wing_right").volume_m3()


def test_resizing_the_spar_matches_the_analytic_tube_volume(params):
    edited = params.model_copy(deep=True)
    edited.spar.outer_diameter_m = 0.020
    model = reconstruct(params=edited)
    spar = model.part("recon_spar")
    expected = (
        math.pi
        / 4
        * (edited.spar.outer_diameter_m**2 - edited.spar.inner_diameter_m**2)
        * edited.spar.span_m
    )
    assert spar.volume_m3() == pytest.approx(expected, rel=1e-6)
    assert spar.volume_m3() > reconstruct(params=params).part("recon_spar").volume_m3()


def test_a_spar_bore_wider_than_the_tube_is_rejected(params):
    bad = params.model_copy(deep=True)
    bad.spar.inner_diameter_m = bad.spar.outer_diameter_m + 0.001
    with pytest.raises(ValueError, match="inner diameter"):
        reconstruct(params=bad)


def test_tip_extension_lengthens_the_span(params):
    extended = params.model_copy(deep=True)
    extended.tip_extension_m = 0.05
    base = reconstruct(params=params).part("recon_wing_right")
    got = reconstruct(params=extended).part("recon_wing_right")
    assert got.bounds_m()[1][1] == pytest.approx(base.bounds_m()[1][1] + 0.05, abs=1e-9)
    assert got.volume_m3() > base.volume_m3()


def test_out_of_order_stations_are_rejected(params):
    bad = params.model_copy(deep=True)
    wing = next(s for s in bad.surfaces if s.category == "wing")
    wing.stations[2].span_y_m = wing.stations[1].span_y_m
    with pytest.raises(ValueError, match="span_y_m"):
        reconstruct(params=bad)


def test_regeneration_is_deterministic(params):
    a = reconstruct(params=params)
    b = reconstruct(params=params)
    for part_id, volume in a.volumes_m3().items():
        assert b.part(part_id).volume_m3() == pytest.approx(volume, rel=1e-9)
    assert a.part_map()["parts"] == b.part_map()["parts"]


def test_whole_aircraft_regenerates_well_under_thirty_seconds(params):
    model = reconstruct(params=params)
    assert model.build_seconds is not None and model.build_seconds < 30.0


def test_features_can_drive_reconstruct_directly(features):
    model = reconstruct(features)
    assert {p.part_id for p in model.parts} == EXPECTED_PARTS
    assert model.source_features_revision_id == features["revision_id"]


def test_an_explicit_left_right_surface_pair_is_not_doubled(features):
    """A1 may emit `vtail_left` + `vtail_right` (symmetric=False) instead of one surface."""
    split = {**features, "surfaces": []}
    for surface in features["surfaces"]:
        if surface["surface_id"] == "vtail_right":
            for side in ("left", "right"):
                split["surfaces"].append(
                    {**surface, "surface_id": f"vtail_{side}", "symmetric": False}
                )
        else:
            split["surfaces"].append(surface)
    model = reconstruct(split)
    assert {p.part_id for p in model.parts} == EXPECTED_PARTS
    assert model.part("recon_vtail_left").mirror_of is None
    assert model.part("recon_vtail_left").bounds_m()[0][1] < 0


def test_part_ids_can_be_bound_to_manifest_ids(params):
    model = reconstruct(params=params, part_ids={"wing_right": "wing-r-abc123"})
    assert model.part("wing-r-abc123").side == "right"


def test_nothing_claims_a_mass_or_a_material_by_itself(model):
    for part in model.parts:
        assert part.parameters.get("mass_kg") is None
