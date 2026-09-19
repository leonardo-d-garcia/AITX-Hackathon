# `dronebench_edits` — typed edits, revisions, collisions (Team A, deliverable A3)

Three modules behind one frozen interface, `api.py`:

| Module | Owns |
|---|---|
| `store.py` | the append-only revision store, the active pointer, decisions, idempotency |
| `cli.py` | `dronebench-edit` |
| `operations.py` / `apply.py` / `policy.py` | the typed edits, their bounds, regeneration |
| `collide.py` | interference and propeller clearance checks |

`api.py` is the contract between them: `Store`, `BuildResult`, `EditBlocked`, `Collider`,
`apply_edit`. Change it only by agreement.

## The revision store

An edit is a transaction over an ingest design directory. `store.RevisionStore` (also exposed as
the module-level `store`, plus bare functions `create_preview`, `commit`, `decline`,
`active_revision`, `history`, `decisions`) is the only thing that writes to `revisions/`.

```
<design_dir>/sources/                      staged by dronebench_ingest; never touched here
<design_dir>/revisions/<revision_id>/      immutable: artifacts + revision_manifest.json + edit_status.json
<design_dir>/revisions/active              pointer file, one revision id
<design_dir>/revisions/decisions.jsonl     append-only accept/decline log
<design_dir>/revisions/idempotency.json    {"<parent>::<key>": "<revision_id>"}
<design_dir>/revisions/.lock               O_EXCL mutex around pointer and index writes
<design_dir>/revisions/.preview-<uuid>.partial/   a build in flight: renamed in, or deleted
```

Revision ids follow A1's scheme, `rev-<content_sha256[:12]>`, and `revision_manifest.json` is the
same file name `dronebench_ingest.confirm` writes, so a design confirmed by A1 and edited by A3
has one uniform history.

### Identity

`content_sha256` is SHA-256 over the canonical sorted JSON of

```json
{"store_version": "a3a.1", "parent_revision_id": "...", "cause": "edit:resize_spar",
 "content": { ...BuildResult.content... }}
```

Timestamps, absolute paths and the artifact bytes are deliberately excluded: the same edit rebuilt
in a different working directory, or at a different moment, must name the same revision. Artifact
hashes live in the enclosing manifest, never inside the bytes they describe.

The consequence is a requirement on the caller: **`BuildResult.content` must carry everything that
distinguishes one edit from another** — operation, target part ids, parameters in SI, and the
version of any parameter set the build read. Two edits that declare the same `content` off the same
parent *are* the same revision as far as this store is concerned, and the second one is returned
rather than rebuilt.

### The transaction

`create_preview(design_dir, parent_revision_id, cause, build, idempotency_key=None)` makes a
private working directory, calls `build(workdir)`, re-hashes every artifact the build declared
*from the bytes on disk*, writes `revision_manifest.json` with state `preview`, and atomically
renames the directory into place. The active pointer does not move: a preview is something to look
at. Artifact paths must be relative and stay inside the revision; a declared file that was never
written is `ARTIFACT_MISMATCH`.

If `build` raises anything — `EditBlocked` from a bound, or a kernel crash — the working directory
is removed and the exception propagates unchanged. No revision directory, no pointer change, no
index entry.

### The verdict: `edit_status.json`

Every preview carries the store's verdict beside the geometry it judges, hashed and listed in the
manifest like any other artifact:

```json
{"status": "ok" | "blocked" | "failed", "committable": true, "verified": false,
 "blocking_checks": [], "advisory_checks": ["verified_movement_unknown"],
 "failed_checks": ["verified_movement_unknown"],
 "unverified_reasons": ["verified_movement_unknown: battery retention and harness are unknown"],
 "reason": null, "cause": "edit:translate_component", "parent_revision_id": "rev-...",
 "checks": [...], "changes": [...], "affected_part_ids": [...]}
```

The status is derived from the build's own evidence, and the store separates *this geometry is
wrong* from *we do not know*:

- **Hard checks** — everything not named in `store.ADVISORY_CHECKS`: interference, propeller
  clearance, every reimport/round-trip check, a check that could not run. One failure makes the
  preview `blocked` and uncommittable.
- **Advisory checks** — `ADVISORY_CHECKS = {"verified_movement_unknown"}`, an evidence gap rather
  than a geometric failure. Architecture §6: unknown retention or harness interfaces block a
  *verified movement claim*, not the operation. A failure here leaves the preview `ok` and
  committable and sets `verified: false`, with the detail text in `unverified_reasons`. The move
  happens; nobody may call it verified. Extend the set only for checks whose failure means "we do
  not know".

`blocking_checks` drives the refusal, `advisory_checks` never does, and `failed_checks` is both.
A caller may also declare the verdict by putting `"edit_status"` in `BuildResult.content`; a
declared non-`ok` is honoured even when the checks are green, but a declared `ok` never overrides a
failed **hard** check. A blocked preview gets its own revision id (the status joins the hash), so it
can never be mistaken for the passing version of the same edit; `verified` does not join the hash,
because it describes the evidence around an edit rather than the edit's inputs. Read it back with
`store.edit_status(design_dir, revision_id)`; `dronebench-edit history` shows it per revision.
`None` means the revision was never an edit — that is what A1's `confirm` leaves.

### Committing

`commit(design_dir, preview_revision_id, expected_active)` runs four gates, all typed refusals,
none of them a crash:

1. `preview_revision_id` must be a real id — `None`, `""`, a non-string or anything with a path
   separator is `INPUT_REJECTED` *before* any path is built from it; an id that names nothing is
   `MISSING_EVIDENCE`.
2. The recorded verdict must be `ok`, else `CONSTRAINT_FAILED` naming the *blocking* checks in
   `details.failed_checks` (advisory ones travel separately in `details.advisory_checks` and never
   cause a refusal). **A blocked edit never becomes the active revision**, whatever the caller
   believes about it.
3. Every artifact must still be on disk with the hash the manifest recorded, else
   `ARTIFACT_MISMATCH`. A commit cannot publish a half-written revision.
4. `expected_active` must still be active, else `STALE_REVISION` naming both ids.

Nothing moves unless all four pass. On success the preview's own manifest is rewritten to state
`committed` (the one edit a revision directory ever receives; artifacts and content hash are
untouched) and `active` points at it. Passing `expected_active=None` waives gate 4 only — use it
for the first commit of a design or a deliberate force.

`decline(design_dir, preview_revision_id, reason)` appends a line to `decisions.jsonl`. It changes
no geometry and leaves `active` alone; the preview stays a preview, so it can still be inspected or
accepted later against the then-current active revision.

`active_revision(design_dir)` reads the pointer, falling back to the newest committed revision when
there is none — which is the state A1's `confirm` leaves a design in. `history(design_dir)` returns
every revision newest first with `parent_revision_id` links intact, children never above their own
parent. Both read `revision_manifest.json` and nothing else: a revision that carries no
`design_manifest.json` (an edit whose builder has not carried the parts list forward) still lists
and can still be active, and a directory whose own manifest is unreadable is skipped rather than
taking the listing down. `dronebench_ingest.load_manifest` is stricter — it needs the parts list —
so whoever writes an edit revision owns putting `design_manifest.json` in it.

Idempotency is per `(parent, key)`: a repeat `create_preview` with the same key returns the first
call's manifest and does not run `build` again. Under a genuine race both callers may build, but
only one directory is published and both get the same id back.

## `dronebench-edit`

JSON on stdout, human logs on stderr. Exit `0` on success, `2` on a usage error, `1` when the
command could not be carried out. **A blocked edit is a success**: the tool did its job by
refusing, so it prints a typed `ErrorEnvelope` or a `CadEditResult` with `status: "blocked"` and
exits `0`.

