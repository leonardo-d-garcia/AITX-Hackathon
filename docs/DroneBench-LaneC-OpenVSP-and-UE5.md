# Lane C — OpenVSP now, Unreal Engine 5 next

Rewritten 2026-09-19. Supersedes `DroneBench-LaneC-OpenVSP-handoff.md`.

Short version: **the analytic tier exists and is tested. OpenVSP/VSPAERO is Path 1 and starts immediately. Unreal Engine 5 is Path 2 and starts only when Path 1 clears its gate.** Both paths are written as agent-executable task blocks at the end of each section.

---

## 0. The two paths, and why they are ordered this way

| | Path 1 — OpenVSP/VSPAERO | Path 2 — Unreal Engine 5 |
|---|---|---|
| Buys us | A real solver behind the numbers. Upgrades the fidelity label from "engineering estimate" to "VSPAERO analysis + mission model" | The demo people remember. Cinematic flyover, stress heatmap on real geometry, part picking in a AAA renderer |
| Risk | Native install, Python ABI mismatch, solver setup | Zero prior UE experience on the team, asset pipeline, embedding question |
| Fails how | Loudly and early — it either installs in the first hour or it doesn't | Quietly and late — it eats the last three hours and produces a half-lit hangar |
| Fallback | Analytic tier, already passing 217 tests | R3F viewport, already the shipping frontend |

Path 1 first because it is the one that changes what we are allowed to *claim*. Path 2 second because it changes what the demo *looks like*, and looks are worthless attached to a broken claim.

**The single rule that makes Path 2 affordable:** Unreal is a renderer, not a plant. It does not integrate equations of motion, it does not compute drag, it does not own aircraft state. It reads `simulation_run.json` and draws it. Every hour someone spends building flight physics inside Unreal is an hour spent rebuilding something Lane C already has, in a language nobody on the team writes. If that rule slips, kill Path 2.

---

## 1. What already exists — tier 1, analytic estimate

A working analytic evaluator for small electric fixed-wing aircraft at `~/Coding/dronebench` (separate repo, 217 tests passing). About 10 ms per run.

| Piece | What it computes |
|---|---|
| Aero | Drag build-up (skin friction × form factor × wetted area) + induced drag; Oswald e; CL, L/D |
| Stability | Neutral point from wing + tail lift slopes with downwash; static margin; tail volumes |
| Propulsion | Motor (KV, Rm, I0) + prop (thrust/power coefficients fitted to APC data) + battery with internal resistance; solves throttle for level flight |
| Performance | Stall, best-endurance and best-range speeds, top speed, climb, endurance, range, Wh/km |
| Structure | Wing spars at 21 spanwise stations, sharing the bending moment by stiffness; safety factor at 3.5 g; servo hinge moments |
| Checks | 14 pass/fail checks (stability, stall, climb, spar, tail volume, servos, currents, wiring, payload, clearance) |
| Per part | Function, why it is there, whether removing it breaks anything, material, tolerances, headroom |

Calibration: a Falcon V2 model at 3.5 kg gives 1.48 Wh/km at 55 km/h against a published 1.6 Wh/km. That is a Falcon number, not an Avenger acceptance criterion.

## 2. Fix these four things before anything else

These are cheap, they are blocking, and an agent can do all four in well under an hour.

1. **Unknown must be a real result.** The evaluator fills every field. It has to be able to return `null` with a status of `unknown` and keep going. Weight-dependent checks downstream must handle a null rather than treating it as zero.
2. **Quarantine, don't clamp.** Implausible inputs currently get clamped silently. Retain the raw value, mark it `conflicted`, surface it. Never alter evidence in place.
3. **Drop the flat ±15% band.** Replace with propagated input ranges — low/nominal/high on the uncertain inputs — reported as an "assumption range," not a confidence interval.
4. **V-tail.** The checks assume a conventional horizontal-plus-vertical tail, so the Avenger fails today for the wrong reason. Model two canted panels; use effective projections for tail volume and mark the conventional-tail heuristics `not_applicable` rather than `fail`.

Acceptance: the existing 217 tests still pass, plus new tests covering a null-mass input, a quarantined input, and a V-tail aircraft that reaches a verdict without a spurious failure.

---

## 3. Path 1 — OpenVSP and VSPAERO

### What it is, and what it is not

OpenVSP builds a **parameterized aerodynamic model**; VSPAERO is its vortex-lattice solver. It gives lift and induced drag for a lifting-surface layout, and stability derivatives when they are set up and checked.

