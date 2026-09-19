"""Measured geometry: wing and V-tail stations, reference areas, fuselage envelope.

Everything here is measured in the **confirmed** FRD frame (x forward from the nose datum, y right,
z down, metres) by slicing the placed reference meshes. Nothing is published from an unconfirmed
frame or an unresolved variant: those calls return an ``ErrorEnvelope`` instead.

How area avoids double counting (architecture §6.6): a station's chord is the *x extent of the
merged section* of every body in the group at that station. Upper and lower skins of one printed
shell, adjacent print sections, and the aileron all contribute to the same section, so each
contributes at most its share of one chord. One side is measured and the planform is doubled; the
mirrored occurrences are never sliced a second time.

The V-tail is two canted panels. The horizontal and vertical *projections* are reported so a
conventional-tail formula can be applied knowingly, but no tail volume coefficient is computed here:
this aircraft has no conventional horizontal or vertical tail.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import trimesh

from dronebench_contracts.models import (
    SCHEMA_VERSION, Claim, DesignManifest, ErrorEnvelope, FuselageStation, GeometryFeatures,
    LiftingSurface, SourceKind, Status, WingStation,
)

from .assembly import placed_mesh
from .errors import assembly_unconfirmed, units_unconfirmed
from .variants import selection_errors

WING_CATEGORIES = ("wing", "aileron")
VTAIL_CATEGORIES = ("vtail", "ruddervator")
FUSELAGE_CATEGORIES = ("fuselage", "canopy", "hatch")
N_WING_STATIONS = 40
N_VTAIL_STATIONS = 16
N_FUSELAGE_STATIONS = 24
N_AIRFOIL_BINS = 24
EDGE_FRACTION = 0.05          # chord fraction used to read leading/trailing-edge height


# ------------------------------------------------------------------ slicing helpers

def _sections(mesh: trimesh.Trimesh, axis: int, positions: np.ndarray) -> list[Optional[np.ndarray]]:
    normal = np.zeros(3)
    normal[axis] = 1.0
    lines, to_3d, _ = trimesh.intersections.mesh_multiplane(mesh, np.zeros(3), normal, positions)
    out: list[Optional[np.ndarray]] = []
    for seg, T in zip(lines, to_3d):
        if len(seg) < 2:
            out.append(None)
            continue
        pts2 = seg.reshape(-1, 2)
        out.append(trimesh.transform_points(np.column_stack([pts2, np.zeros(len(pts2))]), T))
    return out


def _airfoil(x: np.ndarray, z: np.ndarray) -> tuple[float, float, float]:
    """(max thickness/c, max camber/c, x/c of max camber) from a section; x chordwise, z down."""
    i_le, i_te = int(np.argmax(x)), int(np.argmin(x))
    c = x[i_le] - x[i_te]
    if c <= 0:
        return 0.0, 0.0, 0.0
    xn = (x[i_le] - x) / c                     # 0 at LE, 1 at TE
    bins = np.clip((xn * N_AIRFOIL_BINS).astype(int), 0, N_AIRFOIL_BINS - 1)
    upper = np.full(N_AIRFOIL_BINS, np.inf)    # z down: "upper" is the minimum z
    lower = np.full(N_AIRFOIL_BINS, -np.inf)
    np.minimum.at(upper, bins, z)
    np.maximum.at(lower, bins, z)
    ok = np.isfinite(upper) & np.isfinite(lower) & (lower > upper)
    if not ok.any():
        return 0.0, 0.0, 0.0
    centres = (np.arange(N_AIRFOIL_BINS) + 0.5) / N_AIRFOIL_BINS
    up, lo, ct = upper[ok], lower[ok], centres[ok]
    chord_line = z[i_le] + (z[i_te] - z[i_le]) * ct
    camber = (chord_line - (up + lo) / 2) / c   # positive = mean line above the chord line
    j = int(np.argmax(np.abs(camber)))
    return float((lo - up).max() / c), float(camber[j]), float(ct[j])


def naca_name(thickness: float, camber: float, camber_pos: float) -> str:
    m = int(np.clip(round(camber * 100), 0, 9))
    p = int(np.clip(round(camber_pos * 10), 0, 9)) if m > 0 else 0
    tt = int(np.clip(round(thickness * 100), 1, 99))
    return f"NACA {m}{p}{tt:02d}"


def _station_row(section: np.ndarray) -> Optional[tuple[float, float, float, float, float, float, float]]:
    """(chord, x_le, z_mid, twist, t/c, camber, camber_pos) from one section's points."""
    x, z = section[:, 0], section[:, 2]
    chord = float(x.max() - x.min())
    if chord <= 0:
        return None
    edge = EDGE_FRACTION * chord
    z_le = float(z[x >= x.max() - edge].mean())
    z_te = float(z[x <= x.min() + edge].mean())
    twist = float(np.arctan2(z_te - z_le, chord))     # z is down, so positive twist is nose-up
    t, m, p = _airfoil(x, z)
    return chord, float(x.max()), float((z.max() + z.min()) / 2), twist, t, m, p


