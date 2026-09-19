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

- [ ] Units, canonical FRD frame, display-boundary conversion (§5 Identity and coordinates)
- [ ] `Claim` envelope: `value|null`, `unit`, `status`, `source_kind`, `evidence_ids`,
      `confidence?`, `assumptions` (§5 Claim-level evidence)
- [ ] `Evidence`: URI/path, access timestamp, content hash, locator, extraction method, validity
- [ ] `ConflictSet` — conflicting claims preserved with selected value + rationale
- [ ] Identity: `part_id` / `definition_id` / `mirror_of`, `design_id` / `revision_id`
- [ ] Canonical-JSON content hashing, display-only fields excluded from the hash
- [ ] `Artifact`: relative path, SHA-256, media type, representation, associated part IDs
- [ ] Eight boundary artifacts of the §5 table as models
- [ ] Graph node/edge types (§7 Graph semantics)
- [ ] `Recommendation` + the four typed edit operations (§6 Supported edit operations)
- [ ] Transaction states (§7 state machine)
- [ ] Error envelope `{code, message, revision_id, details, retryable}` + the ten §9 codes
- [ ] SSE event model, job model
- [ ] Ports (Protocols) for A's CAD tool and C's evaluator
- [ ] JSON Schema generation → `schema/` (`python -m dronebench_contracts.schema`)
- [ ] No NaN/Infinity can be emitted (validator)

## 2. Frozen fixture — `fixtures/b`, `fixtures/common`

- [ ] `parametric_fixedwing` synthetic design: manifest, parts, geometry features, mission
- [ ] Catalog snapshot, 6–12 items, batteries/spars/servos, labelled synthetic (§7)
- [ ] Regulatory profile: one jurisdiction/operation (US Part 107) with evidence
- [ ] Fixture hash frozen and asserted in `tests/contract`

## 3. Workflow — `packages/workflow`

- [ ] SQLite schema + migrations, WAL, foreign keys, single orchestration owner
- [ ] Append-only revision directories; artifacts immutable, hash in enclosing manifest
- [ ] Revision graph: parent, content hash, mission hash, artifact list, creation cause
- [ ] Transaction state machine: proposed → previewing → review_ready/blocked →
      declined | committing → committed/stale/failed
- [ ] Accept = (proposal id, expected active revision, preview hash, idempotency key) under CAS
- [ ] Idempotency store — repeated key returns the identical outcome
- [ ] Decline logs a decision, changes no design hash
- [ ] Undo switches to an existing validated revision
- [ ] Event log — tool name, input summary, artifact refs, status, elapsed; never chain-of-thought
- [ ] Bounded job queue, unique per-job directories, cancellable

## 4. Graph — `packages/graph`

- [ ] Typed nodes/edges with evidence, status, revision scope
- [ ] Build projection from parts + catalog + regulations + evaluation
- [ ] `near` kept distinct from `mates_with`; `compatible_with` computed from declared interfaces
- [ ] Distinct signal and power networks
- [ ] Bounded neighborhood query (never ship the whole graph to a model)
- [ ] The five §7 queries: mass evidence, what-fails-if-moved, affected-by-spar, fitting
      suppliers, why-a-rule-applies

## 5. Recommend — `packages/recommend`

- [ ] Catalog + regulatory applicability (`applies` / `does_not_apply` / `unknown` + evidence)
- [ ] Deterministic candidate generator from failing checks and typed dependency paths
- [ ] Provider adapter `propose(context, allowed_operations) -> Recommendation[]`, null default
- [ ] Validation: schema, target IDs, base revision, locks, bounds, units, evidence, solver
- [ ] Staged preview through the CAD and evaluate ports — never an LLM's predicted gain
- [ ] Ranking under the mission objective; "unevaluated proposal" when not evaluated
- [ ] Budgets: ≤6 candidates, ≤3 displayed, ≤2 provider calls, ≤3 native analyses queued

## 6. API + CLI — `apps/api`

- [ ] All 15 §9 endpoints, shared error envelope, 202 + job id for long work
- [ ] SSE with monotonic sequence and reconnect via last event id
- [ ] Job cache keys include revision content, mission, solver version, model tier, snapshots
- [ ] `dronebench` CLI over the same service functions; JSON on stdout, logs on stderr,
      nonzero exit on invalid input, modeled infeasibility distinguished from failure
- [ ] `dronebench doctor`

## 7. Web shell — `apps/web/src/app`, `features/graph`, `features/review`

- [ ] Shell, routing, three modes (Inspect / Improve / Simulate), persistent top bar
- [ ] Shared revision/selection/artifact/event context — feature panels own no revision store
- [ ] Graph panel (bounded neighborhood + evidence path)
- [ ] Review panel (recommendation cards, accept/decline, change ledger, history)
- [ ] Mount points for A `features/cad` and C `features/simulation`
- [ ] TypeScript types generated from JSON Schema, not hand-written

## 8. Verification — §13

- [ ] Contract checks: fixtures parse, unknowns stay null, round trip preserves units and IDs,
      references resolve, no NaN/Infinity
- [ ] Workflow checks: decline changes no geometry; accept commits precisely the reviewed
      preview; repeated idempotency key → same outcome; stale accept → conflict; worker failure
      leaves active revision unchanged; undo restores a coherent revision; no partial artifact set
- [ ] E2E: import → confirm → select → graph/evidence → preview → decline → preview → accept →
      compare → export

---

## Review

See `docs/decisions/` for the interface decisions taken during this build and the bottom of this
file for the closing summary.
