# Lane C progress — what is on `lane-c`

Date: 2026-09-19
Repo: [leonardo-d-garcia/AITX-Hackathon](https://github.com/leonardo-d-garcia/AITX-Hackathon)
Branch: `lane-c`

This is the snapshot of **committed** Lane C work so other lanes can start against a real contract instead of guessing. It is not a plan; the plan lives in `docs/DroneBench-LaneC-OpenVSP-and-UE5.md`.

HEAD / `origin/lane-c`: `0762eb2` — C5: VSPAERO polar wired into `evaluate_revision`.

Verified on this machine (committed tests only): **`123 passed in 1.84s`** (`pytest` on Windows Python 3.11.9). That is the suite. There is no second 217-test tree.

---

## What Lane C is

Lane C scores a design revision and emits a mission replay. It does **not** edit the aircraft. An outside agent (Lane A / a coding agent) changes CAD or BOM, then Lane C re-scores.

Two outputs other lanes consume:

1. `evaluation.json` — metrics, gate checks, fidelity label, hashes, assumptions
2. `simulation_run.json` — time-series telemetry for the R3F viewport and (later) Unreal

Unreal is a renderer, not a plant. Do not write flight dynamics in Unreal or in the R3F viewport.

---

## How to get it running

```bash
git checkout lane-c
python -m pip install -e ".[dev]"
python -m pytest
```

```bash
python -m dronebench evaluate \
  --geometry fixtures/c/synthetic_vtail_demo/geometry_features.json \
  --parts fixtures/c/synthetic_vtail_demo/parts.json \
  --design-manifest fixtures/c/synthetic_vtail_demo/design_manifest.json \
  --solver docs/openvsp-c4-sweep-summary.json \
  --out evaluation.json

python -m dronebench simulate \
  --geometry fixtures/c/synthetic_vtail_demo/geometry_features.json \
  --parts fixtures/c/synthetic_vtail_demo/parts.json \
  --out simulation_run.json

python -m dronebench doctor   # OpenVSP/VSPAERO status (needs WSL; see C3)
```

R3F shipping viewport (placeholder airframe, baked fallback telemetry):

```bash
cd apps/web
npm install
npm run dev     # http://localhost:5173
```

The viewport aliases `@telemetry` to `fixtures/c/synthetic_vtail_demo/simulation_run.json`. Play / pause / 0.5× 1× 2× / scrub are wired. Fidelity label in the header is **"Engineering estimate"** for `analytic` and **"VSPAERO analysis + mission model"** for `vspaero`.

---

## Frozen contracts — do not fork these

JSON Schema is the source of truth. Changing a schema requires updating every consumer in the same change.

| File Lane A writes | Schema | Notes |
|---|---|---|
| `design_manifest.json` | `packages/contracts/schemas/design_manifest.schema.json` | `design_id`, `revision_id`, `representation`, FRD, notes |
| `parts.json` | `packages/contracts/schemas/parts.schema.json` | `{frame, occurrences[]}`. Mass and position are **Claims** |
| `geometry_features.json` | `packages/contracts/schemas/geometry_features.schema.json` | FRD metres, radians. `reference.S_m2` / `b_m` / `c_m` **exactly once**. Right-wing stations only (`y >= 0`); left wing is the implied mirror |
| `part_map.json` | `packages/contracts/schemas/part_map.schema.json` | `part_id` → name, mesh node, material provenance |

| File Lane C writes | Schema | Consumed by |
|---|---|---|
| `evaluation.json` | `packages/contracts/schemas/evaluation.schema.json` | Lane B / UI |
| `simulation_run.json` | `packages/contracts/schemas/simulation_run.schema.json` | R3F now; Unreal later |

Every numeric field is a **Claim** (`packages/contracts/schemas/claim.schema.json`):

```json
{
  "value": 2.2,
  "unit": "m",
  "status": "known",
  "source_kind": "assumed",
  "evidence_ids": [],
  "assumptions": ["synthetic demo assumption; not a measurement"],
  "assumption_range": { "low": 2.0, "nominal": 2.2, "high": 2.4 }
}
```

Rules other lanes must honour:

- `value` may be `null`. Null is **not** zero. Status `unknown` ⇒ value is null.
- `source_kind` is one of: `cad`, `bom`, `manual`, `catalog`, `computed`, `inferred`, `assumed`.
- `assumption_range` is a propagated input band (`low <= nominal <= high`), not a confidence interval. Omit it when `value` is null.
- Frame is **FRD** (X forward, Y right, Z down). Lengths in metres, angles in radians, mass in kilograms.
- Do not invent a physical number. If a field is missing, emit `unknown` and name the field.

Python helpers: `packages/contracts/validate.py` (`validate_instance("evaluation", doc)`, etc.).

---

## Task status (committed)

### Done

| Task | What landed | Where |
|---|---|---|
| Repo decision | Lane C is this repo, this branch. Not a second `dronebench` tree | `docs/decisions/repo-boundary.md`, `AGENT.md` |
| Scaffold | `packages/{contracts,evaluate,sim,openvsp_worker,dronebench}`, pytest, pyproject | `c2a8fc7` |
| C1 unknowns / quarantine / ranges | Null mass → CG `unknown` (not 0). Implausible battery energy stays raw and is `conflicted`, not clamped. `assumption_range` ordered | `packages/evaluate/`, `tests/physics/test_claims.py` |
| C2 V-tail | Two canted panels. Conventional tail-volume heuristics are `not_applicable` on a V-tail, never `fail`. Missing `cant_rad` → `unknown` | `packages/evaluate/physics.py`, `tests/physics/test_vtail.py` |
| Contracts + fixtures | Schemas frozen. Two **assumed** demos, not Avenger measurements | `packages/contracts/schemas/`, `fixtures/c/` |
| U0 telemetry | 60 s prescribed mission: straight, climb, coordinated right turn. Energy net of reserve. Right-wing-down is positive FRD +x roll. Fallback file committed | `packages/sim/`, `fixtures/c/synthetic_vtail_demo/simulation_run.json`, `tests/sim/` |
| R3F viewport | Replay of the fallback file. Placeholder geometry (not Titan meshes). NED→three.js at `nedToThree` | `apps/web/` |
| CLI | `python -m dronebench {evaluate,simulate,doctor}` | `packages/dronebench/` |
| C3 OpenVSP gate | OpenVSP **3.51.3** + VSPAERO **7.2.2** on **WSL Ubuntu 26.04, Python 3.14 (cp314)**. Windows 3.11 cannot import the wheel | `docs/openvsp-c3-report.md`, `packages/openvsp_worker/` |
| C4 generate / sweep / validate | Aircraft built from `geometry_features.json` (parameterized wing + V-tail, **not** triangle-mesh import). Alpha sweep −2, 0, 2, 4, 6 deg at 15 m/s. All C4 checks PASS with numbers | `docs/openvsp-c4-validation.md`, `packages/openvsp_worker/` |
| C5 consume polar | `evaluate_revision(..., solver_result=)` interpolates CDi from the C4 polar at trim CL and **replaces** analytic induced drag. Profile / fuselage / interference stay analytic. Hash mismatch stays `analytic`. Mixed-tier compare raises `FidelityMismatch`. Static margin stays `unknown` (C4 computed no derivatives). CLI `--solver` loads the C4 JSON | `0762eb2`, `packages/evaluate/`, `packages/dronebench/cli.py`, `tests/physics/test_aero_fidelity.py` |
| Dump alignment | Evaluator JSON matches `evaluation.schema.json` (check names, Claim `source_kind`, `meta`) | `9a22ae6` |

### Not done (do not wait for these)

| Item | Status |
|---|---|
| Unreal (U1–U5) | **Out of this pass.** No UE project on the branch. Runbook at `UE5-Grok-Titan-Avenger-Runbook.md` is **untracked** |
| Titan / Avenger CAD ingest | Zip + `packages/cad/` + `titan_avenger_inventory.json` are **untracked**. Fixtures are synthetic |
| `packages/sim/frames.py` | Untracked NED→Three / NED→UE helpers. Committed conversion for R3F is `apps/web/src/telemetry.ts` (`nedToThree`) |
| Climb / static margin / CLmax from VSPAERO | Climb stays `unknown` without excess power. Static margin stays `unknown` without validated derivatives. VSPAERO linear lift does **not** set `CLmax` |
| FastAPI / Supabase | Not in this repo. Unreal/UI write-back is a later lane |
| Real Avenger numbers | Do not relabel `fixtures/c/*` as measured. `source_kind` is `assumed` |

---

## Fixtures you can use today

Both under `fixtures/c/`. Every numeric Claim is `source_kind: assumed`.

```
fixtures/c/synthetic_vtail_demo/
  design_manifest.json
  geometry_features.json     # layout: vtail, cant_rad present
  parts.json
  parts_conflicted.json      # quarantine demo
  part_map.json
  simulation_run.json        # U0 fallback, viewport default

fixtures/c/conventional_tail_demo/
  design_manifest.json
  geometry_features.json     # layout: conventional
  parts.json
  part_map.json
```

Reference quantities on the V-tail demo (assumed, not Titan):

- `S = 0.4 m²`, `b = 2.2 m`, `c = 0.2 m`
- cruise `15 m/s`, altitude `120 m`, `rho = 1.225`

C4 polar (VSPAERO, last wake iteration) for that geometry hash:

| alpha_deg | CL | CDi |
|---|---|---|
| −2 | −0.3057 | 0.00282 |
| 0 | −0.0770 | 0.00040 |
| 2 | 0.1515 | 0.00099 |
| 4 | 0.3797 | 0.00458 |
| 6 | 0.6067 | 0.01113 |

`geometry_hash` for that run: `f0d361e699ec0a56c4664ac82a5489be8708a0a6c52a2bdca77909690a25ce1c`

---

## Evaluator behaviour teammates should rely on

Public entry: `from evaluate import evaluate_revision, compare_evaluations, FidelityMismatch`

```python
evaluation = evaluate_revision(
    geometry,          # geometry_features.json
    parts,             # parts.json or {occurrences: [...]}
    mission=None,      # defaults to geometry["mission"]
    solver_result=None,
    design_manifest=None,
)
```

- No solver run for this exact `geometry_hash` → `meta.fidelity_tier = "analytic"`
- Real VSPAERO result with matching hash and finite CL/CDi → `"vspaero"`
- `compare_evaluations(analytic, vspaero)` raises `FidelityMismatch`. Recompute both sides at one tier before showing a delta
- Solver path **replaces** lift and induced drag. Analytic polar already has an induced term; do not add CDi on top
- Gate checks dump to the contract names: `tail_volume_horizontal`, `tail_volume_vertical`, `servo_torque`, `propulsion_chain`, `control_chain`, `vtail_or_tail_layout`, plus stall / climb / spar / currents / payload / clearance / static_margin
- Statuses: `pass`, `fail`, `unknown`, `not_applicable`, `conflicted`

Mission plant: `from sim import simulate_mission`. Prescribed route, not 6DOF. Geometry always comes from `geometry_features.json` (the sim does not keep its own wing dimensions). `energy_wh_remaining` is usable energy **after** the mission reserve is withheld.

---

## OpenVSP notes (if you touch Path 1)

Bindings live in WSL, not Windows:

- Distro: Ubuntu 26.04
- Interpreter: `/root/openvsp-c3/venv/bin/python` (3.14, ABI `cp314`)
- Worker: `packages/openvsp_worker` execs that venv via `wsl`. Do not `import openvsp` into Windows Python 3.11.9
- Generate from `geometry_features.json`. Do not import Avenger STL/GLB into VSPAERO
- FRD → OpenVSP: `(x, y, z)_FRD → (−x, y, −z)`
- Alpha on this 3.51.3 build is **degrees** on `VSPAEROSweep`

`python -m dronebench doctor` prints install status as JSON.

---

## What other lanes should do now

**Lane A (CAD / BOM / geometry)**

- Emit the four input JSON files against the schemas above
- Keep FRD + metres + Claim-wrapped numbers
- Right-wing stations only
- Put `reference.S_m2 / b_m / c_m` once; do not duplicate them on the wing
- If you do not have a cant angle for a V-tail, leave it unknown — Lane C will not invent it
- A GLB for the viewport can land later at `fixtures/c/titan_avenger_cad/meshes/titan_avenger.glb` (already aliased as `@airframe` in Vite; file is not on the branch)

**Lane B / UI**

- Read `evaluation.json` and `simulation_run.json` as-is
- Show the fidelity strings from `fidelityLabel` in `apps/web/src/telemetry.ts`
- Never compare an analytic baseline to a vspaero candidate
- Battery/spar edits do not change outer shape, so a VSPAERO run can be reused; a wing edit invalidates `geometry_hash`

**Unreal / demo look**

- Consume `simulation_run.json` + `part_map.json` only
- Convert FRD/NED → UE left-handed Z-up **once**, at the adapter boundary
- A commanded right turn in the telemetry must bank right on screen
- Do not compute stress or integrate EOM in Unreal; `part_stress` and `load_factor_n` are already in the file
- R3F is the shipping demo path until Unreal exists

---

## What we will not claim

No airworthiness. No validated flight dynamics. No bench test. No accuracy beyond the stated input assumptions. A replay is a reduced-order mission model (vortex-lattice aero when a real run exists), rendered — not a flight.

---

## Commits on `lane-c` since `main`

| SHA | Summary |
|---|---|
| `c2a8fc7` | Scaffold evaluator, contracts, sim packages |
| `79491a9` | R3F mission replay viewport and evaluate/simulate CLI |
| `cdc102e` | C3: OpenVSP 3.51.3 feasible on WSL Ubuntu 26.04 |
| `44eb196` | Freeze `simulation_run.json` telemetry contract (U0) |
| `d104028` | JSON contracts, schemas, synthetic tail fixtures |
| `52da727` | Analytic `evaluate_revision` with C1/C2 physics tests |
| `9e072b2` | Unwrap claim-shaped fixtures so evaluate consumes Lane A JSON |
| `925f587` | `python -m dronebench` entrypoint; ignore generated evaluation dumps |
| `1dbbb8f` | C4: generate VSPAERO sweep from geometry_features; validation report with numbers |
| `9a22ae6` | Align evaluate dump with `evaluation.schema.json` |
| `0762eb2` | C5: wire VSPAERO polar into `evaluate_revision`; do not double-count induced drag |

Standing rules for anyone editing this branch: `AGENT.md`.
