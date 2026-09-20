from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_C = REPO_ROOT / "fixtures" / "c"

FIXTURE_SCHEMA = {
    "design_manifest.json": "design_manifest",
    "parts.json": "parts",
    "parts_conflicted.json": "parts",
    "geometry_features.json": "geometry_features",
    "part_map.json": "part_map",
}


def fixture_json_files() -> list[Path]:
    files = sorted(FIXTURES_C.glob("*/*.json"))
    return [path for path in files if path.name in FIXTURE_SCHEMA]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def vtail_dir() -> Path:
    return FIXTURES_C / "synthetic_vtail_demo"


@pytest.fixture(scope="session")
def conventional_dir() -> Path:
    return FIXTURES_C / "conventional_tail_demo"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))