It is not a flight simulator and not a bench test. Importing the Avenger's triangle meshes does not produce a usable VSPAERO model. The model has to be **generated from the measured geometry** — wing stations, V-tail panels and cant — which is exactly what `geometry_features.json` provides.

### T+0 to T+1h — the feasibility gate

Install the OpenVSP Python bindings and run one shipped example. Match the binding's Python version exactly; the wheel is built against a specific ABI and will import-error or segfault against the wrong one. Record the exact OpenVSP and VSPAERO version strings into the run manifest — VSPAERO's analysis-input names have changed across major generations, so discover available inputs at runtime rather than copying names from an old tutorial.

**Gate:** if a shipped example has not run by T+1h, stop. Move OpenVSP to a separate machine behind a JSON file boundary and carry on with the analytic tier. Do not spend hour two on it.

### T+1h to T+2h30 — generate, run, check

**Generate** the model from `geometry_features.json`. Wing from the stations. V-tail as two canted panels. Reference area, span and chord set **once** — the most common way to get a plausible-looking wrong answer is to set reference quantities in two places. Save `aircraft.vsp3` as an artifact.

**Run** a small alpha sweep, roughly −2° to 6°, at a stated speed and altitude. Keep solver inputs, raw outputs and logs. Angles convert to radians at the adapter boundary, not inside the solver call.

**Check the run; do not trust it blind.**

- Every returned number finite. No NaN, no Infinity.
- Reference area, span and chord come back as the values we set.
- Lift slope positive across the attached-flow range.
- Left/right symmetry within tolerance on a symmetric aircraft.
- One refined-mesh point to expose mesh sensitivity. Record the actual difference. Do not describe this as a convergence study.

### T+2h30 to T+3h — feed it in and label it

Replace the analytic model's estimated lift and induced drag with the solver's. Keep profile, fuselage and interference drag explicit and separate. **Do not count induced drag twice** — this is the single most likely silent error in the whole path, because the analytic build-up already contains an induced term.

Label the tier honestly in the UI:

- No run for this exact geometry → **"Engineering estimate"**
- Real run for this exact geometry hash → **"VSPAERO analysis + mission model"**

Never compare an analytic baseline against a VSPAERO candidate. If fidelity changes, recompute both sides before showing a delta.

**Stability stays unknown** unless VSPAERO's derivatives are genuinely set up and checked. Do not paper over it with a wing quarter-chord guess. Do not bolt on AVL in the last hours to turn a check green.

### Agent task block — Path 1

```
TASK C1 — Unknowns and quarantine
Repo: ~/Coding/dronebench
Read packages/evaluate before editing. Do not restructure modules.
1. Add an `unknown` status to the claim/result type so any metric can be null.
2. Downstream checks that consume a null input must return status `unknown`,
   not fail and not substitute zero.
3. Replace input clamping with quarantine: retain the raw value, mark
   `conflicted`, surface it in the result. Never mutate the input in place.
4. Replace the flat ±15% band with low/nominal/high propagation over the
   uncertain inputs. Call the output field `assumption_range`.
Acceptance: existing 217 tests pass. Add tests for (a) null battery mass →
CG unknown, not zero; (b) an out-of-range input quarantined not clamped;
(c) assumption_range present and ordered low<=nominal<=high.
Run the full suite and paste the summary line. Do not proceed past a red suite.
```

```
TASK C2 — V-tail
Repo: ~/Coding/dronebench
The 14 checks assume a conventional tail. Model two canted panels instead.
1. Tail volume from effective horizontal/vertical projections of the canted
   panels, using the cant angle from geometry_features.json.
2. Conventional-tail-only heuristics return `not_applicable` for a V-tail,
   never `fail`.
3. Do not invent a cant angle. If geometry_features.json lacks it, return
   unknown and say which field is missing.
Acceptance: a V-tail fixture reaches a verdict with no spurious failures, and
a conventional-tail fixture is unchanged from current behaviour.
```

```
TASK C3 — OpenVSP feasibility gate. TIMEBOX 60 MINUTES.
1. Install the OpenVSP Python bindings. Report the Python version the wheel
   was built against and the interpreter you installed into. If they differ,
   fix that before anything else.
2. Run one example shipped WITH THE INSTALLED BUILD. Do not copy an example
   from the web or from an older version.
3. Print and record exact OpenVSP and VSPAERO version strings.
4. Enumerate available analysis inputs AT RUNTIME and print them. Do not
   hardcode input names.
STOP at 60 minutes regardless of state and report: installed yes/no, versions,
example ran yes/no, the exact error if not. Do not keep trying.
```

