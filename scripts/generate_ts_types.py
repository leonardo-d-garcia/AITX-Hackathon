"""Generate TypeScript types from the JSON Schema bundle (architecture section 11).

"TypeScript types are generated from JSON Schema/OpenAPI; do not maintain hand-written lookalikes."

Run: ``python scripts/generate_ts_types.py``

Deliberately a small generator rather than a dependency on ``json-schema-to-typescript``: the
bundle is produced by our own Pydantic models, so it uses a narrow slice of JSON Schema, and a
hundred lines here costs less than a node toolchain step in the build.

The output is committed. A schema change that is not regenerated shows up as a failing test in
``tests/contract`` and as a diff in review, rather than as a type error in someone else's branch.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schema" / "dronebench.schema.json"
TARGET = ROOT / "apps" / "web" / "src" / "lib" / "contracts.gen.ts"

HEADER = """/**
 * Generated from schema/dronebench.schema.json. Do not edit by hand.
 *
 * Regenerate with:  python scripts/generate_ts_types.py
 *
 * Architecture section 11: the web app consumes generated types, never hand-written lookalikes.
 * A field that is `| null` here is a value the backend reports as genuinely unknown - render it as
 * unknown, never as zero.
 */

"""


def ts_name(name: str) -> str:
    """Schema definition names are already PascalCase; sanitise anything unusual."""
    return re.sub(r"[^0-9A-Za-z_]", "_", name)


def render_type(schema: dict[str, Any], defs: dict[str, Any], depth: int = 0) -> str:
    if "$ref" in schema:
        return ts_name(schema["$ref"].rsplit("/", 1)[-1])

    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            parts = [render_type(option, defs, depth) for option in schema[combinator]]
            unique: list[str] = []
            for part in parts:
                if part not in unique:
                    unique.append(part)
            return " | ".join(unique) if unique else "unknown"

    if "allOf" in schema and len(schema["allOf"]) == 1:
        return render_type(schema["allOf"][0], defs, depth)

    if "const" in schema:
        return json.dumps(schema["const"])

    if "enum" in schema:
        return " | ".join(json.dumps(value) for value in schema["enum"])

    kind = schema.get("type")

    if kind == "array":
        items = schema.get("items")
        prefix = schema.get("prefixItems")
        if prefix:
            # A fixed-length tuple, which is how Pydantic renders tuple[...].
            return "[" + ", ".join(render_type(item, defs, depth) for item in prefix) + "]"
        if items is None:
            return "unknown[]"
        inner = render_type(items, defs, depth)
        return f"({inner})[]" if " " in inner else f"{inner}[]"

    if kind == "object" or "properties" in schema:
        properties = schema.get("properties")
        if not properties:
            additional = schema.get("additionalProperties")
            if isinstance(additional, dict):
                return f"Record<string, {render_type(additional, defs, depth)}>"
            return "Record<string, unknown>"
        return render_object(schema, defs, depth)

    return {
        "string": "string",
        "integer": "number",
        "number": "number",
        "boolean": "boolean",
        "null": "null",
    }.get(kind, "unknown")


def render_object(schema: dict[str, Any], defs: dict[str, Any], depth: int) -> str:
    indent = "  " * (depth + 1)
    closing = "  " * depth
    # Every property, not just the schema's `required` set. Pydantic marks a field optional when
    # it has a default, but this bundle is generated in *serialization* mode and `model_dump`
    # emits every field - so on the wire they are all present. Marking them optional would make
    # consumers write `?? []` guards against a case the API cannot produce.
    lines = ["{"]
    for name, prop in schema.get("properties", {}).items():
        optional = ""
        description = prop.get("description")
        if description:
            wrapped = " ".join(description.split())
            lines.append(f"{indent}/** {wrapped} */")
        lines.append(f"{indent}{json.dumps(name)}{optional}: {render_type(prop, defs, depth + 1)};")
    lines.append(closing + "}")
    return "\n".join(lines)


def generate() -> str:
    bundle = json.loads(SCHEMA.read_text(encoding="utf-8"))
    defs: dict[str, Any] = bundle["$defs"]

    chunks = [HEADER]
    chunks.append(
        f"export const CONTRACT_VERSION = "
        f"{json.dumps(bundle.get('x-contract-version', '1.0'))} as const;\n\n"
    )

    for name in sorted(defs):
        schema = defs[name]
        alias = ts_name(name)
        description = schema.get("description")
        if description:
            chunks.append(f"/** {' '.join(description.split())} */\n")

        if "enum" in schema and "properties" not in schema:
            values = " | ".join(json.dumps(value) for value in schema["enum"])
            chunks.append(f"export type {alias} = {values};\n\n")
            continue

        if "properties" in schema or schema.get("type") == "object":
            body = render_object(schema, defs, 0)
            chunks.append(f"export interface {alias} {body}\n\n")
            continue

        chunks.append(f"export type {alias} = {render_type(schema, defs)};\n\n")

    return "".join(chunks)


def main() -> int:
    if not SCHEMA.is_file():
        print(
            f"{SCHEMA} is missing; run `python -m dronebench_contracts.schema schema` first",
            file=sys.stderr,
        )
        return 2
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    source = generate()
    TARGET.write_text(source, encoding="utf-8")
    exported = source.count("\nexport ")
    print(json.dumps({"written": str(TARGET.relative_to(ROOT)), "exports": exported}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
