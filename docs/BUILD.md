# How DroneBench was built

Houston AITX Community Hackathon, 19 September 2026. Three developers, three lanes, one repository,
one specification: [`DroneBench_Final_Architecture.md`](../DroneBench_Final_Architecture.md).

This document records what each lane shipped, what actually integrates today, and what the
remaining work is. It is written to be useful to someone picking the repository up cold — including
us, next week.

---

## The shape of the work

The architecture splits the product three ways (§11), and each lane worked on its own branch
against a frozen contract baseline:

| Lane | Branch | Owns |
|---|---|---|
| A | `team/a-cad` | extraction, reconstruction, CAD execution |
| B | `lane-b` | contracts, revision store, evidence graph, recommender, API, shell |
| C | `lane-c` | analytic evaluator, mission plant, OpenVSP worker |

All three are merged into `main`. The merge was almost clean — two textual conflicts with A, eight
with C, all configuration files. The *semantic* divergence is the real story, and it has its own
section below.

---

## Lane A — extraction, reconstruction, CAD execution

**Branch `team/a-cad`, 13 commits.**

- `packages/ingest` — archive staging, mesh inspection, variant selection, mirroring, frame
  confirmation, assembly, BOM, GLB export, revisions. 13 modules.
- `packages/cad` — CadQuery reconstruction, parameterisation, airfoil handling, STEP/GLB export,
  round-trip verification in a fresh worker, fit reporting.
- `packages/edits` — the typed CAD edit operations and collision checks.
- `packages/viewer` — a static CAD inspector.
- `apps/web/src/features/cad` — four React components plus mock boundary artifacts.

**Measured, not assumed.** A's brief records the archive's real numbers: native bounds per group,
root chord 214 mm and tip 130 mm, V-tail cant ≈32° from horizontal, `motor_mount` at native
Y 588–598 which makes the archive a **pusher**, and the seven bodies that are not watertight.
Fuselage station fitting improved from 13.1 mm to 3.1 mm of fit error across the build.

Tests live in `tests/cad`, `tests/ingest`, `tests/edits`, `tests/viewer`. They need the CAD extra:

```bash
python -m pip install -e ".[cad]"     # cadquery, trimesh
```

Without it those suites fail at collection — that is a missing optional dependency, not a broken
merge.

---

## Lane B — contracts, workflow, graph, recommender, API, shell

**Branch `lane-b`, 6 commits, ~30k lines.**

- `packages/contracts` — the wire vocabulary. 59 models generating `schema/dronebench.schema.json`
  and, from that, 60 TypeScript types. Claim envelope, evidence records, revision and artifact
  identity with canonical content hashing, the eight boundary artifacts of §5, the four typed edit
  operations, the transaction states, the shared error envelope.
- `packages/workflow` — SQLite with WAL and foreign keys, an append-only artifact store, the
  proposal state machine, acceptance as a compare-and-swap inside one transaction, an idempotency
  store, undo over the activation timeline, a bounded job queue with per-job directories.
- `packages/graph` — the typed evidence graph. `near` kept distinct from `mates_with`,
  `compatible_with` computed only from declared interfaces, power and signal as separate networks,
  and the five narrow queries of §7 as bounded traversals.
- `packages/recommend` — deterministic candidate generation from failing checks, typed validation,
  real previews through the CAD and evaluate ports, ranking, US Part 107 and Remote ID
  applicability, and a provider adapter that defaults to none.
- `apps/api` — all 18 endpoints, SSE with a monotonic sequence, and the `dronebench` CLI over the
  same service functions.
- `apps/web` — the shell, the graph and review panels, and a three.js viewport that renders the
  real archive.

**173 tests** in `tests/contract` and `tests/e2e`, written against §13's definition of done rather
than against the implementation.

### Bugs found and fixed during the build

Recorded because each one was a real defect, not a typo:

- Revision ids were derived from content but documents were stamped with a different probe id, so
  proposals referenced revisions that did not exist. The builder now derives and stamps one id and
  excludes derived documents from the hash to break the circularity.
- A stale acceptance left an orphan "committed" revision in the history. History is now the
  *activation* timeline: a revision that was never active was never a state the design was in.
- The committed revision inherited its preview's evaluation, whose run-input hash named the
  preview. It is no longer copied.
- Tradeoff directions were wrong for load and banded metrics — increasing drag read as "improves".
  Now: monotone metrics by sign, banded metrics by their check's status transition, everything else
  `informational` with no verdict attached.
- The battery corridor ran through the payload bay and the spar, so the only proposal the
  recommender could make failed its own geometry check.
- The CG envelope and the static-margin band contradicted each other. Both are now derived from the
  neutral point and MAC, and `Mission` rejects an inconsistent pair.
- `verified_feasible` was a Python property the UI could not see, inviting a second definition of
  "verified" in TypeScript. Now a serialised computed field, ignored on input.
