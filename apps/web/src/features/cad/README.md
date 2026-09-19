# `features/cad` — Team A's viewer components

> **Status: unbuilt and untested.** There is no web root on `team/a-cad` — no `package.json`,
> no bundler, no `node_modules` (disk is tight, so A did not add one). Nothing here has been
> compiled or rendered. It is idiomatic, typed React written against the contract, and it will
> need the usual first-compile fixes when B wires it up.
>
> What **is** verified is the standalone inspector in `packages/viewer/` — same features, one
> self-contained HTML file, checked in headless Chrome. Use that for the demo until the web app
> exists, and treat these components as the port of it.

## Packages B must add

```jsonc
{
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "three": "^0.160.0",            // pin: the static inspector pins r160 too
    "@react-three/fiber": "^8.15.0",
    "@react-three/drei": "^9.99.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/three": "^0.160.0"
  }
}
```

`@react-three/drei`'s `<Environment preset="city">` fetches an HDRI from a CDN. If the demo must
run offline, drop that one line from `CadViewport.tsx` — the three lights beside it are enough.

B owns the root `package.json` and the lockfile (§11), so A did not touch either.

## What the components take

### `<CadViewport>`

The Inspect viewport: orbit/zoom/pan, hover highlight, click-to-pick, explode, and the
reference / reconstruction / overlay modes.

| prop | type | notes |
|---|---|---|
| `manifest` | `DesignManifest` | part ids must match the GLB node names |
| `referenceUrl` | `string` | URL of A1's reference GLB. Required |
| `reconstructionUrl` | `string \| null` | A2's reconstruction GLB; omit and the component pins itself to `reference` |
| `mode` | `'reference' \| 'reconstruction' \| 'overlay'` | controlled; render the label from `VIEW_MODE_LABEL[mode]` |
| `colourBy` | `'status' \| 'category' \| 'neutral'` | default `'status'` |
| `explode` | `number` 0–1 | default 0 |
| `selectedPartId` | `string \| null` | controlled |
| `onSelect` / `onHover` | `(partId \| null) => void` | clicking empty space selects null |
| `onMeasure` | `(dims \| null) => void` | axis-aligned size of the selection, metres |

It owns no revision state and fetches nothing but the two GLB URLs — resolve those through the
shared artifact resolver.

### `<ConfirmPanel>`

Units, axis convention, nose datum, mirror plane, one variant per group, printed-part mass model.
Takes `manifest`, an optional unconfirmed `proposal` from `propose_frame`, `confirmedBy`, and
`onSubmit(payload: ConfirmPayload)`. Submit stays disabled until every variant group is answered
and the axis matrix is a proper rotation. `onPreviewMirror` / `onPreviewVariant` let the host
drive the viewport while the user decides.

`ConfirmPayload` is what `packages/ingest`'s `confirm(...)` takes:
`{design_id, revision_id, units, native_to_frd, nose_datum_native, mirror_plane_native,
variant_selection, mass_model, confirmed_by, notes}`.

### `<PartInspector>`

Takes `manifest`, `partId`, the `measured` dims from `CadViewport.onMeasure`, an optional
`fitReport`, and two optional callbacks: `onProvideClaim(edit: ClaimEdit)` (supplying a value for
an unknown claim — the form requires a provenance note) and `onStartEdit(partId, capability)`.
Unknown always reads "unknown — needs evidence"; it never shows 0.

### `<EditPreview>`

Takes `manifest`, `baseGlbUrl`, `previewGlbUrl`, a `CadEditResult`, and `currentRevisionId`.
Renders the ghost diff, the change ledger and the acceptance checks. Accept is disabled while the
preview is incomplete, stale (`result.base_revision_id !== currentRevisionId`) or has any failed
check; Decline is always enabled.

## Conventions these components assume

- GLB node names equal `part_occurrence.part_id`. A1's `export_reference_glb` and A2's export
  both do this; if either renames nodes, picking silently stops working, so keep it in the
  contract tests.
- trimesh-written GLBs often omit the `NORMAL` attribute, which renders black under a lit
  material. Both the components and the static inspector call `computeVertexNormals()` when it
  is missing.
- GLB axes vs FRD: `glb.x = frd.y`, `glb.y = −frd.z`, `glb.z = −frd.x`. The measured dims are
  reported back in FRD terms.
- Colour is never the only signal. `STATUS_COLOR` is always paired with a text status chip.

## `types.ts`

Hand-written mirror of `dronebench_contracts.models` at schema `0.1.0`, marked temporary.
§11 says the TypeScript types are generated from the contract and that B owns that generation —
replace the file with the generated module, keep the exported names, and the `partStatus` /
`partColor` / `formatClaim` helpers at the bottom can move beside it.
