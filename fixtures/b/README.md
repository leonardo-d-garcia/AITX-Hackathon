# `parametric_fixedwing` — a synthetic demonstrator

**This is not the Titan Avenger.** It is not derived from the supplied archive, it is not a
reconstruction of any real aircraft, and every catalog offer attached to it is a labelled demo
entry with no implied real supplier, price, or availability.

It exists because Team B's revision store, evidence graph, recommender, and approval transaction
all need a design to operate on, and Team A's importer does not exist yet. Architecture section 12
authorises exactly this: *"use a simpler clearly named parametric fixed-wing fixture."*

## What is here

| File | Produced by | Contents |
|---|---|---|
| `design_manifest.json` | A (fixture) | Identity, representation mode, notes |
| `parts.json` | A (fixture) | 12 definitions, 17 installed occurrences, 13 evidence records |
| `geometry_features.json` | A (fixture) | Wing stations, reference quantities, V-tail panels, assumed neutral point |
| `mission.json` | B | Locked cruise mission, CG envelope, static-margin band, Part 107 profile |
| `../common/catalog.json` | B | 8 synthetic catalog items across batteries, spars, and servos |
| `FIXTURE_HASH` | generated | The freeze; asserted by `tests/contract/test_fixture_frozen.py` |

Regenerate with `python fixtures/b/build_fixture.py`. The generator is the source of truth; the
JSON is committed so the hash can be frozen and so A and C branch from identical bytes.

## The aircraft

A 2.00 m span electric fixed-wing with a V-tail, a 0.44 m² wing, a carbon spar, and a 4S 5000 mAh
pack in a movable bay. All-up mass 1.892 kg against a 2.0 kg limit. Canonical FRD throughout:
X forward, Y right, Z down, nose datum at the fuselage forward face — so every station aft of the
nose has a negative `x`, and the aft-positive station is `s = −x`.

## The scenario is deliberate

Two things are configured, not discovered, and both are stated wherever they surface:

1. **The wiring harness has no mass.** That single unknown makes mass, CG, static margin, stall,
   energy, and current all unknown — which is the point. The first thing the recommender does is
   ask for the value rather than promise an endurance figure.
2. **The battery sits at the aft end of its corridor.** Supply the harness mass and the CG lands at
   station 0.390 m against a 0.344–0.382 m envelope, with a 4.5% static margin against an 8–25%
   band. One cause, two failing checks, one bounded fix.

`docs/decisions/0002-synthetic-fixture-scenario.md` records the numbers, why the envelope and the
margin band are consistent with each other, and why the corridor stops where it does.

## What it deliberately does not establish

- No airfoil match. The section is a declared assumption, not a UIUC lookup.
- No neutral point from a stability method. The one present is an assumption, permitted for a
  documented synthetic fixture by section 8 and marked `assumed` in the claim itself.
- No solid model. Clearance is a bounding-box screen at 0.5 mm penetration; Team A's kernel-level
  check supersedes it.
- No supplier reality. `all_synthetic` is true and the offer model refuses to hold a supplier name
  while it is.
