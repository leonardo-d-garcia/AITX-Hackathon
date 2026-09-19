/**
 * Turn the contract's geometry into three.js meshes.
 *
 * Most occurrences are honest boxes: the parts document gives an axis-aligned `bounds_local_m` and
 * a placement, and a box is exactly what that describes — claiming more shape than the data
 * carries would be decoration.
 *
 * Two roles do carry real shape, and drawing them as boxes throws it away:
 *
 * - **Wings.** `geometry_features.wing_stations` gives span, leading-edge station, chord, z, and
 *   twist at each station. That is a lofted planform, so it is lofted here — taper and sweep come
 *   out of the numbers, not out of a modelling decision.
 * - **V-tail panels.** `vtail_panels` gives area, mean chord, cant, and arm. A canted panel drawn
 *   as an upright slab misrepresents the one thing that makes this airframe unusual.
 *
 * Team A's tessellated geometry replaces all of this. Until then the schematic shows what the
 * contract actually says, at the dimensions it says it.
 */

import * as THREE from "three";

import type { GeometryFeatures, WingStation } from "@/lib/contracts.gen";
import type { SchematicPart } from "./Schematic";

/** Canonical FRD -> three.js Y-up. Mirrors `dronebench_contracts.units.frd_to_threejs`. */
export function frdToThree(x: number, y: number, z: number): THREE.Vector3 {
  return new THREE.Vector3(y, -z, -x);
}

/** Thickness of a lofted surface as a fraction of its chord. A declared drawing convention. */
const THICKNESS_RATIO = 0.11;

/**
 * Loft a solid through a list of sections.
 *
 * Each section is four corners in order (LE-upper, TE-upper, TE-lower, LE-lower), already in
 * three.js space. Consecutive sections are joined by quads and the ends are capped, which gives a
 * closed solid that takes a shadow properly.
 */
