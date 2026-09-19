"""Validates the Lane A -> Lane C parts/design_manifest adapter against Lane C's
real JSON Schemas, using a real 42-part Avenger DesignManifest as input."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from dronebench_adapters.parts import to_lanec_design_manifest, to_lanec_parts
from dronebench_contracts.models import DesignManifest

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "packages" / "contracts" / "lanec_schemas"
REAL_MANIFEST_PATH = Path(
    "/tmp/avenger_demo/design/revisions/rev-c1e10160ce73/design_manifest.json"
)


def _validator_for(schema_name: str) -> Draft202012Validator:
    resources = []
    schema = None
    for path in SCHEMAS_DIR.glob("*.schema.json"):
        data = json.loads(path.read_text())
        resource = Resource.from_contents(data)
        resources.append((data["$id"], resource))
        resources.append((path.name, resource))
        if path.name == schema_name:
            schema = data
    assert schema is not None, f"schema {schema_name} not found in {SCHEMAS_DIR}"
    registry = Registry().with_resources(resources)
    return Draft202012Validator(schema, registry=registry)


def _load_real_manifest() -> DesignManifest:
    if REAL_MANIFEST_PATH.exists():
        return DesignManifest.model_validate(json.loads(REAL_MANIFEST_PATH.read_text()))
    pytest.skip(f"real Avenger sample not found at {REAL_MANIFEST_PATH}")


def test_real_avenger_parts_and_manifest_validate_against_lanec_schemas():
    manifest = _load_real_manifest()

    lanec_parts = to_lanec_parts(manifest)
    lanec_dm = to_lanec_design_manifest(manifest)

    parts_validator = _validator_for("parts.schema.json")
    dm_validator = _validator_for("design_manifest.schema.json")

    parts_errors = sorted(parts_validator.iter_errors(lanec_parts), key=str)
    assert not parts_errors, "\n".join(str(e) for e in parts_errors)

    dm_errors = sorted(dm_validator.iter_errors(lanec_dm), key=str)
    assert not dm_errors, "\n".join(str(e) for e in dm_errors)

    occurrences = lanec_parts["occurrences"]
    assert len(occurrences) == 42

    # Printed/mesh parts have no measured or catalog mass in our pipeline and
    # must stay null+unknown, never a fabricated 0. Catalog components (motor,
    # prop, esc, battery, fc, rx, gps, payload, servo) do carry a real
    # estimated mass and must NOT be clobbered to unknown.
    unknown_count = 0
    for occ in occurrences:
        claim = occ["mass_kg"]
        if claim["status"] == "unknown":
            assert claim["value"] is None
            unknown_count += 1
        else:
            assert claim["value"] is not None
            assert claim["value"] != 0
    assert unknown_count > 0

    mirrored_source = [p for p in manifest.parts if p.mirror_of]
    assert mirrored_source, "expected at least one mirrored part in the real sample"

    occ_by_id = {o["part_id"]: o for o in occurrences}
    for src in mirrored_source:
        occ = occ_by_id[src.part_id]
        t = src.T_parent_from_local
        assert occ["position_frd_m"]["x_m"]["value"] == pytest.approx(t[0][3])
        assert occ["position_frd_m"]["y_m"]["value"] == pytest.approx(t[1][3])
        assert occ["position_frd_m"]["z_m"]["value"] == pytest.approx(t[2][3])

    # mirror_of isn't representable on Lane C's occurrence schema; make sure
    # we didn't just drop that provenance silently.
    assert "mirror_of" in lanec_dm["notes"] or "mirror" in lanec_dm["notes"].lower()
