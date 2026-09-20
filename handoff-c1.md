# Handoff C1 — UE5 / print-archive demo

**Date:** 2026-09-19
**Repo:** `leonardo-d-garcia/AITX-Hackathon`, branch `lane-c`
**Session:** plan + implement Path 2 as a *renderer*, not a plant.

This file is for the next agent or human. It records what landed on disk, what was verified, and what is left. Do not treat it as a claim that Unreal has been flown.

---

## One-sentence status

The shipping replay is a 30-part print-archive GLB in R3F, driven by a baked `simulation_run.json`. Unreal 5.8 has a project skeleton and editor Python scripts. **Nobody has opened the Unreal editor or eyeballed the browser this session.**

Last verified pytest line:

```
146 passed in 3.32s
```

Last verified web build: `npm run build` in `apps/web` succeeded (`tsc --noEmit && vite build`).

---

## Standing rules (do not regress)

- Frozen contracts: `design_manifest.json`, `parts.json`, `geometry_features.json`, `evaluation.json`, `simulation_run.json`. Do not change a schema without updating every consumer in the same change.
- Never invent a physical number. Missing → `unknown` + named field. Null is not zero.
- Synthetic fixtures in `fixtures/c/synthetic_*` and `conventional_tail_demo` are `source_kind: assumed`. They are not print-archive measurements. Do not relabel them.
- Simulation does not keep its own wing dimensions. Geometry comes from `geometry_features.json`.
- Unreal (and R3F) **replay**. They do not integrate forces, compute drag, or own aircraft state.
- `tests/contract/test_contracts.py::test_fixtures_are_not_labeled_avenger_or_falcon` greps **JSON file contents** under `fixtures/c/*/*.json`. Do not write the words `avenger` or `falcon` into those files. Folder name `titan_avenger_cad` is fine; `design_id` is `archive_fw_print`.
- Filename of the zip says VTOL. Geometry does not. Do not put VTOL on a slide.
- Pixel Streaming is forbidden for this demo. Mode A only (second window / alt-tab).
- Exactly one session may talk to Unreal Remote Control port **30010**. Only that session writes `Content/`.

---

## What this session did

### 0. Inputs read (not invented)

| Source | Finding |
|---|---|
| `titan_avenger_inventory.json` | 24 binary STLs, 580,404 triangles, native mm, Y aft, Z up, parts pre-assembled |
| `UE5-Grok-Titan-Avenger-Runbook.md` | Import identity; never fuse; 12 mm baseline / 16 mm after; Interchange not Datasmith |
| Zip `Titan+Avenger+(Fixed+Wing)+(VTOL+on+Profile) (1).zip` | Same 24 STLs. No STEP, BOM, mass, motor, battery, spar tube, or rotors |
| This machine | UE **5.8** at `C:\Program Files\Epic Games\UE_5.8`, RTX 5060, no `.uproject` at start |
| Contracts | `simulation_run` frozen, no `delta_a`/`delta_e`. Python validator was stricter than schema on `part_stress` |

A plan was written (session `plan.md`) locking: Mode A, STL→GLB outside Unreal, Python replay first, heatmap from `load_factor_n`, R3F as insurance.

### 1. CAD pipeline (P0) — done

New package `packages/cad/`:

- `titan_archive.py` — native mm → glTF m and FRD m, 30-occurrence plan, convert
- `build_fixture.py` — writes claim-shaped JSON from the inventory

CLIs:

```
.venv\Scripts\python.exe tools\convert_titan.py
.venv\Scripts\python.exe tools\convert_titan.py --wing3 wing3_16mm_hole
.venv\Scripts\python.exe tools\build_archive_fixture.py
```

Measured convert report (actually run):

| GLB | nodes | triangles | span_m |
|---|---|---|---|
| `fixtures/c/titan_avenger_cad/meshes/titan_avenger.glb` | 30 | **606,450** | 2.2245 |
| `fixtures/c/titan_avenger_cad/meshes/titan_avenger_16mm.glb` | 30 | 606,490 | 2.2245 |

**606,450 is correct.** The runbook’s 607,558 used `fuse3` triangle count by mistake while specifying baseline `fuse3_clean`. Do not “fix” the converter to match 607,558.

AABB length after glTF convert was **1.0013 m** (nose at native Y −403.07 through motor mount 598.27). Runbook “fuselage 0.9913 m” omitted the last 10 mm of the motor mount. Report 1.0013 if you cite the GLB bounds.

A copy for Vite: `apps/web/public/titan_avenger.glb` (~29 MB).

### 2. Print-archive fixture — done

`fixtures/c/titan_avenger_cad/` (JSON committed; meshes gitignored *if* ignore rules are applied — see leftovers):

