"""Build the editable aircraft from measured stations plus declared assumptions.

This is the *reconstruction* of the two mandatory representations (architecture §2). It is
never the manufacturer's CAD: the sections are assumed, the fuselage is a station envelope,
and the spar/battery/motor/prop do not exist in the source archive at all.

Everything is built in millimetres (OCCT behaves better away from 1e-3-sized coordinates
and STEP is written in mm); the API and every reported number are in metres.
"""
from __future__ import annotations

import math
import time
from typing import Any, Optional

import cadquery as cq

from .airfoil import naca4_points
from .model import MM, CadModel, ReconPart
from .params import ReconParams, StationParams, SurfaceParams

__all__ = ["reconstruct", "DEFAULT_PART_IDS"]

DEFAULT_PART_IDS = {
    "wing_right": "recon_wing_right",
    "wing_left": "recon_wing_left",
    "vtail_right": "recon_vtail_right",
    "vtail_left": "recon_vtail_left",
    "fuselage": "recon_fuselage",
    "spar": "recon_spar",
    "battery": "recon_battery",
    "motor": "recon_motor",
    "motor_mount": "recon_motor_mount",
    "prop": "recon_prop",
    "wing_bay_plate": "recon_wing_bay_plate",
}

_COLORS = {
    "wing": (0.60, 0.68, 0.80, 1.0),
    "vtail": (0.55, 0.72, 0.68, 1.0),
    "fuselage": (0.78, 0.78, 0.80, 1.0),
    "spar": (0.30, 0.30, 0.34, 1.0),
    "battery": (0.85, 0.65, 0.25, 1.0),
    "motor": (0.35, 0.35, 0.40, 1.0),
    "mount": (0.70, 0.55, 0.45, 1.0),
    "prop": (0.40, 0.45, 0.55, 0.5),
    "plate": (0.72, 0.70, 0.62, 1.0),
}


# ---------------------------------------------------------------- lifting surfaces

def _effective_stations(surface: SurfaceParams, tip_extension_m: float) -> list[StationParams]:
    """Stations after the tip-extension parameter, root -> tip, strictly increasing in y."""
    stations = [s.model_copy(deep=True) for s in surface.stations]
    if tip_extension_m and surface.category == "wing" and len(stations) >= 2:
        stations[-1].span_y_m += tip_extension_m
    ys = [s.span_y_m for s in stations]
    if any(b <= a for a, b in zip(ys, ys[1:])):
        raise ValueError(f"{surface.surface_id}: stations must increase in span_y_m, got {ys}")
    return stations


def _station_wire(station: StationParams, surface: SurfaceParams) -> cq.Wire:
    """One closed section wire, in the plane y = station.span_y_m, in millimetres.

    The section is generated in the same plane the measurement sliced, so a canted panel is
    reproduced by scaling the section thickness by 1/cos(cant) rather than by rotating the
    wire out of its measurement plane. `twist_rad` rotates the chord about the leading edge,
    positive leading-edge-up.
    """
    chord = station.chord_m * MM
    if chord <= 0:
        raise ValueError(f"{surface.surface_id}: non-positive chord at y={station.span_y_m}")
    pts2d = naca4_points(
        thickness=station.thickness_ratio,
        camber=surface.camber,
        camber_pos=surface.camber_pos,
        n_per_side=surface.n_points_per_side,
    )
    if surface.fit_thickness_envelope:
        hs = [h for _, h in pts2d]
        extent = max(hs) - min(hs)
        mid = (max(hs) + min(hs)) / 2
        k = station.thickness_ratio / extent
        pts2d = [(u, (h - mid) * k) for u, h in pts2d]

    cant_stretch = 1.0 / math.cos(surface.cant_rad) if surface.cant_rad else 1.0
    ct, st = math.cos(station.twist_rad), math.sin(station.twist_rad)
    le_x, y, z = station.leading_edge_x_m * MM, station.span_y_m * MM, station.z_m * MM

    verts = []
    for u, h in pts2d:
        aft, up = u * chord, h * chord * cant_stretch
        aft_r = aft * ct + up * st
        up_r = -aft * st + up * ct
        verts.append(cq.Vector(le_x - aft_r, y, z - up_r))  # z is DOWN, so "up" subtracts
    return cq.Wire.makePolygon(verts, close=True)


