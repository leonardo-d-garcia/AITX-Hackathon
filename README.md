# DroneBench Studio

**Click a part, see why it matters, change it with evidence, and watch the same revision flow
through CAD, analysis, and a flight replay.**

DroneBench ingests a real CAD archive, builds a typed evidence graph over it, traces what depends
on what, proposes bounded changes with their tradeoffs, commits the one you accept as an immutable
revision, and flies the result against the design it replaces.

The thing being demonstrated is **traceability across that whole loop**. Every number on screen
names the revision it belongs to and the evidence behind it, and where the evidence runs out the
product says so instead of guessing. A big graph or a pretty flight animation on their own do not
show that.

Built at the Houston AITX Community Hackathon, 19 September 2026, in three parallel lanes.
Specification: [`DroneBench_Final_Architecture.md`](DroneBench_Final_Architecture.md).

---

## Quick start

Python 3.11+ and Node 20+.

```bash
git clone https://github.com/leonardo-d-garcia/AITX-Hackathon.git
cd AITX-Hackathon

# --- backend -------------------------------------------------------------
python -m pip install -e ".[dev,serve]"
python -m pytest tests/contract tests/e2e -q          # 173 passed

# --- the workbench API ---------------------------------------------------
DRONEBENCH_ROOT=artifacts/demo \
  python -m uvicorn dronebench_api.main:app --host 127.0.0.1 --port 8000

# --- the web app (second terminal) ---------------------------------------
cd apps/web && npm install && npm run dev
```

Then open **<http://127.0.0.1:5173>**.

If `pip install -e .` is inconvenient, set the path instead:

```bash
export PYTHONPATH="packages:packages/contracts:packages/graph:packages/recommend:packages/workflow:packages/cad:packages/ingest:packages/viewer:apps/api"
```

On Windows use `;` as the separator.

### Command line

The CLI runs the same service functions as the API — there is no second implementation.

```bash
dronebench doctor                     # what is installed, and what is not
dronebench ingest                     # stage a design
dronebench confirm dsn_parametric-fixedwing --reconstruction-confirmed \
  --claim "prt_harness:mass_kg=0.045:kg:manual:ev_fixture-spec"
dronebench evaluate                   # exit 4 means "modelled infeasibility", not failure
dronebench recommend
dronebench accept rec_battery-cg --idempotency-key demo-0001
dronebench simulate
```

Exit codes: `0` ok · `2` invalid input · `3` tool failure · `4` modelled infeasibility.
The last one is a *result*, and a script can tell it apart from a crash.

---

## Tech stack and architecture

Python 3.11 · FastAPI · Pydantic v2 · SQLite (WAL) · NetworkX · CadQuery/OCP · OpenVSP 3.51.3 ·
React 18 · TypeScript · Vite · three.js

```
                         ┌──────────────────────────────┐
                         │  Web app  (React + three.js) │
                         │  Inspect · Improve · Simulate│
                         └──────────────┬───────────────┘
                                        │  generated TypeScript types
                                        ▼
                         ┌──────────────────────────────┐
                         │  FastAPI  apps/api           │
                         │  18 endpoints + SSE + CLI    │
                         └──────────────┬───────────────┘
                                        │
      ┌─────────────────┬───────────────┼───────────────┬──────────────────┐
      ▼                 ▼               ▼               ▼                  ▼
┌───────────┐   ┌─────────────┐  ┌────────────┐  ┌────────────┐   ┌──────────────┐
│  ingest   │   │    cad      │  │   graph    │  │ recommend  │   │   evaluate   │
│  (Lane A) │   │  (Lane A)   │  │  (Lane B)  │  │  (Lane B)  │   │   (Lane C)   │
│ STL/STEP  │   │ CadQuery    │  │ typed      │  │ candidates │   │ mass · CG ·  │
│ variants  │   │ STEP/GLB    │  │ evidence   │  │ validation │   │ aero · spar  │
│ mirroring │   │ round trip  │  │ traversals │  │ ranking    │   │ VSPAERO      │
└───────────┘   └─────────────┘  └────────────┘  └────────────┘   └──────────────┘
      │                 │               │               │                  │
      └─────────────────┴───────────────┼───────────────┴──────────────────┘
                                        ▼
                         ┌──────────────────────────────┐
                         │  workflow    (Lane B)        │
                         │  append-only revision store  │
                         │  SQLite + compare-and-swap   │
                         └──────────────┬───────────────┘
                                        ▼
                         ┌──────────────────────────────┐
                         │  contracts   (Lane B)         │
                         │  59 models → JSON Schema      │
                         │  → 60 TypeScript types        │
                         └──────────────────────────────┘
```

