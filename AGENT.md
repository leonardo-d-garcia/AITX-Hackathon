# Lane C agent instructions

Repo: `leonardo-d-garcia/AITX-Hackathon`, branch `lane-c`.
This is a greenfield evaluator. There is no 217-test `~/Coding/dronebench` tree.
The suite we write is the suite. Paste the pytest summary line. A red suite is not done.

## Frozen contracts

`design_manifest.json`, `parts.json`, `geometry_features.json`, `evaluation.json`, `simulation_run.json`.
Do not change a schema without saying so explicitly and updating every consumer in the same change.

## Physics honesty

Never invent a physical number. No aerodynamic coefficient, mass, density, cant angle or material property may be filled from your own knowledge. If a value is missing, return unknown and name the missing field.

Synthetic fixtures in `fixtures/c/` are explicitly `source_kind: assumed`. They are not Avenger measurements. Do not relabel them as measured.

Unknown is a valid result. Null is not zero.

Simulation does not keep its own copy of the wing dimensions. Geometry comes from `geometry_features.json`, always.

## Fidelity

- No solver run for this exact `geometry_hash` → `fidelity_tier: analytic`, UI "Engineering estimate"
- Real VSPAERO run for this exact hash → `fidelity_tier: vspaero`, UI "VSPAERO analysis + mission model"
- Never compare an analytic baseline against a vspaero candidate. Raise `FidelityMismatch`.
- Do not count induced drag twice. Analytic polar already has an induced term; solver-informed path *replaces* lift and induced drag only.
- Stability stays `unknown` unless VSPAERO derivatives were actually computed and validated. Do not paper over with a wing quarter-chord guess. Do not add AVL.

## Unreal

Out of this pass. Unreal is a renderer, not a plant. Do not write flight dynamics in Unreal or in the R3F viewport.

## Verification

Run the test suite before reporting done. Paste the summary line. Report what you actually verified, not what you expect to be true.

Timeboxes are hard stops. Report state at the stop and do not continue.
