"""Pytest fixtures wrapping the assumed inline aircraft dicts."""

from __future__ import annotations

import pytest

from tests.physics.aircraft import default_mission, default_parts, vtail_geometry


@pytest.fixture
def geometry():
    return vtail_geometry()


@pytest.fixture
def parts():
    return default_parts()


@pytest.fixture
def mission():
    return default_mission()
