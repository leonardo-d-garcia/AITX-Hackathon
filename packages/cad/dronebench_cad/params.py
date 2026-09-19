"""The editable parameter set for the reconstruction.

Everything the reconstruction knows how to change lives here, in SI units (metres, radians,
kilograms), in the canonical FRD frame (x forward, y right, z down, origin at the confirmed
nose datum). `reconstruct()` takes these and nothing else; A3's edit kernels mutate a copy of
this object and regenerate. Round-tripping through YAML is lossless, so the same file always
produces the same geometry.

Hardware that is not in the archive (spar, battery, motor, prop) is a **synthetic demo
envelope**: shape and placement are ours, mass is only present when someone put it there.
Nothing here is inferred from the meshes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "StationParams",
    "FuselageStationParams",
    "SurfaceParams",
    "SparParams",
    "BoxParams",
    "MotorParams",
    "ReconParams",
    "load_params",
    "dump_params",
    "DEFAULT_PARAMS_PATH",
]

DEFAULT_PARAMS_PATH = Path(__file__).with_name("params.yaml")


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StationParams(_P):
    """One lofted section of a lifting surface, root -> tip."""

    span_y_m: float                 # spanwise station (right side; the left side is mirrored)
    leading_edge_x_m: float
    chord_m: float
    z_m: float                      # mid-thickness height of the section, z down
    twist_rad: float = 0.0          # positive = leading edge up (wash-in)
    thickness_ratio: float = 0.12


class FuselageStationParams(_P):
    x_m: float
    width_m: float
    height_m: float
    z_center_m: float
    exponent: Optional[float] = None  # superellipse exponent; None -> ReconParams.fuselage_exponent


class SurfaceParams(_P):
    surface_id: str
    stations: list[StationParams]   # always given on the +y side, root -> tip
    build_side: Literal["right", "left"] = "right"
    mirror: bool = True             # also build the opposite occurrence, mirrored
    cant_rad: float = 0.0           # rotation of each section about the aircraft x axis
    camber: float = 0.04            # NACA 4-digit m
    camber_pos: float = 0.4         # NACA 4-digit p
    fit_thickness_envelope: bool = True
    """Scale each section so its z extent equals `thickness_ratio * chord`.

    The stations were measured as slice envelopes (top-to-bottom extent), not as a NACA
    thickness parameter, and adding camber inflates the envelope. Scaling makes the
    reconstruction reproduce what was measured; the shape assumption stays the same.
    """
    n_points_per_side: int = 41
    part_id_right: str = ""
    part_id_left: str = ""
    category: str = "wing"
    source_part_ids: list[str] = Field(default_factory=list)
    """Manifest part ids of the reference occurrences this one surface stands in for.

    A lofted whole-wing surrogate has no single manifest counterpart, so the reconstruction
    keeps its own `recon_*` id and records the reference ids here for traceability.
    """


class SparParams(_P):
    enabled: bool = True
    part_id: str = "recon_spar"
    outer_diameter_m: float = 0.016
    inner_diameter_m: float = 0.012
    span_m: float = 1.20            # tip-to-tip length of the tube
    x_m: float = -0.46              # tube axis position, FRD x
    z_m: float = -0.017
    mass_kg: Optional[float] = None
    material_note: str = "unknown; a tube is drawn, no material is claimed"


class BoxParams(_P):
    enabled: bool = True
    part_id: str = "recon_battery"
    length_m: float = 0.155         # along x
    width_m: float = 0.055          # along y
    height_m: float = 0.045         # along z
    center_m: list[float] = Field(default_factory=lambda: [-0.20, 0.0, -0.005])
    mass_kg: Optional[float] = None
    category: str = "battery"


class MotorParams(_P):
    enabled: bool = True
    part_id: str = "recon_motor"
    mount_part_id: str = "recon_motor_mount"
    prop_part_id: str = "recon_prop"
    x_m: float = -1.003             # aft face of the fuselage: this is a PUSHER
    z_m: float = 0.0
    diameter_m: float = 0.045
    length_m: float = 0.040
    mount_length_m: float = 0.012
    mount_size_m: float = 0.052
    prop_diameter_m: float = 0.305
    prop_thickness_m: float = 0.010
    prop_clearance_m: float = 0.012  # gap from the aft motor face to the disc
    mass_kg: Optional[float] = None
    prop_mass_kg: Optional[float] = None


class ReconParams(_P):
    """The complete editable parameter set. One file -> one aircraft."""

    schema_version: str = "0.1.0"
    design_id: str = "titan_avenger"
    revision_id: str = "recon-0001"
    source_features_revision_id: Optional[str] = None
    frame: str = "FRD"

    surfaces: list[SurfaceParams] = Field(default_factory=list)
    fuselage: list[FuselageStationParams] = Field(default_factory=list)
    fuselage_exponent: float = 2.0
    """Superellipse exponent of every fuselage section: |y/a|^n + |z/b|^n = 1.

    Assumed, not measured. Fitting it against the reference is unreliable because most
    fuselage meshes are open shells, so the sampled distance keeps improving as the section
    is driven toward a diamond — that is the metric seeing interior surfaces, not a better
    outline. 2.0 (a plain ellipse) is the simplest defensible choice.
    """
    fuselage_part_id: str = "recon_fuselage"
    fuselage_n_points: int = 48

    spar: SparParams = Field(default_factory=SparParams)
    battery: BoxParams = Field(default_factory=BoxParams)
    motor: MotorParams = Field(default_factory=MotorParams)

    wing_bay_plate_enabled: bool = True
    wing_bay_plate_part_id: str = "recon_wing_bay_plate"
    wing_bay_plate_extent_m: list[list[float]] = Field(
        default_factory=lambda: [[-0.5461, 0.5486, -0.0191], [-0.4835, 0.6976, -0.0078]]
    )

    tip_extension_m: float = 0.0        # A3's set_wing_tip_extension; stretches the outer panel
    assumptions: list[str] = Field(default_factory=list)

    # ---------------------------------------------------------------- construction
    @classmethod
    def from_features(cls, features: Any, **overrides: Any) -> "ReconParams":
        """Derive a starting parameter set from a GeometryFeatures object or dict."""
        data = features if isinstance(features, dict) else features.model_dump(mode="python")

        surfaces: list[SurfaceParams] = []
        for s in data["surfaces"]:
            sid = s["surface_id"]
            base = "vtail" if ("tail" in sid and "wing" not in sid) else "wing"
            stations = [
                StationParams(
                    span_y_m=st["span_y_m"],
                    leading_edge_x_m=st["leading_edge_x_m"],
                    chord_m=st["chord_m"],
                    z_m=st["z_m"],
                    twist_rad=st.get("twist_rad", 0.0) or 0.0,
                    thickness_ratio=st.get("thickness_ratio") or (0.12 if base == "wing" else 0.10),
                )
                for st in s["stations"]
            ]
            # A1 may hand over one symmetric surface ("wing") or an explicit pair
            # ("vtail_left", "vtail_right") whose stations are both given on the +y side.
            symmetric = bool(s.get("symmetric", True))
            side = "left" if sid.endswith("_left") else "right"
            mirror = symmetric  # an explicit left/right pair arrives with symmetric=False
            stem = sid.removesuffix("_left").removesuffix("_right")
            surfaces.append(
                SurfaceParams(
                    surface_id=sid,
                    stations=stations,
                    build_side=side,
                    mirror=mirror,
                    cant_rad=float(s.get("cant_rad") or 0.0),
                    camber=DEFAULTS_CAMBER_BY_SURFACE.get(base, 0.0),
                    camber_pos=0.4,
                    part_id_right=f"recon_{stem}_right",
                    part_id_left=f"recon_{stem}_left",
                    category=base,
                    source_part_ids=list(s.get("part_ids") or []),
                )
            )

        fuselage = [
            FuselageStationParams(
                x_m=f["x_m"], width_m=f["width_m"], height_m=f["height_m"],
                z_center_m=f["z_center_m"],
            )
            for f in data.get("fuselage", [])
        ]

        params = cls(
            design_id=data.get("design_id", "unknown"),
            source_features_revision_id=data.get("revision_id"),
            surfaces=surfaces,
            fuselage=fuselage,
            assumptions=[
                "Airfoil sections are an assumed NACA 4-digit family, not an identified section.",
                "Fuselage cross sections are superellipses fitted only to station width/height.",
                "Spar, battery, motor, prop and their masses are a synthetic demo envelope; "
                "none of them appear in the source archive.",
                "Holes, latches, hinges, print details and internal structure are not reconstructed.",
            ],
        )

        # Place the derived hardware relative to the measured wing.
        wing = next((s for s in params.surfaces if s.surface_id == "wing"), None)
        if wing and wing.stations:
            root, tip = wing.stations[0], wing.stations[-1]
            params.spar.x_m = round(root.leading_edge_x_m - 0.30 * root.chord_m, 5)
            params.spar.z_m = round(root.z_m, 5)
            params.spar.span_m = round(1.1 * tip.span_y_m, 5)
        if params.fuselage:
            aft = min(f["x_m"] if isinstance(f, dict) else f.x_m for f in params.fuselage)
            params.motor.x_m = round(aft - 0.012, 5)

        for key, value in overrides.items():
            setattr(params, key, value)
        return params


DEFAULTS_CAMBER_BY_SURFACE = {"wing": 0.04, "vtail": 0.0}  # a V-tail panel is symmetric


def load_params(path: str | Path) -> ReconParams:
    with open(path, "r", encoding="utf-8") as fh:
        return ReconParams.model_validate(yaml.safe_load(fh))


def dump_params(params: ReconParams, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = params.model_dump(mode="python")
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, default_flow_style=False), encoding="utf-8"
    )
    return path
