# packages/cad — the editable reconstruction (Team A, A2)

The second of the two mandatory representations (architecture §2). Given `GeometryFeatures`
from `packages/ingest`, it builds a parametric CadQuery aircraft, exports a named STEP
assembly plus sidecars, verifies the export by reimporting it in a **fresh process**, and
measures how far it sits from the reference meshes.

It is an engineering reconstruction, never the manufacturer's CAD. Every part, artifact and
filename says so.

## API

```python
from dronebench_cad import reconstruct, export, reimport_check, fit_report, ReconParams

model  = reconstruct(features)                     # or reconstruct(params=ReconParams(...))
arts   = export(model, out_dir)                    # STEP + GLB + part_map/bom/changes JSON
checks = reimport_check(out_dir / "updated_reconstruction.step", model)
report = fit_report(model, manifest_or_reference_dir, features=features)
```

| Function | Returns |
|---|---|
| `reconstruct(features=None, params=None, part_ids=None)` | `CadModel` — named solids + the parameters that made them |
| `export(model, out_dir, changes=None, cause=...)` | `list[Artifact]` dicts with `sha256` |
| `reimport_check(step_path, expected, tolerances=None, timeout_s=120)` | `list[RoundTripCheck]` dicts; never raises on a bad STEP |
| `fit_report(model, reference, frame=None, samples=4000, seed=..., features=None)` | deviation numbers, `confirmed: false` |
| `ReconParams` / `load_params` / `dump_params` | the full editable parameter set, lossless through YAML |

`dronebench_cad/params.yaml` is the baseline parameter set for the Avenger. Edit it (or a
copy) and `reconstruct(params=load_params(path))` regenerates deterministically in ~2 s.

## What is and is not reconstructed

Built: wing (lofted from the measured stations, mirrored for the other side), two canted
V-tail panels, fuselage station envelope, spar tube, battery box, motor and propeller-sweep
envelopes, motor mount block, wing bay plate.

Not built: holes, latches, hinges, fasteners, print details, skin thickness, internal
structure, canopy/hatch split lines, the camera pod, blade geometry. The airfoil is a
**declared assumption** (NACA 4-digit, camber assumed, thickness from the measured
per-station t/c) — no section was identified. Spar, battery, motor and prop do not exist in
the source archive at all; they are synthetic demo envelopes and carry a mass only when a
curated BOM supplies one.

## Tests

```
.venv/bin/python -m pytest tests/cad -q
```

Tests that need the (git-ignored, unlicensed) vendor archive skip cleanly without it.
