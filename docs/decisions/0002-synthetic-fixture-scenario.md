# 0002 — The synthetic fixture, and why its numbers are what they are

Status: accepted · Owner: Team B · Date: 2026-09-19

`fixtures/b/` holds `parametric_fixedwing`, a synthetic demonstrator. Architecture section 12
authorises it explicitly: "If full Avenger reconstruction delays the first edit, use a simpler
clearly named parametric fixed-wing fixture." Team B needed it sooner than that, because the
revision store, graph, recommender, and transaction machine all need a design to operate on and
Team A's importer does not exist.

**It is not the Titan Avenger.** It is not derived from the supplied archive, it makes no claim
about any real aircraft, and no catalog offer in it names a real supplier. The manifest says so,
and `tests/contract/test_fixture_frozen.py` asserts that it keeps saying so.

## The scenario is configured, not discovered

Section 14 wants a failing constraint to demonstrate against, and is emphatic that the demo must
"call it a synthetic scenario on reconstructed geometry, not a discovered defect". Two things are
therefore deliberate:

1. **The wiring harness has no mass.** One occurrence with no mass evidence is enough to make
   all-up mass, centre of gravity, static margin, stall, energy, and current all *unknown* —
   section 8's "missing important masses makes CG and weight-dependent checks unknown", taken at
   face value. This is what the first recommendation answers: supply the value, with provenance,
   before any endurance number is promised.

2. **The battery sits at the aft end of its corridor.** Once the harness mass is supplied, the
   centre of gravity lands at station 0.390 m against a 0.344–0.382 m envelope, and static margin
   at 4.5% against an 8–25% band. Both failures have one cause, which is what makes the fix
   intelligible.

## Why the numbers are consistent with each other

An earlier draft had a CG envelope and a static-margin band that contradicted one another: a CG at
the forward envelope limit implied a 54% static margin, well outside its own band. Both are now
derived from the same two quantities:

    s_CG ∈ [s_NP − SM_max · MAC, s_NP − SM_min · MAC]

with `s_NP = 0.40 m` and `MAC = 0.2224 m`, giving `(0.3444, 0.3822)` for a `(0.08, 0.25)` margin
band. Change one and `Mission`'s validator will reject the pair.

**The neutral point is an assumption, and is recorded as one.** Section 8 permits a documented
synthetic fixture to supply a neutral-point assumption "for illustrating the workflow" provided the
report identifies it as assumed. `GeometryFeatures.neutral_point_station_m` refuses any source kind
other than `assumed` or `computed`, and the static-margin check repeats the caveat in its reason
text. A wing quarter-chord guess would not be valid for a V-tail aircraft and is not used.

## The travel corridor is a real corridor

The battery corridor is `(-0.53, -0.42)` m with mount positions at −0.515, −0.47, −0.44, and −0.42.
Its forward limit is set by the spar web, not by the fuselage: a pack pushed past −0.42 m would
foul the spar, and the CAD port's interference screen catches exactly that. An earlier draft had a
corridor that ran through the payload bay and the spar, so the only proposal the recommender could
generate failed its own geometry check. Every mount position is now collision-free, which
`test_full_loop` exercises end to end.

## Intended contacts are declared, because bounding boxes cannot tell

Section 6: "Collision checks distinguish intended mating engagement from unintended interference.
Declare allowed contact/overlap pairs." A wing root passes through the fuselage and sits over the
spar, its mounts, the battery bay, and the harness run. An axis-aligned box test sees nine
interpenetrations there and cannot tell any of them from a real clash, so those pairs are declared
on the occurrences. The clearance check additionally requires 0.5 mm of genuine penetration, so
bodies that merely touch at a face are not flagged.

## The fuselage centre of mass is not its bounding-box centre

The fuselage is a printed equipment pod plus a light tail boom. Its `local_com_m` sits 0.20 m
forward of its placement datum, under a stated assumption. Section 5 is explicit that a placement
datum is not a centre of mass; this is the fixture demonstrating that rather than asserting it.

## Verified end state

| Battery x | CG station | Envelope | Static margin | Band | Interference |
|---|---|---|---|---|---|
| −0.515 (baseline) | 0.3900 | **out** | 4.5% | **fail** | none |
| −0.47 | 0.3770 | in | 10.3% | ok | none |
| −0.44 | 0.3684 | in | 14.2% | ok | none |
| −0.42 | 0.3626 | in | 16.8% | ok | none |

The recommender proposes the smallest move that works (−0.47, 45 mm forward). The spar upgrade is
also generated, is feasible, and costs 18.5 g, 0.06 min of endurance, and 0.06 km of range for a
2.37× section-modulus gain — which is the tradeoff section 14 wants a reviewer to decline.