```bash
dronebench-edit active   <design_dir>
dronebench-edit history  <design_dir> [--limit N]
dronebench-edit decisions <design_dir>

dronebench-edit accept   <design_dir> <preview_revision_id> [--expected-active <revision_id>]
dronebench-edit decline  <design_dir> <preview_revision_id> --reason "static margin drops"

dronebench-edit propose  <design_dir> --operation resize_spar \
                         --target spar-main --params '{"od_m": 0.016}' \
                         [--base <revision_id>] [--idempotency-key k] [--accept]
dronebench-edit preview  ...    # alias of propose
```

`propose`/`preview` build a `CadEditRequest` and hand it to `dronebench_edits.apply_edit`, imported
lazily so the read and transaction commands work with or without the edit operations installed. If
they are missing the tool prints an `UNSUPPORTED_EDIT` envelope and exits `1`. `--base` defaults to
the active revision; `--accept` commits the preview against that base when the result is `ok`.

## Edit operations, bounds and `apply_edit` (`operations.py` / `policy.py` / `apply.py`, A3b)

```python
from dronebench_edits.apply import apply_edit
result = apply_edit(design_dir, request, store=None, collider=None, policy=None)  # CadEditResult
```

`store`, `collider` and `policy` default to `RevisionStore()`, `collide` and
`packages/edits/edit_policy.yaml`; pass your own to test one layer in isolation.

One edit is: load the manifest and the parent parameter set, refuse it or not
(`policy.check_bounds`), run the pure kernel (`operations.*`), then let the store build the
preview — regenerate with `dronebench_cad.reconstruct`, `export`, `reimport_check` in a fresh
process, and `collide.check`. The parent revision is never touched, and a build that raises
leaves no revision behind.

### The kernels

Each is pure: the parent `ReconParams` is never mutated, and each returns `(new_params, changes)`
where a change is `{part_id, field, before, after, unit, ...}`.

| Function | Effect |
|---|---|
| `translate_component(params, part_id, delta_m)` | moves the movable envelope (the battery). Placement only — the dimensions are untouched |
| `resize_spar(params, outer_d_mm, inner_d_mm=None)` | regenerates the tube; the parent wall thickness is kept unless a bore is given |
| `set_wing_tip_extension(params, extension_m)` | both wing occurrences in one transaction; `reconstruct()` mirrors the panel, so the two sides cannot diverge |

`apply_edit` adds the acceptance checks the architecture asks for: the requested parameter change
is visible in the regenerated geometry, every part the edit did not name is identical to 1e-9 in
volume and centroid, and every solid is valid with a positive volume. The preview also carries its
own `params.yaml`, so the next edit chains off the previous one.

**Unknown stays unknown.** Mass and CG are not known for this aircraft: the printed parts have no
measured mass and the hardware is a synthetic demo BOM. Moving the battery therefore reports a CG
change with `before` and `after` both `null`, `status: "unknown"` and a note — never a number.
A spar resize reports the new cross-section and says the mass is unknown because no material is
claimed. A tip extension reports that the spar was deliberately *not* lengthened with it.

### What a preview revision contains

An edit revision that held only geometry would leave the design unloadable — `load_manifest`
raises, the viewer has no parts, the fit report has no reference. So every preview carries the
design's identity forward beside the new geometry:

| File | Where it comes from |
|---|---|
| `updated_reconstruction.step`, `reconstruction.glb`, `part_map.json`, `bom.json`, `changes.json` | regenerated by `dronebench_cad.export` |
| `params.yaml` | the edited parameter set, so the next edit chains off this one |
| `design_manifest.json`, `parts.json` | the parent's, with the placement updated for any occurrence the edit actually moved, and a warning naming the edit |
| `geometry_features.json` | the parent's, annotated with the edit; after a tip extension the span is restated as `computed` from the parameter and the planform quantities that were not re-derived are marked `conflicted` |
| `reference_meshes.glb` | hard-linked from the parent — identical bytes, no second copy, and revisions are immutable |

`revision_id` inside the carried manifest still names the revision the aircraft was *measured*
in, because the store computes the new id from the build's own content hash; the warning says so.

### Targets