**The contract is the spine.** Pydantic models in `packages/contracts` generate
`schema/dronebench.schema.json`, which generates `apps/web/src/lib/contracts.gen.ts`. Nothing
hand-writes a type that already exists upstream.

Four invariants the type system enforces rather than documents:

| Rule | Where it bites |
|---|---|
| Unknown is a first-class result — never zero, never a confidence | `Claim` rejects a valued "unknown" and an unknown with a confidence |
| Proximity is not a joint | a `mates_with` edge without confirming evidence fails validation |
| A label may not outrun its artifact | `vspaero_informed` is rejected without a real solver run attached |
| Accept commits precisely the reviewed preview | the request quotes a preview hash; the pointer moves under compare-and-swap |

### Repository layout

```
packages/contracts/     Lane B   wire vocabulary, JSON Schema generation
packages/workflow/      Lane B   revision store, transactions, job queue
packages/graph/         Lane B   typed evidence graph and bounded traversals
packages/recommend/     Lane B   candidates, validation, ranking, regulatory
packages/ingest/        Lane A   archive ingest, variants, mirroring, frame
packages/cad/           Lane A   CadQuery reconstruction, STEP/GLB, round trip
packages/edits/         Lane A   typed CAD edit operations
packages/viewer/        Lane A   static CAD inspector
packages/evaluate/      Lane C   analytic evaluator, checks, quarantine
packages/sim/           Lane C   reduced-order mission model, telemetry
packages/openvsp_worker/Lane C   VSPAERO geometry and sweeps
apps/api/               Lane B   FastAPI + CLI + reference ports
apps/web/               Lane B   shell, graph and review panels, 3D viewport
```

---

## Reproducing the demo

**No API keys and no network are required.** The whole product runs locally, and nothing on the
demo path calls an external service. There is no `.env` to fill in.

The only environment variables that exist:

| Variable | Default | What it does |
|---|---|---|
| `DRONEBENCH_ROOT` | `artifacts/workbench` | where revisions and the SQLite database live |
| `DRONEBENCH_PROVIDER` | `none` | language-model adapter. `none` uses the deterministic candidate generator, which is the real path. Anything unrecognised falls back to `none` |
| `DRONEBENCH_API` | `http://127.0.0.1:8000` | API the Vite dev server proxies to |

A sample `.env` is in [`.env.example`](.env.example) — every value in it is optional.

### Staging the aircraft archive

The supplied Titan Avenger ZIP is **not in this repository**. It contains no licence document, so
the original asset stays out of a public repo until reuse terms are established (architecture
§2). To see the real geometry in the viewport, stage your own copy:

```bash
python scripts/extract_titan.py path/to/Titan+Avenger.zip
```

That writes 24 binary STL meshes to `apps/web/public/titan/` (git-ignored) with a SHA-256
manifest. **Without it the app still runs** — the viewport reports that it has no geometry to
draw, which is the honest state rather than a substitute model.

### The demo path

```bash
python scripts/demo_reset.ps1     # PowerShell: wipes the store, restarts the API clean
```

1. **Import** — 17 occurrences stage as a draft. Units, frame, and the reconstruction are
   unconfirmed, so no edit is proposable yet.
2. **Inspect** — the wiring harness reads *mass unknown* in amber. One missing mass makes seven
   checks unknown; the recommender asks for the value instead of promising endurance.
3. **Confirm** — record units, frame, and the reconstruction; supply the harness mass as `manual`
   evidence. CG now computes at station 0.390 m against a 0.344–0.382 m envelope: **fail**, and
   static margin 4.5 % against 8–25 %: **fail**. One cause, two failures.
4. **Improve** — two previewed proposals. Move the battery 45 mm forward (recovers feasibility) or
   upsize the spar (feasible, costs 18.5 g and 0.06 min). Decline one, accept the other.
