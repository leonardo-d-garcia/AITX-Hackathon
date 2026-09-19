"""Adapter: our GeometryFeatures (Team A/Avenger CAD pipeline) -> Lane C's
geometry_features schema (packages/contracts/lanec_schemas/geometry_features.schema.json).

Lane C's schema wants a flatter shape than ours: reference S/b/c exactly once, a
single right-wing-only station list (y >= 0, root -> tip), a V-tail block, and a
handful of mission/aero/spar blocks that our CAD pipeline never measures at all
(we only reconstruct geometry from meshes; we don't run a mission sim or a spar
stress model). Those unmeasured blocks are emitted as explicit "assumed"/"unknown"
Claims -- never a bare invented number -- so Lane C's evaluator can see clearly
which numbers are real Avenger measurements and which are placeholders.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Union

from dronebench_contracts.models import Claim, GeometryFeatures

_DEMO_NOTE = "demo default; not measured from the archive"


def _as_claim_dict(claim: Union[Claim, Mapping[str, Any], None], *, unit: str) -> dict:
    """Convert one of our Claims (object or dict) into Lane C's claim shape."""
    if claim is None:
        return _unknown_claim(unit)
    if isinstance(claim, Claim):
        data = claim.model_dump()
    else:
        data = dict(claim)

    status = data.get("status", "unknown")
    # Lane C's Status enum lacks our "conflicted"; anything we can't map cleanly
    # to known/estimated/unknown/not_applicable falls back to "unknown" rather
    # than silently lying about provenance.
    if status not in ("known", "estimated", "unknown", "not_applicable"):
        status = "unknown"

    value = data.get("value")
    if status == "unknown":
        value = None

    return {
        "value": value,
        "unit": data.get("unit") or unit,
        "status": status,
        "source_kind": data.get("source_kind") or "assumed",
        "evidence_ids": list(data.get("evidence_ids") or []),
        "assumptions": list(data.get("assumptions") or []),
    }


def _assumed_claim(value: Optional[float], unit: str, note: str, *, status: str = "estimated") -> dict:
    """A Claim we invented because Lane C's schema requires the field but our
    CAD pipeline has no measured source for it. Always carries an assumptions[]
    note explaining that provenance -- never a bare invented number."""
    return {
        "value": value,
        "unit": unit,
        "status": status,
        "source_kind": "assumed",
        "evidence_ids": [],
        "assumptions": [note],
    }


def _unknown_claim(unit: str, note: str = "not provided by our CAD pipeline") -> dict:
    return {
        "value": None,
        "unit": unit,
        "status": "unknown",
        "source_kind": "assumed",
        "evidence_ids": [],
        "assumptions": [note],
    }


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _find_surface(surfaces: list, surface_id: str) -> Optional[Any]:
    for s in surfaces:
        if _get(s, "surface_id") == surface_id:
            return s
    return None