| File | Notes |
|---|---|
| `design_manifest.json` | `design_id: archive_fw_print`, `revision_id: rev_archive_fw_001`, `representation: as_measured` |
| `geometry_features.json` | `b_m = 2.2245` cad, `S_m2 = 0.4199` exposed both sides no carry-through, MAC computed, V-tail cant from vtail1 AABB (~0.55 rad, **not** synthetic 0.698), `Do_m = 0.012` cad, `Di_m` unknown, `np_x_m` unknown |
| `parts.json` | 30 occurrences, every `mass_kg` unknown/null, positions from bbox centres in FRD |
| `part_map.json` | 30 keys, material name `unspecified`, status unknown |
| `simulation_run.json` | baked 60 s, `fidelity_tier: analytic`, `part_stress: {}` because Di unknown |

Mission / aero numbers in `geometry_features.mission` and `aero_assumptions` are **assumed** (cruise 15 m/s, rho, CD0, …). HUD must keep saying so. Pack Wh / power in the run are the plant defaults, labelled in `meta.assumptions` when cad-sourced span is used.

### 3. Plant / contracts consumers — done

- `packages/sim/mission.py` unwraps Claim objects (`reference.S_m2.value`, `tail.cant_rad`, …). Flat `{S,b,c,cant}` still works for synthetic tests.
- Unknown `spar.Di_m` and no route `sigma_root_mpa_n1` → **do not emit 41.2 MPa**. `part_stress` is `{}`.
- `packages/sim/validate.py` now allows empty `part_stress` (matches JSON schema). Non-empty keys still need non-empty sample lists.
- `packages/sim/frames.py` — **one** NED/FRD → three.js and UE conversion. Tests in `tests/sim/test_frame_conversion.py`.
- `packages/sim/__init__.py` re-exports `ned_to_three_m`, `ned_to_ue_cm`, `quat_frd_ned_to_three`, `quat_frd_ned_to_ue`.
- `dronebench simulate --route` optional JSON.

Do not bake Avenger-looking telemetry from the synthetic defaults (S=0.4, b=2.2, cant 40°).

### 4. R3F shipping viewport (P1) — code done, not eyeballed

- `apps/web/src/features/simulation/ReplayViewport.tsx` loads `/titan_avenger.glb`, keeps node names, poses from NED + `quatFrdNedToThree`, viridis from `load_factor_n` (not MPa), click → `onPartPick`. Falls back to placeholder boxes if the GLB 404s.
- `apps/web/src/telemetry.ts` ports the Python frame conversion.
- `PartCard.tsx`, `HeatmapLegend.tsx` wired in `App.tsx`.
- `apps/web/vite.config.ts` `@telemetry` → **CAD** `simulation_run.json` (not synthetic). `@airframe` → CAD GLB.
- Colormap PNG: `tools/colormap_viridis.png` and `apps/web/public/colormap_viridis.png`.

Run:

```
cd apps\web
npm run dev
```

Acceptance not yet done by a human: right turn banks **right**, click prints a real `part_id`, wing colour moves with `n` when scrubbing the 30–50 s turn.

### 5. Unreal skeleton (P2 files only) — not executed in editor

```
unreal/DroneBench/DroneBench.uproject     UE 5.8, plugins: PythonScriptPlugin, RemoteControl, InterchangeEditor
unreal/DroneBench/Config/DefaultRemoteControl.ini   port 30010, remote Python
unreal/DroneBench/Config/DefaultEngine.ini          no CPU throttle when unfocused
unreal/DroneBench/Scripts/tag_parts.py
unreal/DroneBench/Scripts/build_heatmap_material.py
unreal/DroneBench/Scripts/build_scene.py
unreal/DroneBench/Scripts/verify_scene.py
unreal/DroneBench/Scripts/replay.py                 load JSON, ned_to_ue_cm, apply_frame, illustrative ailerons
tools/ue.py
tools/launch_demo.bat
UNREAL.md
```

`replay.py` conversion samples were checked **outside** the editor against `packages/sim/frames.py`. Actor/MPC binding was not exercised.

There is **no** `Content/`, no imported GLB, no tagged actors, no PIE session.

### 6. Tests added

- `tests/cad/test_titan_archive.py`
- `tests/cad/test_archive_fixture.py`
- `tests/sim/test_frame_conversion.py`
- `tests/sim/test_mission_cad_geometry.py`

Python: `C:\Users\leona\Downloads\AITX Hackathon\.venv\Scripts\python.exe` (venv from Store 3.11.9; trimesh installed).

---

## What is left

Ordered. Stop at the Unreal 45-minute gate if it is red. R3F is the demo if Unreal dies.

### A. Re-apply session edits that did not stick

These were written by subagents and are **not** in the tree now. Do them before a public commit:

