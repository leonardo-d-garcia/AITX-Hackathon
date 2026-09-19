# 0001 — Team B contract baseline, and what B assumed to get there

Status: accepted · Owner: Team B · Date: 2026-09-19

Architecture section 11: "B freezes the contract baseline with A/C during the first 45 minutes,
commits generated types and fixture hashes, then all three branch from it." This note is that
freeze, plus the assumptions B had to make because A and C had not started.

## What is frozen

| Thing | Where | How to check it |
|---|---|---|
| Wire vocabulary | `packages/contracts/` | `python -m pytest tests/contract` |
| JSON Schema bundle | `schema/dronebench.schema.json` | `python -m dronebench_contracts.schema schema` |
| TypeScript types | `apps/web/src/lib/contracts.gen.ts` | `python scripts/generate_ts_types.py` |
| Synthetic fixture | `fixtures/b/`, `fixtures/common/catalog.json` | `fixtures/b/FIXTURE_HASH` |

`tests/contract/test_fixture_frozen.py` fails if the fixture bytes change. That failure is not a
bug — it means someone made a contract change and needs to say so here and tell A and C.

## Assumptions B made, and why

**A1. The repository root is the project root.** Section 11 draws the tree under `dronebench/`, but
this repository *is* DroneBench, so the packages sit at the root rather than one level down.

**A2. `contracts/models.py` did not exist, so B authored it.** Section 5 refers to it as
"accompanying", but it was not in the supplied material. B wrote `packages/contracts` from the
normative text in sections 5, 6, 7, 8, and 9.

**A3. Import stages a checked-in fixture, not an uploaded archive.** Archive ingestion is
`packages/ingest`, which is Team A's. `POST /api/designs/import` therefore takes a fixture name.
When A's importer lands it takes over that endpoint; nothing else changes, because everything
downstream consumes `parts.json` and `geometry_features.json`, not the archive.

**A4. B ships reference implementations of A's and C's ports.** Section 12 has B building the
revision store, graph, and transaction machine in the first four hours, which is impossible with
nothing on the other side of a CAD call. `apps/api/dronebench_api/stubs/` implements `CadPort`,
`EvaluatePort`, and `SimulatePort`. Each stamps `produced_by="B-stub"`, `available_tiers()` reports
only `analytic`, and `export_step` returns `ok=False` rather than producing an unverified STEP.
Swapping in the real packages is one edit, in `service.build_workbench`.

**A5. The `confirm` endpoint also accepts claim entries.** Section 9 gives confirm the job of
recording units, frame, variants, and the reconstruction decision, and creating the revision that
results. Section 10 separately requires "Unknown mass" to be actionable and to accept a value with
provenance. Rather than invent a second mutation endpoint, B extended confirm with
`claim_entries`. A user-entered value is `manual` or `bom` evidence and must cite an evidence id
already recorded in the revision; `inferred` is rejected, because section 5 says geometry does not
determine mass.

**A6. `EvidenceRequest` is a separate model from `Recommendation`.** Section 7 step 2 lists "ask for
missing battery mass before promising endurance" as a candidate, but that is not one of section 6's
four operations. Adding a fifth operation would have opened the edit union; instead
`RecommendationSet.evidence_requests` carries these, and the union stays closed at four.

## Where B departed from a literal reading, and why

**D1. `Evaluation.verified_feasible` is serialised.** It is derived from the checks, so the UI could
compute it — but then two definitions of "verified" would exist and would drift. It is emitted as a
computed field and *ignored on input*, so a caller cannot assert a feasibility the checks do not
support. See `test_a_caller_cannot_assert_feasibility_the_checks_do_not_support`.

**D2. The JSON Schema bundle is generated in serialization mode.** Consumers read what the API
emits, and `model_dump` emits every field, so a field with a default is present rather than
optional. Validation mode would also have omitted D1.

**D3. History is the activation timeline, not every committed revision.** A commit whose
compare-and-swap loses the race exists on disk but was never active. Listing it would imply an edit
that took effect. `revisions.activated_at` records the first activation and
`revision_history` reads from it.

**D4. A committed revision does not inherit its preview's evaluation.** The preview's
`run_input_hash` names the preview revision; copying it into the commit would produce an artifact
claiming to be about a revision it was not computed for. The design content is identical, so
re-evaluating reproduces the same numbers under the correct identity.

## What B did not build, and who owns it

- `packages/ingest`, `packages/cad`, `apps/web/src/features/cad` — Team A.
- `packages/evaluate`, `packages/sim`, `apps/web/src/features/simulation` — Team C.
- Real VSPAERO, real STEP export, a language-model provider. `dronebench doctor` lists each of
  these as absent rather than letting the UI imply it exists.
