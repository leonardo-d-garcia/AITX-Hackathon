export type FidelityTier = "analytic" | "vspaero";

export type Frame = {
  t: number;
  pos_ned: [number, number, number];
  quat: [number, number, number, number];
  Va: number;
  alpha: number;
  beta: number;
  load_factor_n: number;
  power_w: number;
  energy_wh_remaining: number;
};

export type SimulationRun = {
  meta: {
    revision_id: string;
    geometry_hash: string;
    fidelity_tier: FidelityTier;
    solver_versions: { openvsp: string | null; vspaero: string | null };
    assumptions: string[];
    dt_s: number;
  };
  frames: Frame[];
  part_stress: Record<
    string,
    { t: number; sigma_mpa: number; station_m: number }[]
  >;
};

export function fidelityLabel(tier: FidelityTier): string {
  return tier === "vspaero"
    ? "VSPAERO analysis + mission model"
    : "Engineering estimate";
}

/** FRD/NED metres → three.js Y-up: (x,y,z)_FRD → (y, −z, −x) */
export function nedToThree(pos: [number, number, number]): [number, number, number] {
  const [n, e, d] = pos;
  return [e, -d, -n];
}

export function interpolateFrame(frames: Frame[], t: number): Frame {
  if (frames.length === 0) {
    throw new Error("no frames");
  }
  if (t <= frames[0].t) return frames[0];
  const last = frames[frames.length - 1];
  if (t >= last.t) return last;
  let lo = 0;
  let hi = frames.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t <= t) lo = mid;
    else hi = mid;
  }
  const a = frames[lo];
  const b = frames[hi];
  const u = (t - a.t) / (b.t - a.t);
  const lerp = (x: number, y: number) => x + (y - x) * u;
  const slerpQuat = (
    q0: [number, number, number, number],
    q1: [number, number, number, number],
    uu: number,
  ): [number, number, number, number] => {
    let dot = q0[0] * q1[0] + q0[1] * q1[1] + q0[2] * q1[2] + q0[3] * q1[3];
    const bq: [number, number, number, number] = [...q1];
    if (dot < 0) {
      bq[0] = -bq[0];
      bq[1] = -bq[1];
      bq[2] = -bq[2];
      bq[3] = -bq[3];
      dot = -dot;
    }
    if (dot > 0.9995) {
      const r: [number, number, number, number] = [
        lerp(q0[0], bq[0]),
        lerp(q0[1], bq[1]),
        lerp(q0[2], bq[2]),
        lerp(q0[3], bq[3]),
      ];
      const n = Math.hypot(...r) || 1;
      return [r[0] / n, r[1] / n, r[2] / n, r[3] / n];
    }
    const theta = Math.acos(Math.min(1, dot));
    const s = Math.sin(theta);
    const w0 = Math.sin((1 - uu) * theta) / s;
    const w1 = Math.sin(uu * theta) / s;
    return [
      q0[0] * w0 + bq[0] * w1,
      q0[1] * w0 + bq[1] * w1,
      q0[2] * w0 + bq[2] * w1,
      q0[3] * w0 + bq[3] * w1,
    ];
  };
  return {
    t,
    pos_ned: [
      lerp(a.pos_ned[0], b.pos_ned[0]),
      lerp(a.pos_ned[1], b.pos_ned[1]),
      lerp(a.pos_ned[2], b.pos_ned[2]),
    ],
    quat: slerpQuat(a.quat, b.quat, u),
    Va: lerp(a.Va, b.Va),
    alpha: lerp(a.alpha, b.alpha),
    beta: lerp(a.beta, b.beta),
    load_factor_n: lerp(a.load_factor_n, b.load_factor_n),
    power_w: lerp(a.power_w, b.power_w),
    energy_wh_remaining: lerp(a.energy_wh_remaining, b.energy_wh_remaining),
  };
}

