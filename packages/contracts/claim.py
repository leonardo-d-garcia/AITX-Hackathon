"""Claim helpers shared by fixtures, tests, and consumers."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, MutableMapping

CLAIM_STATUSES = (
    "known",
    "estimated",
    "unknown",
    "conflicted",
    "not_applicable",
)
SOURCE_KINDS = (
    "cad",
    "bom",
    "manual",
    "catalog",
    "computed",
    "inferred",
    "assumed",
)

CLAIM_KEYS = frozenset(
    {
        "value",
        "unit",
        "status",
        "source_kind",
        "evidence_ids",
        "assumptions",
        "assumption_range",
    }
)


def make_claim(
    value: float | None,
    unit: str,
    *,
    status: str = "known",
    source_kind: str = "assumed",
    evidence_ids: Iterable[str] | None = None,
    assumptions: Iterable[str] | None = None,
    assumption_range: tuple[float, float, float] | Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build a Claim dict. Omits assumption_range when value is null."""
    claim: dict[str, Any] = {
        "value": value,
        "unit": unit,
        "status": status,
        "source_kind": source_kind,
        "evidence_ids": list(evidence_ids or []),
        "assumptions": list(assumptions or []),
    }
    if assumption_range is not None:
        if value is None:
            raise ValueError("assumption_range must be omitted when value is null")
        if isinstance(assumption_range, Mapping):
            low = assumption_range["low"]
            nominal = assumption_range["nominal"]
            high = assumption_range["high"]
        else:
            low, nominal, high = assumption_range
        claim["assumption_range"] = {
            "low": low,
            "nominal": nominal,
            "high": high,
        }
    return claim


def is_claim(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    keys = set(obj)
    if not {"value", "unit", "status", "source_kind", "evidence_ids", "assumptions"} <= keys:
        return False
    return keys <= CLAIM_KEYS


def iter_claims(
    obj: Any, path: str = "$"
) -> Iterable[tuple[str, MutableMapping[str, Any]]]:
    if is_claim(obj):
        yield path, obj
        return
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            yield from iter_claims(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from iter_claims(value, f"{path}[{i}]")
