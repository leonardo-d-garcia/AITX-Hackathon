"""Shared fixtures for the A3 suite (store, operations, collisions).

Three of them, and they are the contract between the three A3 test modules:

``avenger_design``  session-scoped, the real vendor archive staged and confirmed **once** for the
                    whole suite (wing3_16mm_hole + fuse3_clean, mm, mirrored about x=0). Yields
                    ``(design_dir, revision)``. Skips when the git-ignored archive is absent.
``tiny_design``     function-scoped, three synthetic boxes staged and confirmed. Fast enough to use
                    in every transaction test; use this unless the test is *about* the Avenger.
``fake_build``      a factory for ``build`` callbacks that write small files and return a
                    ``BuildResult``. Store tests never reconstruct CAD.

The vendor archive is git-ignored and unlicensed: it is read in place, never copied into the repo.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

REPO = Path(__file__).resolve().parents[2]
for _pkg in ("packages/edits", "packages/ingest", "packages/contracts", "packages/cad"):
    _path = str(REPO / _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)

AVENGER = REPO / "vendor_assets" / "avenger"
# The 16 mm hole is the variant A3b's spar bound is measured against; fuse3_clean has no camera
# cutout, so nothing in the fuselage depends on an accessory that is not in the BOM.
AVENGER_SELECTION = {"wing3": "Wings/wing3_16mm_hole.stl", "fuse3": "Fuselage/fuse3_clean.stl"}

# Three boxes standing in for a wing panel, a fuselage and a tail fin. The names matter: ingest
# groups parts by filename stem, so a design with no "wing*" part has no wing stations to measure.
TINY_PARTS = {
    "wing3": {"extents": (600.0, 200.0, 24.0), "at": (400.0, 0.0, 0.0)},
    "fuse1": {"extents": (120.0, 900.0, 90.0), "at": (0.0, 100.0, 0.0)},
    "vtail1": {"extents": (90.0, 160.0, 120.0), "at": (0.0, 520.0, 60.0)},
}


@pytest.fixture(scope="session")
def avenger_selection() -> dict[str, str]:
    """The variant choices a user would make at confirmation, as {group_id: source_path}."""
    return dict(AVENGER_SELECTION)


@pytest.fixture(scope="session")
def avenger_design(tmp_path_factory) -> tuple[Path, Any]:
    """The real archive, staged and confirmed once for the whole session.

    Returns ``(design_dir, revision_manifest)``. Staging rehashes 11 MB of STL and confirming
    measures every station, so this runs exactly once — do not ask for a per-test copy of it.
    """
    if not AVENGER.is_dir():
        pytest.skip(f"vendor archive not present at {AVENGER}")
    from dronebench_ingest import confirm, stage_archive

    design_dir = tmp_path_factory.mktemp("avenger-design")
    stage_archive(AVENGER, design_dir)
    revision = confirm(design_dir, units="mm", variants=AVENGER_SELECTION, mirror="x=0",
                       mass_model="none", confirmed_by="pytest")
    return design_dir, revision


@pytest.fixture
def tiny_design(tmp_path) -> tuple[Path, Any]:
    """Three synthetic boxes, staged and confirmed. Returns ``(design_dir, revision_manifest)``.

    Function-scoped on purpose: transaction tests move the active pointer and write decision logs,
    and every one of them deserves a design nobody else has touched.
    """
    import trimesh
    from dronebench_ingest import confirm, stage_archive

    sources = tmp_path / "boxes"
    sources.mkdir()
    for name, spec in TINY_PARTS.items():
        mesh = trimesh.creation.box(extents=spec["extents"])
        mesh.apply_translation(spec["at"])
        mesh.export(sources / f"{name}.stl")

    design_dir = tmp_path / "design"
    stage_archive(sources, design_dir)
    revision = confirm(design_dir, units="mm", variants={}, mirror=False, mass_model="none",
                       confirmed_by="pytest")
    return design_dir, revision


@pytest.fixture
def fake_build() -> Callable[..., Callable[[Path], Any]]:
    """Factory for a ``build`` callback: ``fake_build(content=..., files=..., calls=[])``.

    The callback writes a couple of small files into the working directory it is handed and returns
    a ``BuildResult`` naming them, which is all the store needs — no CadQuery, no meshes. Pass a
    list as ``calls`` to count invocations (the idempotency tests do), or ``raises`` to make the
    build fail the way a blocked or crashed edit would.
    """
    from dronebench_contracts.models import Artifact, RoundTripCheck
    from dronebench_edits.api import BuildResult

    def factory(content: Optional[dict[str, Any]] = None,
                files: Optional[dict[str, str]] = None,
                calls: Optional[list[Path]] = None,
                raises: Optional[BaseException] = None,
                changes: Optional[list[dict[str, Any]]] = None,
                checks: Optional[list[RoundTripCheck]] = None,
                affected_part_ids: Optional[list[str]] = None) -> Callable[[Path], Any]:
        payload = {"operation": "demo", "parameters": {"delta_m": [0.02, 0.0, 0.0]}} \
            if content is None else content
        written = {"demo.step": "ISO-10303-21;\nDEMO;\nEND-ISO-10303-21;\n",
                   "part_map.json": '{"parts": ["p1"]}\n'} if files is None else files

        def build(workdir: Path):
            if calls is not None:
                calls.append(workdir)
            if raises is not None:
                raise raises
            artifacts = []
            for name, text in written.items():
                path = workdir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                media = "application/json" if name.endswith(".json") else "application/step"
                artifacts.append(Artifact(path=name, sha256="", media_type=media,
                                          representation="reconstruction"))
            return BuildResult(
                artifacts=artifacts,
                changes=changes if changes is not None else
                    [{"part_id": "p1", "field": "translation_m", "before": [0.0, 0.0, 0.0],
                      "after": [0.02, 0.0, 0.0], "unit": "m"}],
                checks=checks if checks is not None else
                    [RoundTripCheck(name="reimport", passed=True, detail="demo")],
                affected_part_ids=affected_part_ids if affected_part_ids is not None else ["p1"],
                content=payload,
            )

        return build

    return factory
