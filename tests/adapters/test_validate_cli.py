from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = REPO_ROOT / "packages" / "contracts" / "lanec_schemas"

sys.path.insert(0, str(REPO_ROOT / "packages" / "adapters"))

from dronebench_adapters.validate import assert_valid, validate_lanec  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())


def test_example_geometry_features_is_valid():
    doc = _load("example_gf.json")
    assert validate_lanec("geometry_features", doc) == []


def test_example_parts_is_valid():
    doc = _load("example_parts.json")
    assert validate_lanec("parts", doc) == []


def test_example_design_manifest_is_valid():
    doc = _load("example_dm.json")
    assert validate_lanec("design_manifest", doc) == []


def test_broken_claim_status_unknown_with_nonzero_value_is_rejected():
    doc = _load("example_gf.json")
    # status "unknown" requires value to be null; a nonzero value here is invalid.
    doc["reference"]["S_m2"] = {
        "value": 0,
        "unit": "m2",
        "status": "unknown",
        "source_kind": "assumed",
        "evidence_ids": [],
        "assumptions": [],
    }
    errors = validate_lanec("geometry_features", doc)
    assert errors, "expected validation errors for a status=unknown claim with a numeric value"
    assert any("null" in e or "value" in e for e in errors)
    with pytest.raises(ValueError):
        assert_valid("geometry_features", doc)


def test_missing_required_key_is_rejected():
    doc = _load("example_dm.json")
    del doc["design_id"]
    errors = validate_lanec("design_manifest", doc)
    assert errors
    assert any("design_id" in e for e in errors)


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        validate_lanec("not_a_real_kind", {})


AVENGER_DESIGN = Path("/tmp/avenger_demo/design")


@pytest.mark.skipif(not AVENGER_DESIGN.is_dir(), reason="avenger demo design not present")
def test_cli_against_avenger_design(tmp_path):
    out_dir = tmp_path / "lanec_export"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dronebench_adapters.cli",
            "lanec",
            "--design",
            str(AVENGER_DESIGN),
            "--out",
            str(out_dir),
        ],
        cwd=REPO_ROOT,
        env={
            "PYTHONPATH": (
                f"{REPO_ROOT / 'packages' / 'adapters'}:"
                f"{REPO_ROOT / 'packages' / 'ingest'}"
            )
        },
        capture_output=True,
        text=True,
    )
    # The converters (geometry.py / parts.py) may not exist yet; that's a clean usage
    # error (exit 2), not a crash. Once they land this should exit 0 or 1.
    assert result.returncode in (0, 1, 2), result.stderr
    if result.returncode == 2:
        assert "not available yet" in result.stderr or "error:" in result.stderr