def to_lanec_geometry(
    features: Union[GeometryFeatures, Mapping[str, Any]],
    mission: Optional[Mapping[str, Any]] = None,
    spar: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Convert our GeometryFeatures (object or dict) into a dict that validates
    against Lane C's geometry_features.schema.json.

    `mission` / `spar` let the caller supply real values for the blocks our CAD
    pipeline never measures (mission profile, aero coefficients, spar sizing).
    Each should be a mapping of field name -> Lane C claim dict (value/unit/
    status/source_kind/evidence_ids/assumptions). Any field left unsupplied is
    emitted as an explicit assumed/unknown Claim with an assumptions[] note --
    we never invent a number without saying so.
    """
    if isinstance(features, GeometryFeatures):
        f = features.model_dump()
    elif isinstance(features, Mapping):
        f = dict(features)
    else:
        raise TypeError(f"unsupported features type: {type(features)!r}")

    surfaces = f.get("surfaces") or []
    wing = _find_surface(surfaces, "wing")
    if wing is None and surfaces:
        wing = surfaces[0]

    # Our WingStation fields are plain floats (no per-field Claim, no evidence
    # ids) -- the provenance lives one level up, on the surface's own Claims
    # (span_m/area_m2/... e.g. status "estimated", source_kind "computed").
    # Carry that same provenance down onto each station field rather than
    # inventing "known"/"assumed" out of nothing.
    surface_status = "estimated"
    surface_source_kind = "computed"
    surface_note = "derived from CAD-fit wing stations, not a per-station Claim in our model"
    if wing is not None:
        ref_claim = _get(wing, "area_m2")
        if ref_claim is not None:
            surface_status = _get(ref_claim, "status", surface_status) or surface_status
            surface_source_kind = _get(ref_claim, "source_kind", surface_source_kind) or surface_source_kind

    def _station_field_claim(value: Optional[float], unit: str) -> dict:
        return {
            "value": value,
            "unit": unit,
            "status": surface_status,
            "source_kind": surface_source_kind,
            "evidence_ids": [],
            "assumptions": [surface_note],
        }

    wing_stations = []
    if wing is not None:
        stations = sorted(
            (s for s in (_get(wing, "stations") or []) if _get(s, "span_y_m", 0.0) >= 0.0),
            key=lambda s: _get(s, "span_y_m", 0.0),
        )
        for st in stations:
            wing_stations.append(
                {
                    "span_y_m": _station_field_claim(_get(st, "span_y_m"), "m"),
                    "leading_edge_x_m": _station_field_claim(_get(st, "leading_edge_x_m"), "m"),
                    "chord_m": _station_field_claim(_get(st, "chord_m"), "m"),
                    "z_m": _station_field_claim(_get(st, "z_m"), "m"),
                    "twist_rad": _station_field_claim(_get(st, "twist_rad", 0.0), "rad"),
                }
            )

    vtail_left = _find_surface(surfaces, "vtail_left")
    vtail_right = _find_surface(surfaces, "vtail_right")
    tail_panel = vtail_left or vtail_right

    if tail_panel is not None:
        panel_area = _as_claim_dict(_get(tail_panel, "area_m2"), unit="m2")
        panel_span = _as_claim_dict(_get(tail_panel, "span_m"), unit="m")
        cant_val = _get(tail_panel, "cant_rad")
        cant = (
            {
                "value": cant_val,
                "unit": "rad",
                "status": surface_status,
                "source_kind": surface_source_kind,
                "evidence_ids": [],
                "assumptions": ["derived from CAD-fit V-tail panel, not a per-field Claim in our model"],
            }
            if cant_val is not None
            else _unknown_claim("rad", "V-tail cant not present on this surface")
        )
        tail = {
            "layout": "vtail",
            "cant_rad": cant,
            "panel_count": {
                "value": 2 if (vtail_left and vtail_right) else 1,
                "unit": "1",
                "status": "known",
                "source_kind": "computed",
                "evidence_ids": [],
                "assumptions": ["counted from vtail_left/vtail_right surfaces present in our GeometryFeatures"],
            },
            "panel_area_m2": panel_area,
            "panel_span_m": panel_span,
            "tail_arm_m": _assumed_claim(None, "m", _DEMO_NOTE, status="unknown"),
        }
    else:
        tail = {
            "layout": "vtail",
            "cant_rad": _unknown_claim("rad", "no V-tail surface in source GeometryFeatures"),
            "panel_count": _unknown_claim("1", "no V-tail surface in source GeometryFeatures"),
            "panel_area_m2": _unknown_claim("m2", "no V-tail surface in source GeometryFeatures"),
            "panel_span_m": _unknown_claim("m", "no V-tail surface in source GeometryFeatures"),
            "tail_arm_m": _unknown_claim("m", "no V-tail surface in source GeometryFeatures"),
        }

    mission = mission or {}
    mission_defaults = {
        "cruise_mps": ("m/s", 15.0),
        "altitude_m": ("m", 120.0),
        "rho_kgm3": ("kg/m3", 1.225),
        "g_mps2": ("m/s2", 9.80665),
        "reserve_wh_fraction": ("1", 0.2),
        "load_factor_limit": ("1", 3.5),
    }
    mission_block = {}
    for key, (unit, default) in mission_defaults.items():
        if key in mission:
            mission_block[key] = mission[key]
        else:
            mission_block[key] = _assumed_claim(default, unit, _DEMO_NOTE)

    aero_defaults = {
        "CD0_profile": ("1", 0.015),
        "CD0_fuselage": ("1", 0.008),
        "CD0_interference": ("1", 0.002),
        "oswald_e": ("1", 0.8),
        "CLmax": ("1", 1.3),
    }
    aero_block = {}
    for key, (unit, default) in aero_defaults.items():
        aero_block[key] = _assumed_claim(default, unit, _DEMO_NOTE)

    spar = spar or {}
    spar_defaults = {
        "Do_m": ("m", 0.016),
        "Di_m": ("m", 0.012),
        "sigma_allow_mpa": ("MPa", 400.0),
        "stations": ("1", 21),
    }
    spar_block = {}
    for key, (unit, default) in spar_defaults.items():
        if key in spar:
            spar_block[key] = spar[key]
        else:
            spar_block[key] = _assumed_claim(default, unit, _DEMO_NOTE)

    result = {
        "schema_version": 1,
        "frame": f.get("frame") or "FRD",
        "units": "m",
        "reference": {
            "S_m2": _as_claim_dict(f.get("reference_area_m2"), unit="m2"),
            "b_m": _as_claim_dict(f.get("reference_span_m"), unit="m"),
            "c_m": _as_claim_dict(f.get("reference_chord_m"), unit="m"),
        },
        "wing_stations": wing_stations,
        "tail": tail,
        "mission": mission_block,
        "aero_assumptions": aero_block,
        "spar": spar_block,
    }
    return result
