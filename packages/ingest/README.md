# `dronebench_ingest` (deliverable A1)

Stage a mesh archive, QA it, let a human confirm what it means, then measure it.

```bash
.venv/bin/python -m dronebench_ingest.cli ingest vendor_assets/avenger --design-dir /tmp/avenger
.venv/bin/python -m dronebench_ingest.cli inspect --design-dir /tmp/avenger
.venv/bin/python -m dronebench_ingest.cli confirm --design-dir /tmp/avenger --units mm \
    --mirror x=0 --select wing3=Wings/wing3_12mm_hole.stl --select fuse3=Fuselage/fuse3.stl
.venv/bin/python -m dronebench_ingest.cli features --design-dir /tmp/avenger
.venv/bin/python -m dronebench_ingest.cli parts    --design-dir /tmp/avenger
.venv/bin/python -m dronebench_ingest.cli export-reference --design-dir /tmp/avenger --out ref.glb
```

JSON on stdout, logs on stderr. A non-zero exit means the command could not run; an *unconfirmed*
design is a valid report and exits 0 with an `ErrorEnvelope`.

## Layout a design directory ends up with

```
<design_dir>/sources/...                     byte-identical staged originals (never committed)
<design_dir>/revisions/rev-<12 hex>/         immutable, append-only
    design_manifest.json  parts.json  geometry_features.json  reference_meshes.glb
    revision_manifest.json                   sha256 of each artifact
```

The revision id is derived from the source hashes plus the confirmed choices, so re-confirming the
same thing returns the same revision instead of mutating it.

## What this package refuses to do

- publish any metric before `confirm` (units, axes, nose datum, one option per variant group)
- select a variant, a side or a mirror plane on your behalf
- turn mesh volume into mass: printed mass is `unknown` unless `--mass-model shell_estimate` is
  chosen explicitly, and then every claim carries the model's assumptions
- treat proximity as a functional connection: only declared mating/nesting pairs are recorded
- claim an exact airfoil, a material, a supplier, a price, or that the reconstruction is Titan CAD

`demo_bom.yaml` is hand-authored, labelled synthetic, and is the only source of bought components —
the archive contains no motors, batteries, spars or avionics.

## Consumers

- **A2 (CadQuery)**: `geometry_features.json` — wing stations root→tip in FRD metres, V-tail panels
  with `cant_rad`, fuselage station envelopes, and `design_manifest.json` for part identity.
- **A4 (viewer)**: `reference_meshes.glb` (one node per `part_id`, glTF Y-up, metres) plus
  `design_manifest.json` / `parts.json` for claims, status chips and evidence.
