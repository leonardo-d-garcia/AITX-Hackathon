import json
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from dronebench_adapters.geometry import to_lanec_geometry

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = REPO_ROOT / "packages" / "contracts" / "lanec_schemas"
AVENGER_SAMPLE = Path("/tmp/avenger_demo/design/revisions/rev-c1e10160ce73/geometry_features.json")


def _validator() -> Draft202012Validator:
    schema = json.loads((SCHEMAS_DIR / "geometry_features.schema.json").read_text())
    resources = []
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        doc = json.loads(path.read_text())
        resources.append((path.name, Resource.from_contents(doc)))
    registry = Registry().with_resources(resources)
    return Draft202012Validator(schema, registry=registry)


@pytest.mark.skipif(not AVENGER_SAMPLE.exists(), reason="real Avenger geometry_features.json sample not present")
def test_real_avenger_sample_converts_and_validates():
    source = json.loads(AVENGER_SAMPLE.read_text())
    out = to_lanec_geometry(source)

    _validator().validate(out)

    stations = out["wing_stations"]
    assert len(stations) > 5
    ys = [s["span_y_m"]["value"] for s in stations]
    assert all(y >= 0 for y in ys)
    assert ys == sorted(ys)

    assert out["reference"]["S_m2"]["value"] == source["reference_area_m2"]["value"]
    assert out["reference"]["b_m"]["value"] == source["reference_span_m"]["value"]
    assert out["reference"]["c_m"]["value"] == source["reference_chord_m"]["value"]


def test_unknown_stays_null_and_hand_built_geometry_validates():
    features = {
        "schema_version": "0.1.0",
        "design_id": "d1",
        "revision_id": "r1",
        "frame": "FRD",
        "reference_area_m2": {"value": 1.0, "unit": "m2", "status": "known", "source_kind": "cad",
                               "evidence_ids": [], "assumptions": []},
        "reference_span_m": {"value": 2.0, "unit": "m", "status": "known", "source_kind": "cad",
                              "evidence_ids": [], "assumptions": []},
        "reference_chord_m": {"value": 0.5, "unit": "m", "status": "known", "source_kind": "cad",
                               "evidence_ids": [], "assumptions": []},
        "surfaces": [
            {
                "surface_id": "wing",
                "part_ids": [],
                "stations": [
                    {"span_y_m": 0.0, "leading_edge_x_m": 0.0, "chord_m": 0.3, "z_m": 0.0, "twist_rad": 0.0},
                    {"span_y_m": 0.3, "leading_edge_x_m": -0.01, "chord_m": 0.25, "z_m": 0.0, "twist_rad": 0.0},
                    {"span_y_m": 0.6, "leading_edge_x_m": -0.02, "chord_m": 0.2, "z_m": 0.0, "twist_rad": 0.0},
                    {"span_y_m": 0.9, "leading_edge_x_m": -0.03, "chord_m": 0.15, "z_m": 0.0, "twist_rad": 0.0},
                    {"span_y_m": 1.0, "leading_edge_x_m": -0.04, "chord_m": 0.1, "z_m": 0.0, "twist_rad": 0.0},
                ],
                "symmetric": True,
                "span_m": {"value": 2.0, "unit": "m", "status": "known", "source_kind": "cad",
                           "evidence_ids": [], "assumptions": []},
                "area_m2": {"value": 1.0, "unit": "m2", "status": "known", "source_kind": "cad",
                            "evidence_ids": [], "assumptions": []},
                "mac_m": {"value": None, "unit": "m", "status": "unknown", "source_kind": "assumed",
                          "evidence_ids": [], "assumptions": []},
                "x_mac_le_m": {"value": None, "unit": "m", "status": "unknown", "source_kind": "assumed",
                               "evidence_ids": [], "assumptions": []},
                "aspect_ratio": {"value": None, "unit": "1", "status": "unknown", "source_kind": "assumed",
                                 "evidence_ids": [], "assumptions": []},
                "sweep_le_rad": {"value": None, "unit": "rad", "status": "unknown", "source_kind": "assumed",
                                 "evidence_ids": [], "assumptions": []},
                "dihedral_rad": {"value": None, "unit": "rad", "status": "unknown", "source_kind": "assumed",
                                 "evidence_ids": [], "assumptions": []},
                "airfoil": {"value": None, "unit": "1", "status": "unknown", "source_kind": "assumed",
                            "evidence_ids": [], "assumptions": []},
            }
        ],
        "fuselage": [],
        "fuselage_length_m": {"value": None, "unit": "m", "status": "unknown", "source_kind": "assumed",
                               "evidence_ids": [], "assumptions": []},
        "mass_kg": {"value": None, "unit": "kg", "status": "unknown", "source_kind": "assumed",
                    "evidence_ids": [], "assumptions": []},
        "cg_m": {"value": None, "unit": "m", "status": "unknown", "source_kind": "assumed",
                 "evidence_ids": [], "assumptions": []},
        "quality": {},
    }

    out = to_lanec_geometry(features)
    _validator().validate(out)

    # No V-tail surface in this hand-built fixture -> cant/panel fields stay
    # explicit unknowns, never an invented number.
    assert out["tail"]["cant_rad"]["value"] is None
    assert out["tail"]["cant_rad"]["status"] == "unknown"