1. **`AGENT.md` Unreal section** still says “Out of this pass.” Replace with Path 2 authorized as renderer only (Mode A, Python replay first, port 30010 lock, never fuse, unknown stays unknown). Keep frozen-contract / physics-honesty / fidelity / verification blocks.
2. **`.gitignore`** still lacks zip / glb / Unreal binary ignores. Append:

   ```
   Titan*.zip
   *Avenger*.zip
   *.glb
   fixtures/c/titan_avenger_cad/meshes/
   unreal/**/Binaries/
   unreal/**/Intermediate/
   unreal/**/Saved/
   unreal/**/DerivedDataCache/
   unreal/**/Content/
   ```

   Then confirm the 29 MB GLBs and the original zip will not be committed. License on the zip is unknown.
3. **`pyproject.toml`** optional extra `cad = ["trimesh>=4"]` was requested and is not present.
4. **`README.md`** still has no “Mission replay demo” section.

### B. Browser verification (15 min) — required before calling P1 done

```
cd apps\web
npm run dev
```

- Play / pause / 0.5× / 2× / scrub.
- At t ≈ 30–50 s, right-wing-down on screen (FRD +roll).
- Click `aileron_L`, `motor_mount`, `hatch_1` → unknown mass/material card.
- Header: **Engineering estimate**.
- Heatmap legend: colour is **n**, not MPa.

No browser tools were used this session. `npm run build` is not that check.

### C. Unreal editor gate (45 min hard stop) — not started

1. `tools\launch_demo.bat` or open `unreal\DroneBench\DroneBench.uproject` in UE 5.8.
2. Confirm Remote Control listening on **30010**.
3. Gate:

   ```
   echo import unreal; print(unreal.SystemLibrary.get_engine_version()) | .venv\Scripts\python.exe tools\ue.py
   ```

   If this is red at 45 minutes, **abandon Unreal**. Do not debug plugins into hour two.
4. Import `titan_avenger.glb` with **transforms preserved**. Combine / auto-centre / fit-to-grid **off**.
5. Verify: 30 actors, span ≈ **222 cm**, canopy above, motor mount **aft**, not inside-out.
6. Run Scripts in order: `tag_parts.py` → `build_heatmap_material.py` → `build_scene.py` → `verify_scene.py` → `replay.py`.
7. Watch: commanded right turn banks **right**. Record MP4 immediately (`recorded-run.mp4`).
8. Optional: import 16 mm GLB and swap only `wing_3_L` / `wing_3_R`.

First C++ class (stretch) needs the editor **closed** for a cold `Build.bat`. Do not start that unless replay already looks right.

### D. Demo packaging

- Dual window: R3F on 5173 + Unreal PIE.
- Talk track is in the session plan: honesty → engineering estimate → fly the turn → 12/16 hole → “not 6DOF, not VTOL, not a bench test.”
- Freeze all Unreal work at T−45 min.

### E. Out of scope / stretch (do not start unless C is green and >2 h remain)

- C++ `ATelemetryReplayActor`
- Pixel Streaming
- VSPAERO C4/C5 **on this print-archive `geometry_hash`**. C3/C4 notes already exist for the synthetic/OpenVSP worker path (`docs/openvsp-c4-validation.md`). Do not relabel this fixture `fidelity_tier: vspaero` without a real run for its hash.
- FastAPI / Supabase write-back. Part pick is on-screen only.
- Adding `delta_a` / `delta_e` to `simulation_run` (schema frozen). Ailerons in Unreal are a **display mapping**.

---

## Commands cheat sheet

```bat
cd /d C:\Users\leona\Downloads\AITX Hackathon
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m dronebench simulate --geometry fixtures/c/titan_avenger_cad/geometry_features.json --parts fixtures/c/titan_avenger_cad/parts.json --out fixtures/c/titan_avenger_cad/simulation_run.json
.venv\Scripts\python.exe tools\convert_titan.py
copy fixtures\c\titan_avenger_cad\meshes\titan_avenger.glb apps\web\public\titan_avenger.glb
cd apps\web && npm run dev
tools\launch_demo.bat
```

---

## Honesty table (keep on the HUD)

| Quantity | Status |
|---|---|
| Span, taper, V-tail AABB cant, hole Do, part meshes | known, cad |
| S = 0.4199 m² exposed, both sides, no carry-through | known, convention set once |
| Mass, material, Di, E, motor, battery, pack Wh | unknown |
| Cruise, rho, CD0, pack/power used in the run | assumed, labelled |
| Trajectory / bank / n | prescribed kinematics, not 6DOF |
| σ MPa | unknown (no Di) — colour is n |
| Fidelity | analytic → UI “Engineering estimate” |
| VTOL | not applicable |

If a judge asks what the simulation is: a reduced-order mission model on measured print geometry, rendered in a game engine. A prettier picture of a model is still a picture of a model.
