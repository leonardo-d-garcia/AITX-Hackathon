# dronebench-adapters

Converts our design artifacts (`design_manifest.json`, `geometry_features.json`) into the
schema shapes Lane C's evaluator expects, and validates the result against
`packages/contracts/lanec_schemas/`.

## CLI

```
dronebench-export lanec --design DESIGN_DIR [--revision REV] [--out OUTDIR] \
    [--mission mission.json] [--spar spar.json]
```

Loads the given design revision via `dronebench_ingest`, converts it with
`dronebench_adapters.geometry.to_lanec_geometry` and
`dronebench_adapters.parts.to_lanec_parts` / `to_lanec_design_manifest`, validates each
output against Lane C's schemas, and writes `geometry_features.json`, `parts.json`, and
`design_manifest.json` into `OUTDIR` (default `<design>/lanec_export/<revision>/`).

Prints a JSON summary: `{"written": [...], "valid": bool, "errors": {...}}`.

Exit codes: `0` all outputs valid, `1` one or more outputs failed validation (errors are
printed), `2` usage error (bad design dir, or a converter isn't implemented yet).

## Validation

`dronebench_adapters.validate` exposes:

- `validate_lanec(kind, doc) -> list[str]` — human-readable error strings, empty if valid.
- `assert_valid(kind, doc)` — raises `ValueError` with the joined errors.

`kind` is one of `geometry_features`, `parts`, `design_manifest`, `evaluation`,
`simulation_run`.
