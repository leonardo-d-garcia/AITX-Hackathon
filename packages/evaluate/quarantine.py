"""Quarantine implausible inputs. Retain the raw value; never clamp in place."""

from __future__ import annotations

from typing import Any

from .models import Claim, make_claim

# Policy thresholds from the frozen evaluator contract, not aero coefficients.
LIPO_WH_PER_KG = 200.0
LIION_WH_PER_KG = 270.0


def quarantine_input(
    value: Any,
    *,
    field: str,
    reason: str,
    unit: str | None = None,
    missing_fields: list[str] | None = None,
) -> Claim:
    """Keep the raw value and mark the claim conflicted. Never mutate the source."""
    if isinstance(value, Claim):
        return value.model_copy(
            update={
                "status": "conflicted",
                "source": field or value.source,
                "notes": reason,
                "unit": unit if unit is not None else value.unit,
                "missing_fields": list(missing_fields or value.missing_fields),
            }
        )
    return make_claim(
        value,
        "conflicted",
        unit=unit,
        source=field,
        notes=reason,
        missing_fields=missing_fields,
    )


def chemistry_wh_per_kg_limit(chemistry: str | None) -> float:
    chem = (chemistry or "").lower().replace("-", "").replace("_", "").replace(" ", "")
    if "liion" in chem or chem in {"lion", "nmc", "nca"}:
        return LIION_WH_PER_KG
    return LIPO_WH_PER_KG


def specific_energy_wh_kg(energy_wh: float, mass_kg: float) -> float | None:
    if mass_kg is None or mass_kg <= 0:
        return None
    return energy_wh / mass_kg
