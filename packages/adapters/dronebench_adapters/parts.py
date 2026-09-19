"""Adapter: our DesignManifest (Team A/Avenger CAD pipeline) -> Lane C's
parts.schema.json and design_manifest.schema.json
(packages/contracts/lanec_schemas/).

Lane C's `parts.json` occurrence shape is much flatter than ours: `part_id`,
`type` (a narrow enum), `locked`, a `mass_kg` Claim and a `position_frd_m`
Claim-triple. It has no room for our `side`/`mirror_of`/`category` fields
(the schema is `additionalProperties: false`), so those get folded into the
adapter's mapping logic and surfaced as notes on the design_manifest instead
of being silently dropped.

Rules preserved from our source data:
- Our Avenger mass_kg is genuinely unknown for every printed part -> it must
  stay `value: null, status: "unknown"`, never a fabricated 0.
- Position comes from `T_parent_from_local`'s translation column (already
  FRD metres in our pipeline), tagged `source_kind: "cad"` since it comes
  straight off the reconstructed geometry, not a placement guess.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Union

from dronebench_contracts.models import Claim, DesignManifest, PartOccurrence

# Our `category` values that map straight onto Lane C's occurrence `type` enum.
_CATEGORY_TO_TYPE = {
    "motor": "motor",
    "prop": "prop",
    "esc": "esc",
    "battery": "battery",
    "servo": "servo",
    "fc": "fc",
    "rx": "rx",
    "gps": "gps",
    "spar": "spar",
    "wing": "wing",
    "fuselage": "fuselage",
    "vtail": "tail",
    "tail": "tail",
    "aileron": "surface",
    "ruddervator": "surface",
    "surface": "surface",
    "hinge": "hinge",
    "linkage": "linkage",
    "fastener": "fastener",
    "payload": "payload",
}
# Everything else (canopy, mount, hatch, ...) has no equivalent in Lane C's
# narrower enum and falls back to "other".
_FALLBACK_TYPE = "other"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _claim_dict(claim: Union[Claim, Mapping[str, Any], None], *, unit: str) -> dict:
    """Convert one of our mass/local_com Claims into Lane C's claim shape."""
    if claim is None:
        data: dict = {}
    elif isinstance(claim, Claim):
        data = claim.model_dump()
    else:
        data = dict(claim)

    status = data.get("status") or "unknown"
    if status not in ("known", "estimated", "unknown", "conflicted", "not_applicable"):
        status = "unknown"
    # Lane C has no "conflicted" state for a scalar; treat it as unknown
    # rather than picking a value that isn't actually agreed on.
    if status == "conflicted":
        status = "unknown"

    value = data.get("value")
    if status == "unknown" or value is None:
        value = None
        status = "unknown"

    source_kind = data.get("source_kind") or "assumed"
    if source_kind not in ("cad", "bom", "manual", "catalog", "computed", "inferred", "assumed"):
        source_kind = "assumed"

    return {
        "value": value,
        "unit": data.get("unit") or unit,
        "status": status,
        "source_kind": source_kind,
        "evidence_ids": list(data.get("evidence_ids") or []),
        "assumptions": list(data.get("assumptions") or []),
    }


def _position_claim(value: float) -> dict:
    """A position component read straight off T_parent_from_local -- this is
    a real CAD measurement, not an assumption."""
    return {
        "value": float(value),
        "unit": "m",
        "status": "known",
        "source_kind": "cad",
        "evidence_ids": [],
        "assumptions": ["translation component of T_parent_from_local"],
    }


def _occurrence_type(category: Optional[str]) -> str:
    return _CATEGORY_TO_TYPE.get((category or "").lower(), _FALLBACK_TYPE)


def to_lanec_parts(manifest: Union[DesignManifest, Mapping[str, Any]]) -> dict:
    """Our DesignManifest.parts -> Lane C's parts.json {frame, occurrences[]}."""
    parts = _get(manifest, "parts") or []

    occurrences = []
    for part in parts:
        category = _get(part, "category")
        transform = _get(part, "T_parent_from_local")
        tx, ty, tz = transform[0][3], transform[1][3], transform[2][3]

        occurrence = {
            "part_id": _get(part, "part_id"),
            "type": _occurrence_type(category),
            "locked": bool(_get(part, "locked", False)),
            "mass_kg": _claim_dict(_get(part, "mass_kg"), unit="kg"),
            "position_frd_m": {
                "x_m": _position_claim(tx),
                "y_m": _position_claim(ty),
                "z_m": _position_claim(tz),
            },
        }
        occurrences.append(occurrence)

    return {
        "schema_version": 1,
        "frame": "FRD",
        "occurrences": occurrences,
    }


def to_lanec_design_manifest(manifest: Union[DesignManifest, Mapping[str, Any]]) -> dict:
    """Our DesignManifest header -> Lane C's design_manifest.json."""
    design_id = _get(manifest, "design_id")
    revision_id = _get(manifest, "revision_id")
    title = _get(manifest, "title") or design_id

    parts = _get(manifest, "parts") or []
    categories = sorted({_get(p, "category") for p in parts if _get(p, "category")})
    unmapped = sorted(
        {
            _get(p, "category")
            for p in parts
            if _occurrence_type(_get(p, "category")) == _FALLBACK_TYPE and _get(p, "category")
        }
    )
    mirrored = [
        f"{_get(p, 'part_id')} (mirror_of={_get(p, 'mirror_of')}, side={_get(p, 'side')})"
        for p in parts
        if _get(p, "mirror_of")
    ]

    notes_lines = [
        f"Converted from Avenger CAD pipeline design '{title}' ({design_id}/{revision_id}); "
        f"{len(parts)} part occurrences.",
        f"Source categories seen: {', '.join(categories) if categories else 'none'}.",
    ]
    if unmapped:
        notes_lines.append(
            "Categories with no direct Lane C type equivalent, mapped to 'other': "
            + ", ".join(unmapped)
            + "."
        )
    if mirrored:
        notes_lines.append(
            "Lane C's occurrence schema has no side/mirror_of fields, so mirrored-part "
            "provenance is recorded here instead of on the occurrence: " + "; ".join(mirrored) + "."
        )

    return {
        "schema_version": 1,
        "design_id": design_id,
        "revision_id": revision_id,
        "representation": "editable_reconstruction",
        "frame": "FRD",
        "units": "SI",
        "notes": " ".join(notes_lines),
    }
