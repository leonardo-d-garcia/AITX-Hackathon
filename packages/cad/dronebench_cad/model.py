"""The in-memory reconstruction: named solids plus the parameters that produced them."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import cadquery as cq

from .params import ReconParams

__all__ = ["ReconPart", "CadModel", "MM", "to_m", "to_m3"]

MM = 1000.0  # the model is built in millimetres; the API speaks metres


def to_m(v: float) -> float:
    return v / MM


def to_m3(v: float) -> float:
    return v / (MM**3)


@dataclass
class ReconPart:
    """One named solid of the editable representation.

    `representation` is always `"reconstruction"` or `"envelope"`: nothing in this package
    is the manufacturer's geometry, and the label travels with the part into part_map.json,
    the STEP labels and the GLB node names.
    """

    part_id: str
    name: str
    category: str
    solid: cq.Solid
    representation: str = "reconstruction"
    parameters: dict[str, Any] = field(default_factory=dict)
    side: Optional[str] = None
    mirror_of: Optional[str] = None
    color: tuple[float, float, float, float] = (0.68, 0.72, 0.78, 1.0)
    notes: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- measurements (SI)
    def volume_m3(self) -> float:
        return to_m3(self.solid.Volume())

    def bounds_m(self) -> list[list[float]]:
        bb = self.solid.BoundingBox()
        return [
            [to_m(bb.xmin), to_m(bb.ymin), to_m(bb.zmin)],
            [to_m(bb.xmax), to_m(bb.ymax), to_m(bb.zmax)],
        ]

    def centroid_m(self) -> list[float]:
        c = self.solid.Center()
        return [to_m(c.x), to_m(c.y), to_m(c.z)]

    def is_valid(self) -> bool:
        return bool(self.solid.isValid())


@dataclass
class CadModel:
    """A regenerated aircraft: the parts, the parameters, and where they came from."""

    design_id: str
    revision_id: str
    params: ReconParams
    parts: list[ReconPart]
    source_features_revision_id: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    build_seconds: Optional[float] = None

    def __post_init__(self) -> None:
        ids = [p.part_id for p in self.parts]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate part_id in reconstruction: {sorted(dupes)}")

    def part(self, part_id: str) -> ReconPart:
        for p in self.parts:
            if p.part_id == part_id:
                return p
        raise KeyError(part_id)

    def assembly(self, scale: float = 1.0) -> cq.Assembly:
        """A CadQuery assembly with one named child per part (never fused).

        `scale` is applied to the geometry, not to a placement, so a scaled assembly is a
        separate export-only copy (the GLB is written in metres, the STEP in millimetres).
        """
        assy = cq.Assembly(name=f"{self.design_id}_reconstruction")
        for p in self.parts:
            solid = p.solid if scale == 1.0 else p.solid.scale(scale)
            assy.add(solid, name=p.part_id, color=cq.Color(*p.color))
        return assy

    def volumes_m3(self) -> dict[str, float]:
        return {p.part_id: p.volume_m3() for p in self.parts}

    def bounds_m(self) -> list[list[float]]:
        bb = None
        for p in self.parts:
            b = p.solid.BoundingBox()
            bb = b if bb is None else bb.add(b)
        assert bb is not None
        return [
            [to_m(bb.xmin), to_m(bb.ymin), to_m(bb.zmin)],
            [to_m(bb.xmax), to_m(bb.ymax), to_m(bb.zmax)],
        ]

    def part_map(self) -> dict[str, Any]:
        """The sidecar the round-trip check verifies the STEP against."""
        return {
            "schema_version": "0.1.0",
            "design_id": self.design_id,
            "revision_id": self.revision_id,
            "source_features_revision_id": self.source_features_revision_id,
            "frame": "FRD",
            "units": "m",
            "step_units": "mm",
            "representation": "reconstruction",
            "label": "Editable reconstruction — not the original Titan CAD",
            "parts": [
                {
                    "part_id": p.part_id,
                    "name": p.name,
                    "category": p.category,
                    "representation": p.representation,
                    "side": p.side,
                    "mirror_of": p.mirror_of,
                    "step_name": p.part_id,
                    "glb_node": p.part_id,
                    "volume_m3": p.volume_m3(),
                    "bounds_m": p.bounds_m(),
                    "centroid_m": p.centroid_m(),
                    "parameters": p.parameters,
                    "notes": p.notes,
                }
                for p in self.parts
            ],
            "warnings": self.warnings,
        }
