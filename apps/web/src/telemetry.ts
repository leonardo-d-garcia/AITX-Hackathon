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