5. **Simulate** — the accepted design and the original fly the same route together. The original
   falls behind; the readout shows both on one clock.
6. **Export** — refuses with `SOLVER_UNAVAILABLE`, because without the CAD kernel there is no
   verified round trip. That refusal is the correct behaviour, not a gap.

There is also a scripted five-beat narrative at **`/demo`** which renders the real Titan archive.

### Verifying it yourself

```bash
python -m pytest tests/contract tests/e2e -q       # Lane B: 173 passed
python -m pytest tests/physics tests/sim -q        # Lane C: 41 passed
cd apps/web && npx tsc --noEmit && npx vite build  # web: clean
node apps/web/scripts/shoot.mjs                    # drives a real browser, 11 frames
```

`shoot.mjs` walks the whole loop in headless Chromium and reports any element clipped by an
overflow with no scroller, or drawn outside the viewport. Last run: 11/11 frames clean, zero
console errors.

---

## Data and provenance

Every figure in this product carries how it was obtained. Three categories, kept apart:

### 1. The supplied archive — real, unmodified

Titan Avenger (fixed wing, VTOL on profile). **24 binary STL files, 580,404 triangles,
11,241,502 compressed bytes.** All 24 lengths match their declared triangle counts — a format
check, not a manifoldness or assembly validation.

What it does **not** contain, and what we therefore do not claim: no STEP, no feature history, no
BOM, no mission, no assembly manifest, no motors, batteries, spars, avionics, or wiring
specification, and **no licence document**.

Consequences we handled rather than papered over:

- Three `wing3` variants and three `fuse3` variants. Exactly one of each is installed; the rest are
  recorded as excluded alternatives so they cannot be counted as mass twice.
- Wing and tail meshes sit predominantly on positive native X — one side supplied, the other
  mirrored as a distinct occurrence with an explicit `mirror_of`.
- Frame mapping is a **candidate**: `x = −(Y − Y_nose)·0.001`, `y = −X·0.001`, `z = −Z·0.001`,
  `Y_nose ≈ −403.07 mm`. It must be confirmed in the viewer before any metric is published, and the
  UI blocks edits until it is.
- Not watertight: `fuse2`, `fuse4`, `fuse5`, `hatch2`, `wing1`, `wing3*`, `motor_mount`. Volume-based
  mass would be invalid for them — and geometry is not evidence of mass in any case.
- `motor_mount` sits at native Y 588–598, aft: the archive is a **pusher** configuration.

### 2. Synthetic fixtures — clearly labelled, not the Avenger

`fixtures/b/parametric_fixedwing` is a synthetic demonstrator authored for Lane B, permitted by
architecture §12. It is **not** the Titan Avenger and reconstructs no real aircraft. It exists
because the revision store, graph, recommender, and transaction machine all need a design to work
on, and it is frozen by hash in `tests/contract/test_fixture_frozen.py`.

Its failing scenario is **configured, not discovered**: the wiring harness has no mass, and the
battery sits at the aft end of its corridor. Both are deliberate, both are stated wherever they
surface. The numbers and why they are mutually consistent are recorded in
[`docs/decisions/0002`](docs/decisions/0002-synthetic-fixture-scenario.md).

Lane C's fixtures live in `fixtures/c/` (`synthetic_vtail_demo`, `conventional_tail_demo`).

### 3. The catalog — synthetic, and structurally unable to name a supplier

`fixtures/common/catalog.json` holds 8 items across batteries, spars, and servos. Every offer is
marked synthetic, and `CatalogOffer` **refuses to validate** if a synthetic entry carries a supplier
name, product URL, or source URL. A demo fixture cannot accidentally assert that a real company
sells a real part at a real price.

### What is computed versus recorded

| Source | Used for |
|---|---|
| `computed` | mass, CG, static margin, drag polar, power, endurance, spar stress — all from the analytic evaluator |
| `assumed` | CLmax, CD0, Oswald efficiency, the neutral point, single-point propulsion efficiencies. Each states its assumption in the claim itself |
| `recorded` | the VSPAERO figures in the `/demo` narrative. OpenVSP 3.51.3 runs on Lane C's WSL host, but a live solve is not put on a stage clock, so the run is replayed and the UI says *"recorded run, replayed here"* |
| `unknown` | printed shell masses and the wiring harness. Left null, propagated, never defaulted |

