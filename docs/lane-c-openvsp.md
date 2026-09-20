# Lane C and OpenVSP — where we are

Written by Team A, 2026-09-19. Short version: **Lane C's analytic tier already exists and is tested. OpenVSP/VSPAERO has not been started.**

## What already exists (tier 1: analytic estimate)

A working analytic evaluator for small electric fixed-wing aircraft, at `~/Coding/dronebench` (separate repo, 217 tests passing). It does, in about 10 ms per run:

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

**Known gaps against the new architecture:** it fills every field instead of leaving unknowns null, it clamps implausible inputs instead of quarantining them, it carries a flat ±15% band, and its checks assume a conventional tail — so a V-tail or flying wing fails today. Those are the first things Lane C should change.

## What OpenVSP is for, and what it is not

OpenVSP builds a **parameterized aerodynamic model**; VSPAERO is its vortex-lattice solver. It gives lift and induced drag for a lifting-surface layout, and stability derivatives when they are set up and checked.

It is **not** a flight simulator and not a bench test. Importing the Avenger's triangle meshes does not produce a usable VSPAERO model — the model has to be **generated from the measured geometry** (wing stations, V-tail panels and cant), which is exactly what Team A's `geometry_features.json` provides.

## The plan for OpenVSP

1. **Feasibility gate first.** Install the OpenVSP Python bindings and run one of the shipped examples. Match the binding's Python version; record the exact OpenVSP and VSPAERO versions. If it does not install in about an hour, keep it on a separate machine behind a JSON file boundary and carry on with the analytic tier.
2. **Generate the model** from `geometry_features.json`: wing from the stations, V-tail as two canted panels, reference area/span/chord set once. Save `aircraft.vsp3`.
3. **Run a small alpha sweep** (about −2° to 6°) at a stated speed and altitude. Keep the solver inputs, raw outputs and logs as artifacts.
4. **Sanity-check the run**, don't trust it blind: finite numbers, reference quantities as intended, lift slope positive in the attached range, left/right symmetry, and one refined-mesh point to expose mesh sensitivity.
5. **Feed the results into the analytic mission model**, replacing its estimated lift/induced drag while keeping profile, fuselage and interference drag explicit. Do not count induced drag twice.
6. **Label the tier in the UI.** "Engineering estimate" when no run exists, "VSPAERO analysis + mission model" only when a real run for that exact geometry exists. Never compare an analytic baseline against a VSPAERO candidate: recompute both sides.
7. **Stability stays unknown** unless VSPAERO's derivatives are actually set up and checked. Do not paper over it with a wing quarter-chord guess, and do not bolt on another solver in the last hours.

## Handoff between lanes

- **A → C:** `design_manifest.json`, `parts.json`, `geometry_features.json` (FRD frame, metres, claims with status). Simulation must not keep its own copy of the wing dimensions.
- **C → B/UI:** `evaluation.json` (metrics, check statuses, fidelity tier, assumptions, input hashes) and `simulation_run.json` (solver versions, logs, telemetry).
- Battery and spar edits change mass, CG and structure but not the outer shape, so the aerodynamic run can be reused — say so in the UI. A wing edit invalidates it.

## What we will not claim

No airworthiness, no validated flight dynamics, no physical bench test, and no accuracy claim beyond the stated input assumptions. A replay animation shows modelled mission consequences, not flight.