- **Nothing in the interface could confirm the reconstruction.** The validator had always rejected
  edits with *"the reconstruction has not been confirmed"*, but with no way to satisfy it the
  recommender simply looked empty. A gate the product enforces and the interface hides is worse
  than no gate.
- Regenerating proposals recomputed an evaluation with a fresh `elapsed_s`, which the append-only
  store read as a content change and refused with a 500. Display-only fields are excluded from
  every content hash, so the store now treats artifacts differing only in those fields as the same
  bytes.

---

## Lane C — evaluator, mission plant, OpenVSP

**Branch `lane-c`, 13 commits.**

- `packages/evaluate` — analytic physics, gate checks, hashing, quarantine for inconsistent inputs.
- `packages/sim` — the reduced-order mission model, attitude, telemetry I/O and validation.
- `packages/openvsp_worker` — VSPAERO geometry generation from `geometry_features`, sweep running,
  a runtime probe, and a validation report.
- `packages/contracts` — Lane C's own contract module and seven JSON Schemas.
- `fixtures/c/` — `synthetic_vtail_demo` and `conventional_tail_demo`.

**OpenVSP 3.51.3 is confirmed working on WSL Ubuntu** — the §12 hour-one feasibility gate, actually
passed. C4 generates a VSPAERO sweep from `geometry_features` and validates the result with numbers;
C5 wires the polar into `evaluate_revision` without double-counting induced drag.

`tests/physics` (18) and `tests/sim` (23) pass on a clean checkout. `tests/test_openvsp_worker.py`
needs OpenVSP installed; 4 tests fail without it.

Lane C deliberately does **not** edit the aircraft. An outside agent changes CAD or BOM, and Lane C
re-scores.

---

## Integration state

**This is the honest part.** Each lane is individually well advanced. Integrated, the product is
not yet one system, and the reason is specific.

### What works today

- All three lanes are merged into `main` and coexist on disk.
- `python -m pytest tests --ignore=tests/cad --ignore=tests/ingest --ignore=tests/viewer
  --ignore=tests/edits` → **222 passed, 4 failed** (the 4 need OpenVSP installed).
- The web app builds and runs, rendering the real archive.
- Lane B's loop runs end to end against reference ports.

### What does not

All three lanes wrote their own `packages/contracts`, which §11 explicitly forbids: *"B owns
contracts changes; no teammate forks a private variant."* By the time that was visible, each lane
had a working tree built on its own version.

The good news is the part that matters most agrees. The `Claim` envelope — `value`, `unit`,
`status`, `source_kind`, `evidence_ids`, `assumptions`, null meaning unknown, no NaN — is
substantially identical in all three. Everyone read §5 the same way.

The aggregate documents did not converge. For `geometry_features.json`, the artifact Lane A
*produces* and both B and C *consume*:

```
shared by all three:  schema_version
A only:  reference_area_m2, reference_span_m, reference_chord_m, surfaces, fuselage, cg_m, mass_kg
B only:  wing_reference_area_m2, wing_span_m, wing_mac_m, vtail_panels, frame_confirmed, ...
C only:  reference, tail, spar, aero_assumptions, cg_inputs, mission, units
B and C: wing_stations
```

Running each lane's real artifacts through Lane B's validators: A's manifest → 12 errors, A's
features → 18, C's features → 41. Nothing crosses the boundary today.

### The fix, and why it is this one

**Write adapters, do not renegotiate the schema.** Two functions in
`packages/contracts/adapters/` — `a_features_to_b` and `b_features_to_c` — roughly 150 lines,
mostly mechanical renames (`reference_area_m2` → `wing_reference_area_m2`). Then delete the
duplicate contract trees and point every lane at one module.

Renegotiating three schemas costs more than it saves and touches every file in all three lanes.
Adapters are reversible, testable in isolation, and let the convergence happen after the
demonstration rather than during it.

After that, two one-line changes in `apps/api/dronebench_api/service.py::build_workbench` swap
Lane A's real `CadPort` and Lane C's real `EvaluatePort` in for the reference implementations. The
`B-stub` labels and the export refusal then disappear on their own, because both are computed from
`port.owner` and `available_tiers()` rather than hard-coded.

---

## Conventions worth keeping

- **Contracts are generated, never hand-written.** Change a Pydantic model, then run
  `python -m dronebench_contracts.schema schema` and `python scripts/generate_ts_types.py`. A stale
  bundle fails a test rather than surprising another lane.
- **Verification means numbers.** `apps/web/scripts/shoot.mjs` drives the real app in a browser and
  measures whether anything is clipped; it does not trust CSS intent. Backend claims are asserted in
  `tests/contract` against §13's wording.
- **A breaking contract change needs a decision note** in `docs/decisions/`, updated examples, and
  consumer validation in the same merge.
- **The frozen fixture is a contract.** `tests/contract/test_fixture_frozen.py` fails if its bytes
  change. That failure is a prompt to tell the other lanes, not a test to silence.
