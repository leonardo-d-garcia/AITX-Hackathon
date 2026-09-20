/**
 * The Titan Avenger archive, as actually supplied.
 *
 * 24 binary STL meshes, 580,404 triangles. This is the real customer file — no reconstruction, no
 * surrogate. Architecture section 2 is blunt about what it does and does not contain: no STEP, no
 * feature history, no BOM, no assembly manifest. So the placement below is *our* assembly
 * hypothesis laid over byte-identical source meshes, and the UI says so.
 *
 * Three decisions the archive forces, all from section 2:
 *
 * - Three `wing3` variants (12 mm hole, 16 mm hole, no hole) and three `fuse3` variants. Exactly
 *   one of each is installed; the others are excluded alternatives and must not be counted as mass.
 * - Wing and tail meshes sit predominantly on positive native X, so one side was supplied and the
 *   other is mirrored.
 * - The candidate frame mapping is `x = -(Y - Y_nose) * 0.001`, `y = -X * 0.001`, `z = -Z * 0.001`.
 */

export interface TitanPart {
  /** Stable identity for this installed occurrence. */
  partId: string;
  file: string;
  name: string;
  role: string;
  /** Mirrored copy of another occurrence: distinct identity, shared source mesh. */
  mirrorOf?: string;
  /** Extra translation in canonical metres, applied after the archive mapping. */
  offsetM?: [number, number, number];
  massKg: number | null;
  massSource: "bom" | "manual" | "computed" | "unknown";
}

/** Variants deliberately not installed. Section 2: do not count overlapping alternatives as mass. */
export const EXCLUDED_VARIANTS = [
  { file: "wing3_12mm_hole.stl", why: "wing3 variant not selected — 12 mm spar hole" },
  { file: "wing3_no_hole.stl", why: "wing3 variant not selected — no spar hole" },
  { file: "fuse3.stl", why: "fuse3 variant not selected — ordinary" },
  { file: "fuse3_belly_cam.stl", why: "fuse3 variant not selected — belly camera" },
  { file: "canopy2.stl", why: "second canopy not installed on this configuration" },
  { file: "hatch2.stl", why: "second hatch not installed on this configuration" },
  { file: "vtail2.stl", why: "mirrored from vtail1 rather than installed separately" },
];

/**
 * The installed occurrences.
 *
 * Masses marked `unknown` are genuinely unknown: the archive carries no BOM, and a printed shell's
 * mass cannot be read off its geometry. Those propagate through every weight-dependent check.
 */
export const TITAN_PARTS: TitanPart[] = [
  { partId: "prt_fuse1", file: "fuse1.stl", name: "Fuselage section 1", role: "fuselage", massKg: null, massSource: "unknown" },
  { partId: "prt_fuse2", file: "fuse2.stl", name: "Fuselage section 2", role: "fuselage", massKg: null, massSource: "unknown" },
  { partId: "prt_fuse3", file: "fuse3_clean.stl", name: "Fuselage section 3 (clean)", role: "fuselage", massKg: null, massSource: "unknown" },
  { partId: "prt_fuse4", file: "fuse4.stl", name: "Fuselage section 4", role: "fuselage", massKg: null, massSource: "unknown" },
  { partId: "prt_fuse5", file: "fuse5.stl", name: "Fuselage section 5", role: "fuselage", massKg: null, massSource: "unknown" },
  { partId: "prt_canopy", file: "canopy1.stl", name: "Canopy", role: "hatch", massKg: 0.041, massSource: "manual" },
  { partId: "prt_hatch", file: "hatch1.stl", name: "Access hatch", role: "hatch", massKg: 0.018, massSource: "manual" },

  { partId: "prt_wing1-r", file: "wing1.stl", name: "Wing section 1, right", role: "wing", massKg: 0.132, massSource: "manual" },
  { partId: "prt_wing2-r", file: "wing2.stl", name: "Wing section 2, right", role: "wing", massKg: 0.124, massSource: "manual" },
  { partId: "prt_wing3-r", file: "wing3_16mm_hole.stl", name: "Wing section 3, right (16 mm)", role: "wing", massKg: 0.089, massSource: "manual" },
  { partId: "prt_wing4-r", file: "wing4.stl", name: "Wing section 4, right", role: "wing", massKg: 0.101, massSource: "manual" },
  { partId: "prt_wing5-r", file: "wing5.stl", name: "Wing tip, right", role: "wing", massKg: 0.118, massSource: "manual" },
  { partId: "prt_aileron-r", file: "aileron.stl", name: "Aileron, right", role: "surface", massKg: 0.032, massSource: "manual" },

  { partId: "prt_wing1-l", file: "wing1.stl", name: "Wing section 1, left", role: "wing", mirrorOf: "prt_wing1-r", massKg: 0.132, massSource: "manual" },
  { partId: "prt_wing2-l", file: "wing2.stl", name: "Wing section 2, left", role: "wing", mirrorOf: "prt_wing2-r", massKg: 0.124, massSource: "manual" },
  { partId: "prt_wing3-l", file: "wing3_16mm_hole.stl", name: "Wing section 3, left (16 mm)", role: "wing", mirrorOf: "prt_wing3-r", massKg: 0.089, massSource: "manual" },
  { partId: "prt_wing4-l", file: "wing4.stl", name: "Wing section 4, left", role: "wing", mirrorOf: "prt_wing4-r", massKg: 0.101, massSource: "manual" },
  { partId: "prt_wing5-l", file: "wing5.stl", name: "Wing tip, left", role: "wing", mirrorOf: "prt_wing5-r", massKg: 0.118, massSource: "manual" },
  { partId: "prt_aileron-l", file: "aileron.stl", name: "Aileron, left", role: "surface", mirrorOf: "prt_aileron-r", massKg: 0.032, massSource: "manual" },

  { partId: "prt_vtail-r", file: "vtail1.stl", name: "V-tail panel, right", role: "tail_panel", massKg: 0.067, massSource: "manual" },
  { partId: "prt_vtail-l", file: "vtail1.stl", name: "V-tail panel, left", role: "tail_panel", mirrorOf: "prt_vtail-r", massKg: 0.067, massSource: "manual" },
  { partId: "prt_taileron", file: "taileron.stl", name: "Taileron", role: "surface", massKg: 0.029, massSource: "manual" },

  // motor_mount.stl and wing_bay_plate.stl are authored about their own local origins rather
  // than the assembly frame, so the shared archive mapping puts them far off the airframe.
  // Section 2: the archive carries no assembly manifest, and this is exactly that gap showing.
  // They are held out of the render until Team A’s importer supplies per-body placements.
];

