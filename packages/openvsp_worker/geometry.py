"""Unwrap geometry_features.json claims into an OpenVSP build spec.

Does not import openvsp. Reference S/b/c are taken once from geometry.reference.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

# Task C4 sweep. Not read from the fixture (fixture has no alpha grid).
ALPHAS_DEG: tuple[float, ...] = (-2.0, 0.0, 2.0, 4.0, 6.0)

# geometry_features.json is FRD (+X forward, +Y right, +Z down).
# OpenVSP aircraft axes are +X aft, +Y right, +Z up.
def frd_xyz_to_openvsp(x_frd: float, y_frd: float, z_frd: float) -> tuple[float, float, float]:
    return (-float(x_frd), float(y_frd), -float(z_frd))


class GeometryError(ValueError):
    """Missing or unusable geometry_features field."""


def is_claim(obj: Any) -> bool:
    return isinstance(obj, dict) and "value" in obj and "status" in obj


def claim_value(obj: Any, path: str) -> Any:
    """Unwrap a Claim object. Unknown/null is an error here (C4 cannot invent)."""
    if is_claim(obj):
        status = obj.get("status")
        value = obj.get("value")
        if status == "unknown" or value is None:
            raise GeometryError(f"{path} is unknown/null; C4 will not invent it")
        return value
    return obj


def require_float(obj: Any, path: str) -> float:
    value = claim_value(obj, path)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise GeometryError(f"{path} is not a float: {value!r}") from exc
    if not math.isfinite(out):
        raise GeometryError(f"{path} is not finite: {value!r}")
    return out


def require_int(obj: Any, path: str) -> int:
    value = require_float(obj, path)
    if abs(value - round(value)) > 1e-9:
        raise GeometryError(f"{path} is not an integer: {value!r}")
    return int(round(value))


@dataclass(frozen=True)
class Station:
    y_m: float
    x_le_frd_m: float
    chord_m: float
    z_frd_m: float
    twist_rad: float
    x_le_vsp_m: float
    z_vsp_m: float
    twist_deg: float


@dataclass(frozen=True)
class WingSection:
    """One OpenVSP wing section (inboard station -> outboard station), VSP axes."""

    index: int
    span_m: float
    sweep_deg: float
    dihedral_deg: float
    twist_out_deg: float
    root_chord_m: float
    tip_chord_m: float
    y_in_m: float
    y_out_m: float


@dataclass(frozen=True)
class GeometrySpec:
    sref_m2: float
    bref_m: float
    cref_m: float
    stations: tuple[Station, ...]
    sections: tuple[WingSection, ...]
    cant_rad: float
    cant_deg: float
    panel_count: int
    panel_area_m2: float
    panel_span_m: float
    panel_chord_m: float
    tail_arm_m: float
    vinf_mps: float
    altitude_m: float
    rho_kgm3: float
    alphas_deg: tuple[float, ...]
    frame: str
    wing_x_rel_m: float
    wing_z_rel_m: float
    tail_x_rel_m: float
    symmetry: str
    airfoil: str
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_spec(geometry: dict[str, Any]) -> GeometrySpec:
    if not isinstance(geometry, dict):
        raise GeometryError("geometry_features must be an object")
    frame = str(geometry.get("frame") or "")
    if frame != "FRD":
        raise GeometryError(f"geometry.frame must be FRD, got {frame!r}")

    ref = geometry.get("reference")
    if not isinstance(ref, dict):
        raise GeometryError("geometry.reference is missing")
    sref = require_float(ref.get("S_m2"), "geometry.reference.S_m2")
    bref = require_float(ref.get("b_m"), "geometry.reference.b_m")
    cref = require_float(ref.get("c_m"), "geometry.reference.c_m")

    raw_stations = geometry.get("wing_stations")
    if not isinstance(raw_stations, list) or len(raw_stations) < 2:
        raise GeometryError("geometry.wing_stations must have at least two stations")
    stations = tuple(_parse_station(item, i) for i, item in enumerate(raw_stations))
    ys = [s.y_m for s in stations]
    if any(y < -1e-12 for y in ys):
        raise GeometryError("wing_stations must be RIGHT wing (span_y_m >= 0)")
    if abs(ys[0]) > 1e-9:
        raise GeometryError(f"first wing station span_y_m must be 0 (root), got {ys[0]}")
    if any(ys[i] >= ys[i + 1] for i in range(len(ys) - 1)):
        raise GeometryError("wing_stations span_y_m must be strictly increasing")

    sections = tuple(_sections_from_stations(stations))
    half_span = stations[-1].y_m
    if abs(2.0 * half_span - bref) > 1e-6:
        # Not fatal: bref is the VSPAERO reference span, set independently.
        span_note = (
            f"2*tip_y={2.0 * half_span} m vs reference.b_m={bref} m; "
            "bref is still set from reference.b_m exactly once"
        )
    else:
        span_note = f"2*tip_y={2.0 * half_span} m matches reference.b_m"

    tail = geometry.get("tail")
    if not isinstance(tail, dict):
        raise GeometryError("geometry.tail is missing")
    layout = tail.get("layout")
    if layout != "vtail":
        raise GeometryError(f"C4 generate requires tail.layout=vtail, got {layout!r}")
    cant_rad = require_float(tail.get("cant_rad"), "geometry.tail.cant_rad")
    panel_count = require_int(tail.get("panel_count"), "geometry.tail.panel_count")
    if panel_count != 2:
        raise GeometryError(f"vtail panel_count must be 2, got {panel_count}")
    panel_area = require_float(tail.get("panel_area_m2"), "geometry.tail.panel_area_m2")
    panel_span = require_float(tail.get("panel_span_m"), "geometry.tail.panel_span_m")
    if panel_span <= 0.0:
        raise GeometryError("geometry.tail.panel_span_m must be > 0")
    tail_arm = require_float(tail.get("tail_arm_m"), "geometry.tail.tail_arm_m")
    panel_chord = panel_area / panel_span

    mission = geometry.get("mission")
    if not isinstance(mission, dict):
        raise GeometryError("geometry.mission is missing")
    vinf = require_float(mission.get("cruise_mps"), "geometry.mission.cruise_mps")
    altitude = require_float(mission.get("altitude_m"), "geometry.mission.altitude_m")
    rho = require_float(mission.get("rho_kgm3"), "geometry.mission.rho_kgm3")

    root = stations[0]
    notes = (
        "OpenVSP WING + V-tail use geom Sym_Planar_Flag=SYM_XZ (left side is the XZ mirror).",
        "Airfoil is the OpenVSP WING default four-series (t/c=0.10, camber=0); geometry_features.json has no airfoil.",
        "VSPAEROSweep AlphaStart/AlphaEnd are degrees on OpenVSP 3.51.3 (defaults 0 and 10; shipped tests pass 1.0 deg).",
        "Sref/bref/cref are set once on VSPAEROSweep with RefFlag=MANUAL_REF. Not copied onto WingGeom TotalArea/TotalSpan.",
        "V-tail root LE is at X_vsp=tail_arm_m (aft of model origin). No extra AC offset is applied.",
        "MachStart=0 (incompressible). Vinf and Rho come from the fixture. Speed of sound is not in the fixture.",
        "Panel chord = panel_area_m2 / panel_span_m (rectangular; fixture has no tail taper).",
        span_note,
    )
    return GeometrySpec(
        sref_m2=sref,
        bref_m=bref,
        cref_m=cref,
        stations=stations,
        sections=sections,
        cant_rad=cant_rad,
        cant_deg=math.degrees(cant_rad),
        panel_count=panel_count,
        panel_area_m2=panel_area,
        panel_span_m=panel_span,
        panel_chord_m=panel_chord,
        tail_arm_m=tail_arm,
        vinf_mps=vinf,
        altitude_m=altitude,
        rho_kgm3=rho,
        alphas_deg=ALPHAS_DEG,
        frame=frame,
        wing_x_rel_m=root.x_le_vsp_m,
        wing_z_rel_m=root.z_vsp_m,
        tail_x_rel_m=tail_arm,
        symmetry="openvsp_SYM_XZ",
        airfoil="openvsp_wing_default_four_series_tc0.10_camber0",
        notes=notes,
    )


def _parse_station(item: Any, index: int) -> Station:
    if not isinstance(item, dict):
        raise GeometryError(f"geometry.wing_stations[{index}] must be an object")
    y = require_float(item.get("span_y_m"), f"geometry.wing_stations[{index}].span_y_m")
    x_frd = require_float(
        item.get("leading_edge_x_m"), f"geometry.wing_stations[{index}].leading_edge_x_m"
    )
    chord = require_float(item.get("chord_m"), f"geometry.wing_stations[{index}].chord_m")
    z_frd = require_float(item.get("z_m"), f"geometry.wing_stations[{index}].z_m")
    twist = require_float(item.get("twist_rad"), f"geometry.wing_stations[{index}].twist_rad")
    if chord <= 0.0:
        raise GeometryError(f"geometry.wing_stations[{index}].chord_m must be > 0")
    x_vsp, _y_vsp, z_vsp = frd_xyz_to_openvsp(x_frd, y, z_frd)
    return Station(
        y_m=y,
        x_le_frd_m=x_frd,
        chord_m=chord,
        z_frd_m=z_frd,
        twist_rad=twist,
        x_le_vsp_m=x_vsp,
        z_vsp_m=z_vsp,
        twist_deg=math.degrees(twist),
    )


def _sections_from_stations(stations: tuple[Station, ...]) -> list[WingSection]:
    out: list[WingSection] = []
    for i in range(1, len(stations)):
        a = stations[i - 1]
        b = stations[i]
        dy = b.y_m - a.y_m
        dz = b.z_vsp_m - a.z_vsp_m
        dx = b.x_le_vsp_m - a.x_le_vsp_m
        span = math.hypot(dy, dz)
        if span <= 0.0:
            raise GeometryError(f"wing section {i} has zero YZ length")
        # Sweep_Location=0 (LE). atan2(dX_aft, dY) in OpenVSP axes.
        sweep_deg = math.degrees(math.atan2(dx, dy))
        dihedral_deg = math.degrees(math.atan2(dz, dy))
        out.append(
            WingSection(
                index=i,
                span_m=span,
                sweep_deg=sweep_deg,
                dihedral_deg=dihedral_deg,
                twist_out_deg=b.twist_deg,
                root_chord_m=a.chord_m,
                tip_chord_m=b.chord_m,
                y_in_m=a.y_m,
                y_out_m=b.y_m,
            )
        )
    return out


def geometry_hash(geometry: dict[str, Any]) -> str:
    """sha256 of canonical sorted geometry JSON. Matches evaluate.hashing.geometry_hash."""
    try:
        from evaluate.hashing import geometry_hash as _hash
    except Exception:  # noqa: BLE001
        import hashlib
        import json

        return hashlib.sha256(
            json.dumps(geometry, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
                "utf-8"
            )
        ).hexdigest()
    return _hash(geometry)