def _loft_surface(
    surface: SurfaceParams, tip_extension_m: float
) -> tuple[cq.Solid, list[StationParams]]:
    stations = _effective_stations(surface, tip_extension_m)
    wires = [_station_wire(s, surface) for s in stations]
    solid = cq.Solid.makeLoft(wires, ruled=True)
    return solid, stations


def _mirror_y(solid: cq.Solid) -> cq.Solid:
    """Mirror a solid about the aircraft centre plane.

    Mirroring is a change to the geometry definition (with the orientation repaired), never
    a placement — placements in this project stay proper rotations, per the contract.
    """
    mirrored = solid.mirror("XZ")
    if mirrored.Volume() < 0:
        mirrored = mirrored.copy()
        mirrored.wrapped.Reverse()
    return cq.Solid(mirrored.wrapped)


# ---------------------------------------------------------------- fuselage

def _superellipse_wire(
    x_m: float, half_w_m: float, half_h_m: float, z_c_m: float, exponent: float, n: int
) -> cq.Wire:
    a, b, zc, x = half_w_m * MM, half_h_m * MM, z_c_m * MM, x_m * MM
    a, b = max(a, 1e-3), max(b, 1e-3)
    verts = []
    for i in range(n):
        t = 2.0 * math.pi * i / n
        ct, st = math.cos(t), math.sin(t)
        y = math.copysign(abs(ct) ** (2.0 / exponent), ct) * a
        z = math.copysign(abs(st) ** (2.0 / exponent), st) * b
        verts.append(cq.Vector(x, y, zc + z))
    return cq.Wire.makePolygon(verts, close=True)


def _loft_fuselage(params: ReconParams) -> cq.Solid:
    stations = sorted(params.fuselage, key=lambda f: -f.x_m)  # nose (x=0) first, tail last
    if len(stations) < 2:
        raise ValueError("fuselage needs at least two stations")
    wires = [
        _superellipse_wire(
            f.x_m, f.width_m / 2, f.height_m / 2, f.z_center_m,
            f.exponent or params.fuselage_exponent, params.fuselage_n_points,
        )
        for f in stations
    ]
    return cq.Solid.makeLoft(wires, ruled=True)


# ---------------------------------------------------------------- hardware envelopes

def _tube(outer_d_m: float, inner_d_m: float, length_m: float, x_m: float, z_m: float) -> cq.Solid:
    if inner_d_m >= outer_d_m:
        raise ValueError(f"spar inner diameter {inner_d_m} >= outer {outer_d_m}")
    origin = cq.Vector(x_m * MM, -length_m * MM / 2, z_m * MM)
    axis = cq.Vector(0, 1, 0)
    outer = cq.Solid.makeCylinder(outer_d_m * MM / 2, length_m * MM, origin, axis)
    if inner_d_m <= 0:
        return outer
    inner = cq.Solid.makeCylinder(inner_d_m * MM / 2, length_m * MM, origin, axis)
    return cq.Solid(outer.cut(inner).wrapped)


def _box(center_m: list[float], dims_m: list[float]) -> cq.Solid:
    l, w, h = (d * MM for d in dims_m)
    cx, cy, cz = (c * MM for c in center_m)
    return cq.Solid.makeBox(l, w, h, cq.Vector(cx - l / 2, cy - w / 2, cz - h / 2))


# ---------------------------------------------------------------- entry point

