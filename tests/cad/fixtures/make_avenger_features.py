"""Regenerate `avenger_features.json` from the measured Avenger reference meshes.

This is a *stand-in* for `packages/ingest.geometry_features` (builder A1). It exists so
`packages/cad` has a deterministic, checked-in GeometryFeatures fixture while the real
ingest pipeline is being written, and so the numbers in the fixture are traceable to the
slicing procedure that produced them rather than typed in by hand.

Run:  .venv/bin/python tests/cad/fixtures/make_avenger_features.py
Needs `vendor_assets/avenger/` (git-ignored, unlicensed — never copied into the repo).

Frame: candidate native->FRD from tasks/a.md, with the source side mapped to POSITIVE y
(right). That mapping is a reflection, so it is applied to the mesh definition and the
winding is flipped; it is not a placement. Unconfirmed: nothing here may be published as
an aircraft metric until a human confirms the frame.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import trimesh

REPO = Path(__file__).resolve().parents[3]
VENDOR = REPO / "vendor_assets" / "avenger"
OUT = Path(__file__).with_name("avenger_features.json")

Y_NOSE_NATIVE = -403.0700988769531  # native Y of the extreme forward fuselage vertex
SCALE = 0.001

WING = ["wing1", "wing2", "wing3_16mm_hole", "wing4", "wing5", "aileron"]
TAIL = ["vtail1", "vtail2", "taileron"]
FUSE = ["fuse1", "fuse2", "fuse3", "fuse4", "fuse5", "canopy1", "canopy2", "hatch1", "hatch2"]

WING_Y = [0.070, 0.150, 0.250, 0.400, 0.550, 0.700, 0.900, 1.050, 1.090, 1.1105]
VTAIL_Y = [0.0555, 0.090, 0.130, 0.170, 0.210, 0.245, 0.265, 0.2855]
FUSE_X = [
    -0.0431, -0.0843, -0.1254, -0.1665, -0.2077, -0.2500, -0.2900, -0.3311, -0.3722,
    -0.4134, -0.4956, -0.5779, -0.6602, -0.7424, -0.7836, -0.8247, -0.8659, -0.9070,
    -0.9481, -0.9890,
]


def to_frd(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    v = mesh.vertices
    out = mesh.copy()
    out.vertices = np.column_stack(
        [-(v[:, 1] - Y_NOSE_NATIVE) * SCALE, v[:, 0] * SCALE, -v[:, 2] * SCALE]
    )
    out.invert()  # y-mirror reverses orientation; repair the winding
    return out


def group(folder: str, names: list[str]) -> trimesh.Trimesh:
    parts = [to_frd(trimesh.load(str(VENDOR / folder / f"{n}.stl"), process=False)) for n in names]
    return trimesh.util.concatenate(parts)


def slice_y(mesh: trimesh.Trimesh, y: float) -> dict | None:
    sec = mesh.section(plane_origin=[0, y, 0], plane_normal=[0, 1, 0])
    if sec is None:
        return None
    p = sec.vertices
    le, te = float(p[:, 0].max()), float(p[:, 0].min())
    ztop, zbot = float(p[:, 2].min()), float(p[:, 2].max())  # z is DOWN: min z is the top
    chord = le - te
    return {
        "span_y_m": round(y, 5),
        "leading_edge_x_m": round(le, 5),
        "chord_m": round(chord, 5),
        "z_m": round((ztop + zbot) / 2, 5),
        "twist_rad": 0.0,
        "thickness_ratio": round((zbot - ztop) / chord, 5),
    }


def claim(value, unit, *, status="estimated", source="computed", assumptions=(), evidence=()):
    return {
        "value": value,
        "unit": unit,
        "status": status,
        "source_kind": source,
        "evidence_ids": list(evidence),
        "confidence": None,
        "assumptions": list(assumptions),
    }


def planform_area(stations: list[dict]) -> float:
    y = np.array([s["span_y_m"] for s in stations])
    c = np.array([s["chord_m"] for s in stations])
    return float(np.trapezoid(c, y)) if hasattr(np, "trapezoid") else float(np.trapz(c, y))


def mac(stations: list[dict]) -> float:
    y = np.array([s["span_y_m"] for s in stations])
    c = np.array([s["chord_m"] for s in stations])
    integ = np.trapezoid if hasattr(np, "trapezoid") else np.trapz
    return float(integ(c * c, y) / integ(c, y))


def main() -> int:
    if not VENDOR.exists():
        print(f"missing {VENDOR}", file=sys.stderr)
        return 2

    wing = group("Wings", WING)
    tail = group("Tail", TAIL)
    fuse = group("Fuselage", FUSE)

    wing_st = [s for s in (slice_y(wing, y) for y in WING_Y) if s]
    vtail_st = [s for s in (slice_y(tail, y) for y in VTAIL_Y) if s]
    for s in vtail_st:
        s["thickness_ratio"] = 0.10  # cant dominates the axis-aligned slice; assumed, not measured

    fus_st = []
    for x in FUSE_X:
        sec = fuse.section(plane_origin=[x, 0, 0], plane_normal=[1, 0, 0])
        if sec is None:
            continue
        p = sec.vertices
        fus_st.append(
            {
                "x_m": round(float(x), 5),
                "width_m": round(float(p[:, 1].max() - p[:, 1].min()), 5),
                "height_m": round(float(p[:, 2].max() - p[:, 2].min()), 5),
                "z_center_m": round(float((p[:, 2].max() + p[:, 2].min()) / 2), 5),
            }
        )
    fus_st.insert(0, {"x_m": 0.0, "width_m": 0.004, "height_m": 0.004, "z_center_m": 0.0})

    # V-tail cant: least-squares slope of panel mid-height against spanwise y.
    vy = np.array([s["span_y_m"] for s in vtail_st])
    vz = np.array([s["z_m"] for s in vtail_st])
    slope = float(np.polyfit(vy, vz, 1)[0])
    cant = float(np.arctan(-slope))  # z is down, so a negative slope means the panel rises

    half_area = planform_area(wing_st)
    span_exposed = wing_st[-1]["span_y_m"] - wing_st[0]["span_y_m"]
    tip_to_tip = 2 * wing_st[-1]["span_y_m"]
    area = 2 * half_area  # exposed panels, both sides, counted once (aileron mapped to wing)
    mac_m = mac(wing_st)
    le_sweep = float(
        np.arctan(
            -(wing_st[-2]["leading_edge_x_m"] - wing_st[0]["leading_edge_x_m"])
            / (wing_st[-2]["span_y_m"] - wing_st[0]["span_y_m"])
        )
    )
    dihedral = float(
        np.arctan(
            -(wing_st[-2]["z_m"] - wing_st[0]["z_m"])
            / (wing_st[-2]["span_y_m"] - wing_st[0]["span_y_m"])
        )
    )
    x_mac_le = float(
        np.average(
            [s["leading_edge_x_m"] for s in wing_st], weights=[s["chord_m"] for s in wing_st]
        )
    )

    vhalf = planform_area(vtail_st)
    vspan = float(
        np.hypot(
            vtail_st[-1]["span_y_m"] - vtail_st[0]["span_y_m"],
            vtail_st[-1]["z_m"] - vtail_st[0]["z_m"],
        )
    )

    airfoil_note = (
        "NACA 4-digit family, camber assumed (m=0.04, p=0.4), thickness taken from the "
        "measured per-station t/c. Not an exact match claim; no UIUC identification attempted."
    )

    def surface(sid, part_ids, stations, *, symmetric, cant_rad, span, area_v, controls, mac_v,
                x_le, ar, sweep, dih):
        return {
            "surface_id": sid,
            "part_ids": part_ids,
            "stations": stations,
            "symmetric": symmetric,
            "cant_rad": cant_rad,
            "span_m": claim(round(span, 5), "m", assumptions=["frame unconfirmed"]),
            "area_m2": claim(
                round(area_v, 6), "m2",
                assumptions=["projected planform, exposed panels only (no fuselage carry-through)"],
            ),
            "mac_m": claim(round(mac_v, 5), "m"),
            "x_mac_le_m": claim(round(x_le, 5), "m"),
            "aspect_ratio": claim(round(ar, 4), None),
            "sweep_le_rad": claim(round(sweep, 5), "rad"),
            "dihedral_rad": claim(round(dih, 5), "rad"),
            "airfoil": claim(
                "NACA 44xx (assumed)", None, status="estimated", source="assumed",
                assumptions=[airfoil_note],
            ),
            "control_surfaces": controls,
            "fit_rms_m": None,
        }

    features = {
        "schema_version": "0.1.0",
        "design_id": "titan_avenger",
        "revision_id": "fixture-0001",
        "frame": "FRD",
        "reference_area_m2": claim(
            round(area, 6), "m2",
            assumptions=["exposed wing panels both sides; no fuselage carry-through"],
        ),
        "reference_span_m": claim(
            round(tip_to_tip, 5), "m",
            assumptions=["source side mirrored about the aircraft centreline"],
        ),
        "reference_chord_m": claim(round(mac_m, 5), "m"),
        "surfaces": [
            surface(
                "wing", ["wing1", "wing2", "wing3", "wing4", "wing5", "aileron"], wing_st,
                symmetric=True, cant_rad=None, span=tip_to_tip, area_v=area,
                controls=["aileron"], mac_v=mac_m, x_le=x_mac_le,
                ar=tip_to_tip**2 / area, sweep=le_sweep, dih=dihedral,
            ),
            surface(
                "vtail_right", ["vtail1", "vtail2", "taileron"], vtail_st,
                symmetric=True, cant_rad=round(cant, 5), span=vspan, area_v=vhalf,
                controls=["taileron"], mac_v=mac(vtail_st),
                x_le=vtail_st[0]["leading_edge_x_m"],
                ar=vspan**2 / vhalf, sweep=float(
                    np.arctan(
                        -(vtail_st[-1]["leading_edge_x_m"] - vtail_st[0]["leading_edge_x_m"]) / vspan
                    )
                ),
                dih=cant,
            ),
        ],
        "fuselage": fus_st,
        "fuselage_length_m": claim(0.99125, "m"),
        "mass_kg": claim(None, "kg", status="unknown", source=None,
                         assumptions=["no BOM in the archive; mesh volume is not mass"]),
        "cg_m": claim(None, "m", status="unknown", source=None,
                      assumptions=["mass distribution unknown"]),
        "quality": {
            "frame_confirmed": False,
            "method": "axis-aligned mesh sections of the FRD-transformed reference groups",
            "wing_exposed_span_m": round(span_exposed, 5),
            "wing_root_station_m": wing_st[0]["span_y_m"],
            "vtail_cant_deg": round(np.degrees(cant), 3),
            "variant_selected": "wing3_16mm_hole",
            "warnings": [
                "Stand-in fixture produced by tests/cad/fixtures/make_avenger_features.py, "
                "not by packages/ingest.",
                "Several source meshes are not watertight; section extents are still valid but "
                "no volume or mass may be derived from them.",
                "V-tail t/c is assumed 0.10; the axis-aligned slice cannot measure it.",
                "Areas exclude the fuselage carry-through; compare like for like.",
            ],
        },
    }

    OUT.write_text(json.dumps(features, indent=2) + "\n")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
