# DroneBench demo — one page, five acts

Goal: a single self-contained HTML file that tells the whole story on a projector,
driven by REAL data already produced by the three lanes. No server, no backend.

Open with: `demo/dronebench_demo.html` (file:// works; three.js from jsDelivr).

## Acts (tabs across the top)

1. **Ingest** — "drop a CAD file" (the Titan Avenger archive, 24 STL files). Shows the
   staging/QA table, the variant choices (wing3 ×3, fuse3 ×3), the frame confirmation,
   and the measured numbers: span 2.2245 m, wing area 0.38075 m², AR 13.0,
   V-tail cant 30.2°, fuselage 0.99125 m. 42 parts, 10 mirrored.
2. **Parts** — interactive 3D (orbit/zoom/click/explode) + part list + claim inspector.
   Colour by claim status; unknown is amber and says "needs evidence", never 0.
3. **Graph** — dependency/evidence graph: click a part, light the path to the things it
   affects (spar → wing panels → structure check; battery → CG → stability).
4. **Suggestions** — three real critiques with real numbers (see data). Each card has
   Apply / Decline. Apply swaps the 3D model to that revision's reconstruction GLB,
   shows the geometry diff, the typed change list, and offers the STEP download.
   A fourth card is the REFUSED one (17 mm spar) and must show why it was refused.
5. **Bench test** — baseline vs improved flying side by side with a HUD (speed, power,
   energy, endurance), play/pause/scrub. On finish, the metrics feed back into the
   Suggestions tab (each card shows its measured delta).

## Hard rules (these are the product's credibility)

- Every number carries where it came from: measured / computed / assumed / unknown.
- Unknown stays unknown. Never render a null as 0.
- The reconstruction is labelled a reconstruction, never "Titan's CAD".
- The VSPAERO polar is Lane C's, run on THEIR fixture geometry — label it as such.
- Flight replay is a modelled mission, not a flight test. Say so in the HUD.

## Files and contract between builders

- `demo/data/demo_data.json` — everything the page needs (built by the data agent).
- `demo/assets/*.glb` — reference + one reconstruction per revision (copied, decimated if big).
- `demo/flight.js` — the bench-test scene, mounted by the page via
  `window.DroneBenchFlight.mount(container, data, opts)` returning
  `{play(), pause(), seek(t), on(event, cb), dispose()}`.
- `demo/dronebench_demo.html` — the page: acts 1–4 + mounts act 5.

Source data on disk (real, already generated):
`/tmp/avenger_demo/design/revisions/` — rev-c1e10160ce73 (baseline confirm),
rev-a24b8cb9f550 (battery +20 mm), rev-6a2f7b11f428 (spar 16→12 mm),
rev-25de2628970d (wing tip +0.1 m). Each edit revision holds changes.json,
edit_status.json, reconstruction.glb, updated_reconstruction.step, parts.json,
geometry_features.json.