---

## Known limitations

**Honest about what this is.** A skeptical judge can inspect a real file, trace a recommendation to
its sources, decline without changes, accept a concrete edit, and see which run analysed which
revision. It does **not** mean airworthiness, regulatory approval, full reverse engineering, or
validated flight dynamics.

### Integration

- **The contract forked three ways.** All three lanes wrote their own `packages/contracts`, which
  §11 forbids. The `Claim` envelope is substantially identical across all three — everyone read §5
  the same way — but the aggregate documents are not. `geometry_features.json` shares only
  `schema_version` between the three variants. **Nothing crosses the A→B and A→C boundaries yet.**
  Adapters, not a schema renegotiation, are the right fix; see
  [`docs/BUILD.md`](docs/BUILD.md#integration-state).
- Lane B runs against reference implementations of A's and C's ports. Every stub output is stamped
  `B-stub`, and `dronebench doctor` lists what is absent.

### Engineering model

- **STEP export refuses.** Without the CAD kernel there is no verified round trip, and §6 requires
  one before a download exists.
- **VSPAERO is not live in the UI.** The worker runs (Lane C, OpenVSP 3.51.3 on WSL); the demo
  replays a recorded sweep.
- **Static margin rests on an assumed neutral point.** No stability method has produced one, and a
  wing quarter-chord guess is not valid for a V-tail aircraft.
- **Not modelled, and listed on every evaluation:** spar buckling, joints, adhesive, local damage;
  skin/spar load sharing; trim drag; propeller-airframe interaction; battery internal resistance
  and voltage sag; manoeuvre loads and turn drag; Reynolds dependence of CD0; stall behaviour
  beyond the assumed CLmax.
- **Clearance is a bounding-box screen** at 0.5 mm penetration. A kernel-level solid check
  supersedes it.
- **Two meshes are held out of the render** (`motor_mount`, `wing_bay_plate`): they are authored
  about their own local origins, so the shared archive mapping lands them off the airframe. Detected
  by measurement, not guessed at a placement — this is the missing-assembly-manifest gap showing.
- **The flight replay is a display.** The mission model is straight and level; the bank in a turn is
  a declared visual convention, not a modelled manoeuvre load. Not a flight test.
- **Regulatory output is applicability only** — `applies` / `does_not_apply` / `unknown` with
  evidence. It does not certify anything.

### Next steps

1. **Converge the contract.** Two adapters (`A_features → B_features`, `B_features → C_features`),
   roughly 150 lines, then delete the duplicate `packages/contracts` trees. This is the one thing
   standing between three good lanes and one working product.
2. Wire A's real `CadPort` and C's real `EvaluatePort` in `service.build_workbench` — a one-line
   change each; the `B-stub` labels and the export refusal disappear on their own.
3. Live VSPAERO behind the job queue, with the fidelity tier reported from `available_tiers()`.
4. Native STEP assembly import with per-body placements, which resolves the two held-out meshes.
5. Measured masses for the printed shells, which is the largest single unknown in the model.
6. Joints, buckling, and control authority; independent bench validation before any performance
   claim leaves the tool.

---

## Documentation

| Document | What it covers |
|---|---|
| [`DroneBench_Final_Architecture.md`](DroneBench_Final_Architecture.md) | the specification; normative |
| [`docs/BUILD.md`](docs/BUILD.md) | how it was built, what each lane shipped, integration state |
| [`docs/decisions/0001`](docs/decisions/0001-team-b-contract-baseline.md) | the contract freeze and every assumption made |
| [`docs/decisions/0002`](docs/decisions/0002-synthetic-fixture-scenario.md) | the fixture scenario and its numbers |
| [`CLAUDE.md`](CLAUDE.md) | repository instructions for contributors |
| [`PRD.md`](PRD.md) | the earlier scorer spec, superseded by §2 of the architecture |

## Licence

MIT, see [`LICENSE`](LICENSE). The Titan Avenger archive is **not** covered by it and is not
distributed here.