```
TASK C4 — Generate, sweep, validate
Only start if C3 reported success.
1. Build aircraft.vsp3 from geometry_features.json. Wing from stations,
   V-tail as two canted panels. Set reference area/span/chord EXACTLY ONCE.
2. Alpha sweep -2,0,2,4,6 degrees at a declared speed and altitude. Convert
   degrees to radians at the adapter boundary only.
3. Persist aircraft.vsp3, solver inputs, raw outputs and logs as artifacts.
4. Validate: all finite; reference quantities match what we set; lift slope
   positive; left/right symmetric within tolerance. Fail loudly on violation.
5. One refined-mesh point. Record the actual delta. Do NOT call it convergence.
Acceptance: a validation report listing each check with pass/fail and the
actual numbers. Do not summarise as "looks reasonable".
```

```
TASK C5 — Wire into the mission model
1. Replace estimated lift and induced drag with solver values. Keep profile,
   fuselage and interference drag explicit and separate.
2. CRITICAL: verify induced drag is not counted twice. Write a test that a
   solver-informed run and an analytic run of the same geometry differ in
   induced drag by a stated mechanism, not by a factor of two.
3. Fidelity tier field: "analytic" unless a real run exists for this exact
   geometry hash, then "vspaero".
4. Stability checks stay `unknown` unless derivatives were actually computed
   and passed C4 validation.
Acceptance: attempting to compare an analytic baseline against a vspaero
candidate raises a typed error rather than returning a delta.
```

---

## 4. The gate between paths

Path 2 does not start until **all** of these are true. Check them off explicitly; do not start Unreal because someone is bored of Python.

- [ ] C1 and C2 merged, suite green
- [ ] C3 returned a verdict either way — installed, or formally moved to the JSON boundary
- [ ] If C3 succeeded: C4 validation report exists with real numbers
- [ ] `simulation_run.json` is being emitted with a frozen schema (§5.2)
- [ ] The R3F viewport already runs the demo end to end

That last one is the important one. **R3F remains the shipping demo path.** Unreal is an upgrade applied on top of a demo that already works, never a replacement for one that doesn't.

Recommended wall-clock: do not begin Path 2 with less than three hours left, and freeze all work at T−45min regardless of state.

---

## 5. Path 2 — Unreal Engine 5

### 5.1 Decide the delivery mode first

This decision costs hours and cannot be deferred.

**Mode A — second window (recommended).** UE5 runs as its own application on the demo machine, ideally a second display. You alt-tab or switch outputs during the demo. Cost: essentially zero infrastructure. The React workbench keeps its R3F viewport for inspection and part picking; Unreal is the cinematic segment of the script.

**Mode B — embedded in React via Pixel Streaming.** UE5 renders headless and streams WebRTC video into an iframe in the workbench. What this actually requires:

- A **packaged standalone build**. The plugin does not stream from editor play-in-editor.
- The **signalling server** from Epic's PixelStreamingInfrastructure repo, on a branch that **matches your UE version exactly**. A 5.5 project with a 5.3 infrastructure folder mostly works and then silently fails, which is the worst possible failure shape at a demo.
- A GPU with a **hardware encoder** — NVENC on NVIDIA, AMF on AMD, VideoToolbox on Mac. Without one you get "No compatible GPU found" and no video at all.
- Localhost-only deployment does remove the STUN/TURN requirement, which is the one genuine simplification available.

Mode B cannot be hosted on Vercel; Vercel serves the frontend, the GPU instance lives elsewhere. If you want Mode B, prototype it on a throwaway blank project **before** putting the aircraft in it, so a failure costs 40 minutes instead of your art pipeline.

Pick Mode A unless someone has already made Pixel Streaming work on this machine.

### 5.2 Telemetry — the contract that keeps Unreal cheap

Unreal consumes what Lane C already emits. Freeze this schema now, on the Python side, before the Unreal work starts.

```json
{
  "meta": {
    "revision_id": "rev_0042",
    "geometry_hash": "sha256:...",
    "fidelity_tier": "analytic | vspaero",
    "solver_versions": {"openvsp": "...", "vspaero": "..."},
    "assumptions": ["straight and level", "no wind", "..."],
    "dt_s": 0.02
  },
  "frames": [
    {
      "t": 0.00,
      "pos_ned": [0.0, 0.0, -120.0],
      "quat": [1.0, 0.0, 0.0, 0.0],
      "Va": 18.5,
      "alpha": 0.043, "beta": 0.0,
      "load_factor_n": 1.0,
      "power_w": 142.0,
      "energy_wh_remaining": 88.4
    }
  ],
  "part_stress": {
    "spar_L": [{"t": 0.0, "sigma_mpa": 41.2, "station_m": 0.0}]
  }
}
```

