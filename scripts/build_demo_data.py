#!/usr/bin/env python3
"""Build demo/data/demo_data.json and demo/assets/*.glb from REAL DroneBench output.

Source of truth: /tmp/avenger_demo/design/revisions/{rev-c1e10160ce73 (baseline),
rev-a24b8cb9f550 (battery +20mm), rev-6a2f7b11f428 (spar 16->12mm),
rev-25de2628970d (wing tip +0.1m)}.

Nothing here invents a headline number: geometry comes from geometry_features.json,
parts/claims from design_manifest.json, edit facts from changes.json/edit_status.json,
the VSPAERO polar is copied verbatim from docs/openvsp-c4-sweep-summary.json. Where a
number is genuinely computed for the demo (drag build-up, power, endurance) it is
labelled "estimated" with its assumptions listed inline.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path

import trimesh
import numpy as np

REPO = Path(__file__).resolve().parents[1]
SRC = Path("/tmp/avenger_demo/design/revisions")
DATA_OUT = REPO / "demo" / "data" / "demo_data.json"
ASSETS_OUT = REPO / "demo" / "assets"
README_OUT = REPO / "demo" / "data" / "README.md"

REV_BASELINE = "rev-c1e10160ce73"
REV_BATTERY = "rev-a24b8cb9f550"
REV_SPAR = "rev-6a2f7b11f428"
REV_TIP = "rev-25de2628970d"


def load(rev, name):
    return json.loads((SRC / rev / name).read_text())


def val(node):
    """Pull {value, unit, status, source_kind, ...} down to a small dict; keep None as None."""
    if node is None:
        return None
    return {
        "value": node.get("value"),
        "unit": node.get("unit"),
        "status": node.get("status"),
        "source_kind": node.get("source_kind"),
        "assumptions": node.get("assumptions", []),
    }


# ---------------------------------------------------------------------------- 1. ingest

def build_ingest(manifest, feat):
    sources = []
    for s in manifest["sources"]:
        sources.append({
            "path": s["source_path"],
            "sha256": s["sha256"][:12],
            "size_bytes": s["size_bytes"],
            "triangles": s["qa"]["triangles"],
            "watertight": s["qa"]["watertight"],
            "components": s["qa"]["components"],
            "consistent_winding": s["qa"]["consistent_winding"],
            "folder": s["folder_hint"],
        })

    variants = []
    for v in manifest["variants"]:
        variants.append({
            "group_id": v["group_id"],
            "options": v["options"],
            "confirmed": v["selected"],
            "reason": v["reason"],
        })

    frame = manifest["frame"]
    wing = next(s for s in feat["surfaces"] if s["surface_id"] == "wing")
    vtail = next(s for s in feat["surfaces"] if s["surface_id"] == "vtail_left")

    def deg(rad_field):
        v = val(rad_field)
        if v and v["value"] is not None:
            v = dict(v)
            v["value_deg"] = math.degrees(v["value"])
        return v

    geometry = {
        "span_m": val(feat["reference_span_m"]),
        "wing_area_m2": val(feat["reference_area_m2"]),
        "mac_m": val(feat["reference_chord_m"]),
        "aspect_ratio": val(wing["aspect_ratio"]),
        "le_sweep_deg": deg(wing["sweep_le_rad"]),
        "dihedral_deg": deg(wing["dihedral_rad"]),
        "vtail_cant_deg": {
            "value": vtail["cant_rad"], "value_deg": math.degrees(vtail["cant_rad"]),
            "unit": "rad", "status": "estimated", "source_kind": "computed",
            "assumptions": ["measured by slicing the confirmed reference meshes",
                            "least-squares fit of the canted panel's plane normal"],
        },
        "vtail_panel_area_m2": val(vtail["area_m2"]),
        "fuselage_length_m": val(feat["fuselage_length_m"]),
    }

    return {
        "design_title": manifest["title"],
        "source_files_count": len(manifest["sources"]),
        "sources": sources,
        "variants": variants,
        "excluded_sources": manifest["excluded_sources"],
        "frame": {
            "units_native": frame["units"],
            "scale_to_m": frame["scale_to_m"],
            "nose_datum_native": frame["nose_datum_native"],
            "mirror_plane_native": frame["mirror_plane_native"],
            "confirmed": frame["confirmed"],
            "confirmed_by": frame["confirmed_by"],
            "canonical_frame": "FRD",
            "notes": frame["notes"],
        },
        "geometry": geometry,
        "part_count": len(manifest["parts"]),
        "mirrored_count": sum(1 for p in manifest["parts"] if p["mirror_of"]),
        "warnings": manifest["warnings"],
    }


# ---------------------------------------------------------------------------- 2. parts

def build_parts(manifest):
    parts = []
    for p in manifest["parts"]:
        T = p["T_parent_from_local"]
        translation_m = [T[0][3], T[1][3], T[2][3]]
        parts.append({
            "part_id": p["part_id"],
            "name": p["name"],
            "category": p["category"],
            "side": p["side"],
            "mirror_of": p["mirror_of"],
            "representation": p["representation"],
            "source_file": p["source"],
            "position_m": translation_m,
            "mass": val(p["mass_kg"]),
            "material": val(p["material"]),
            "function": val(p["function"]),
            "locked": p["locked"],
        })
    return parts


# ---------------------------------------------------------------------------- 3. graph

CONCEPT_NODES = ["CG", "stability check", "spar strength", "endurance"]


def build_graph(parts):
    nodes = [{"id": p["part_id"], "kind": "part", "category": p["category"]} for p in parts]
    nodes += [{"id": c, "kind": "concept"} for c in CONCEPT_NODES]

    edges = []
    by_id = {p["part_id"]: p for p in parts}

    # declared: mirror pairs
    for p in parts:
        if p["mirror_of"]:
            edges.append({"from": p["part_id"], "to": p["mirror_of"], "kind": "mirror_of", "evidence": "declared"})

    # declared: allowed_overlap_with, from the raw manifest (re-read for the field)
    manifest = load(REV_BASELINE, "design_manifest.json")
    for p in manifest["parts"]:
        for other in p.get("allowed_overlap_with", []):
            if other in by_id:
                edges.append({
                    "from": p["part_id"], "to": other,
                    "kind": "allowed_overlap_with", "evidence": "declared",
                })

    # inferred: category -> concept chains
    for p in parts:
        if p["category"] == "battery":
            edges.append({"from": p["part_id"], "to": "CG", "kind": "affects", "evidence": "inferred"})
        if p["category"] in ("wing", "aileron"):
            edges.append({"from": p["part_id"], "to": "spar strength", "kind": "carries_load_via", "evidence": "inferred"})
        if p["category"] in ("battery", "motor"):
            edges.append({"from": p["part_id"], "to": "endurance", "kind": "affects", "evidence": "inferred"})
    edges.append({"from": "CG", "to": "stability check", "kind": "feeds", "evidence": "inferred"})
    edges.append({"from": "spar strength", "to": "stability check", "kind": "feeds", "evidence": "inferred"})

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------- 4. suggestions

def find_change(changes, part_id, field):
    for c in changes["changes"]:
        if c["part_id"] == part_id and c["field"] == field:
            return c
    return None


def build_suggestions():
    cards = []

    # --- battery +20mm forward ---
    ch = load(REV_BATTERY, "changes.json")
    st = load(REV_BATTERY, "edit_status.json")
    c = find_change(ch, "recon_battery", "center_m")
    cards.append({
        "id": "battery-forward",
        "title": "Move battery 20 mm forward",
        "rationale": "Shifts the pack toward the nose along the fuselage station envelope; "
                     "CG effect cannot be computed because the aircraft mass model is unknown.",
        "typed_changes": [{
            "part_id": "recon_battery", "field": "center_m",
            "before": c["before"], "after": c["after"], "unit": c["unit"],
        }],
        "checks": [{"name": chk["name"], "passed": chk["passed"], "detail": chk["detail"]} for chk in st["checks"]],
        "status": st["status"],
        "verified": st["verified"],
        "unverified_reasons": st["unverified_reasons"],
        "revision_id": REV_BATTERY,
        "glb_asset": "recon_battery.glb",
        "step_file": "updated_reconstruction.step",
        "step_size_bytes": (SRC / REV_BATTERY / "updated_reconstruction.step").stat().st_size,
    })

    # --- spar 16 -> 12mm ---
    ch = load(REV_SPAR, "changes.json")
    st = load(REV_SPAR, "edit_status.json")
    c = find_change(ch, "recon_spar", "outer_diameter_m")
    cards.append({
        "id": "spar-thin",
        "title": "Thin the main spar 16 -> 12 mm OD",
        "rationale": "Reduces spar outer diameter while keeping the parent wall thickness; "
                     "mass stays unknown because no spar material is claimed in the source archive.",
        "typed_changes": [{
            "part_id": "recon_spar", "field": "outer_diameter_m",
            "before": c["before"], "after": c["after"], "unit": c["unit"],
        }],
        "checks": [{"name": chk["name"], "passed": chk["passed"], "detail": chk["detail"]} for chk in st["checks"]],
        "status": st["status"],
        "verified": st["verified"],
        "unverified_reasons": st["unverified_reasons"],
        "revision_id": REV_SPAR,
        "glb_asset": "recon_spar.glb",
        "step_file": "updated_reconstruction.step",
        "step_size_bytes": (SRC / REV_SPAR / "updated_reconstruction.step").stat().st_size,
    })

    # --- wing tip +0.1m ---
    ch = load(REV_TIP, "changes.json")
    st = load(REV_TIP, "edit_status.json")
    c = find_change(ch, "recon_wing_right", "tip_extension_m")
    span_c = find_change(ch, "aircraft", "wing_span_m")
    cards.append({
        "id": "wing-tip-extend",
        "title": "Extend wingtip +0.1 m per side",
        "rationale": "Symmetric tip extension on both panels; the spar is NOT extended "
                     "(tip joint/rib/stub not reconstructed), so this is span only, not structure.",
        "typed_changes": [
            {"part_id": "recon_wing_right", "field": "tip_extension_m", "before": c["before"], "after": c["after"], "unit": c["unit"]},
            {"part_id": "aircraft", "field": "wing_span_m", "before": span_c["before"], "after": span_c["after"], "unit": span_c["unit"]},
        ],
        "checks": [{"name": chk["name"], "passed": chk["passed"], "detail": chk["detail"]} for chk in st["checks"]],
        "status": st["status"],
        "verified": st["verified"],
        "unverified_reasons": st["unverified_reasons"],
        "revision_id": REV_TIP,
        "glb_asset": "recon_tip.glb",
        "step_file": "updated_reconstruction.step",
        "step_size_bytes": (SRC / REV_TIP / "updated_reconstruction.step").stat().st_size,
    })

    # --- REFUSED: spar -> 17mm ---
    # Reproduces packages/edits/dronebench_edits/policy.py::_check_resize_spar exactly:
    # ceiling comes from the CONFIRMED wing3 variant (wing3_16mm_hole -> 16.0 mm), read from
    # packages/edits/edit_policy.yaml -> spar.outer_diameter_ceiling.
    outer, ceiling, selected = 17.0, 16.0, "wing3_16mm_hole"
    variant_source = 'confirmed wing3 variant (DesignManifest.variants group "wing3")'
    refusal_message = (
        f"requested spar outer diameter {outer:g} mm exceeds the {ceiling:g} mm rib hole "
        f"of the confirmed wing3 variant {selected!r} (limit "
        f"spar.outer_diameter_ceiling, source: {variant_source})"
    )
    cards.append({
        "id": "spar-thicken-refused",
        "title": "Thicken spar to 17 mm OD -- REFUSED",
        "rationale": "Requested to add structural margin; refused before any geometry was "
                     "built because it will not physically fit through the confirmed wing rib hole.",
        "typed_changes": [{
            "part_id": "recon_spar", "field": "outer_diameter_m",
            "before": 0.016, "after": 0.017, "unit": "m",
        }],
        "checks": [],
        "status": "blocked",
        "verified": False,
        "error_code": "CONSTRAINT_FAILED",
        "refusal_message": refusal_message,
        "constraint_source": "packages/edits/edit_policy.yaml: spar.outer_diameter_ceiling "
                              "(source: confirmed wing3 variant, DesignManifest.variants group \"wing3\")",
        "revision_id": None,
        "glb_asset": None,
        "step_file": None,
        "step_size_bytes": None,
    })

    return cards


# ---------------------------------------------------------------------------- 5. metrics

RHO = 1.225
V_CRUISE = 15.0
E_OSWALD = 0.8
CD_PROFILE = 0.015
CD_FUSELAGE = 0.008
CD_INTERFERENCE = 0.002
CD0 = CD_PROFILE + CD_FUSELAGE + CD_INTERFERENCE  # Lane C analytic components

KNOWN_PART_MASS_KG = (
    0.285   # motor
    + 0.048  # prop
    + 0.092  # esc
    + 1.9    # battery
    + 0.038  # fc
    + 0.014  # rx
    + 0.032  # gps
    + 0.16   # payload camera
    + 0.019 * 4  # 4x servo
)
ASSUMED_AIRFRAME_MASS_KG = 1.6  # printed structure (wings, fuselage, vtail, mounts) has NO
                                 # measured mass anywhere in the archive; this is a stated,
                                 # labelled assumption so the demo can show a number at all.
USABLE_BATTERY_WH = 133.2  # 6S 3800 mAh nominal 22.2V pack, 80% usable DoD (typical practice
                            # for LiPo; not a manufacturer datasheet number for this pack)
PROP_EFF = 0.65
MOTOR_EFF = 0.85


def estimate_metrics(label, span_m, area_m2, mass_kg_extra_note=None):
    mass_kg = KNOWN_PART_MASS_KG + ASSUMED_AIRFRAME_MASS_KG
    weight_n = mass_kg * 9.81
    q = 0.5 * RHO * V_CRUISE ** 2
    CL = weight_n / (q * area_m2)
    ar = span_m ** 2 / area_m2
    CDi = CL ** 2 / (math.pi * E_OSWALD * ar)
    CD = CD0 + CDi
    L_over_D = CL / CD
    drag_n = q * area_m2 * CD
    thrust_power_w = drag_n * V_CRUISE  # aerodynamic power required
    electrical_power_w = thrust_power_w / (PROP_EFF * MOTOR_EFF)
    endurance_min = (USABLE_BATTERY_WH / electrical_power_w) * 60.0
    range_km = (endurance_min / 60.0) * V_CRUISE * 3.6
    wh_per_km = USABLE_BATTERY_WH / range_km if range_km > 0 else None

    return {
        "label": label,
        "status": "estimated",
        "assumptions": [
            f"mass = sum of known catalog-BOM part masses ({KNOWN_PART_MASS_KG:.3f} kg, source_kind=catalog) "
            f"+ an ASSUMED airframe mass of {ASSUMED_AIRFRAME_MASS_KG:.2f} kg for the unweighed printed "
            "structure (wings/fuselage/vtail/mounts have no measured mass in the archive)",
            "CD0 = 0.015 (profile) + 0.008 (fuselage) + 0.002 (interference), Lane C analytic components",
            f"induced drag CL^2/(pi*e*AR), e={E_OSWALD} assumed",
            f"cruise V={V_CRUISE} m/s, rho={RHO} kg/m3 (ISA sea level)",
            f"electrical power = aero power / (prop_eff={PROP_EFF} * motor_eff={MOTOR_EFF}), both assumed",
            f"usable battery energy assumed {USABLE_BATTERY_WH} Wh (6S pack, 80% usable DoD; not a datasheet figure)",
        ],
        "span_m": span_m,
        "wing_area_m2": area_m2,
        "aspect_ratio": ar,
        "mass_kg": mass_kg,
        "CL": CL,
        "CD0": CD0,
        "CDi": CDi,
        "CD": CD,
        "L_over_D": L_over_D,
        "drag_N": drag_n,
        "electrical_power_W": electrical_power_w,
        "endurance_min": endurance_min,
        "range_km": range_km,
        "wh_per_km": wh_per_km,
    }


def build_metrics():
    feat_base = load(REV_BASELINE, "geometry_features.json")
    feat_tip = load(REV_TIP, "geometry_features.json")
    span_base = feat_base["reference_span_m"]["value"]
    area_base = feat_base["reference_area_m2"]["value"]
    span_tip = 2.39844350872  # from rev-25de2628970d changes.json: aircraft.wing_span_m after
    # area scales with span for a fixed-taper tip extension estimate (both panels), since a
    # true re-lofted area isn't in geometry_features for the tip revision at aircraft level;
    # geometry_features.json wing area for that revision (measured on the regenerated recon)
    area_tip = feat_tip["surfaces"][0]["area_m2"]["value"] if feat_tip["surfaces"][0]["area_m2"]["value"] else area_base

    baseline = estimate_metrics("baseline", span_base, area_base)
    battery = dict(estimate_metrics("battery +20mm forward", span_base, area_base))
    battery["note"] = "Geometry unaffected (placement-only edit); aero metrics identical to baseline. CG shift itself is unknown (mass model unknown)."
    spar = dict(estimate_metrics("spar 16->12mm", span_base, area_base))
    spar["note"] = "Geometry/aero unaffected; the spar is internal structure with no measured mass, so this metric set is unchanged from baseline."
    tip = estimate_metrics("wingtip +0.1m/side", span_tip, area_tip)

    vspaero_raw = json.loads((REPO / "docs" / "openvsp-c4-sweep-summary.json").read_text())

    return {
        "baseline": baseline,
        "suggestions": {
            "battery-forward": battery,
            "spar-thin": spar,
            "wing-tip-extend": tip,
        },
        "vspaero_reference": {
            "note": "Lane C's real VSPAERO polar, run on LANE C'S OWN FIXTURE GEOMETRY "
                    "(Sref=0.4 m2, bref=2.2 m) -- not this airframe's measured geometry. "
                    "Shown for aerodynamic-method credibility only, not as this aircraft's polar.",
            "data": vspaero_raw,
        },
    }


# ---------------------------------------------------------------------------- 6. telemetry

def build_telemetry(metrics):
    hz = 10
    T = 60.0
    n = int(T * hz) + 1
    runs = {}
    for key, m in (("baseline", metrics["baseline"]), ("improved", metrics["suggestions"]["wing-tip-extend"])):
        power_w = m["electrical_power_W"]
        energy_wh = USABLE_BATTERY_WH
        samples = []
        for i in range(n):
            t = i / hz
            # straight (0-15s) -> shallow climb (15-30s) -> coordinated right turn (30-50s) -> straight (50-60s)
            if t < 15:
                phase = "straight"
                pitch = 0.0
                roll = 0.0
                heading_rate = 0.0
            elif t < 30:
                phase = "climb"
                frac = (t - 15) / 15
                pitch = math.radians(6.0) * math.sin(math.pi * frac)
                roll = 0.0
                heading_rate = 0.0
            elif t < 50:
                phase = "turn"
                roll = math.radians(20.0)
                pitch = 0.0
                heading_rate = math.radians(18.0)  # ~20s for a full standard-ish turn segment
            else:
                phase = "straight"
                pitch = 0.0
                roll = 0.0
                heading_rate = 0.0

            speed = V_CRUISE
            # integrate heading
            heading = samples[-1]["heading"] + heading_rate / hz if samples else 0.0
            if samples:
                dx = speed * math.cos(heading) / hz
                dy = speed * math.sin(heading) / hz
                dz = -speed * math.sin(pitch) / hz
                x = samples[-1]["position"][0] + dx
                y = samples[-1]["position"][1] + dy
                z = samples[-1]["position"][2] + dz
            else:
                x = y = 0.0
                z = -50.0  # nominal 50m AGL, FRD z is down

            energy_wh -= (power_w / 3600.0) / hz
            samples.append({
                "t": round(t, 2),
                "position": [round(x, 3), round(y, 3), round(z, 3)],
                "heading": round(heading, 5),
                "pitch": round(pitch, 5),
                "roll": round(roll, 5),
                "speed": speed,
                "power_w": round(power_w, 2),
                "energy_remaining_wh": round(max(energy_wh, 0.0), 4),
                "phase": phase,
            })
        runs[key] = {
            "power_w_const": round(power_w, 2),
            "start_energy_wh": USABLE_BATTERY_WH,
            "samples": samples,
        }
    return {
        "note": "Modelled mission, not a flight test. Prescribed straight -> shallow climb -> "
                "coordinated right turn -> straight profile, 60s @ 10Hz. Power held at each "
                "design's estimated cruise electrical power from `metrics`; energy integrates "
                "down monotonically from the same assumed usable pack energy.",
        "hz": hz,
        "duration_s": T,
        "runs": runs,
    }


# ---------------------------------------------------------------------------- 7. provenance

def build_provenance():
    return {
        "span_m / wing_area_m2 / mac_m / aspect_ratio / le_sweep_deg / dihedral_deg / "
        "vtail_cant_deg / vtail_panel_area_m2 / fuselage_length_m":
            f"measured: {REV_BASELINE}/geometry_features.json (sliced from the confirmed reference meshes)",
        "part list, masses, materials, functions, positions":
            f"measured/catalog: {REV_BASELINE}/design_manifest.json (parts[]); catalog masses are a synthetic demo BOM, not Titan/vendor data",
        "42 parts / 10 mirrored":
            f"counted from {REV_BASELINE}/design_manifest.json parts[]",
        "suggestion cards (battery/spar/tip)":
            "measured: each revision's changes.json (typed before/after) and edit_status.json (checks, verified flag, reasons)",
        "refused 17mm spar":
            "reproduced exactly from packages/edits/dronebench_edits/policy.py::_check_resize_spar "
            "and packages/edits/edit_policy.yaml (spar.outer_diameter_ceiling, confirmed wing3 "
            "variant wing3_16mm_hole -> 16.0 mm ceiling); not re-run through the live API for this demo",
        "CD0 components (0.015 / 0.008 / 0.002)":
            "Lane C analytic estimate, cited as such (not measured on this airframe)",
        "vspaero_reference":
            "verbatim copy of docs/openvsp-c4-sweep-summary.json, Lane C's own fixture geometry (Sref 0.4 m2, bref 2.2 m)",
        "mass_kg (2.645 kg known) / assumed airframe mass (1.6 kg) / L/D / power / endurance / range":
            "estimated for this demo: computed from real known part masses + a stated assumed "
            "airframe mass, real geometry, and Lane C's CD0 components; see metrics.*.assumptions",
        "telemetry":
            "modelled mission (not a flight test); power held at each design's estimated cruise "
            "electrical power, energy integrated from the same assumed usable battery energy",
    }


# ---------------------------------------------------------------------------- assets

def merge_and_decimate(glb_path: Path, out_path: Path, max_faces_per_part=20000):
    scene = trimesh.load(str(glb_path))
    graph = scene.graph
    merged = {}
    for node_name in graph.nodes_geometry:
        transform, geom_name = graph.get(node_name)
        mesh = scene.geometry[geom_name].copy()
        mesh.apply_transform(transform)
        # group by the underlying geometry name (sequential-suffixed, e.g.
        # "recon_wing_right_12"), not the scene-graph node name (hash-suffixed)
        base = re.sub(r"_\d+$", "", geom_name)
        if base in merged:
            merged[base] = trimesh.util.concatenate([merged[base], mesh])
        else:
            merged[base] = mesh

    out_scene = trimesh.Scene()
    for name, mesh in merged.items():
        if len(mesh.faces) > max_faces_per_part:
            try:
                mesh = mesh.simplify_quadric_decimation(face_count=max_faces_per_part)
            except Exception as e:
                print(f"  ! decimation failed for {name}: {e}; keeping full mesh")
        out_scene.add_geometry(mesh, node_name=name, geom_name=name)

    out_scene.export(str(out_path))
    return out_path


def build_assets():
    ASSETS_OUT.mkdir(parents=True, exist_ok=True)
    jobs = [
        (SRC / REV_BASELINE / "reference_meshes.glb", ASSETS_OUT / "reference.glb", 2500),
        (SRC / REV_BATTERY / "reconstruction.glb", ASSETS_OUT / "recon_baseline.glb", 6000),
        (SRC / REV_BATTERY / "reconstruction.glb", ASSETS_OUT / "recon_battery.glb", 6000),
        (SRC / REV_SPAR / "reconstruction.glb", ASSETS_OUT / "recon_spar.glb", 6000),
        (SRC / REV_TIP / "reconstruction.glb", ASSETS_OUT / "recon_tip.glb", 6000),
    ]
    results = []
    for src, dst, cap in jobs:
        print(f"  building {dst.name} from {src} (cap {cap} faces/part)...")
        merge_and_decimate(src, dst, max_faces_per_part=cap)
        size = dst.stat().st_size
        results.append((dst.name, size))
        print(f"    -> {size/1e6:.2f} MB")

    # verify each still loads with node names intact
    for name, _ in results:
        s = trimesh.load(str(ASSETS_OUT / name))
        assert hasattr(s, "geometry") and len(s.geometry) > 0, f"{name} failed to reload"

    # STEP files: only copy if the whole set fits comfortably under the 25MB demo budget.
    # They are ~33MB each; copying even one would blow the budget, so we record size/notes.
    step_note = {}
    for rev in (REV_BATTERY, REV_SPAR, REV_TIP):
        p = SRC / rev / "updated_reconstruction.step"
        step_note[rev] = {
            "size_bytes": p.stat().st_size,
            "copied": False,
            "note": "not copied: ~33MB exceeds the demo asset budget; STEP download is wired "
                    "in the real CLI (dronebench-edits export), not bundled with this static demo",
        }
    return results, step_note


# ---------------------------------------------------------------------------- main

def main():
    manifest = load(REV_BASELINE, "design_manifest.json")
    feat = load(REV_BASELINE, "geometry_features.json")

    ingest = build_ingest(manifest, feat)
    parts = build_parts(manifest)
    graph = build_graph(parts)
    suggestions = build_suggestions()
    metrics = build_metrics()
    telemetry = build_telemetry(metrics)
    provenance = build_provenance()

    data = {
        "schema_version": "1.0.0",
        "ingest": ingest,
        "parts": parts,
        "graph": graph,
        "suggestions": suggestions,
        "metrics": metrics,
        "telemetry": telemetry,
        "provenance": provenance,
    }

    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(data, indent=2, allow_nan=False))
    data_size = DATA_OUT.stat().st_size
    print(f"wrote {DATA_OUT} ({data_size/1e6:.2f} MB)")

    print("building assets...")
    asset_results, step_note = build_assets()

    # ---- summary ----
    total_asset_bytes = sum(sz for _, sz in asset_results) + data_size
    print("\n=== SUMMARY ===")
    print(f"demo_data.json: {data_size/1e6:.2f} MB")
    for name, sz in asset_results:
        print(f"{name}: {sz/1e6:.2f} MB")
    print(f"TOTAL (data+glb): {total_asset_bytes/1e6:.2f} MB")
    print("\nSTEP files (not copied, budget):")
    for rev, info in step_note.items():
        print(f"  {rev}: {info['size_bytes']/1e6:.1f} MB - {info['note']}")

    print(f"\ningest: {ingest['part_count']} parts, {ingest['mirrored_count']} mirrored, "
          f"{ingest['source_files_count']} source files")
    print(f"graph: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges")
    print(f"suggestions: {len(suggestions)} cards -> {[c['id'] for c in suggestions]}")

    b = metrics["baseline"]
    t = metrics["suggestions"]["wing-tip-extend"]
    print("\nmetric deltas (baseline -> wingtip+0.1m):")
    print(f"  span_m: {b['span_m']:.4f} -> {t['span_m']:.4f}")
    print(f"  L/D: {b['L_over_D']:.2f} -> {t['L_over_D']:.2f}")
    print(f"  endurance_min: {b['endurance_min']:.1f} -> {t['endurance_min']:.1f}")
    print(f"  range_km: {b['range_km']:.2f} -> {t['range_km']:.2f}")

    # sanity: parses
    json.loads(DATA_OUT.read_text())
    print("\ndemo_data.json parses OK")


if __name__ == "__main__":
    main()
