# DroneBench Studio — repository instructions

The specification is `DroneBench_Final_Architecture.md`. It is normative. This file is a short
orientation, not a summary of it — read the relevant section before changing anything substantial.

> **Scope note.** `README.md` and `PRD.md` describe the earlier scorer, which "never suggests
> changes — no recommendations, no suppliers". The architecture packet supersedes that (§2): the
> product is now a workbench with an evidence graph, a recommender, an approval transaction, and a
> visualisation. Those two files are left as the repository owner wrote them.

## What this is

Import a design → inspect the evidence behind every claim → trace what depends on what → propose a
bounded change → preview its real consequences → accept or decline → export → compare runs.

The valuable property is traceability across that whole loop. A big graph or a pretty flight
animation on their own do not demonstrate it.

## Ownership (§11)

| Lane | Owns | Do not edit |
|---|---|---|
| A | `packages/ingest`, `packages/cad`, `apps/web/src/features/cad` | anything else |
| **B** | `packages/{contracts,graph,recommend,workflow}`, `apps/api`, `apps/web/src/app`, `apps/web/src/features/{graph,review}`, `tests/`, root dependency files | `packages/{ingest,cad,evaluate,sim}` |
| C | `packages/evaluate`, `packages/sim`, `apps/web/src/features/simulation` | anything else |

Only B changes root dependency files, app routing, and schema versions. A breaking contract change
needs a note in `docs/decisions/`, updated examples, and consumer validation in the same merge.

## Rules that are easy to break by accident

1. **Unknown is a first-class result.** A missing value stays `null`. It is not zero, it carries no
   confidence, and it propagates: one occurrence with no mass makes every weight-dependent check
   unknown. Do not add a default to make a number appear.
2. **Geometry does not determine mass, material, or function.** A filled bounding envelope is not
   "plastic volume". A placement datum is not a centre of mass.
3. **`near` is not `mates_with`.** Proximity is inferred and proves nothing. `compatible_with` is
   computed from declared interfaces only, never from graph proximity.
4. **A label may not outrun its artifact.** `vspaero_informed` requires a real solver run attached.
   A download requires a passing round trip. Where a capability is absent, say so — `dronebench
   doctor` lists what this installation cannot do.
5. **An edit is a typed operation, never interpreted code.** The four operations in §6 are the
   whole union. Never execute model-authored Python, CadQuery, or shell.
6. **Accept commits precisely the reviewed preview.** The request quotes the preview hash and the
   expected active revision; the pointer moves under compare-and-swap. Decline changes nothing.
7. **Modelled infeasibility is a result, not an error.** The CLI exits 4 for it, distinct from 2
   (invalid input) and 3 (tool failure).
8. **Events never carry chain-of-thought.** Tool name, input summary, artifact refs, status,
   elapsed time. The model has no field for anything else.

## Working here

```bash
# Python (3.11+). No install needed; the paths are on pytest's pythonpath.
python -m pytest tests -q

# Regenerate the contract artifacts after any change to packages/contracts
python -m dronebench_contracts.schema schema
python scripts/generate_ts_types.py

# Rebuild the frozen fixture (a contract change — see docs/decisions/0001)
python fixtures/b/build_fixture.py

# CLI
python -m dronebench_api.cli --root artifacts/workbench doctor
python -m dronebench_api.cli --root artifacts/workbench ingest

# API and web
uvicorn dronebench_api.main:app --reload      # needs the `serve` extra
cd apps/web && npm install && npm run dev
```

Set `PYTHONPATH` to `packages/contracts;packages/graph;packages/recommend;packages/workflow;apps/api`
when running outside pytest, or `pip install -e .`.

## Verification means numbers, not assertions

Before calling something done: run `python -m pytest tests -q`, and for anything touching the web
app, `cd apps/web && npx tsc --noEmit && npx vite build`. For a change to the fixture or the
evaluator, print the resulting checks and compare them against `docs/decisions/0002`, which records
the intended scenario and the numbers it produces.

## Context discipline

Do not paste mesh data, solver logs, or whole Parquet/JSON artifacts into a model's context. Pass
compact descriptors, the relevant failure, and artifact paths. `ProposalContext` exists to be the
entire input surface a provider sees; keep it that way.
