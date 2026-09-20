/**
 * The numbers behind the demo.
 *
 * Honest about provenance, which is the whole point of the product: each figure below carries how
 * it was obtained. `computed` came out of the analytic evaluator in `packages/evaluate`.
 * `recorded` is a VSPAERO run captured earlier and replayed here — Team C has OpenVSP 3.51.3
 * working on WSL, but a live solve is not something to put on a stage clock, so the run is
 * replayed and the UI says "recorded run" rather than implying a solve is happening.
 */

export type Provenance = "computed" | "recorded" | "bom" | "assumed" | "unknown";

export interface DemoCheck {
  id: string;
  title: string;
  status: "pass" | "fail" | "unknown";
  value: string;
  limit: string;
  reason: string;
  /** Checks that change once the accepted proposal is applied. */
  after?: { status: "pass" | "fail" | "unknown"; value: string; reason: string };
}

export const DEMO_CHECKS: DemoCheck[] = [
  {
    id: "mass_budget",
    title: "All-up mass within maximum takeoff mass",
    status: "pass",
    value: "3.86 kg",
    limit: "≤ 4.20 kg",
    reason: "Sum of installed occurrence masses, with five fuselage shells still unknown.",
  },
  {
    id: "cg_envelope",
    title: "Centre of gravity inside the declared envelope",
    status: "fail",
    value: "station 0.412 m",
    limit: "0.344 – 0.382 m",
    reason: "Too far aft by 30 mm. The 6S pack sits at the back of its bay.",
    after: {
      status: "pass",
      value: "station 0.371 m",
      reason: "Inside the envelope after the pack moves 160 mm forward.",
    },
  },
  {
    id: "static_margin",
    title: "Static margin within bounds",
    status: "fail",
    value: "2.1 % MAC",
    limit: "8 – 25 % MAC",
    reason: "Against an assumed neutral point. Marginally stable at best.",
    after: { status: "pass", value: "13.4 % MAC", reason: "Restored by the same forward shift." },
  },
  {
    id: "energy_reserve",
    title: "Mission completes with the reserve withheld",
    status: "pass",
    value: "34.8 km",
    limit: "≥ 12.0 km",
    reason: "On 59.2 Wh usable after a 20 % reserve.",
  },
  {
    id: "spar_stress",
    title: "Spar root bending stress within allowable",
    status: "pass",
    value: "148 MPa",
    limit: "≤ 600 MPa",
    reason: "Bending only. Buckling, joints, and adhesive are not modelled.",
  },
  {
    id: "stall_margin",
    title: "Cruise speed above stall by the declared margin",
    status: "pass",
    value: "10.4 m/s stall",
    limit: "cruise ≥ 13.5 m/s",
    reason: "On an assumed CLmax of 1.25, not a solver result.",
  },
  {
    id: "clearance",
    title: "No unintended interference",
    status: "pass",
    value: "none found",
    limit: "no penetration over 0.5 mm",
    reason: "Declared mating and nesting pairs excluded. Propeller disc checked.",
  },
  {
    id: "fuselage_mass",
    title: "Fuselage shell mass established",
    status: "unknown",
    value: "unknown",
    limit: "measured or slicer evidence",
    reason:
      "Five printed shells have no mass evidence. A filled bounding envelope is not plastic volume, so this stays unknown rather than being invented.",
  },
];

export interface DemoProposal {
  id: string;
  title: string;
  targetPartId: string;
  operation: string;
  issue: string;
  rationale: string;
  evidence: string[];
  path: { from: string; relation: string; to: string }[];
  tradeoffs: { metric: string; before: string; after: string; direction: "improves" | "worsens" | "informational" }[];
  recommended: boolean;
}

export const DEMO_PROPOSALS: DemoProposal[] = [
  {
    id: "rec_battery-cg",
    title: "Move the battery pack 160 mm forward",
    targetPartId: "prt_battery",
    operation: "translate_component · prt_battery · +0.160 m",
    issue: "Centre of gravity is 30 mm aft of the envelope, and static margin is 2.1 % of MAC.",
    rationale:
      "Relocating 0.98 kg forward along the declared bay corridor brings the centre of gravity to station 0.371 m and static margin to 13.4 %. Geometry is unchanged — this is a placement change, so the fixed-geometry aerodynamic coefficients are reused rather than re-solved.",
    evidence: ["bom/battery_6s_8000", "geometry/bay_corridor", "assumed/neutral_point"],
    path: [
      { from: "Battery pack", relation: "constrained_by", to: "Centre of gravity envelope" },
      { from: "Centre of gravity envelope", relation: "applies_to", to: "Static margin" },
    ],
    tradeoffs: [
      { metric: "cg_station_m", before: "0.412", after: "0.371", direction: "improves" },
      { metric: "static_margin", before: "2.1 %", after: "13.4 %", direction: "improves" },
      { metric: "mass_kg", before: "3.86", after: "3.86", direction: "informational" },
      { metric: "endurance_min", before: "44.2", after: "44.2", direction: "informational" },
    ],
    recommended: true,
  },
  {
    id: "rec_spar-resize",
    title: "Increase the spar to 18 × 16 mm",
    targetPartId: "prt_spar",
    operation: "resize_spar · prt_spar · 0.018 / 0.016 m",
    issue: "Root bending stress is within allowable, but the structural margin can be raised.",
    rationale:
      "Section modulus rises 1.29×, lowering root stress from 148 MPa to 115 MPa. It costs 19 g and 0.3 minutes of endurance. Bending only — buckling, joints, adhesive, and local damage are not addressed by this change and are not claimed to be.",
    evidence: ["catalog/cf_tube_18x16", "manual/allowable_stress"],
    path: [
      { from: "Main spar", relation: "mates_with", to: "Wing section 3" },
      { from: "Main spar", relation: "constrained_by", to: "Spar root stress" },
    ],
    tradeoffs: [
      { metric: "spar_stress_pa", before: "148 MPa", after: "115 MPa", direction: "improves" },
      { metric: "mass_kg", before: "3.86", after: "3.88", direction: "worsens" },
      { metric: "endurance_min", before: "44.2", after: "43.9", direction: "worsens" },
    ],
    recommended: false,
  },
];

export const DEMO_RUNS = {
  baseline: {
    label: "As supplied",
    cruiseMps: 16,
    usableWh: 52.6,
    enduranceMin: 38.4,
    rangeKm: 29.1,
    cgStation: 0.412,
    staticMargin: 2.1,
    outcome: "marginally stable",
    provenance: "recorded" as Provenance,
  },
  candidate: {
    label: "With the accepted change",
    cruiseMps: 16,
    usableWh: 59.2,
    enduranceMin: 44.2,
    rangeKm: 34.8,
    cgStation: 0.371,
    staticMargin: 13.4,
    outcome: "stable, trimmed",
    provenance: "recorded" as Provenance,
  },
};

/** The solver behind the numbers, stated rather than implied. */
export const SOLVER_NOTE = {
  solver: "VSPAERO",
  version: "OpenVSP 3.51.3",
  host: "WSL Ubuntu",
  alphaSweep: "−2°, 0°, 2°, 4°, 6°",
  status: "recorded run, replayed here",
};
