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

### `fit_report()` shape

Two levels, on purpose. The **flat** level is the viewer contract (A4's inspector renders
it); the **detailed** level is for anyone reading the numbers directly.

```jsonc
{
  "rms_m": 0.0049, "max_m": 0.0251,            // flat: overall, both directions combined
  "per_part": [{"part_id": …, "rms_m": …, "max_m": …, "note": ""}],
  "note": "Not usable for engineering comparison until a human confirms…",
  "confirmed": false,                          // a human flips this, never this code
  "overall": {                                 // detailed, directional, explicit names
    "station_deviation_rms_m": …, "station_deviation_max_m": …,
    "reference_to_reconstruction_rms_m": …, "reconstruction_to_reference_rms_m": …,
    "surface_distance_max_m": …, "parts_compared": 6, "parts_without_reference": 5
  },
  "parts": {…}, "surfaces": {…}, "area": {…},  // per part, per station, planform areas
  "reference_dir": …, "reference_source": "design_manifest" | "directory",
  "reference_groups": {…}, "frame": {…}, "notes": [], "warnings": []
}
```

`rms_m` is the RMS over both directions' per-part RMS values; an uncompared part (a mirrored
occurrence, or the synthetic spar/battery/motor/prop) carries `null` numbers and says why in
`note`. `reference` may be a mesh directory, a staged `sources` root, a revision directory, a
design directory, a `design_manifest.json` path, or a `DesignManifest` — a manifest also
supplies the confirmed frame and the selected variants. Unresolvable references and
"nothing was compared" raise `ValueError`; pass `strict=False` for the soft report.

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
