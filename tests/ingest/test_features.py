"""Measured geometry of the Avenger, checked against hand calculations from the archive.

The hand calculation uses only numbers that can be read off the source bounds:
  * root chord 213.89 mm  = native Y extent of wing1, at native X = 70 mm
  * chord 130.21 mm       = native Y extent of wing5, at native X = 1028.09 mm
  * tip at native X = 1112.25 mm
A straight taper through those two chords gives a tip chord of 122.86 mm, so the exposed planform
of both panels is 2 x (213.89 + 122.86)/2 x (1112.25 - 70) mm^2 = 0.35098 m^2, and the gross area
adds the carry-through 2 x 70 mm x 213.89 mm = 0.02994 m^2.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from dronebench_contracts.models import ErrorEnvelope
from dronebench_ingest import geometry_features, placed_mesh, preview_manifest

ROOT_CHORD_M = 0.21389
MID_CHORD_M = 0.13021
ROOT_STATION_M = 0.070
MID_STATION_M = 1.02809
TIP_STATION_M = 1.11225
TIP_CHORD_M = ROOT_CHORD_M + (MID_CHORD_M - ROOT_CHORD_M) * (TIP_STATION_M - ROOT_STATION_M) / (
    MID_STATION_M - ROOT_STATION_M)
EXPOSED_AREA_M2 = 2 * 0.5 * (ROOT_CHORD_M + TIP_CHORD_M) * (TIP_STATION_M - ROOT_STATION_M)
CARRY_THROUGH_M2 = 2 * ROOT_STATION_M * ROOT_CHORD_M


def _wing(features):
    return next(s for s in features.surfaces if s.surface_id == "wing")


def test_unconfirmed_design_yields_an_error_envelope_not_a_number(staged):
    design_dir, _, _ = staged
    result = geometry_features(preview_manifest(design_dir))
    assert isinstance(result, ErrorEnvelope)
    assert result.code.value == "UNITS_UNCONFIRMED"
    assert result.retryable is False


def test_unresolved_variants_block_metrics(staged):
    from dronebench_ingest import detect_variants, load_staged, propose_frame
    from dronebench_ingest.manifest import build_manifest
    design_dir, _, sources = staged
    frame = propose_frame(sources).model_copy(update={"confirmed": True, "confirmed_by": "test"})
    manifest = build_manifest("d", "r", load_staged(design_dir), sources, frame,
                              detect_variants(sources))
    result = geometry_features(manifest)
    assert isinstance(result, ErrorEnvelope)
    assert result.code.value == "ASSEMBLY_UNCONFIRMED"
    assert set(result.details["groups"]) == {"wing3", "fuse3"}


def test_span_and_reference_values(confirmed):
    _, _, _, features = confirmed
    wing = _wing(features)
    assert wing.span_m.value == pytest.approx(2.2245, abs=0.002)
    assert features.reference_span_m.value == wing.span_m.value
    assert features.reference_area_m2.value == wing.area_m2.value
    assert features.reference_chord_m.value == wing.mac_m.value
    assert features.frame == "FRD"


def test_wing_area_is_counted_once(confirmed):
    _, _, manifest, features = confirmed
    wing = _wing(features)
    quality = features.quality["wing"]
    assert quality["exposed_area_m2"] == pytest.approx(EXPOSED_AREA_M2, rel=0.02)
    assert quality["carry_through_area_m2"] == pytest.approx(CARRY_THROUGH_M2, rel=0.02)
    assert wing.area_m2.value == pytest.approx(EXPOSED_AREA_M2 + CARRY_THROUGH_M2, rel=0.02)

    # the aileron is part of its parent's chord, never an extra panel
    aileron_ids = [p.part_id for p in manifest.parts if p.category == "aileron"]
    assert sorted(wing.control_surfaces) == sorted(aileron_ids)
    assert not any(s.surface_id.startswith("aileron") for s in features.surfaces)

    # skins are not surfaces: the merged mesh area is far larger than the planform
    wetted = sum(placed_mesh(manifest, p).area for p in manifest.parts
                 if p.category in ("wing", "aileron"))
    assert wing.area_m2.value < 0.5 * wetted


def test_wing_planform_numbers(confirmed):
    _, _, _, features = confirmed
    wing = _wing(features)
    quality = features.quality["wing"]
    assert wing.mac_m.value == pytest.approx(0.1725, abs=0.005)
    assert wing.aspect_ratio.value == pytest.approx(
        wing.span_m.value ** 2 / wing.area_m2.value, rel=1e-9)
    assert wing.aspect_ratio.value == pytest.approx(13.0, abs=0.3)
    assert np.degrees(wing.sweep_le_rad.value) == pytest.approx(3.0, abs=1.0)
    assert abs(np.degrees(wing.dihedral_rad.value)) < 1.0       # this wing is flat
    assert quality["root_chord_m"] == pytest.approx(ROOT_CHORD_M, rel=0.02)
    assert wing.fit_rms_m is not None and wing.fit_rms_m < 1e-3
    assert len(wing.stations) >= 30
    etas = [s.span_y_m for s in wing.stations]
    assert etas == sorted(etas)                                  # root -> tip
    assert etas[0] > ROOT_STATION_M and etas[-1] < TIP_STATION_M
    for station in wing.stations:
        assert station.chord_m > 0
        assert 0.05 < station.thickness_ratio < 0.25
        assert abs(station.twist_rad) < np.radians(10)


def test_airfoil_is_declared_as_an_assumption(confirmed):
    _, _, _, features = confirmed
    wing = _wing(features)
    assert wing.airfoil.value.startswith("NACA ")
    assert "(assumed)" in wing.airfoil.value
    assert wing.airfoil.status.value == "estimated"
    assert wing.airfoil.source_kind.value == "assumed"
    assert any("NOT an exact airfoil match" in a for a in wing.airfoil.assumptions)


def test_vtail_is_two_canted_panels(confirmed):
    _, _, _, features = confirmed
    panels = [s for s in features.surfaces if s.surface_id.startswith("vtail")]
    assert {s.surface_id for s in panels} == {"vtail_left", "vtail_right"}
    quality = features.quality["vtail"]
    for panel in panels:
        assert panel.symmetric is False
        assert panel.cant_rad is not None
        assert np.degrees(panel.cant_rad) == pytest.approx(30.0, abs=4.0)
        assert panel.dihedral_rad.value is None                  # cant, not dihedral
        assert panel.area_m2.value == pytest.approx(0.032, abs=0.006)
        assert panel.span_m.value == pytest.approx(0.278, abs=0.02)
        assert panel.control_surfaces                            # the taileron of that side
    left, right = panels
    assert left.area_m2.value == pytest.approx(right.area_m2.value, rel=1e-9)
    total = quality["panel_area_total_m2"]
    assert total == pytest.approx(sum(p.area_m2.value for p in panels), rel=1e-9)
    assert quality["projected_horizontal_area_m2"] == pytest.approx(
        total * np.cos(left.cant_rad), rel=1e-6)
    assert quality["projected_vertical_area_m2"] == pytest.approx(
        total * np.sin(left.cant_rad), rel=1e-6)


def test_no_conventional_tail_volume_is_claimed(confirmed):
    _, _, _, features = confirmed
    text = json.dumps(features.model_dump(mode="json")).lower()
    assert "tail_volume" not in text and "vbar" not in text
    assert not any(s.surface_id in ("htail", "vtail") for s in features.surfaces)


def test_fuselage_stations_and_length(confirmed):
    _, _, _, features = confirmed
    assert features.fuselage_length_m.value == pytest.approx(0.99125, abs=0.002)
    assert len(features.fuselage) >= 20
    xs = [s.x_m for s in features.fuselage]
    assert xs == sorted(xs)
    assert all(x <= 0 for x in xs)                               # aft of the nose datum
    assert max(s.width_m for s in features.fuselage) == pytest.approx(0.1647, abs=0.005)
    assert all(s.height_m > 0 for s in features.fuselage)


def test_mass_and_cg_stay_unknown_without_measured_mass(confirmed):
    _, _, _, features = confirmed
    assert features.mass_kg.value is None and features.mass_kg.status.value == "unknown"
    assert features.cg_m.value is None
    missing = features.quality["mass"]["parts_without_mass"]
    assert len(missing) >= 30
    assert "no mass claim" in features.mass_kg.assumptions[0]


def test_shell_estimate_gives_a_mass_but_the_cg_stays_unknown(staged):
    """Selecting the mass model buys an estimated total; it does not buy a CG."""
    from dronebench_ingest import confirm, load_features
    from .conftest import SELECTION
    design_dir, _, _ = staged
    revision = confirm(design_dir, units="mm", variants=SELECTION, mirror="x=0",
                       mass_model="shell_estimate", confirmed_by="pytest")
    features = load_features(design_dir, revision.revision_id)
    assert features.mass_kg.status.value == "estimated"
    assert 2.0 < features.mass_kg.value < 20.0
    assert any("mass model: shell_estimate" in a for a in features.mass_kg.assumptions)
    assert features.cg_m.value is None                           # open meshes have no centroid
    assert "watertight" in features.cg_m.assumptions[0]
    assert features.quality["mass"]["parts_without_com"]


def test_every_published_number_carries_evidence_and_assumptions(confirmed):
    _, _, _, features = confirmed
    for surface in features.surfaces:
        for name in ("span_m", "area_m2", "mac_m", "aspect_ratio", "sweep_le_rad"):
            claim = getattr(surface, name)
            assert claim.value is not None
            assert claim.status.value == "estimated"
            assert claim.assumptions
            assert claim.evidence_ids
