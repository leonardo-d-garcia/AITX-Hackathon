"""Shared fixtures. Every test runs against a temporary store and the frozen synthetic design."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dronebench_api.service import ClaimEntry, ConfirmRequest, Workbench, build_workbench

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_B = ROOT / "fixtures" / "b"
FIXTURE_COMMON = ROOT / "fixtures" / "common"

DESIGN_ID = "dsn_parametric-fixedwing"

#: The harness mass the Inspect panel supplies. Its absence is what makes the baseline unknown.
HARNESS_MASS_KG = 0.045


@pytest.fixture
def workbench(tmp_path: Path) -> Workbench:
    bench = build_workbench(tmp_path / "store")
    yield bench
    bench.close()


@pytest.fixture
def imported(workbench: Workbench) -> tuple[Workbench, str]:
    """A design imported but not yet confirmed: units, frame, reconstruction all unconfirmed."""
    job = workbench.jobs.wait(workbench.import_fixture("b").job_id)
    assert job.status == "succeeded", job.error_message
    return workbench, workbench.active_revision(DESIGN_ID)


@pytest.fixture
def confirmed(imported: tuple[Workbench, str]) -> tuple[Workbench, str]:
    """Confirmed, with the harness mass supplied, so the checks can actually be computed."""
    workbench, _ = imported
    manifest = workbench.confirm(
        DESIGN_ID,
        ConfirmRequest(
            units_confirmed=True,
            frame_confirmed=True,
            reconstruction_confirmed=True,
            variant_decisions={},
            claim_entries=[
                ClaimEntry(
                    part_id="prt_harness",
                    quantity="mass_kg",
                    value=HARNESS_MASS_KG,
                    unit="kg",
                    source_kind="manual",
                    evidence_id="ev_fixture-spec",
                )
            ],
        ),
    )
    return workbench, manifest.revision.revision_id


@pytest.fixture
def reviewed(confirmed: tuple[Workbench, str]):
    """Confirmed, evaluated, and with previewed proposals ready for a decision."""
    workbench, revision_id = confirmed
    workbench.evaluate(revision_id)
    recommendations = workbench.recommend(revision_id)
    return workbench, revision_id, recommendations


def fixture_json(name: str) -> dict:
    base = FIXTURE_COMMON if name == "catalog" else FIXTURE_B
    return json.loads((base / f"{name}.json").read_text(encoding="utf-8"))