def _fit(eta: np.ndarray, value: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Least-squares line; returns (slope, intercept, residuals)."""
    if len(eta) < 2 or np.ptp(eta) == 0:
        return 0.0, float(value.mean()) if len(value) else 0.0, np.zeros_like(value)
    slope, intercept = np.polyfit(eta, value, 1)
    return float(slope), float(intercept), value - (slope * eta + intercept)


def _claim(value, unit, evidence_ids, *assumptions, status=Status.estimated,
           source_kind=SourceKind.computed) -> Claim:
    return Claim(value=value, unit=unit, status=status, source_kind=source_kind,
                 evidence_ids=list(evidence_ids), assumptions=list(assumptions))


# ------------------------------------------------------------------ surfaces

def _group_mesh(manifest: DesignManifest, categories: tuple[str, ...], side: Optional[str]
                ) -> tuple[Optional[trimesh.Trimesh], list[str]]:
    parts = [p for p in manifest.parts
             if p.category in categories and p.representation == "reference_mesh"
             and (side is None or p.side == side) and p.mirror_of is None]
    if not parts:
        return None, []
    meshes = [placed_mesh(manifest, p) for p in parts]
    merged = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    return merged, sorted(p.part_id for p in parts)


def _profile(mesh: trimesh.Trimesh, n: int) -> tuple[np.ndarray, float, list[tuple]]:
    """Station y positions, spacing, and the measured rows at the stations that produced a section."""
    lo, hi = float(mesh.bounds[0][1]), float(mesh.bounds[1][1])
    d = (hi - lo) / n
    positions = lo + d * (np.arange(n) + 0.5)
    rows = []
    for y, section in zip(positions, _sections(mesh, 1, positions)):
        if section is None:
            continue
        row = _station_row(section)
        if row is not None:
            rows.append((float(y), *row))
    return positions, d, rows


def _wing_surface(manifest: DesignManifest, evidence_ids: list[str], quality: dict) -> Optional[LiftingSurface]:
    # one side only: the mirrored occurrences repeat the same geometry
    sides = {p.side for p in manifest.parts if p.category in WING_CATEGORIES and p.mirror_of is None}
    side = "left" if "left" in sides else ("right" if "right" in sides else None)
    mesh, part_ids = _group_mesh(manifest, WING_CATEGORIES, side=side)
    if mesh is None or not len(mesh.faces):
        return None

    positions, d, rows = _profile(mesh, N_WING_STATIONS)
    if len(rows) < 3:
        return None
    arr = np.array(rows)
    y, chord, x_le, z_mid, twist, tc, camber, camber_pos = (arr[:, i] for i in range(8))
    eta = np.abs(y)
    order = np.argsort(eta)
    y, chord, x_le, z_mid, twist, tc = (v[order] for v in (y, chord, x_le, z_mid, twist, tc))
    eta = eta[order]

    exposed_half = float(chord.sum() * d)
    area_exposed = 2.0 * exposed_half
    root_eta, tip_eta = float(eta.min() - d / 2), float(eta.max() + d / 2)
    root_chord = float(chord[np.argmin(eta)])
    carry_through = float(2.0 * root_eta * root_chord)
    area_gross = area_exposed + carry_through
    span = 2.0 * tip_eta
    mac = float((chord ** 2).sum() * d / exposed_half)
    x_mac_le = float((chord * x_le).sum() * d / exposed_half)

    sweep_slope, _, r_le = _fit(eta, x_le)
    z_slope, _, r_z = _fit(eta, z_mid)
    _, _, r_c = _fit(eta, chord)
    fit_rms = float(np.sqrt(np.mean(np.concatenate([r_le, r_z, r_c]) ** 2)))
    sweep = float(np.arctan(-sweep_slope))     # LE moving aft (x decreasing) outboard = positive sweep
    dihedral = float(np.arctan(-z_slope))      # z down, so rising outboard is positive dihedral

    quality["wing"] = {
        "stations_measured": int(len(eta)),
        "stations_attempted": int(len(positions)),
        "station_spacing_m": float(d),
        "side_measured": side,
        "exposed_area_m2": area_exposed,
        "carry_through_area_m2": carry_through,
        "root_station_m": root_eta,
        "tip_station_m": tip_eta,
        "root_chord_m": root_chord,
        "tip_chord_m": float(chord[np.argmax(eta)]),
        "fit_rms_m": fit_rms,
        "notes": [
            "area is the projected planform of the merged wing+aileron sections, measured on one "
            "side and doubled; skins, print sections and the aileron cannot double count",
            "gross area adds a rectangular carry-through (root chord x fuselage width) to the "
            "exposed panels; the exposed figure is given separately",
            "fit_rms_m is the residual of a single straight-taper fit to chord, leading edge and "
            "mid-height against span; it measures how non-linear the real planform is, not accuracy",
        ],
    }
    ass = ("measured by slicing the confirmed reference meshes; not a manufacturer specification",)
    return LiftingSurface(
        surface_id="wing",
        part_ids=part_ids,
        stations=[WingStation(span_y_m=float(e), leading_edge_x_m=float(xl), chord_m=float(c),
                              z_m=float(zz), twist_rad=float(tw), thickness_ratio=float(t))
                  for e, xl, c, zz, tw, t in zip(eta, x_le, chord, z_mid, twist, tc)],
        symmetric=True,
        span_m=_claim(span, "m", evidence_ids, *ass, "tip-to-tip after mirroring"),
        area_m2=_claim(area_gross, "m2", evidence_ids, *ass,
                       "gross projected planform including the carry-through through the fuselage"),
        mac_m=_claim(mac, "m", evidence_ids, *ass, "computed over the exposed panels"),
        x_mac_le_m=_claim(x_mac_le, "m", evidence_ids, *ass,
                          "FRD x of the leading edge at the mean aerodynamic chord"),
        aspect_ratio=_claim(float(span ** 2 / area_gross), None, evidence_ids, *ass,
                            "span^2 / gross area"),
        sweep_le_rad=_claim(sweep, "rad", evidence_ids, *ass,
                            "least-squares fit of the leading edge against span"),
        dihedral_rad=_claim(dihedral, "rad", evidence_ids, *ass,
                            "least-squares fit of section mid-height against span"),
        airfoil=_claim(naca_name(float(np.median(tc)), float(np.median(camber)),
                                 float(np.median(camber_pos))) + " (assumed)",
                       None, evidence_ids,
                       "tentative: the nearest NACA 4-digit designation to the measured thickness "
                       "and camber of a hollow printed shell",
                       "NOT an exact airfoil match and not a UIUC identification; use it as a "
                       "declared assumption for reconstruction only",
                       source_kind=SourceKind.assumed),
        control_surfaces=sorted(p.part_id for p in manifest.parts if p.category == "aileron"),
        fit_rms_m=fit_rms,
    )


def _vtail_surfaces(manifest: DesignManifest, evidence_ids: list[str], quality: dict) -> list[LiftingSurface]:
    out: list[LiftingSurface] = []
    horiz_total = vert_total = panel_total = 0.0
    for side in ("left", "right"):
        parts = [p for p in manifest.parts if p.category in VTAIL_CATEGORIES and p.side == side]
        if not parts:
            continue
        originals = [p for p in parts if p.mirror_of is None]
        source_side = side if originals else next(
            (p.side for p in manifest.parts
             if p.category in VTAIL_CATEGORIES and p.mirror_of is None), None)
        mesh, _ = _group_mesh(manifest, VTAIL_CATEGORIES, side=source_side)
        if mesh is None:
            continue
        positions, d, rows = _profile(mesh, N_VTAIL_STATIONS)
        if len(rows) < 3:
            continue
        arr = np.array(rows)
        y, chord, x_le, z_mid, twist, tc, camber, camber_pos = (arr[:, i] for i in range(8))
        eta = np.abs(y)
        order = np.argsort(eta)
        y, chord, x_le, z_mid, twist, tc = (v[order] for v in (y, chord, x_le, z_mid, twist, tc))
        eta = eta[order]

        z_slope, _, r_z = _fit(eta, z_mid)
        cant = float(np.arctan(-z_slope))            # above horizontal
        horiz = float(chord.sum() * d)               # horizontal projection of this panel
        panel_area = horiz / max(np.cos(cant), 1e-6)
        vert = panel_area * float(np.sin(abs(cant)))
        panel_len = (float(eta.max() - eta.min()) + d) / max(np.cos(cant), 1e-6)
        sweep_slope, _, r_le = _fit(eta, x_le)
        _, _, r_c = _fit(eta, chord)
        fit_rms = float(np.sqrt(np.mean(np.concatenate([r_le, r_z, r_c]) ** 2)))
        mac = float((chord ** 2).sum() * d / horiz)
        x_mac_le = float((chord * x_le).sum() * d / horiz)
        horiz_total += horiz
        vert_total += vert
        panel_total += panel_area

        ass = ("measured by slicing the confirmed reference meshes",
               "panel area is the horizontal projection divided by cos(cant); the panel is a single "
               "canted surface, not a horizontal or a vertical tail")
        out.append(LiftingSurface(
            surface_id=f"vtail_{side}",
            part_ids=sorted(p.part_id for p in parts),
            stations=[WingStation(span_y_m=float(e), leading_edge_x_m=float(xl), chord_m=float(c),
                                  z_m=float(zz), twist_rad=float(tw), thickness_ratio=float(t))
                      for e, xl, c, zz, tw, t in zip(eta, x_le, chord, z_mid, twist, tc)],
            symmetric=False,
            cant_rad=cant,
            span_m=_claim(panel_len, "m", evidence_ids, *ass, "length along the canted panel"),
            area_m2=_claim(panel_area, "m2", evidence_ids, *ass, "one panel, counted once"),
            mac_m=_claim(mac, "m", evidence_ids, *ass),
            x_mac_le_m=_claim(x_mac_le, "m", evidence_ids, *ass),
            aspect_ratio=_claim(float(panel_len ** 2 / panel_area), None, evidence_ids, *ass,
                                "per panel"),
            sweep_le_rad=_claim(float(np.arctan(-sweep_slope)), "rad", evidence_ids, *ass),
            dihedral_rad=Claim.unknown("rad", "a canted V-tail panel has a cant angle, not a "
                                              "dihedral; see cant_rad"),
            airfoil=_claim(naca_name(float(np.median(tc)), float(np.median(camber)),
                                     float(np.median(camber_pos))) + " (assumed)", None, evidence_ids,
                           "tentative; the section is cut normal to y, so it is an oblique cut "
                           "through a canted panel and its thickness ratio is inflated by ~1/cos(cant)",
                           source_kind=SourceKind.assumed),
            control_surfaces=sorted(p.part_id for p in manifest.parts
                                    if p.category == "ruddervator" and p.side == side),
            fit_rms_m=fit_rms,
        ))
    if out:
        quality["vtail"] = {
            "panels": len(out),
            "cant_rad": [s.cant_rad for s in out],
            "projected_horizontal_area_m2": horiz_total,
            "projected_vertical_area_m2": vert_total,
            "panel_area_total_m2": panel_total,
            "notes": [
                "two canted panels: the horizontal and vertical figures are projections of the same "
                "surface and must not be added together as if they were separate tails",
                "no tail volume coefficient is computed: a conventional-tail template does not apply "
                "to this aircraft unchanged",
            ],
        }
    return out


def _fuselage(manifest: DesignManifest, quality: dict) -> tuple[list[FuselageStation], Optional[float]]:
    mesh, _ = _group_mesh(manifest, FUSELAGE_CATEGORIES, side=None)
    if mesh is None:
        return [], None
    lo, hi = float(mesh.bounds[0][0]), float(mesh.bounds[1][0])
    d = (hi - lo) / N_FUSELAGE_STATIONS
    positions = lo + d * (np.arange(N_FUSELAGE_STATIONS) + 0.5)
    stations = []
    for x, section in zip(positions, _sections(mesh, 0, positions)):
        if section is None:
            continue
        y, z = section[:, 1], section[:, 2]
        stations.append(FuselageStation(x_m=float(x), width_m=float(y.max() - y.min()),
                                        height_m=float(z.max() - z.min()),
                                        z_center_m=float((z.max() + z.min()) / 2)))
    quality["fuselage"] = {
        "stations_measured": len(stations),
        "max_width_m": max((s.width_m for s in stations), default=None),
        "max_height_m": max((s.height_m for s in stations), default=None),
        "notes": ["envelope of the fuselage, canopy and hatch bodies; the canopy raises the height "
                  "of the stations it covers"],
    }
    return stations, hi - lo


# ------------------------------------------------------------------ mass

def _mass_and_cg(manifest: DesignManifest, quality: dict) -> tuple[Claim, Claim]:
    total, moments, no_mass, no_com = 0.0, np.zeros(3), [], []
    for part in manifest.parts:
        m = part.mass_kg.value
        if m is None:
            no_mass.append(part.part_id)
            continue
        total += float(m)
        com = part.local_com_m.value
        if com is None:
            no_com.append(part.part_id)
            continue
        T = np.array(part.T_parent_from_local, dtype=float)
        moments += float(m) * (T[:3, :3] @ np.array(com, dtype=float) + T[:3, 3])
    quality["mass"] = {"parts_without_mass": sorted(no_mass), "parts_without_com": sorted(no_com),
                       "mass_model": manifest.mass_model}
    if no_mass:
        why = (f"{len(no_mass)} installed parts have no mass claim; a total summed from the rest "
               "would understate the aircraft")
        return Claim.unknown("kg", why), Claim.unknown("m", why + " — and so would its CG")
    mass = _claim(total, "kg", [], "sum of the per-part mass claims; no part was weighed",
                  f"mass model: {manifest.mass_model}")
    if no_com:
        return mass, Claim.unknown(
            "m", f"{len(no_com)} parts carry a mass but no centre of mass (their meshes are not "
                 "watertight), so a CG from the rest would be biased towards the parts that have one")
    return mass, _claim(
        [float(v) for v in moments / total], "m", [],
        "mass-weighted centroid of part centres of mass under the stated per-part assumptions",
        "a geometric centroid is not a measured centre of mass")


# ------------------------------------------------------------------ entry point

def geometry_features(manifest: DesignManifest) -> GeometryFeatures | ErrorEnvelope:
    """Measure the confirmed assembly. Returns an ``ErrorEnvelope`` when it may not be measured."""
    if not manifest.frame.confirmed:
        return units_unconfirmed(
            "units, axes and nose datum are not confirmed; no geometry may be published",
            design_id=manifest.design_id, revision_id=manifest.revision_id)
    unresolved = selection_errors(manifest.variants)
    if unresolved:
        return assembly_unconfirmed(
            f"variant groups without a selection: {', '.join(unresolved)}",
            design_id=manifest.design_id, revision_id=manifest.revision_id, groups=unresolved)

    evidence_ids = [e.evidence_id for e in manifest.evidence if e.method.startswith("stl_")]
    quality: dict = {"frame": "FRD, metres, origin at the confirmed nose datum",
                     "source": "reference meshes only; no reconstruction is involved",
                     "warnings": list(manifest.warnings)}
    surfaces = []
    wing = _wing_surface(manifest, evidence_ids, quality)
    if wing is not None:
        surfaces.append(wing)
    surfaces += _vtail_surfaces(manifest, evidence_ids, quality)
    stations, length = _fuselage(manifest, quality)
    mass, cg = _mass_and_cg(manifest, quality)

    if wing is not None:
        ref_area, ref_span, ref_chord = wing.area_m2, wing.span_m, wing.mac_m
    else:
        why = "no wing group in the manifest"
        ref_area, ref_span, ref_chord = (Claim.unknown("m2", why), Claim.unknown("m", why),
                                         Claim.unknown("m", why))
    quality["reference"] = {"definition": "wing gross projected area, tip-to-tip span, wing MAC"}
    return GeometryFeatures(
        schema_version=SCHEMA_VERSION,
        design_id=manifest.design_id,
        revision_id=manifest.revision_id,
        reference_area_m2=ref_area,
        reference_span_m=ref_span,
        reference_chord_m=ref_chord,
        surfaces=surfaces,
        fuselage=stations,
        fuselage_length_m=_claim(float(length), "m", evidence_ids,
                                 "x extent of the fuselage, canopy and hatch bodies in the "
                                 "confirmed frame") if length else Claim.unknown("m"),
        mass_kg=mass,
        cg_m=cg,
        quality=quality,
    )