/**
 * Bought components the archive does not contain.
 *
 * Section 2: "No motors, batteries, spars, avionics, wiring specification". They are added as
 * separately identified envelopes and labelled as a curated demo BOM, never inferred from the
 * archive name.
 */
export interface EnvelopePart {
  partId: string;
  name: string;
  role: string;
  /** Centre in canonical FRD metres. */
  centreM: [number, number, number];
  sizeM: [number, number, number];
  massKg: number | null;
  massSource: "bom" | "unknown";
  editable?: boolean;
  corridorM?: [number, number];
}

export const TITAN_ENVELOPES: EnvelopePart[] = [
  {
    partId: "prt_battery",
    name: "Battery pack, 6S 8000 mAh",
    role: "battery",
    centreM: [-0.62, 0, 0.02],
    sizeM: [0.19, 0.07, 0.05],
    massKg: 0.98,
    massSource: "bom",
    editable: true,
    corridorM: [-0.66, -0.42],
  },
  { partId: "prt_motor", name: "Motor, 3520 400 KV", role: "motor", centreM: [-0.05, 0, 0], sizeM: [0.06, 0.042, 0.042], massKg: 0.195, massSource: "bom" },
  { partId: "prt_prop", name: "Propeller, 15 x 8", role: "propeller", centreM: [-0.01, 0, 0], sizeM: [0.02, 0.381, 0.381], massKg: 0.034, massSource: "bom" },
  { partId: "prt_esc", name: "ESC, 80 A", role: "esc", centreM: [-0.26, 0, 0.03], sizeM: [0.07, 0.032, 0.014], massKg: 0.062, massSource: "bom" },
  { partId: "prt_avionics", name: "Flight controller / GPS", role: "flight_controller", centreM: [-0.36, 0, 0.032], sizeM: [0.06, 0.05, 0.022], massKg: 0.071, massSource: "bom" },
  { partId: "prt_spar", name: "Main spar, CF 16 x 14", role: "spar", centreM: [-0.52, 0, 0], sizeM: [0.016, 2.0, 0.016], massKg: 0.146, massSource: "bom" },
  { partId: "prt_payload", name: "Mission payload", role: "payload", centreM: [-0.44, 0, 0.04], sizeM: [0.1, 0.07, 0.05], massKg: 0.35, massSource: "bom" },
  { partId: "prt_harness", name: "Wiring harness", role: "harness", centreM: [-0.45, 0, -0.02], sizeM: [0.6, 0.03, 0.012], massKg: null, massSource: "unknown" },
];

/** Section 2's candidate archive mapping, in millimetres in and metres out. */
export const TITAN_Y_NOSE_MM = -403.07;
