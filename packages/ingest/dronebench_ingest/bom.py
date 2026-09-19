"""The curated demo BOM: bought components the archive does not contain.

Everything here is explicitly synthetic (see ``demo_bom.yaml``). Components enter the manifest as
``envelope`` occurrences with ``source_kind: catalog`` and ``status: estimated`` mass claims, an
assumed placement, and the file's own note attached to every claim. No supplier, price or stock
claim is produced, and nothing in this module reads the meshes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from dronebench_contracts.models import Claim, Evidence, SourceKind, Status

DEMO_BOM_PATH = Path(__file__).resolve().parent.parent / "demo_bom.yaml"
SYNTHETIC_NOTE = ("synthetic demo BOM entry: typical class hardware, not measured, not vendor data, "
                  "not derived from the STL archive")


def load_demo_bom(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path is not None else DEMO_BOM_PATH
    data = yaml.safe_load(p.read_text())
    if not data.get("synthetic"):
        raise ValueError(f"{p}: demo BOM must declare synthetic: true")
    return data


def bom_evidence(path: str | Path | None = None) -> Evidence:
    p = Path(path) if path is not None else DEMO_BOM_PATH
    import hashlib
    return Evidence(
        evidence_id="ev-demo-bom",
        uri=p.name,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        locator="components",
        method="curated_demo_bom",
        note=SYNTHETIC_NOTE,
    )


def _notes(entry: dict[str, Any]) -> list[str]:
    return [SYNTHETIC_NOTE, *entry.get("notes", [])]


def mass_claim(entry: dict[str, Any]) -> Claim:
    value = entry.get("mass_kg")
    if value is None:
        return Claim.unknown("kg", SYNTHETIC_NOTE, "no mass given for this component")
    return Claim(value=float(value), unit="kg", status=Status.estimated, source_kind=SourceKind.catalog,
                 evidence_ids=["ev-demo-bom"], assumptions=_notes(entry))


def function_claim(entry: dict[str, Any]) -> Claim:
    text: Optional[str] = entry.get("function")
    if not text:
        return Claim.unknown(None, SYNTHETIC_NOTE)
    return Claim(value=text, status=Status.estimated, source_kind=SourceKind.catalog,
                 evidence_ids=["ev-demo-bom"], assumptions=_notes(entry))


def com_claim(entry: dict[str, Any]) -> Claim:
    """Local COM of an envelope: its own centre, under an explicit uniform-distribution assumption."""
    return Claim(value=[0.0, 0.0, 0.0], unit="m", status=Status.estimated, source_kind=SourceKind.assumed,
                 evidence_ids=["ev-demo-bom"],
                 assumptions=[SYNTHETIC_NOTE,
                              "centre of mass assumed at the centre of the envelope; a real component's "
                              "COM is offset and is not determined by its box"])


def instances(entry: dict[str, Any]) -> list[tuple[str, list[float]]]:
    """(side, placement in FRD metres) per installed instance; paired entries mirror across y."""
    x, y, z = (float(v) for v in entry["placement_m"])
    sides = entry.get("sides")
    if sides:
        out = []
        for side in sides:
            sign = -1.0 if side == "left" else 1.0
            out.append((side, [x, sign * abs(y), z]))
        return out
    return [(entry.get("side", "center"), [x, y, z])]