type Vec3 = [number, number, number];
type Quat = [number, number, number, number];
type Mat3 = [Vec3, Vec3, Vec3];

/** Body-to-NED quat → body-to-three.js quat (scalar-first).
 *  three.js is Y-up right-handed with X=east, Z=-north. Identity FRD
 *  therefore has body forward along −Z, right along +X, down along −Y.
 *  Compose M * R(q) where M maps NED (n,e,d) → (e, −d, −n).
 */
export function quatFrdNedToThree(
  q: [number, number, number, number],
): [number, number, number, number] {
  const rBn = rotFromQuat(q);
  const m: Mat3 = [
    [0, 1, 0],
    [0, 0, -1],
    [-1, 0, 0],
  ];
  return quatFromRot(mmul(m, rBn));
}

/** Rotate a body FRD point into three.js world axes (translation not applied). */
export function rotateBodyPointThree(
  q: [number, number, number, number],
  bodyFrd: [number, number, number],
): [number, number, number] {
  return qv(quatFrdNedToThree(q), bodyFrd);
}

function rotFromQuat(quat: Quat): Mat3 {
  const [w, x, y, z] = quat;
  const xx = x * x;
  const yy = y * y;
  const zz = z * z;
  const xy = x * y;
  const xz = x * z;
  const yz = y * z;
  const wx = w * x;
  const wy = w * y;
  const wz = w * z;
  return [
    [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
    [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
    [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
  ];
}

function mmul(a: Mat3, b: Mat3): Mat3 {
  const row = (i: 0 | 1 | 2): Vec3 => [
    a[i][0] * b[0][0] + a[i][1] * b[1][0] + a[i][2] * b[2][0],
    a[i][0] * b[0][1] + a[i][1] * b[1][1] + a[i][2] * b[2][1],
    a[i][0] * b[0][2] + a[i][1] * b[1][2] + a[i][2] * b[2][2],
  ];
  return [row(0), row(1), row(2)];
}

function mv(r: Mat3, v: Vec3): Vec3 {
  return [
    r[0][0] * v[0] + r[0][1] * v[1] + r[0][2] * v[2],
    r[1][0] * v[0] + r[1][1] * v[1] + r[1][2] * v[2],
    r[2][0] * v[0] + r[2][1] * v[1] + r[2][2] * v[2],
  ];
}

function qv(q: Quat, v: Vec3): Vec3 {
  return mv(rotFromQuat(q), v);
}

function quatFromRot(r: Mat3): Quat {
  const [m00, m01, m02] = r[0];
  const [m10, m11, m12] = r[1];
  const [m20, m21, m22] = r[2];
  const trace = m00 + m11 + m22;
  let w: number;
  let x: number;
  let y: number;
  let z: number;
  if (trace > 0) {
    const s = 0.5 / Math.sqrt(trace + 1);
    w = 0.25 / s;
    x = (m21 - m12) * s;
    y = (m02 - m20) * s;
    z = (m10 - m01) * s;
  } else if (m00 > m11 && m00 > m22) {
    const s = 2 * Math.sqrt(Math.max(1e-15, 1 + m00 - m11 - m22));
    w = (m21 - m12) / s;
    x = 0.25 * s;
    y = (m01 + m10) / s;
    z = (m02 + m20) / s;
  } else if (m11 > m22) {
    const s = 2 * Math.sqrt(Math.max(1e-15, 1 + m11 - m00 - m22));
    w = (m02 - m20) / s;
    x = (m01 + m10) / s;
    y = 0.25 * s;
    z = (m12 + m21) / s;
  } else {
    const s = 2 * Math.sqrt(Math.max(1e-15, 1 + m22 - m00 - m11));
    w = (m10 - m01) / s;
    x = (m02 + m20) / s;
    y = (m12 + m21) / s;
    z = 0.25 * s;
  }
  const n = Math.sqrt(w * w + x * x + y * y + z * z) || 1;
  return [w / n, x / n, y / n, z / n];
}
