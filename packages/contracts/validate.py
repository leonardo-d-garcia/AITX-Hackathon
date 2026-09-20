"""Load JSON Schemas and enforce Claim invariants JSON Schema cannot express."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource

from .claim import iter_claims

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

SCHEMA_FILES = {
    "claim": "claim.schema.json",
    "design_manifest": "design_manifest.schema.json",
    "parts": "parts.schema.json",
    "geometry_features": "geometry_features.schema.json",
    "part_map": "part_map.schema.json",
    "evaluation": "evaluation.schema.json",
    "simulation_run": "simulation_run.schema.json",
}


def load_schema(name: str) -> dict[str, Any]:
    filename = SCHEMA_FILES.get(name, name)
    path = SCHEMA_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"unknown schema {name!r} ({path})")
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def registry() -> Registry:
    resources: list[tuple[str, Resource]] = []
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents)
        resources.append((path.name, resource))
        schema_id = contents.get("$id")
        if isinstance(schema_id, str):
            resources.append((schema_id, resource))
    return Registry().with_resources(resources)


def get_validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    return Draft202012Validator(schema, registry=registry())


def validate_instance(name: str, instance: Any) -> None:
    get_validator(name).validate(instance)
    assert_claim_invariants(instance)
    assert_all_finite(instance)


def assert_all_finite(obj: Any, path: str = "$") -> None:
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            assert_all_finite(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            assert_all_finite(value, f"{path}[{i}]")
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        if not math.isfinite(obj):
            raise ValidationError(f"non-finite number at {path}")


def assert_claim_invariants(obj: Any) -> None:
    for path, claim in iter_claims(obj):
        value = claim.get("value")
        if value is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
            if not math.isfinite(value):
                raise ValidationError(f"non-finite claim value at {path}")
        rng = claim.get("assumption_range")
        if rng is None:
            continue
        if value is None:
            raise ValidationError(f"assumption_range present with null value at {path}")
        try:
            low = rng["low"]
            nominal = rng["nominal"]
            high = rng["high"]
        except (TypeError, KeyError) as exc:
            raise ValidationError(f"malformed assumption_range at {path}") from exc
        for label, item in (("low", low), ("nominal", nominal), ("high", high)):
            if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
                raise ValidationError(f"non-finite assumption_range.{label} at {path}")
        if not (low <= nominal <= high):
            raise ValidationError(
                f"assumption_range must satisfy low <= nominal <= high at {path}"
            )
