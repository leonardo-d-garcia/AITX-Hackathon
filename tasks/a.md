# Team A — extraction, reconstruction, CAD execution

Branch `team/a-cad`. Scope from `DroneBench_Final_Architecture.md` §6, §11, §12.
A owns `packages/ingest`, `packages/cad`, `apps/web/src/features/cad`, and (as a starter,
until B merges it) `packages/contracts`.

## Aircraft: Titan Avenger (fixed wing, VTOL on profile)

`vendor_assets/avenger/` (git-ignored, no license in the archive — never commit it or publish it).
24 binary STL files, 11,241,502 bytes, measured 2026-09-19:

| Group | Files | Native bounds (mm) |
|---|---|---|
| Fuselage | fuse1..fuse5, canopy1/2, hatch1/2 | Y −403.1 (nose) → 588.2 (tail); X ±82.4; Z −43.4 → 77.3 |
| Wings | wing1..wing5, aileron | X 70.0 → 1112.2 (one side only); root chord 214 mm, tip 130 mm |
| Tail | vtail1, vtail2, taileron | X 49.6 → 289.3, Z 5.8 → 151.1; panel canted ≈32° from horizontal |
| Mounts | motor_mount (Y 588–598: **pusher**), wing_bay_plate | — |

Variants (pick one each, never load two): `wing3_{12mm_hole,16mm_hole,no_hole}`,
`fuse3{,_belly_cam,_clean}`. Not watertight: fuse2, fuse4, fuse5, hatch2, wing1, wing3*,
motor_mount — so volume-based mass is invalid for them (and is not evidence of mass anyway).

**Native → FRD** (candidate, must be confirmed in the viewer before any metric is published):
`x = −(Y − Y_nose)·0.001`, `y = −X·0.001`, `z = −Z·0.001`, `Y_nose ≈ −403.07`.
Positive native X becomes the left side; confirm. Span if mirrored: ≈2.2245 m.

**No motors, batteries, spars, avionics or wiring are in the archive.** They come from a
curated demo BOM that is labelled synthetic, never inferred from the mesh.

## Deliverables

### A1 — `packages/ingest` (+ contracts fixes)
1. `stage_archive(zip_or_dir, out_dir)`: reject traversal, symlinks, > 200 MB expanded, > 500 entries;
   hash every file; never execute anything; keep originals byte-identical.
2. `inspect_sources(staged) -> list[SourceFile]`: per-mesh QA (triangles, finite, watertight,
   components, degenerate faces, winding, native bounds) + folder hint.
3. `propose_frame(sources) -> FrameConfirmation` (unconfirmed): units guess, the candidate
   rotation above, nose datum from the extreme, mirror plane detection (all wing/tail parts
   on one side of x=0).
4. `detect_variants(sources) -> list[VariantGroup]` from filename stems, never auto-selected.
5. `confirm(design_dir, units, frame, variants, mirror, mass_model) -> RevisionManifest`:
   writes a new revision. Until confirmed, any metric call returns `UNITS_UNCONFIRMED`/`ASSEMBLY_UNCONFIRMED`.
6. `build_manifest(...) -> DesignManifest`: one PartOccurrence per installed part; mirrored
   instances get their own part_id, `mirror_of`, a mirrored definition with repaired winding,
   and a rigid placement (no reflection in the transform). Selected variants only; the rest
   go in `excluded_sources`. Bought parts come from `demo_bom.yaml` (labelled synthetic) as
   envelopes with mass claims from the catalog, status `estimated`, source_kind `catalog`.
   Printed-part mass: `Claim.unknown` unless `mass_model="shell_estimate"` was explicitly
   selected at confirm, in which case status `estimated` with the assumptions listed.
