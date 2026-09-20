# C4 OpenVSP generate / alpha sweep / validate

Aircraft generated from `fixtures/c/synthetic_vtail_demo/geometry_features.json`.
OpenVSP parameterized wing + V-tail; triangle meshes were not imported.

## Environment

- OpenVSP: `OpenVSP 3.51.3`
- VSPAERO: `VSPAERO v.7.2.2 --- Compiled on: Aug 17 2026 at 20:47:37 PST`
- interpreter: `/root/openvsp-c3/venv/bin/python`
- python: `3.14.4 (main, Aug 20 2026, 10:41:58) [GCC 15.2.0]`
- geometry_hash: `f0d361e699ec0a56c4664ac82a5489be8708a0a6c52a2bdca77909690a25ce1c`

## Model choices (not invented aero numbers)

- OpenVSP WING + V-tail use geom Sym_Planar_Flag=SYM_XZ (left side is the XZ mirror).
- Airfoil is the OpenVSP WING default four-series (t/c=0.10, camber=0); geometry_features.json has no airfoil.
- VSPAEROSweep AlphaStart/AlphaEnd are degrees on OpenVSP 3.51.3 (defaults 0 and 10; shipped tests pass 1.0 deg).
- Sref/bref/cref are set once on VSPAEROSweep with RefFlag=MANUAL_REF. Not copied onto WingGeom TotalArea/TotalSpan.
- V-tail root LE is at X_vsp=tail_arm_m (aft of model origin). No extra AC offset is applied.
- MachStart=0 (incompressible). Vinf and Rho come from the fixture. Speed of sound is not in the fixture.
- Panel chord = panel_area_m2 / panel_span_m (rectangular; fixture has no tail taper).
- 2*tip_y=2.2 m matches reference.b_m

## Sweep

- alphas_deg: `[-2.0, 0.0, 2.0, 4.0, 6.0]`
- Vinf_mps: `15.0`
- altitude_m: `120.0`
- Rho: `1.225`
- Alpha unit: `deg` — OpenVSP 3.51.3 VSPAEROSweep AlphaStart/AlphaEnd are degrees. GetAnalysisInputDoc: defaults AlphaStart=0.0, AlphaEnd=10.0, AlphaNpts=3. Shipped /opt/OpenVSP/scripts/python_scripts/SweptTest.py and HersheyTest.py set AlphaStart=[1.0] and treat CL_alpha as per-degree (multiply theoretical per-rad by pi/180). Adapter does not convert to radians.

## Validation

| check | result | numbers |
|---|---|---|
| every returned number finite | PASS | count=53, nonfinite=[], min=-2, max=15 |
| reference S/b/c come back as set | PASS | set_Sref=0.4, set_bref=2.2, set_cref=0.2, readback_Sref=0.4, readback_bref=2.2, readback_cref=0.2, history_Sref=0.4, history_bref=2.2, history_cref=0.2 |
| lift slope dCL/dalpha > 0 from -2 to 6 deg | PASS | alphas_deg=[-2.0, 0.0, 2.0, 4.0, 6.0], CL=[-0.305746565536, -0.07699981555, 0.151546782981, 0.379698147482, 0.606676163152], dCL_dalpha_per_deg=[0.11437337499299999, 0.1142732992655, 0.1140756822505, 0.11348900783500002] |
| left/right symmetry (CStot side force, CMxtot rolling) | PASS | tolerance_abs_CStot=0.005, tolerance_abs_CMxtot=0.005, CStot=[4.20732e-07, 7.88892e-07, 1.4315673e-05, 2.7987694e-05, 4.550201e-05], CMxtot=[-7.6184e-08, 6.2676e-08, -1.967925e-06, -4.004084e-06, -5.675597e-06], max_abs_CStot=4.550201e-05, max_abs_CMxtot=5.675597e-06, method=full-span model via OpenVSP SYM_XZ; VSPAEROSweep Symmetry=0; this 3.51.3 history names CStot (side) and CMxtot (roll) |
| one refined-mesh point (not a convergence study) | PASS | alpha_deg=2, CL_baseline=0.15154678, CL_refined=0.14957152, dCL=-0.0019752582, CDi_baseline=0.00099181864, CDi_refined=0.0010410698, dCDi=4.9251195e-05, tess_u=8 -> 16, tess_w=17 -> 33, note=Single refined-mesh point (SectTess_U and Tess_W doubled). Not a convergence study. |
| MainWing TotalProjectedSpan near reference.b_m (geometry check, not Sref) | PASS | TotalProjectedSpan=2.2, TotalSpan=2.2014994, TotalArea=0.48431322, reference_b_m=2.2, tol_m=0.05 |

## Polar (VSPAERO, last wake iteration)

| alpha_deg | CL | CDi | CStot | CMxtot |
|---|---|---|---|---|
| -2 | -0.30574657 | 0.0028226023 | 4.20732e-07 | -7.6184e-08 |
| 0 | -0.076999816 | 0.00040392802 | 7.88892e-07 | 6.2676e-08 |
| 2 | 0.15154678 | 0.00099181864 | 1.4315673e-05 | -1.967925e-06 |
| 4 | 0.37969815 | 0.0045823853 | 2.7987694e-05 | -4.004084e-06 |
| 6 | 0.60667616 | 0.011130069 | 4.550201e-05 | -5.675597e-06 |

## Refined-mesh point

Single point. **Not a convergence study.**

- alpha_deg: `2`
- tess_u baseline/refined: `8` / `16`
- tess_w baseline/refined: `17` / `33`
- CL baseline/refined/delta: `0.15154678` / `0.14957152` / `-0.0019752582`
- CDi baseline/refined/delta: `0.00099181864` / `0.0010410698` / `4.9251195e-05`

## Artifact paths

- vsp3: `/mnt/c/Users/leona/.grok/worktrees/downloads-aitx-hackathon/subagent-01a0bbac-589d-7aa2-8a89-e22217069693/artifacts/openvsp/aircraft.vsp3`
- solver_inputs: `/mnt/c/Users/leona/.grok/worktrees/downloads-aitx-hackathon/subagent-01a0bbac-589d-7aa2-8a89-e22217069693/artifacts/openvsp/solver_inputs.json`
- outputs: `/mnt/c/Users/leona/.grok/worktrees/downloads-aitx-hackathon/subagent-01a0bbac-589d-7aa2-8a89-e22217069693/artifacts/openvsp/raw_outputs.json`
- csv: `/mnt/c/Users/leona/.grok/worktrees/downloads-aitx-hackathon/subagent-01a0bbac-589d-7aa2-8a89-e22217069693/artifacts/openvsp/vspaero_results.csv`
- logs: `/mnt/c/Users/leona/.grok/worktrees/downloads-aitx-hackathon/subagent-01a0bbac-589d-7aa2-8a89-e22217069693/artifacts/openvsp/vspaero.log`
- sweep_result: `/mnt/c/Users/leona/.grok/worktrees/downloads-aitx-hackathon/subagent-01a0bbac-589d-7aa2-8a89-e22217069693/artifacts/openvsp/sweep_result.json`