def reconstruct(
    features: Any = None,
    params: Optional[ReconParams] = None,
    part_ids: Optional[dict[str, str]] = None,
) -> CadModel:
    """Regenerate the editable aircraft.

    Pass `features` (a `GeometryFeatures` model or its dict) to derive a starting parameter
    set, `params` to build from an exact parameter set, or both (params wins; features then
    only supply provenance). `part_ids` maps the logical keys in `DEFAULT_PART_IDS` onto
    manifest part ids where the manifest has one.
    """
    if params is None:
        if features is None:
            raise ValueError("reconstruct() needs features, params, or both")
        params = ReconParams.from_features(features)

    ids = dict(DEFAULT_PART_IDS)
    ids.update(part_ids or {})
    started = time.perf_counter()
    parts: list[ReconPart] = []
    warnings: list[str] = []

    for surface in params.surfaces:
        base = surface.category  # "wing" | "vtail"
        lofted, stations = _loft_surface(surface, params.tip_extension_m)

        # Surface ids come from the parameters; `part_ids` only overrides them, by logical
        # key ("wing_right") or by the default id itself.
        overrides = part_ids or {}

        def resolve(key: str, default: str) -> str:
            return overrides.get(key) or overrides.get(default) or default

        right_id = resolve(f"{base}_right", surface.part_id_right or f"recon_{base}_right")
        left_id = resolve(f"{base}_left", surface.part_id_left or f"recon_{base}_left")
        primary_side = surface.build_side
        primary_id = right_id if primary_side == "right" else left_id
        other_side = "left" if primary_side == "right" else "right"
        other_id = left_id if primary_side == "right" else right_id
        primary_solid = lofted if primary_side == "right" else _mirror_y(lofted)

        shared = {
            "surface_id": surface.surface_id,
            "airfoil": f"NACA 4-digit, camber m={surface.camber}, p={surface.camber_pos} (assumed)",
            "cant_rad": surface.cant_rad,
            "tip_extension_m": params.tip_extension_m if base == "wing" else 0.0,
            "source_part_ids": list(surface.source_part_ids),
            "stations": [s.model_dump() for s in stations],
        }
        notes = [
            "Airfoil is a declared assumption; no section was identified from the meshes.",
            "Control surfaces (aileron, taileron) are included in the parent surface, not split.",
        ]
        mirror_note = "Mirrored geometry definition; the placement stays identity."
        parts.append(
            ReconPart(
                part_id=primary_id, name=f"{surface.surface_id} ({primary_side})", category=base,
                solid=primary_solid, side=primary_side,
                parameters=shared if primary_side == "right" else {**shared, "mirrored_about": "y=0"},
                color=_COLORS.get(base, _COLORS["wing"]),
                notes=notes + ([] if primary_side == "right" else [mirror_note]),
            )
        )
        if surface.mirror:
            parts.append(
                ReconPart(
                    part_id=other_id, name=f"{surface.surface_id} ({other_side})", category=base,
                    solid=_mirror_y(primary_solid),
                    parameters={**shared, "mirrored_about": "y=0"},
                    side=other_side, mirror_of=primary_id,
                    color=_COLORS.get(base, _COLORS["wing"]),
                    notes=notes + [mirror_note],
                )
            )

    if params.fuselage:
        parts.append(
            ReconPart(
                part_id=ids["fuselage"], name="fuselage envelope", category="fuselage",
                solid=_loft_fuselage(params), side="center", color=_COLORS["fuselage"],
                parameters={
                    "superellipse_exponent": params.fuselage_exponent,
                    "n_points": params.fuselage_n_points,
                    "stations": [f.model_dump() for f in params.fuselage],
                },
                notes=[
                    "A lofted station envelope, not the printed fuselage: no hatches, canopy "
                    "split lines, latches, camera pod or internal structure.",
                ],
            )
        )

    sp = params.spar
    if sp.enabled:
        parts.append(
            ReconPart(
                part_id=ids.get("spar", sp.part_id), name="wing spar tube", category="spar",
                solid=_tube(sp.outer_diameter_m, sp.inner_diameter_m, sp.span_m, sp.x_m, sp.z_m),
                representation="envelope", side="center", color=_COLORS["spar"],
                parameters={
                    "outer_diameter_m": sp.outer_diameter_m,
                    "inner_diameter_m": sp.inner_diameter_m,
                    "span_m": sp.span_m, "x_m": sp.x_m, "z_m": sp.z_m,
                    "mass_kg": sp.mass_kg,
                },
                notes=["No spar exists in the source archive. " + sp.material_note],
            )
        )

    bat = params.battery
    if bat.enabled:
        parts.append(
            ReconPart(
                part_id=ids.get("battery", bat.part_id), name="battery envelope",
                category=bat.category,
                solid=_box(bat.center_m, [bat.length_m, bat.width_m, bat.height_m]),
                representation="envelope", side="center", color=_COLORS["battery"],
                parameters={
                    "length_m": bat.length_m, "width_m": bat.width_m, "height_m": bat.height_m,
                    "center_m": list(bat.center_m), "mass_kg": bat.mass_kg,
                },
                notes=["Synthetic demo envelope; mass only if a curated BOM supplied one."],
            )
        )

    mt = params.motor
    if mt.enabled:
        motor_origin = cq.Vector(mt.x_m * MM, 0.0, mt.z_m * MM)
        parts.append(
            ReconPart(
                part_id=ids.get("motor", mt.part_id), name="motor envelope (pusher)",
                category="motor",
                solid=cq.Solid.makeCylinder(
                    mt.diameter_m * MM / 2, mt.length_m * MM, motor_origin, cq.Vector(-1, 0, 0)
                ),
                representation="envelope", side="center", color=_COLORS["motor"],
                parameters={
                    "diameter_m": mt.diameter_m, "length_m": mt.length_m,
                    "x_m": mt.x_m, "z_m": mt.z_m, "mass_kg": mt.mass_kg,
                    "configuration": "pusher (aft of the fuselage, per motor_mount at the tail)",
                },
                notes=["Synthetic demo envelope; no motor is present in the source archive."],
            )
        )
        parts.append(
            ReconPart(
                part_id=ids.get("motor_mount", mt.mount_part_id), name="motor mount block",
                category="mount",
                solid=_box(
                    [mt.x_m + mt.mount_length_m / 2, 0.0, mt.z_m],
                    [mt.mount_length_m, mt.mount_size_m, mt.mount_size_m],
                ),
                side="center", color=_COLORS["mount"],
                parameters={
                    "mount_length_m": mt.mount_length_m, "mount_size_m": mt.mount_size_m,
                    "x_m": mt.x_m, "z_m": mt.z_m,
                },
                notes=["A simplified block at the tail; the printed mount's bolt pattern, "
                       "cooling cutouts and fillets are not reconstructed."],
            )
        )
        prop_x = mt.x_m - mt.length_m - mt.prop_clearance_m
        parts.append(
            ReconPart(
                part_id=ids.get("prop", mt.prop_part_id), name="propeller swept envelope",
                category="prop",
                solid=cq.Solid.makeCylinder(
                    mt.prop_diameter_m * MM / 2, mt.prop_thickness_m * MM,
                    cq.Vector(prop_x * MM, 0.0, mt.z_m * MM), cq.Vector(-1, 0, 0),
                ),
                representation="envelope", side="center", color=_COLORS["prop"],
                parameters={
                    "prop_diameter_m": mt.prop_diameter_m,
                    "prop_thickness_m": mt.prop_thickness_m,
                    "x_m": prop_x, "z_m": mt.z_m, "mass_kg": mt.prop_mass_kg,
                },
                notes=["Swept disc, not blade geometry; used for clearance checks only."],
            )
        )

    if params.wing_bay_plate_enabled:
        (x0, y0, z0), (x1, y1, z1) = params.wing_bay_plate_extent_m
        parts.append(
            ReconPart(
                part_id=ids.get("wing_bay_plate", params.wing_bay_plate_part_id),
                name="wing bay plate", category="mount",
                solid=_box(
                    [(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2],
                    [abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)],
                ),
                side="right", color=_COLORS["plate"],
                parameters={"extent_m": params.wing_bay_plate_extent_m},
                notes=["Bounding-box stand-in for the printed plate; one occurrence only, "
                       "matching the single source part."],
            )
        )

    if params.tip_extension_m:
        warnings.append(
            f"tip_extension_m={params.tip_extension_m} m applied to the outermost wing station; "
            "the spar span was not changed automatically."
        )

    model = CadModel(
        design_id=params.design_id,
        revision_id=params.revision_id,
        params=params,
        parts=parts,
        source_features_revision_id=params.source_features_revision_id,
        warnings=warnings
        + [
            "Editable reconstruction of the Avenger reference meshes. Not the original CAD.",
            *params.assumptions,
        ],
    )
    model.build_seconds = time.perf_counter() - started
    return model