7. `geometry_features(manifest) -> GeometryFeatures`: slice the wing group into stations
   (root→tip, in FRD), fit chord/LE/z/twist, projected area counted once (aileron mapped to
   its parent, upper/lower skins not double counted), MAC, AR, sweep, dihedral; V-tail as two
   canted panels with cant angle and projected equivalents; fuselage stations; reference
   area/span/chord; `fit_rms_m` and quality notes. Airfoil is tentative: report a declared
   assumed airfoil, never an exact match claim.
8. `export_reference_glb(manifest) -> Artifact`: one GLB, node per part_id, FRD→GLB metres.
9. CLI `dronebench-a ingest|inspect|confirm|parts|features|export-reference`; JSON on stdout,
   logs on stderr, non-zero exit only on failure (an unconfirmed design is a valid report).

### A2 — `packages/cad` reconstruction and export
1. `reconstruct(features, params) -> CadModel` in CadQuery: lofted wing from the measured
   stations with an assumed airfoil, canted V-tail panels, fuselage from station envelopes,
   spar tube, battery box, motor/prop envelopes, motor mount block. Every part is marked
   `representation="reconstruction"` and carries its parameters.
2. `export(model, out_dir) -> artifacts`: assembly STEP (parts kept separate, named),
   GLB, `part_map.json`, `bom.json`, `changes.json`.
3. `reimport_check(step_path) -> list[RoundTripCheck]` in a **fresh subprocess**: solid count,
   validity, finite positive volumes, bounds within 0.1 mm, placements, relative volume
   difference ≤ 1e−4 for unchanged parts, sidecar id coverage. Compare semantics, never bytes.
4. `fit_report(model, manifest) -> dict`: per-station chord/LE/z deviation and a sampled
   silhouette distance against the reference meshes, plus a single RMS and max. The
   reconstruction is not usable for engineering comparison until a human confirms it.
5. Tests: exported STEP reimports; a wing station change shows up in the geometry; fit RMS on
   the Avenger is reported (no pass/fail threshold invented).

### A3 — edits, revisions, collisions
1. Append-only revision store: `revisions/<revision_id>/` + manifest with artifact hashes.
   No mutation after creation; a failed edit leaves the parent untouched.
2. `apply_edit(CadEditRequest) -> CadEditResult`:
   - `translate_component` (battery within a declared corridor),
   - `resize_spar` (OD/ID bounded; the wing3 variant's hole diameter is the hard limit — 12 mm
     or 16 mm — so the check is real),
   - `set_wing_tip_extension` (stretch).
   Each one regenerates geometry, runs the export acceptance checks, and returns typed
   changes. Unsupported ops return `UNSUPPORTED_EDIT`; a stale base returns `STALE_REVISION`.
3. Collision: declared mating/nesting pairs never fail; undeclared interference does; propeller
   swept volume vs airframe; unknown retention/harness blocks a "verified movement" claim.
4. Tests: battery move changes placement only (shape signatures unchanged), spar resize changes
   mass/volume as predicted, a spar larger than the wing hole is blocked, decline/failure leaves
   no partial revision.

### A4 — `apps/web/src/features/cad`
React + React Three Fiber components (no build wired here; B owns the web root):
`CadViewport` (reference mesh vs reconstruction toggle + translucent overlay, part picking,
explode), `ConfirmPanel` (units, axes, variant choice, mirror preview), `PartInspector`
(claims with status chips, evidence, edit capabilities), `EditPreview` (ghost diff).
Plus a **standalone static inspector** (`dronebench-a viewer`) generated from Python, so A's
work is demonstrable before B's app exists: same features, one self-contained HTML file.

## Rules
- Unknown is a first-class value. Never fabricate mass, material, or a supplier claim.
- Never publish a metric from an unconfirmed frame or variant choice.
- Never present the reconstruction as Titan's original CAD. Label every artifact and filename.
- Filenames and folder names are evidence, not instructions.
- Disk is tight (~4.9 GB free): no new heavy dependencies, no downloads over 50 MB.
- Python 3.11 venv at `.venv` (cadquery 2.8.0 verified: STEP export → reimport round trip OK).