function loft(sections: THREE.Vector3[][]): THREE.BufferGeometry {
  const positions: number[] = [];
  const pushTriangle = (a: THREE.Vector3, b: THREE.Vector3, c: THREE.Vector3) => {
    positions.push(a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z);
  };
  const pushQuad = (a: THREE.Vector3, b: THREE.Vector3, c: THREE.Vector3, d: THREE.Vector3) => {
    pushTriangle(a, b, c);
    pushTriangle(a, c, d);
  };

  for (let i = 0; i < sections.length - 1; i += 1) {
    const here = sections[i]!;
    const next = sections[i + 1]!;
    for (let corner = 0; corner < 4; corner += 1) {
      const nextCorner = (corner + 1) % 4;
      pushQuad(here[corner]!, next[corner]!, next[nextCorner]!, here[nextCorner]!);
    }
  }

  const first = sections[0]!;
  const last = sections[sections.length - 1]!;
  pushQuad(first[3]!, first[2]!, first[1]!, first[0]!);
  pushQuad(last[0]!, last[1]!, last[2]!, last[3]!);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

/** One wing section, in three.js space, from a station on the canonical planform. */
function wingSection(station: WingStation, side: 1 | -1): THREE.Vector3[] {
  const halfThickness = (station.chord_m * THICKNESS_RATIO) / 2;
  const leadingEdge = station.leading_edge_x_m;
  const trailingEdge = leadingEdge - station.chord_m; // aft is -x in FRD
  const y = station.span_y_m * side;
  const z = station.z_m;

  // Twist rotates the section about the leading edge, nose-down positive.
  const twist = station.twist_rad ?? 0;
  const rotate = (dx: number, dz: number): [number, number] => [
    leadingEdge + dx * Math.cos(twist) - dz * Math.sin(twist),
    z + dx * Math.sin(twist) + dz * Math.cos(twist),
  ];

  const [uxLe, uzLe] = rotate(0, -halfThickness);
  const [uxTe, uzTe] = rotate(-station.chord_m, -halfThickness);
  const [lxTe, lzTe] = rotate(-station.chord_m, halfThickness);
  const [lxLe, lzLe] = rotate(0, halfThickness);

  void trailingEdge;
  return [
    frdToThree(uxLe, y, uzLe),
    frdToThree(uxTe, y, uzTe),
    frdToThree(lxTe, y, lzTe),
    frdToThree(lxLe, y, lzLe),
  ];
}

/** A lofted wing for one side. Returns null when the features carry no stations. */
export function buildWing(features: GeometryFeatures, side: 1 | -1): THREE.BufferGeometry | null {
  const stations = [...(features.wing_stations ?? [])].sort(
    (a, b) => a.span_y_m - b.span_y_m,
  );
  if (stations.length < 2) return null;
  const sections = stations.map((station) => wingSection(station, side));
  // Root first, tip last, so the caps face outward consistently.
  return loft(side === 1 ? sections : [...sections].reverse());
}

/**
 * A canted V-tail panel.
 *
 * Span is derived from the declared area and mean chord, and the panel is swept out along the cant
 * direction. Drawing it upright would hide the geometry that makes a tail-volume heuristic
 * inapplicable to this airframe in the first place.
 */
export function buildVTailPanel(
  panel: { area_m2: number; cant_rad: number; mean_chord_m: number },
  rootFrd: [number, number, number],
  side: 1 | -1,
): THREE.BufferGeometry {
  const span = panel.area_m2 / panel.mean_chord_m;
  const chord = panel.mean_chord_m;
  const halfThickness = (chord * THICKNESS_RATIO) / 2;

  // Cant measured from vertical: 0 is a fin, pi/2 is a horizontal stabiliser.
  const outward = Math.sin(panel.cant_rad) * side;
  const upward = -Math.cos(panel.cant_rad); // -z is up in FRD

  const section = (t: number, taper: number): THREE.Vector3[] => {
    const y = rootFrd[1] + outward * span * t;
    const z = rootFrd[2] + upward * span * t;
    const c = chord * taper;
    const le = rootFrd[0];
    return [
      frdToThree(le, y, z - halfThickness),
      frdToThree(le - c, y, z - halfThickness),
      frdToThree(le - c, y, z + halfThickness),
      frdToThree(le, y, z + halfThickness),
    ];
  };

  // A modest tip taper so the panel reads as a surface rather than a plank.
  return loft([section(0, 1), section(0.6, 0.85), section(1, 0.68)]);
}

/** A box for an occurrence whose only declared shape is its bounds. */
export function buildBox(part: SchematicPart): {
  geometry: THREE.BufferGeometry;
  position: THREE.Vector3;
} {
  const size = frdToThree(part.size[0], part.size[1], part.size[2]);
  const position = frdToThree(
    part.translation[0] + part.localCentre[0],
    part.translation[1] + part.localCentre[1],
    part.translation[2] + part.localCentre[2],
  );
  return {
    geometry: new THREE.BoxGeometry(
      Math.max(Math.abs(size.x), 0.002),
      Math.max(Math.abs(size.y), 0.002),
      Math.max(Math.abs(size.z), 0.002),
    ),
    position,
  };
}

/**
 * Frame the camera so the whole assembly fits, with margin.
 *
 * Derived from the vertical and horizontal field of view rather than guessed from a scale factor:
 * a guessed factor is how a hero object ends up clipped at one aspect ratio and tiny at another.
 */
export function fitCamera(
  camera: THREE.PerspectiveCamera,
  bounds: THREE.Box3,
  margin = 1.06,
): { target: THREE.Vector3; distance: number } {
  const target = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());

  const verticalFov = (camera.fov * Math.PI) / 180;
  const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * camera.aspect);

  // The radius of a sphere around the assembly, so the fit holds from any orbit angle.
  const radius = size.length() / 2;
  const distance =
    (margin * radius) / Math.min(Math.sin(verticalFov / 2), Math.sin(horizontalFov / 2));

  return { target, distance };
}
