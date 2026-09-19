# Team B — evidence graph, proposals, revisions, shell

Source of truth: `DroneBench_Final_Architecture.md` §5 (data model), §7 (Team B), §9 (API/job
contract), §11 (ownership), §12 (build order, B column), §13 (definition of done).

B owns: `packages/contracts`, `packages/graph`, `packages/recommend`, `packages/workflow`,
`apps/api`, database/migrations, `apps/web/src/app`, `apps/web/src/features/{graph,review}`,
`tests/contract`, `tests/e2e`, root dependency files, root `CLAUDE.md`.

B does **not** own: `packages/ingest`, `packages/cad` (A), `packages/evaluate`, `packages/sim` (C),
`apps/web/src/features/{cad,simulation}` (A/C).

Because A and C have not started, B builds against a frozen synthetic fixture (§12 fallback:
"a simpler clearly named parametric fixed-wing fixture") and typed ports with reference stub
implementations. Every stub is labelled in its output; nothing claims a solver ran.

---

## 1. Contracts — `packages/contracts`

- [x] Units, canonical FRD frame, display-boundary conversion (§5 Identity and coordinates)
- [x] `Claim` envelope: `value|null`, `unit`, `status`, `source_kind`, `evidence_ids`,
      `confidence?`, `assumptions` (§5 Claim-level evidence)
- [x] `Evidence`: URI/path, access timestamp, content hash, locator, extraction method, validity
- [x] `ConflictSet` — conflicting claims preserved with selected value + rationale
- [x] Identity: `part_id` / `definition_id` / `mirror_of`, `design_id` / `revision_id`
- [x] Canonical-JSON content hashing, display-only fields excluded from the hash
- [x] `Artifact`: relative path, SHA-256, media type, representation, associated part IDs
- [x] Eight boundary artifacts of the §5 table as models
- [x] Graph node/edge types (§7 Graph semantics)
- [x] `Recommendation` + the four typed edit operations (§6 Supported edit operations)
- [x] Transaction states (§7 state machine)
- [x] Error envelope `{code, message, revision_id, details, retryable}` + the ten §9 codes
- [x] SSE event model, job model
- [x] Ports (Protocols) for A's CAD tool and C's evaluator
- [x] JSON Schema generation → `schema/` (`python -m dronebench_contracts.schema`)
- [x] No NaN/Infinity can be emitted (validator)

## 2. Frozen fixture — `fixtures/b`, `fixtures/common`

- [x] `parametric_fixedwing` synthetic design: manifest, parts, geometry features, mission
- [x] Catalog snapshot, 6–12 items, batteries/spars/servos, labelled synthetic (§7)
- [x] Regulatory profile: one jurisdiction/operation (US Part 107) with evidence
- [x] Fixture hash frozen and asserted in `tests/contract`

## 3. Workflow — `packages/workflow`

- [x] SQLite schema + migrations, WAL, foreign keys, single orchestration owner
- [x] Append-only revision directories; artifacts immutable, hash in enclosing manifest
- [x] Revision graph: parent, content hash, mission hash, artifact list, creation cause
- [x] Transaction state machine: proposed → previewing → review_ready/blocked →
      declined | committing → committed/stale/failed
- [x] Accept = (proposal id, expected active revision, preview hash, idempotency key) under CAS
- [x] Idempotency store — repeated key returns the identical outcome
- [x] Decline logs a decision, changes no design hash
- [x] Undo switches to an existing validated revision
- [x] Event log — tool name, input summary, artifact refs, status, elapsed; never chain-of-thought
- [x] Bounded job queue, unique per-job directories, cancellable

## 4. Graph — `packages/graph`

- [x] Typed nodes/edges with evidence, status, revision scope
- [x] Build projection from parts + catalog + regulations + evaluation
- [x] `near` kept distinct from `mates_with`; `compatible_with` computed from declared interfaces
- [x] Distinct signal and power networks
- [x] Bounded neighborhood query (never ship the whole graph to a model)
- [x] The five §7 queries: mass evidence, what-fails-if-moved, affected-by-spar, fitting
      suppliers, why-a-rule-applies

## 5. Recommend — `packages/recommend`

- [x] Catalog + regulatory applicability (`applies` / `does_not_apply` / `unknown` + evidence)
- [x] Deterministic candidate generator from failing checks and typed dependency paths
- [x] Provider adapter `propose(context, allowed_operations) -> Recommendation[]`, null default
- [x] Validation: schema, target IDs, base revision, locks, bounds, units, evidence, solver
- [x] Staged preview through the CAD and evaluate ports — never an LLM's predicted gain
- [x] Ranking under the mission objective; "unevaluated proposal" when not evaluated
- [x] Budgets: ≤6 candidates, ≤3 displayed, ≤2 provider calls, ≤3 native analyses queued

## 6. API + CLI — `apps/api`