`target_part_ids` may name a manifest occurrence (the battery envelope's hashed BOM id) or a
reconstruction part (`recon_spar`, `recon_wing_right`). It has to allow both: the archive contains
no spar at all, and the wings are lofted surrogates, so those parts exist only in the
reconstruction and have no manifest occurrence to name. An operation with exactly one possible
target — `resize_spar`, and `set_wing_tip_extension`, which always moves both wing occurrences in
one transaction — resolves it from the parameter set when the caller names none.
`translate_component` never does: which component is moving *is* the request.

Nothing comes back refused without a reason. Every non-`ok` result carries an `ErrorEnvelope`
naming the bound, capability or check that refused it, and the store records its own verdict in
`edit_status.json`, so a preview with a failed check cannot be committed even if a caller tries.

### Where the bounds come from

Every limit is declared in `packages/edits/edit_policy.yaml`, never in code, and every entry says
whether it is a demo fixture. All of them are — except one.

| Bound | Value | Source |
|---|---|---|
| battery corridor (centre, FRD m) | x ∈ [−0.420, −0.120], y ∈ ±0.020, z ∈ [−0.030, 0.015] | DEMO FIXTURE: the lofted fuselage bay, eyeballed; the printed bay is not reconstructed |
| harness allowance | 0.030 m per edit | DEMO FIXTURE: stands in for slack in an unknown harness and an unknown retention strap |
| spar wall thickness floor | 0.5 mm | DEMO FIXTURE: no material, layup or supplier is claimed |
| spar minimum OD | 4 mm | DEMO FIXTURE: sanity floor |
| **spar OD ceiling** | **12 mm / 16 mm / none** | **REAL: the confirmed `wing3` variant.** `wing3_12mm_hole` → 12 mm, `wing3_16mm_hole` → 16 mm, `wing3_no_hole` → no through-spar at all |
| tip extension | −0.050 … 0.150 m | DEMO FIXTURE: the tip joint, rib and spar stub are not reconstructed |
| propeller clearance | ≥ 0.010 m | DEMO FIXTURE: no blade geometry, no flex or vibration model |
| interference tolerance | 0.0005 m | DEMO FIXTURE: architecture §6 demo validation setting |
| declared overlap pairs | spar↔wing, spar↔fuselage, battery↔fuselage, motor↔mount, wing↔fuselage, … | intended mating of the *reconstruction*; the reference meshes carry their own `allowed_overlap_with` in the manifest |

`policy.spar_hole_limit_mm(manifest)` reads the selection a human made at ingest
(`DesignManifest.variants`). No confirmed `wing3`, an undeclared variant, or `wing3_no_hole` all
refuse the resize: an unknown limit is never guessed.

### Refusals

`check_bounds` raises `EditBlocked` carrying a typed `ErrorEnvelope`; `apply_edit` turns it into
`status="blocked"` and never raises for a refused edit.

* `UNSUPPORTED_EDIT` — an operation this kernel does not implement (`replace_catalog_component` is
  in the contract's enum as a stretch item and is refused here), a locked reference mesh, a target
  whose `edit_capabilities` do not include the operation, or an unknown part id.
* `CONSTRAINT_FAILED` — a declared bound was crossed. The message always names the limit, the
  limit's source and the requested value, e.g.
  `requested spar outer diameter 17 mm exceeds the 16 mm rib hole of the confirmed wing3 variant
  'wing3_16mm_hole' (limit spar.outer_diameter_ceiling, source: confirmed wing3 variant …)`.
* `MISSING_EVIDENCE` — the geometry is clean but the edit cannot be called *verified*, because
  A3c found an evidence gap (unknown retention, harness or mount interface). A battery move on
  this aircraft ends here by design: the preview exists and can be inspected, but nothing claims
  the pack stays put. The fix is a measurement, not a different edit.
* `GEOMETRY_INVALID` — regeneration, export or the store raised; `status="failed"`.

Targets are resolved manifest-first: a `PartOccurrence` brings its own `edit_capabilities`, and the
battery envelope's hashed BOM id maps onto `recon_battery` by category. The synthetic spar and the
lofted wings have no manifest counterpart at all (the archive contains no spar), so
`reconstruction_targets` in the policy file declares what they may do.

## Tests

`tests/edits/` — `conftest.py` provides `avenger_design` (the real archive staged and confirmed
once per session: wing3_16mm_hole + fuse3_clean, mm, mirrored about x=0), `tiny_design` (three
synthetic boxes, per test) and `fake_build` (a `build` callback writing small files, so store tests
never reconstruct CAD).

```bash
.venv/bin/python -m pytest tests/edits -q
```

## Collision and clearance checks (`collide.py`, A3c)

```python
from dronebench_edits.collide import check
checks = check(model, manifest, params, policy, changed_part_ids=None)  # -> list[RoundTripCheck]
```

`model` is a `CadModel` (or anything with `.parts`), `manifest` a `DesignManifest` or its JSON,
`params` the `ReconParams` that built the model, `policy` the loaded `edit_policy.yaml` as a plain
dict. It implements the `Collider` protocol in `api.py` and **never raises**: bad input comes back
as a failed check.

| Check | Meaning |
|---|---|
| `collision_declared_engagement` | Engagement depth of pairs that are *allowed* to overlap. Always `passed=True` — intended mating is evidence, not a verdict. |
| `collision_undeclared_interference` | Two parts nobody declared may overlap do, deeper than `interference_tolerance_m` (default 0.5 mm). `passed=False` blocks the edit; the detail names both part ids and the depth. |
| `propeller_clearance` | Minimum distance from the propeller swept volume to every airframe part. `passed=False` below `prop_clearance_min_m`. |
| `verified_movement_unknown` | An **evidence** gap, not a geometric one: a moved part whose retention / harness / mount interface is unknown, so "it still fits and stays put" cannot be verified. Emitted only when `changed_part_ids` is given. A3b must treat this differently from a hard interference. |
| `collision_geometry_unusable` | A part could not be tessellated, or its mesh is degenerate or not a closed volume, so it was left out of the measurements. |
| `collision_check_error` | The check itself could not run. Returned instead of raising. |

**Declared pairs.** A pair is declared when either side lists the other in its
`PartOccurrence.allowed_overlap_with`, or when it matches a pattern pair in the policy
(`declared_overlaps` or `edit_policy.yaml`'s `declared_overlap_pairs`, e.g. `[spar*, wing*]`,
glob-matched in both orders). Proximity alone never declares a pair.

**Depth.** Sampled points of A (its vertices plus an even surface sample) are tested for
containment in B, and the deepest contained point's distance to B's surface is the penetration —
measured both ways, the larger wins. A part that is not a closed volume cannot be tested for
containment; the depth is then reported as unmeasurable in the detail rather than guessed.

**Clearance.** The swept volume is a disc built from the prop envelope in `params`, on the axis
from the motor to the propeller — so the Avenger reports `pusher (disc aft of the motor)` because
the geometry says so, not because it was hardcoded. Distance is the minimum sampled surface
distance in both directions. The motor and its mount (`motor.part_id` / `motor.mount_part_id`) are
reported as drivetrain, not airframe, and do not fail the check.

**Cost.** Tessellation is cached per `(part_id, shape signature)`, so a repeated call inside an
edit loop re-meshes nothing (`collide.cache_stats()`, `collide.clear_cache()`). Pairs are
prefiltered by expanded AABB overlap, and `changed_part_ids` restricts the pairs to those
involving a changed part — the detail says how many pairs were skipped as untouched. On the
reconstructed Avenger (11 parts, 55 pairs): 11 pairs measured, 44 rejected on bounding box,
2.6 s cold / 1.1 s with the tessellations cached; a single-part edit is ~1.0 s.

**Limits.** Containment sampling can miss a shallow edge-only crossing that contains no sample
point; the tolerance, not the sampling, is the declared floor. Meshes that are not closed volumes
are excluded from depth (never silently passed). The swept volume is a disc, not blade geometry,
and carries no vibration, flex or gyroscopic model. Everything is measured on the 0.1 mm-deviation
tessellation, not on the exact B-rep.

```
.venv/bin/python -m pytest tests/edits/test_collide.py -q
```
