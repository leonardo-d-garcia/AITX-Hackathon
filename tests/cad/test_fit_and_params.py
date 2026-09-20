"""The fit report reports numbers (and no verdict), and the parameter set round-trips."""
from __future__ import annotations

import pytest

from dronebench_cad import (
    DEFAULT_PARAMS_PATH,
    ReconParams,
    dump_params,
    fit_report,
    load_params,
    reconstruct,
)


# ---------------------------------------------------------------- parameters

def test_params_round_trip_through_yaml_is_lossless(params, tmp_path):
    path = dump_params(params, tmp_path / "params.yaml")
    assert load_params(path) == params


def test_the_shipped_params_file_rebuilds_the_same_aircraft(model):
    shipped = load_params(DEFAULT_PARAMS_PATH)
    rebuilt = reconstruct(params=shipped)
    assert {p.part_id for p in rebuilt.parts} == {p.part_id for p in model.parts}
    for part_id, volume in model.volumes_m3().items():
        assert rebuilt.part(part_id).volume_m3() == pytest.approx(volume, rel=1e-9)


def test_the_parameter_set_covers_the_minimum_editable_parameterisation(params):
    """Architecture §6: wing stations, fuselage envelopes, V-tail cant, spar, battery, motor."""
    station = params.surfaces[0].stations[0]
    for field in ("span_y_m", "leading_edge_x_m", "chord_m", "z_m", "twist_rad"):
        assert hasattr(station, field)
    assert params.fuselage and all(
        hasattr(f, "width_m") and hasattr(f, "height_m") for f in params.fuselage
    )
    assert any(s.cant_rad for s in params.surfaces if s.category == "vtail")
    assert params.spar.outer_diameter_m and params.spar.inner_diameter_m and params.spar.span_m
    assert params.battery.length_m and params.battery.center_m
    assert params.motor.diameter_m and params.motor.prop_diameter_m


def test_unknown_parameters_are_rejected_rather_than_silently_ignored():
    with pytest.raises(Exception):
        ReconParams.model_validate({"surfaces": [], "wing_sweep_deg": 3.0})


def test_assumptions_are_carried_with_the_parameters(params):
    text = " ".join(params.assumptions).lower()
    assert "assumed" in text and "synthetic" in text


# ---------------------------------------------------------------- fit report

def test_fit_report_is_numbers_only_and_unconfirmed(model, avenger_dir, features):
    report = fit_report(model, avenger_dir, samples=800, features=features)
    assert report["confirmed"] is False
    assert "pass" not in {k.lower() for k in report["overall"]}

    overall = report["overall"]
    assert overall["station_deviation_rms_m"] >= 0
    assert overall["station_deviation_max_m"] >= overall["station_deviation_rms_m"]
    assert overall["reference_to_reconstruction_rms_m"] > 0
    assert overall["reconstruction_to_reference_rms_m"] > 0
    assert overall["parts_compared"] >= 3

    wing = report["parts"]["recon_wing_right"]
    assert wing["reference_to_reconstruction"]["n_samples"] == 800
    assert wing["reference_to_reconstruction"]["max_m"] >= wing["reference_to_reconstruction"]["rms_m"]

    # The frame is a candidate until a human confirms it, and the report has to say so.
    assert any("unconfirmed" in note.lower() for note in report["notes"])


def test_fit_report_skips_the_parts_with_no_reference(model, avenger_dir):
    report = fit_report(model, avenger_dir, samples=400)
    for part_id in ("recon_spar", "recon_battery", "recon_motor", "recon_prop"):
        assert "source archive" in report["parts"][part_id]["skipped"]
    assert "mirrored occurrence" in report["parts"]["recon_wing_left"]["skipped"]


def test_fit_report_stations_line_up_with_the_reference(model, avenger_dir):
    report = fit_report(model, avenger_dir, samples=400)
    wing = report["surfaces"]["wing"]
    assert wing["station_deviation_rms_m"] < 1e-3, wing["station_deviation_rms_m"]
    row = next(r for r in wing["stations"] if "chord_m" in r)
    assert set(row["chord_m"]) == {"reference", "reconstruction", "deviation_m"}


def test_fit_report_compares_areas_like_for_like(model, avenger_dir, features):
    report = fit_report(model, avenger_dir, samples=200, features=features)
    area = report["area"]
    assert area["reconstruction_gross_planform_m2"] > area["reconstruction_exposed_planform_m2"]
    assert abs(area["relative_difference_vs_exposed"]) < 0.03


def test_fit_report_exposes_the_flat_keys_the_viewer_reads(model, avenger_dir):
    """A4's static inspector reads rms_m / max_m / per_part / note off the top level."""
    report = fit_report(model, avenger_dir, samples=300)
    assert report["rms_m"] > 0 and report["max_m"] >= report["rms_m"]
    assert {p["part_id"] for p in report["per_part"]} == {p.part_id for p in model.parts}
    assert "confirm" in report["note"].lower()
    for row in report["per_part"]:
        assert set(row) == {"part_id", "rms_m", "max_m", "note"}
        assert row["rms_m"] is not None or row["note"], "an uncompared part must say why"


def test_fit_report_raises_when_it_cannot_find_the_reference(model, tmp_path):
    with pytest.raises(ValueError, match="not available"):
        fit_report(model, tmp_path / "not_here", samples=100)


def test_fit_report_raises_when_nothing_matches_rather_than_returning_nulls(model, tmp_path):
    """An empty but existing directory used to come back as a report full of nulls."""
    empty = tmp_path / "empty_sources"
    empty.mkdir()
    with pytest.raises(ValueError, match="nothing was compared"):
        fit_report(model, empty, samples=100)


def test_fit_report_degrades_cleanly_without_the_reference(model, tmp_path):
    report = fit_report(model, tmp_path / "not_here", samples=100, strict=False)
    assert report["confirmed"] is False
    assert report["parts"] == {} and report["overall"] == {}
    assert report["rms_m"] is None and report["per_part"] == []
    assert any("not available" in note for note in report["notes"])


def test_fit_report_is_deterministic(model, avenger_dir):
    a = fit_report(model, avenger_dir, samples=300)
    b = fit_report(model, avenger_dir, samples=300)
    assert a["overall"] == b["overall"]