Notes that matter: `pos_ned` is FRD/NED metres, `quat` is scalar-first, `energy_wh_remaining` is energy usable **after** the mission reserve is withheld. Unreal converts FRD→UE's left-handed Z-up frame at the adapter boundary and nowhere else. Write that conversion once, test it with a nonzero translation and a non-identity rotation, and never let it get duplicated into Blueprints.

**Bake a fallback file.** Generate one good `simulation_run.json` and check it in. If the backend is down at demo time, Unreal still flies.

### 5.3 Geometry into Unreal

Two routes, in order of preference:

1. **Datasmith CAD Importer with the STEP** (AP203/214/242). Tessellates on import and preserves assembly hierarchy, part names and metadata, producing a Static Mesh per body. This is Unreal's genuinely strong suit and the reason part IDs can survive.
2. **The GLB** Lane A already exports for R3F. Simpler, fewer plugins, but check that node names survived the export or part picking dies.

Either way, **tag every imported actor with its `part_id`** immediately on import, via an editor utility script rather than by hand. Everything downstream — picking, heatmap, write-back — keys off that tag.

### 5.4 The two visuals that justify the port

**Stress heatmap.** Do not compute stress in Unreal. Lane C's structure model already gives σ at 21 spanwise stations. Feed it in:

- Dynamic Material Instance on the wing/spar meshes with a scalar parameter for normalised stress.
- Material samples a colormap gradient — viridis or turbo, not rainbow — with the spanwise UV or local position driving the lookup.
- Drive the scalar from `load_factor_n` each frame so the wing visibly lights up during the pull-up and the spiral. That single behaviour is the most persuasive thing in the whole demo, because it shows the physics and the geometry are actually coupled.
- A Material Parameter Collection is the cheap way to push one global load factor to every part at once.

**Terrain flyover.** Landscape with a modest heightmap, an airstrip as a decal or flattened textured strip, a hangar from Fab. Camera on a Sequencer track or a spring-arm chase rig following the telemetry actor. Resist building a large world; a small well-lit one reads better on a projector and never hitches.

### 5.5 Part picking and write-back

Line trace under the cursor → hit actor → read its `part_id` tag → HTTP POST to the FastAPI backend, which owns the Supabase write. Do not put Supabase credentials in the Unreal client. Unreal talks to our API; our API talks to the database. Same rule as the browser.

### 5.6 Acceptance for Path 2

- Aircraft flies the baked `simulation_run.json` with correct attitude — confirm visually that a commanded right turn banks right, which is where frame-conversion bugs surface.
- Heatmap responds to load factor in real time.
- Clicking a part prints the correct `part_id`.
- The whole thing launches from a desktop shortcut in under 30 seconds, cold.
- The R3F demo still works, untouched.

### Agent task block — Path 2

```
TASK U0 — Freeze the telemetry contract. Python side only. Do this BEFORE
touching Unreal.
1. Emit simulation_run.json exactly per the schema in section 5.2.
2. pos_ned in metres FRD, quat scalar-first, energy_wh_remaining net of reserve.
3. Generate and commit ONE good fallback file: a 60-second flight with a
   straight segment, a climb, and a coordinated turn that produces a visible
   load factor above 1.
Acceptance: schema validation test, plus a test that energy never goes below
zero and time is monotonic.
```

```
TASK U1 — Unreal project skeleton. TIMEBOX 45 MINUTES.
1. New UE5 project, Blank, no starter content.
2. Enable Datasmith CAD Importer. Confirm it loads without crashing the editor.
3. Import the STEP. Report: did part hierarchy survive, did names survive.
4. Editor utility script: tag every imported actor with its part_id from
   part_map.json. Do not tag by hand.
STOP at 45 minutes and report state. If the CAD importer fails, fall back to
the GLB and say so.
```

```
TASK U2 — Telemetry replay actor
1. Read simulation_run.json from disk at BeginPlay. File path configurable.
2. ONE frame-conversion function, FRD/NED metres -> UE left-handed Z-up cm.
   Unit-test it with a nonzero translation and a non-identity rotation.
   This function must exist in exactly one place.
3. Interpolate position and attitude between frames; do not snap.
4. Playback controls: play, pause, scrub, 0.5x/1x/2x.
DO NOT implement flight dynamics. DO NOT compute forces. Unreal replays
telemetry. If you find yourself writing an integrator, stop and report.
Acceptance: a commanded right turn in the telemetry banks the aircraft RIGHT
on screen. Verify this explicitly before moving on.
```