- [x] All 15 §9 endpoints, shared error envelope, 202 + job id for long work
- [x] SSE with monotonic sequence and reconnect via last event id
- [x] Job cache keys include revision content, mission, solver version, model tier, snapshots
- [x] `dronebench` CLI over the same service functions; JSON on stdout, logs on stderr,
      nonzero exit on invalid input, modeled infeasibility distinguished from failure
- [x] `dronebench doctor`

## 7. Web shell — `apps/web/src/app`, `features/graph`, `features/review`

- [x] Shell, routing, three modes (Inspect / Improve / Simulate), persistent top bar
- [x] Shared revision/selection/artifact/event context — feature panels own no revision store
- [x] Graph panel (bounded neighborhood + evidence path)
- [x] Review panel (recommendation cards, accept/decline, change ledger, history)
- [x] Mount points for A `features/cad` and C `features/simulation`
- [x] TypeScript types generated from JSON Schema, not hand-written

## 8. Verification — §13

- [x] Contract checks: fixtures parse, unknowns stay null, round trip preserves units and IDs,
      references resolve, no NaN/Infinity
- [x] Workflow checks: decline changes no geometry; accept commits precisely the reviewed
      preview; repeated idempotency key → same outcome; stale accept → conflict; worker failure
      leaves active revision unchanged; undo restores a coherent revision; no partial artifact set
- [x] E2E: import → confirm → select → graph/evidence → preview → decline → preview → accept →
      compare → export

---


---

## Review

Delivered on branch `lane-b`. `python -m pytest tests -q` → **115 passed**.
`cd apps/web && npx tsc --noEmit && npx vite build` → clean.

### What was built

| Package | Lines | What it does |
|---|---|---|
| `packages/contracts` | ~2,600 | The wire vocabulary. 59 JSON Schema definitions, 60 generated TS types. |
| `packages/workflow` | ~1,300 | SQLite + append-only artifacts, the state machine, CAS accept, jobs. |
| `packages/graph` | ~900 | Typed projection and the five narrow queries. |
| `packages/recommend` | ~1,500 | Candidates, validation, preview, ranking, regulatory applicability. |
| `apps/api` | ~2,400 | Service layer, 18 endpoints, SSE, CLI, and the reference A/C ports. |
| `apps/web` | ~1,900 | Shell, three modes, graph and review panels, A/C mount points. |
| `fixtures/`, `tests/` | ~2,600 | The frozen demonstrator and 115 checks. |

### The loop, end to end

1. Import → units, frame, and reconstruction unconfirmed; no edit is proposable.
2. The harness has no mass → mass, CG, static margin, stall, energy, and current all **unknown**.
   The recommender asks for the value instead of proposing an edit.
3. Confirm, supplying 0.045 kg as `manual` evidence → CG 0.390 m (envelope 0.344–0.382) and static
   margin 4.5% (band 8–25%) both **fail**.
4. Two proposals, both previewed on real child revisions: move the battery 45 mm forward
   (recovers feasibility, ranked first) and upsize the spar (feasible, costs 18.5 g and 0.06 min
   of endurance for 2.37× section modulus — the one to decline).
5. Decline the spar → no revision, no hash changes. Accept the battery move under CAS → committed;
   the same key replayed returns the same outcome; accepting against the superseded base conflicts.
6. Evaluate the commit → all checks pass. Simulate → 151 samples, route complete.
7. Export → **refused**, `SOLVER_UNAVAILABLE`, because there is no CAD kernel to verify a round trip.

### Bugs found and fixed while building

- Revision ids were derived from content but documents were stamped with a different probe id, so
  proposals referenced revisions that did not exist. The builder now derives and stamps one id, and
  excludes derived documents from the hash to break the circularity.
- A stale acceptance left an orphan "committed" revision in the history. History is now the
  activation timeline.
- The committed revision inherited the preview's evaluation, whose run-input hash named the
  preview. It is no longer copied.
- Tradeoff directions were wrong for load and banded metrics — increasing drag read as "improves".
  Now: monotone metrics by sign, banded metrics by their check's status transition, everything else
  `informational` with no verdict.
- The battery corridor ran through the payload bay and the spar, so the only proposal the
  recommender could make failed its own geometry check. Bays re-laid; every mount is clear.
- The CG envelope and the static-margin band contradicted each other. Both are now derived from the
  neutral point and MAC, and `Mission` rejects an inconsistent pair.
- `verified_feasible` was a Python property the UI could not see, inviting a second definition of
  "verified" in TypeScript. It is now a computed field, serialised and ignored on input.

### Handoff

- **A**: implement `CadPort` in `packages/cad`; replace `dronebench_api.stubs.ParametricCadPort` in
  `service.build_workbench`. The `B-stub` labels and the export refusal disappear on their own.
- **C**: implement `EvaluatePort` and `SimulatePort`. Report real tiers from `available_tiers()`;
  the UI reads its fidelity label from there.
- Both: mount into `apps/web/src/features/{cad,simulation}` and read revision and selection from
  `useWorkbench()`. Do not keep a second revision store.
- Contract changes go through `docs/decisions/` and regenerate both the schema and the TS types.
