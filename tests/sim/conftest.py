from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim import simulate_mission

REPO_ROOT = Path(__file__).resolve().parents[2]
FALLBACK_PATH = REPO_ROOT / "fixtures" / "c" / "synthetic_vtail_demo" / "simulation_run.json"
SYNTHETIC_GEOMETRY = {
    "S": 0.4,
    "b": 2.2,
    "c": 0.2,
    "cant": 0.6981317007977318,
}
SYNTHETIC_PARTS = [{"id": "spar_L", "type": "spar"}]


@pytest.fixture(scope="session")
def fallback_path() -> Path:
    return FALLBACK_PATH


@pytest.fixture(scope="session")
def fallback_run(fallback_path: Path) -> dict:
    with fallback_path.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture(scope="session")
def live_run() -> dict:
    return simulate_mission(SYNTHETIC_GEOMETRY, SYNTHETIC_PARTS)