```
TASK U3 — Stress heatmap
1. Dynamic Material Instance on wing and spar meshes, scalar param
   `NormalisedStress`, colormap gradient (viridis or turbo, NOT rainbow).
2. Drive the scalar from load_factor_n each frame via a Material Parameter
   Collection.
3. Colour bar widget with real MPa labels, not 0-1.
Do not compute stress in Unreal. Consume part_stress from the telemetry file.
Acceptance: scrubbing to the turn visibly reddens the spar root; scrubbing to
level flight returns it to the low end of the colormap.
```

```
TASK U4 — Scene and camera
1. Landscape, modest heightmap, airstrip strip, hangar asset from Fab.
2. Spring-arm chase camera following the replay actor, with damping.
3. Two Sequencer shots: a low fast pass, and a slow orbit of the parked aircraft.
Keep the playable area small. Do not build an open world.
Acceptance: cold launch to flying aircraft in under 30 seconds.
```

```
TASK U5 — Part picking
1. Line trace under cursor, read the part_id actor tag, highlight the hit part.
2. HTTP POST the part_id to the FastAPI backend.
NEVER put Supabase credentials in the Unreal client. Unreal talks to our API;
our API talks to the database.
```

---

## 6. Rollback

Path 2 is abandoned, not debugged, if any of these happen:

- Pixel Streaming has not produced a video frame after 45 minutes → drop to Mode A immediately.
- The frame conversion is still wrong after two attempts → the aircraft flies inverted on stage; cut it.
- Anyone starts writing physics in Unreal.
- T−45min arrives.

Abandoning costs nothing because R3F never stopped working. Record a screen capture of the Unreal scene as soon as it looks good — a recording labelled "recorded run" is an honest fallback, and it survives a crash on stage.

---

## 7. Running the agent

### Standing instructions

Put this in the repo as `AGENT.md` and load it into every session:

```
Frozen contracts: design_manifest.json, parts.json, geometry_features.json,
evaluation.json, simulation_run.json. Do not change a schema without saying
so explicitly and updating every consumer in the same change.

Never invent a physical number. No aerodynamic coefficient, mass, density,
cant angle or material property may be filled from your own knowledge. If a
value is missing, return unknown and name the missing field.

Unknown is a valid result. Null is not zero.

Simulation does not keep its own copy of the wing dimensions. Geometry comes
from geometry_features.json, always.

Run the test suite before reporting done. Paste the summary line. A red suite
is not done.

Report what you actually verified, not what you expect to be true. "Tests pass"
requires having run them.

Timeboxes are hard stops. Report state at the stop and do not continue.
```

### How to drive it

One task block per session. They are ordered and mostly sequential: C1 and C2 can run in parallel with C3 because C3 is pure environment work, but C4 needs C3 and C5 needs C4. U0 must land before any U-task.

Give it the block verbatim. Resist expanding a block mid-session — if scope grows, finish, commit, start a fresh session with a new block. Long sessions drift, and drift on a frozen contract is expensive.

Verify by running things yourself, not by reading the summary. The two claims most worth distrusting are "tests pass" and "the frame conversion is correct." For the second one, look at the screen: does a right turn bank right.

### Merge discipline

Small vertical slices, merged often. Lane C's repo is separate from the main one — decide now whether it stays separate behind a JSON boundary or gets vendored in, and write that decision down. Discovering at T−1h that two copies of the evaluator have diverged is a demo-ending event.

---

## 8. Handoff between lanes

- **A → C:** `design_manifest.json`, `parts.json`, `geometry_features.json` (FRD frame, metres, claims with status). Simulation must not keep its own copy of the wing dimensions.
- **C → B/UI:** `evaluation.json` (metrics, check statuses, fidelity tier, assumptions, input hashes) and `simulation_run.json` (solver versions, logs, telemetry).
- **C → Unreal:** `simulation_run.json` plus `part_map.json`. Nothing else. Unreal never reads the database directly.
- Battery and spar edits change mass, CG and structure but not the outer shape, so the aerodynamic run can be reused — say so in the UI. A wing edit invalidates it.

## 9. What we will not claim

No airworthiness. No validated flight dynamics. No physical bench test. No accuracy claim beyond the stated input assumptions.

A replay animation shows modelled mission consequences, not flight — and that stays true when the renderer is Unreal. A prettier picture of a model is still a picture of a model. If a judge asks what the simulation is, the answer is: a reduced-order mission model, with vortex-lattice aerodynamics where a real run exists, rendered in a game engine. That answer is both honest and better than what most of the room will say.
