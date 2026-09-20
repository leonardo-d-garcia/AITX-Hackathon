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

Unreal is a renderer, not a plant. Do not write flight dynamics in Unreal or in the R3F viewport.

- Path 2 is authorized: Mode A only (second window / alt-tab). Pixel Streaming is forbidden.
- Python replay first. Do not start a C++ `ATelemetryReplayActor` unless replay already looks right and the editor is closed for a cold `Build.bat` (stretch; skip unless asked).
- Exactly one session may talk to Remote Control port 30010. Only that session writes `unreal/DroneBench/Content/`.
- Never fuse or combine the 30 part meshes. Import with identity / transforms preserved; combine, auto-centre, and fit-to-grid off.
- Unknown stays unknown. Null is not zero. Do not invent mass, Di, material, motor, or battery.
- 45-minute editor gate: if Remote Control + `import unreal; print(unreal.SystemLibrary.get_engine_version())` via `tools/ue.py` is still red at 45 minutes, abandon Unreal. R3F is the shipping fallback.
- Kill Path 2 on: physics in UE, two Content writers, inverted aircraft after two conversion attempts, Pixel Streaming, or T-45 min.

## Verification

Run the test suite before reporting done. Paste the summary line. Report what you actually verified, not what you expect to be true.

Timeboxes are hard stops. Report state at the stop and do not continue.
