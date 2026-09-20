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

.venv/bin/python -m dronebench_ingest.cli viewer --design-dir /tmp/avenger \
    [--reconstruction reconstruction.glb] [--out inspector.html]
```

`viewer` renders A4's standalone inspector (`packages/viewer`) from the revision's own artifacts;
it does not reimplement one. Pass `--reconstruction` once A2 has a GLB to overlay.

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

The GLB carries an explicit NORMAL attribute per primitive — glTF never computes normals, and a
primitive without them renders black in three.js. Vertices are split at edges sharper than 30 deg
so a printed part's hard edges are not smeared. That costs size: the Avenger's reference GLB is
about 19 MB for 580k triangles, and A4's self-contained inspector that embeds it is about 26 MB.

The revision id is derived from the source hashes, the confirmed choices and `PIPELINE_VERSION`, so
re-confirming the same thing returns the same revision instead of mutating it — and a change to what
the artifacts contain produces a new revision rather than leaving stale bytes behind a familiar id.

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
