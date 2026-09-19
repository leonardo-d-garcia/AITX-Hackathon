"""Validation harness for Lane C schemas.

Loads schemas from packages/contracts/lanec_schemas/<kind>.schema.json and validates
documents against them using jsonschema's Draft 2020-12 validator, with a referencing
Registry preloaded from every *.schema.json in that directory so relative $refs
(e.g. "claim.schema.json") resolve offline without any network access.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts" / "lanec_schemas"

_KIND_TO_FILE = {
    "geometry_features": "geometry_features.schema.json",
    "parts": "parts.schema.json",
    "design_manifest": "design_manifest.schema.json",
    "evaluation": "evaluation.schema.json",
    "simulation_run": "simulation_run.schema.json",
}

_registry_cache: Registry | None = None


def _build_registry() -> Registry:
    resources = []
    for path in _SCHEMA_DIR.glob("*.schema.json"):
        contents = json.loads(path.read_text())
        resource = Resource.from_contents(contents)
        # Register both under its declared $id (used by other schemas' $refs) and
        # under its bare filename (in case a $ref is written as a relative path).
        resources.append((contents.get("$id", path.name), resource))
        resources.append((path.name, resource))
    return Registry().with_resources(resources)


def _get_registry() -> Registry:
    global _registry_cache
    if _registry_cache is None:
        _registry_cache = _build_registry()
    return _registry_cache


def _schema_path(kind: str) -> Path:
    try:
        filename = _KIND_TO_FILE[kind]
    except KeyError:
        raise ValueError(
            f"unknown schema kind {kind!r}; expected one of {sorted(_KIND_TO_FILE)}"
        ) from None
    path = _SCHEMA_DIR / filename
    if not path.is_file():
        raise ValueError(f"schema file not found for kind {kind!r}: {path}")
    return path


def validate_lanec(kind: str, doc: dict[str, Any]) -> list[str]:
    """Validate `doc` against Lane C's schema for `kind`.

    Returns a list of human-readable error strings; an empty list means the
    document is valid.
    """
    schema = json.loads(_schema_path(kind).read_text())
    validator = Draft202012Validator(schema, registry=_get_registry())
    errors = []
    for error in sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(p) for p in error.absolute_path) or "<root>"
        errors.append(f"{location}: {error.message}")
    return errors


def assert_valid(kind: str, doc: dict[str, Any]) -> None:
    """Raise ValueError with the joined errors if `doc` does not satisfy the schema."""
    errors = validate_lanec(kind, doc)
    if errors:
        raise ValueError(
            f"{kind} failed Lane C schema validation ({len(errors)} error(s)):\n"
            + "\n".join(f"  - {e}" for e in errors)
        )
