/* DroneBench — Act 5: bench-test flight replay.
 *
 * Loaded as an ES module. Needs an importmap on the host page:
 *   "three":          https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js
 *   "three/addons/":  https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/
 *
 * Public API (set on window):
 *   DroneBenchFlight.mount(container, data, opts)
 *     -> { play, pause, seek(t), setSpeed(x), on(event, cb), dispose }
 *   DroneBenchFlight.makeMockData()   // shape-compatible fallback for harness pages
 *
 * Events: "tick" {t, baseline, improved}, "complete" {summary}
 *
 * HONESTY: this replays a MODELLED mission. Nothing here is a flight test.
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

let GLTFLoader = null;
try {
  ({ GLTFLoader } = await import('three/addons/loaders/GLTFLoader.js'));
} catch (e) {
  console.warn('[flight] GLTFLoader unavailable, primitives only:', e.message);
}

/* ---------------------------------------------------------------- frames --
 * Telemetry is FRD-ish: x forward (north), y right (east), z DOWN, metres.
 * three.js is Y-up right-handed.  Mapping (determinant +1, handedness kept):
 *
 *     three.x =  frd.x     (forward stays forward / +X)
 *     three.y = -frd.z     (down becomes up)
 *     three.z =  frd.y     (right becomes +Z)
 *
 * Bank convention: roll > 0 == RIGHT WING DOWN, applied as a rotation about
 * the aircraft's own forward axis. Heading/pitch come from the path tangent
 * (more stable than integrating the logged angles) — logged heading is only
 * used as a tie-breaker when the aircraft is momentarily stationary.
 */
const FRD = (p) => new THREE.Vector3(p[0], -p[2], p[1]);

const ACCENT = 0x63b3ff;   // improved
const GHOST = 0x9aa4b2;   // baseline

/* ------------------------------------------------------------------ data -- */

function makeMockData() {
  const dt = 0.1, T = 60;
  const run = (kind) => {
    const s = [];
    const cruise = kind === 'improved' ? 19.2 : 18.0;
    const pw = kind === 'improved' ? 186 : 218;
    const wh0 = 222;
    let wh = wh0;
    for (let i = 0; i * dt <= T; i++) {
      const t = i * dt;
      // prescribed mission: climb-out, racetrack circuit, descent
      const ph = Math.min(1, t / 8);
      const alt = 4 + 46 * ph - (t > 52 ? (t - 52) * 4 : 0);
      const u = t / T;
      const ang = u * Math.PI * 4;
      const R = 120, Rz = 55;
      const x = R * Math.sin(ang);
      const y = Rz * Math.sin(2 * ang);
      const spd = cruise + 1.4 * Math.sin(ang * 2);
      const bank = 0.55 * Math.cos(ang) * (kind === 'improved' ? 0.92 : 1);
      const power = pw + 34 * Math.abs(Math.sin(ang)) + (t < 8 ? 120 * (1 - ph) : 0);
      wh = Math.max(0, wh - power * dt / 3600);
      s.push({
        t: +t.toFixed(2),
        position: [x, y, -Math.max(2, alt)],   // z DOWN
        heading: ang % (2 * Math.PI), pitch: t < 8 ? 0.18 : 0.0, roll: bank,
        speed: spd, power_w: power, energy_remaining_wh: wh,
      });
    }
    return s;
  };
  const m = (v, status, assumptions) => ({ value: v, status, assumptions });
  return {
    telemetry: { baseline: run('baseline'), improved: run('improved') },
    metrics: {
      baseline: {
        mass_kg: m(6.42, 'estimated', 'Mass from reconstruction volumes × assumed densities.'),
        ld: m(13.1, 'estimated', 'VSPAERO polar run on Lane C fixture geometry, NOT this airframe.'),
        power: m(218, 'estimated', 'Cruise shaft power from L/D and assumed 0.62 prop/ESC chain efficiency.'),
        endurance_min: m(61.1, 'estimated', 'Pack 222 Wh assumed at 90% usable.'),
        range_km: m(65.9, 'estimated', 'Endurance × cruise speed, still air assumed.'),
        wh_per_km: m(3.03, 'estimated', 'Derived from power and cruise speed.'),
      },
      improved: {
        mass_kg: m(6.38, 'estimated', 'Mass from reconstruction volumes × assumed densities.'),
        ld: m(14.4, 'estimated', 'VSPAERO polar run on Lane C fixture geometry, NOT this airframe.'),
        power: m(186, 'estimated', 'Cruise shaft power from L/D and assumed 0.62 prop/ESC chain efficiency.'),
        endurance_min: m(71.6, 'estimated', 'Pack 222 Wh assumed at 90% usable.'),
        range_km: m(82.5, 'estimated', 'Endurance × cruise speed, still air assumed.'),
        wh_per_km: m(2.42, 'estimated', 'Derived from power and cruise speed.'),
      },
    },
    __mock: true,
  };
}

// Tolerant readers — the real demo_data.json may nest things slightly differently.
function pickRuns(data) {
  const tel = data && (data.telemetry || data.flight || {});
  const get = (k, alts) => {
    if (Array.isArray(tel[k])) return tel[k];
    if (tel[k] && Array.isArray(tel[k].samples)) return tel[k].samples;
    for (const a of alts) {
      if (Array.isArray(tel[a])) return tel[a];
      if (tel[a] && Array.isArray(tel[a].samples)) return tel[a].samples;
    }
    const R = tel.runs;
    if (Array.isArray(R)) {
      const r = R.find((x) => [k, ...alts].includes(x.name || x.design || x.id));
      if (r) return r.samples || r.telemetry || [];
    } else if (R && typeof R === 'object') {
      for (const key of [k, ...alts]) {
        const r = R[key];
        if (Array.isArray(r)) return r;
        if (r && Array.isArray(r.samples)) return r.samples;
      }
    }
    return null;
  };
  return {
    baseline: get('baseline', ['base', 'reference', 'rev-c1e10160ce73']),
    improved: get('improved', ['revised', 'candidate', 'best']),
  };
}

function pickMetrics(data, improvedPowerW) {
  const m = (data && data.metrics) || {};
  const one = (k, alts) => {
    for (const key of [k, ...alts]) if (m[key]) return m[key];
    if (Array.isArray(m.designs)) {
      const d = m.designs.find((x) => [k, ...alts].includes(x.design || x.name || x.id));
      if (d) return d.metrics || d;
    }
    return null;
  };
  const baseline = one('baseline', ['base', 'reference']) || {};
  let improved = one('improved', ['revised', 'candidate', 'best']);
  let improvedLabel = improved && improved.label;
  if (!improved && m.suggestions && typeof m.suggestions === 'object') {
    // No explicit "improved" design in the data: pick the suggestion whose modelled
    // cruise power matches the improved telemetry run (that IS the run being flown).
    const entries = Object.entries(m.suggestions);
    let best = null, bestErr = Infinity;
    for (const [id, v] of entries) {
      const pw = v.electrical_power_W ?? v.power_w ?? v.power;
      const err = improvedPowerW != null && typeof pw === 'number'
        ? Math.abs(pw - improvedPowerW)
        : -(v.endurance_min || 0);
      if (err < bestErr) { bestErr = err; best = v; improvedLabel = v.label || id; }
    }
    improved = best || {};
  }
  return { baseline, improved: improved || {}, improvedLabel: improvedLabel || 'improved' };
}

const num = (mv) => {
  if (mv == null) return null;
  if (typeof mv === 'number') return mv;
  const v = mv.value ?? mv.val ?? mv.v;
  return typeof v === 'number' ? v : null;
};
const stat = (mv, design) => (mv && typeof mv === 'object' && (mv.status || mv.provenance))
  || (design && design.status) || 'unknown';
const notes = (mv, design) => {
  const a = (mv && typeof mv === 'object' && (mv.assumptions || mv.note || mv.assumption))
    || (design && (design.assumptions || design.note));
  if (!a) return 'No assumptions recorded.';
  return Array.isArray(a) ? a.map((x) => '\u2022 ' + x).join('\n') : String(a);
};
const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? '—' : v.toFixed(d));

const METRIC_ROWS = [
  ['mass_kg', 'Mass', 'kg', 2, ['mass', 'mass_kg']],
  ['ld', 'L/D', '', 1, ['ld', 'L_over_D', 'l_over_d', 'lift_to_drag', 'LD']],
  ['power', 'Cruise power', 'W', 0, ['electrical_power_W', 'power', 'power_w', 'cruise_power_w']],
  ['endurance_min', 'Endurance', 'min', 1, ['endurance_min', 'endurance']],
  ['range_km', 'Range', 'km', 1, ['range_km', 'range']],
  ['wh_per_km', 'Energy / km', 'Wh/km', 2, ['wh_per_km', 'whkm', 'energy_per_km']],
];
const readMetric = (obj, keys) => { for (const k of keys) if (obj && obj[k] != null) return obj[k]; return null; };

/* -------------------------------------------------------------- airframe -- */

function stylisedAirframe(colour, ghost) {
  // Fallback airframe: ~2.2 m span twin-boom V-tail, matching the Avenger's
  // measured proportions. Built from primitives so the scene NEVER fails.
  const g = new THREE.Group();
  const mat = new THREE.MeshStandardMaterial({
    color: colour, metalness: 0.15, roughness: 0.55,
    transparent: ghost, opacity: ghost ? 0.42 : 1,
  });
  const fuse = new THREE.Mesh(new THREE.CapsuleGeometry(0.075, 0.72, 4, 12), mat);
  fuse.rotation.z = Math.PI / 2; g.add(fuse);
  const nose = new THREE.Mesh(new THREE.ConeGeometry(0.075, 0.22, 12), mat);
  nose.rotation.z = -Math.PI / 2; nose.position.x = 0.54; g.add(nose);
  const wing = new THREE.Mesh(new THREE.BoxGeometry(0.17, 0.022, 2.2245), mat);
  wing.position.set(0.02, 0.055, 0); g.add(wing);
  for (const s of [-1, 1]) {
    const boom = new THREE.Mesh(new THREE.CylinderGeometry(0.022, 0.022, 0.78, 8), mat);
    boom.rotation.z = Math.PI / 2; boom.position.set(-0.3, 0.05, s * 0.34); g.add(boom);
    const vt = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.34, 0.016), mat);
    vt.position.set(-0.64, 0.19, s * 0.42);
    vt.rotation.x = s * (30.2 * Math.PI / 180);   // measured V-tail cant
    g.add(vt);
  }
  return g;
}

async function loadAirframe(colour, ghost, candidates = []) {
  if (GLTFLoader) {
    const loader = new GLTFLoader();
    for (const url of candidates) {
      try {
        const gltf = await loader.loadAsync(url);
        const root = gltf.scene;
        const box = new THREE.Box3().setFromObject(root);
        const size = box.getSize(new THREE.Vector3());
        const span = Math.max(size.x, size.y, size.z) || 1;
        root.scale.setScalar(2.4 / span);          // normalise to ~2.4 m span
        box.setFromObject(root);
        root.position.sub(box.getCenter(new THREE.Vector3()));
        root.traverse((o) => {
          if (!o.isMesh) return;
          o.material = new THREE.MeshStandardMaterial({
            color: colour, metalness: 0.15, roughness: 0.55,
            transparent: ghost, opacity: ghost ? 0.42 : 1,
          });
          o.castShadow = !ghost;
        });
        const wrap = new THREE.Group(); wrap.add(root);
        return wrap;
      } catch (_) { /* try next */ }
    }
  }
  return stylisedAirframe(colour, ghost);
}

const GLB_IMPROVED = ['assets/recon_tip.glb', 'assets/recon_battery.glb', 'assets/reconstruction.glb'];
const GLB_BASELINE = ['assets/recon_baseline.glb', 'assets/reference.glb'];

/* ------------------------------------------------------------------- UI -- */

const CSS = `
.dbf-root{position:relative;width:100%;height:100%;overflow:hidden;background:#070a0f;
  color:#e9edf3;font:14px/1.4 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Inter,Helvetica,Arial,sans-serif}
.dbf-root canvas{display:block}
.dbf-ov{position:absolute;pointer-events:none}
.dbf-card{background:rgba(12,16,23,.82);border:1px solid #2b333f;border-radius:12px;
  backdrop-filter:blur(7px);box-shadow:0 8px 28px rgba(0,0,0,.45)}
.dbf-hud{top:16px;left:16px;padding:12px 14px;min-width:270px}
.dbf-hud h3{margin:0 0 9px;font-size:12px;letter-spacing:.14em;text-transform:uppercase;color:#93a0b1;font-weight:700}
.dbf-row{display:grid;grid-template-columns:1fr 84px 84px;gap:6px;align-items:baseline;padding:3px 0}
.dbf-row span:first-child{color:#93a0b1;font-size:12px}
.dbf-row b{font:600 17px/1 ui-monospace,SFMono-Regular,Menlo,monospace;text-align:right}
.dbf-b{color:#c3cbd6}.dbf-i{color:#63b3ff}
.dbf-head{grid-template-columns:1fr 84px 84px;font-size:11px;color:#6f7d8f;
  text-transform:uppercase;letter-spacing:.1em;border-bottom:1px solid #242c37;padding-bottom:5px;margin-bottom:5px}
.dbf-head i{font-style:normal;text-align:right}
.dbf-gap{margin-top:10px;padding:8px 10px;border-radius:9px;background:rgba(99,179,255,.13);
  border:1px solid rgba(99,179,255,.38);color:#9ccbff;font-weight:650;font-size:14px}
.dbf-charts{right:16px;top:16px;width:340px;padding:11px 12px}
.dbf-charts h4{margin:0 0 4px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:#93a0b1}
.dbf-charts canvas{width:100%;height:96px;display:block;margin-bottom:8px;border-radius:6px;background:#0b0f16}
.dbf-metrics{right:16px;bottom:74px;width:340px;padding:11px 12px;pointer-events:auto;max-height:40%;overflow:auto}
.dbf-metrics table{width:100%;border-collapse:collapse;font-size:12.5px}
.dbf-metrics th{text-align:right;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
  color:#6f7d8f;font-weight:700;padding-bottom:4px}
.dbf-metrics th:first-child{text-align:left}
.dbf-metrics td{padding:3px 0;border-top:1px solid #1d242e;text-align:right;
  font:500 13px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace}
.dbf-metrics td:first-child{text-align:left;font:inherit;font-size:12.5px;color:#c3cbd6;cursor:help}
.dbf-tag{display:inline-block;margin-left:5px;font:600 9.5px/1.5 ui-sans-serif;letter-spacing:.06em;
  text-transform:uppercase;padding:0 5px;border-radius:5px;vertical-align:1px}
.dbf-tag.estimated{background:#16264a;color:#8fb4ff}
.dbf-tag.assumed,.dbf-tag.unknown{background:#3d2a08;color:#ffc061}
.dbf-tag.measured,.dbf-tag.computed,.dbf-tag.known{background:#123528;color:#5fd2a3}
.dbf-legend{left:16px;bottom:74px;padding:9px 12px;font-size:12.5px;line-height:1.7}
.dbf-sw{display:inline-block;width:22px;height:4px;border-radius:2px;margin-right:8px;vertical-align:3px}
.dbf-note{color:#8a94a3;font-size:11px;margin-top:6px;max-width:250px;line-height:1.35}
.dbf-honest{left:50%;transform:translateX(-50%);top:16px;padding:7px 15px;border-radius:999px;
  background:rgba(61,42,8,.9);border:1px solid #7a5a1c;color:#ffc061;font-weight:700;
  font-size:12.5px;letter-spacing:.02em;white-space:nowrap}
.dbf-tc{left:16px;right:16px;bottom:16px;padding:9px 13px;display:flex;align-items:center;
  gap:12px;pointer-events:auto}
.dbf-tc button{background:#1b2230;border:1px solid #303a48;color:#e9edf3;border-radius:8px;
  padding:6px 13px;cursor:pointer;font:600 13px/1 inherit}
.dbf-tc button:hover{background:#26303f}
.dbf-tc button[aria-pressed="true"]{background:#63b3ff;border-color:#63b3ff;color:#06101d}
.dbf-tc input[type=range]{flex:1;accent-color:#63b3ff;cursor:pointer}
.dbf-clock{font:600 14px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:#c3cbd6;min-width:98px;text-align:right}
.dbf-fps{position:absolute;right:16px;bottom:78px}
.dbf-tip{position:absolute;z-index:9;max-width:290px;padding:8px 10px;border-radius:9px;
  background:#101724;border:1px solid #37414f;color:#d7dee8;font-size:12px;line-height:1.4;
  pointer-events:none;opacity:0;transition:opacity .12s;box-shadow:0 10px 30px rgba(0,0,0,.5)}
`;

/* ---------------------------------------------------------------- mount -- */

function mount(container, data, opts = {}) {
  const O = Object.assign({ showMetrics: true, autoplay: true, speed: 1, lateralOffset: 30, modelScale: 6 }, opts);
  const listeners = { tick: [], complete: [] };
  const emit = (ev, payload) => listeners[ev]?.forEach((cb) => { try { cb(payload); } catch (e) { console.error(e); } });

  if (!document.getElementById('dbf-style')) {
    const st = document.createElement('style'); st.id = 'dbf-style'; st.textContent = CSS;
    document.head.appendChild(st);
  }

  const root = document.createElement('div');
  root.className = 'dbf-root';
  container.appendChild(root);

  let runs = pickRuns(data);
  const mockedRuns = !(runs.baseline?.length && runs.improved?.length);
  if (mockedRuns) {
    console.warn('[flight] telemetry missing/short — using built-in mock profile');
    const mk = makeMockData();
    runs = { baseline: runs.baseline?.length ? runs.baseline : mk.telemetry.baseline,
             improved: runs.improved?.length ? runs.improved : mk.telemetry.improved };
  }
  const impPower = (() => {
    const r = (data?.telemetry?.runs || {}).improved;
    return r?.power_w_const ?? runs.improved?.[0]?.power_w ?? null;
  })();
  let metrics = pickMetrics(data, impPower);
  if (!Object.keys(metrics.baseline).length || !Object.keys(metrics.improved).length) {
    const mk = makeMockData();
    metrics = { ...mk.metrics, improvedLabel: 'improved (mock)' };
  }

  const S = (s) => ({
    t: s.t ?? s.time ?? 0,
    p: s.position || s.pos || [0, 0, -50],
    speed: s.speed ?? s.airspeed ?? 0,
    power: s.power_w ?? s.power ?? 0,
    wh: s.energy_remaining_wh ?? s.energy_wh ?? s.energy_remaining ?? null,
    roll: s.roll ?? 0, pitch: s.pitch ?? 0, heading: s.heading ?? 0,
  });
  const B = runs.baseline.map(S), I = runs.improved.map(S);
  const T = Math.max(B[B.length - 1].t, I[I.length - 1].t);

  const sampleAt = (arr, t) => {
    // arrays are time-sorted and ~uniform; binary search keeps this O(log n)
    let lo = 0, hi = arr.length - 1;
    if (t <= arr[0].t) return { a: arr[0], b: arr[0], f: 0 };
    if (t >= arr[hi].t) return { a: arr[hi], b: arr[hi], f: 0 };
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (arr[m].t <= t) lo = m; else hi = m; }
    const span = arr[hi].t - arr[lo].t || 1;
    return { a: arr[lo], b: arr[hi], f: (t - arr[lo].t) / span };
  };
  const lerpS = (arr, t) => {
    const { a, b, f } = sampleAt(arr, t);
    const L = (x, y) => x + (y - x) * f;
    return {
      t, speed: L(a.speed, b.speed), power: L(a.power, b.power),
      wh: a.wh == null ? null : L(a.wh, b.wh ?? a.wh), roll: L(a.roll, b.roll),
      pos: [L(a.p[0], b.p[0]), L(a.p[1], b.p[1]), L(a.p[2], b.p[2])],
    };
  };

  /* ---- three.js scene ---- */
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x070a0f);
  scene.fog = new THREE.Fog(0x070a0f, 260, 900);

  const camera = new THREE.PerspectiveCamera(48, 16 / 9, 0.5, 4000);
  camera.position.set(-165, 130, 190);   // replaced by the route fit below

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  root.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.06;
  controls.target.set(0, 30, 0);
  controls.maxPolarAngle = Math.PI * 0.495;

  scene.add(new THREE.HemisphereLight(0x8fb4ff, 0x0a0f16, 0.9));
  const sun = new THREE.DirectionalLight(0xffeedd, 1.5);
  sun.position.set(-150, 220, 120);
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  const sc = sun.shadow.camera;
  sc.left = -140; sc.right = 140; sc.top = 140; sc.bottom = -140; sc.far = 900;
  scene.add(sun, sun.target);
  const sunOff = new THREE.Vector3(-150, 220, 120);   // shadow frustum rides with the aircraft

  // ground + subtle grid
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(1600, 1600),
    new THREE.MeshStandardMaterial({ color: 0x121a24, roughness: 1, metalness: 0 }));
  ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true;
  scene.add(ground);
  const grid = new THREE.GridHelper(1200, 60, 0x47617f, 0x243140);
  grid.position.y = 0.05; grid.material.transparent = true; grid.material.opacity = 0.75;
  scene.add(grid);

  // route ribbons (improved on the true path; baseline offset laterally, LABELLED)
  const off = O.lateralOffset;
  const ribbon = (arr, colour, dz, opacity) => {
    const pts = arr.map((s) => { const v = FRD(s.p); v.z += dz; return v; });
    const curve = new THREE.CatmullRomCurve3(pts);
    const geo = new THREE.TubeGeometry(curve, Math.min(600, pts.length), 0.55, 6, false);
    const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      color: colour, transparent: true, opacity,
    }));
    scene.add(mesh);
    return mesh;
  };
  const ribI = ribbon(I, ACCENT, 0, 0.55);
  const ribB = ribbon(B, GHOST, -off, 0.3);

  // frame the whole route once, so any mission size fills the viewport
  const routeBox = new THREE.Box3().setFromPoints([...I, ...B].map((sm) => FRD(sm.p)));
  const routeC = routeBox.getCenter(new THREE.Vector3());
  const routeR = Math.max(20, routeBox.getSize(new THREE.Vector3()).length() * 0.5);
  const wholeRoute = () => {
    controls.target.copy(routeC);
    camera.position.copy(routeC).add(new THREE.Vector3(-0.75, 0.55, 0.9).normalize().multiplyScalar(routeR * 2.1));
  };
  wholeRoute();

  const gImp = new THREE.Group(), gBase = new THREE.Group();
  gBase.position.z = -off;
  scene.add(gImp, gBase);

  const markers = [];
  const addMarker = (g, colour) => {
    const m = new THREE.Mesh(new THREE.SphereGeometry(1.2, 12, 8),
      new THREE.MeshBasicMaterial({ color: colour }));
    g.add(m); markers.push(m); return m;
  };
  addMarker(gImp, ACCENT); addMarker(gBase, GHOST);

  let disposed = false;
  (async () => {
    const [ai, ab] = await Promise.all([loadAirframe(ACCENT, false, GLB_IMPROVED), loadAirframe(GHOST, true, GLB_BASELINE)]);
    if (disposed) return;
    ai.scale.multiplyScalar(O.modelScale); ab.scale.multiplyScalar(O.modelScale);  // drawn oversize so it reads on a projector (labelled in the legend)
    gImp.add(ai); gBase.add(ab);
    markers.forEach((m) => { m.visible = false; });
  })();

  /* ---- overlays ---- */
  const el = (cls, html) => { const d = document.createElement('div'); d.className = cls; if (html) d.innerHTML = html; root.appendChild(d); return d; };

  el('dbf-ov dbf-card dbf-honest', 'Modelled mission replay — not a flight test');

  const hud = el('dbf-ov dbf-card dbf-hud', `
    <h3>Mission HUD</h3>
    <div class="dbf-row dbf-head"><span>t = <b id="dbf-t" style="display:inline;font-size:12px">0.0 s</b></span><i>Baseline</i><i>Improved</i></div>
    <div class="dbf-row"><span>Speed (m/s)</span><b class="dbf-b" id="dbf-sb">—</b><b class="dbf-i" id="dbf-si">—</b></div>
    <div class="dbf-row"><span>Power (W)</span><b class="dbf-b" id="dbf-pb">—</b><b class="dbf-i" id="dbf-pi">—</b></div>
    <div class="dbf-row"><span>Energy (Wh)</span><b class="dbf-b" id="dbf-eb">—</b><b class="dbf-i" id="dbf-ei">—</b></div>
    <div class="dbf-gap" id="dbf-gap">—</div>`);
  const q = (id) => hud.querySelector('#' + id);
  const uiT = q('dbf-t'), uiSB = q('dbf-sb'), uiSI = q('dbf-si'), uiPB = q('dbf-pb'),
    uiPI = q('dbf-pi'), uiEB = q('dbf-eb'), uiEI = q('dbf-ei'), uiGap = q('dbf-gap');

  const charts = el('dbf-ov dbf-card dbf-charts', `
    <h4>Power (W) vs time</h4><canvas id="dbf-cp" width="640" height="192"></canvas>
    <h4>Energy remaining (Wh) vs time</h4><canvas id="dbf-ce" width="640" height="192"></canvas>`);

  el('dbf-ov dbf-card dbf-legend', `
    <div><span class="dbf-sw" style="background:#9aa4b2"></span>Baseline (as-ingested)</div>
    <div><span class="dbf-sw" style="background:#63b3ff"></span>Improved — ${metrics.improvedLabel || 'revised design'}</div>
    <div class="dbf-note">Same prescribed ${T.toFixed(0)} s mission. Baseline is drawn ${off} m to one side
      for legibility — both runs fly the identical route.
      Airframes drawn ${O.modelScale}\u00d7 actual size to be visible at this range.</div>`);

  const fpsEl = el('dbf-ov dbf-card dbf-fps');
  fpsEl.style.cssText += 'padding:5px 9px;font:600 11px ui-monospace,monospace;color:#6f7d8f';

  const tip = document.createElement('div'); tip.className = 'dbf-tip'; root.appendChild(tip);

  const vspNote = data?.metrics?.vspaero_reference?.note
    ? String(data.metrics.vspaero_reference.note).replace(/</g, '&lt;') : '';
  if (O.showMetrics) {
    const rows = METRIC_ROWS.map(([, label, unit, dp, keys]) => {
      const mb = readMetric(metrics.baseline, keys), mi = readMetric(metrics.improved, keys);
      const s = stat(mi ?? mb, metrics.improved);
      const extra = (metrics.improved && metrics.improved.note) ? '\n\u2022 ' + metrics.improved.note : '';
      const why = notes(mi ?? mb, metrics.improved) + extra;
      return `<tr data-tip="${String(why).replace(/"/g, '&quot;').replace(/\n/g, '&#10;')}">
        <td>${label}${unit ? ` <span style="color:#6f7d8f">${unit}</span>` : ''}<span class="dbf-tag ${s}">${s}</span></td>
        <td class="dbf-b">${fmt(num(mb), dp)}</td><td class="dbf-i">${fmt(num(mi), dp)}</td></tr>`;
    }).join('');
    const panel = el('dbf-ov dbf-card dbf-metrics', `
      <table><thead><tr><th>Modelled metric — hover for assumptions</th><th>Baseline</th><th>Improved</th></tr></thead>
      <tbody>${rows}</tbody></table>
      <div class="dbf-note">Every figure is <b>estimated</b>, not measured. The VSPAERO polar behind
        L/D and power was run on <b>Lane C's fixture geometry, not this airframe</b>.
        ${vspNote ? `<br>${vspNote}` : ''}</div>`);
    panel.addEventListener('mousemove', (e) => {
      const tr = e.target.closest('tr[data-tip]');
      if (!tr) { tip.style.opacity = 0; return; }
      tip.style.whiteSpace = 'pre-line'; tip.textContent = tr.dataset.tip;
      const r = root.getBoundingClientRect();
      tip.style.left = Math.max(8, e.clientX - r.left - 300) + 'px';
      tip.style.top = (e.clientY - r.top - 12) + 'px';
      tip.style.opacity = 1;
    });
    panel.addEventListener('mouseleave', () => { tip.style.opacity = 0; });
  }

  const tc = el('dbf-ov dbf-card dbf-tc', `
    <button id="dbf-pp">Pause</button>
    <button id="dbf-fl">Follow</button>
    <input id="dbf-sk" type="range" min="0" max="${T}" step="0.05" value="0">
    <span class="dbf-clock" id="dbf-ck">0.0 / ${T.toFixed(0)} s</span>
    <button class="dbf-sp" data-x="0.5">0.5×</button>
    <button class="dbf-sp" data-x="1">1×</button>
    <button class="dbf-sp" data-x="2">2×</button>`);
  const btnPP = tc.querySelector('#dbf-pp'), btnFL = tc.querySelector('#dbf-fl'), slider = tc.querySelector('#dbf-sk'),
    clock = tc.querySelector('#dbf-ck');

  /* ---- charts (static overlay drawn once + a moving playhead) ---- */
  const drawChart = (canvas, pick, lo, hi) => {
    const c = canvas.getContext('2d'), W = canvas.width, H = canvas.height, pad = 6;
    c.clearRect(0, 0, W, H);
    c.strokeStyle = '#1d2531'; c.lineWidth = 1;
    for (let i = 1; i < 4; i++) { const y = (H / 4) * i; c.beginPath(); c.moveTo(0, y); c.lineTo(W, y); c.stroke(); }
    const line = (arr, colour, w) => {
      c.beginPath(); c.strokeStyle = colour; c.lineWidth = w;
      arr.forEach((s, i) => {
        const v = pick(s); if (v == null) return;
        const x = (s.t / T) * W;
        const y = H - pad - ((v - lo) / (hi - lo || 1)) * (H - pad * 2);
        i ? c.lineTo(x, y) : c.moveTo(x, y);
      });
      c.stroke();
    };
    line(B, '#9aa4b2', 2); line(I, '#63b3ff', 2.6);
    c.fillStyle = '#6f7d8f'; c.font = '600 15px ui-monospace, monospace';
    c.fillText(hi.toFixed(0), 5, 17); c.fillText(lo.toFixed(0), 5, H - 6);
  };
  const vals = (arr, f) => arr.map(f).filter((v) => v != null && !Number.isNaN(v));
  const pAll = [...vals(B, (s) => s.power), ...vals(I, (s) => s.power)];
  const eAll = [...vals(B, (s) => s.wh), ...vals(I, (s) => s.wh)];
  const padR = (a, f = 0.12) => { const lo = Math.min(...a), hi = Math.max(...a), r = (hi - lo) || 1; return [lo - r * f, hi + r * f]; };
  const [pLo, pHi] = padR(pAll);
  const [eLo, eHi] = eAll.length ? padR(eAll) : [0, 1];
  const cP = charts.querySelector('#dbf-cp'), cE = charts.querySelector('#dbf-ce');
  const bufP = document.createElement('canvas'), bufE = document.createElement('canvas');
  bufP.width = bufE.width = 640; bufP.height = bufE.height = 192;
  drawChart(bufP, (s) => s.power, pLo, pHi);
  drawChart(bufE, (s) => s.wh, eLo, eHi);
  const blitPlayhead = (canvas, buf, t) => {
    const c = canvas.getContext('2d');
    c.clearRect(0, 0, canvas.width, canvas.height);
    c.drawImage(buf, 0, 0);
    const x = (t / T) * canvas.width;
    c.strokeStyle = '#ffc061'; c.lineWidth = 1.5;
    c.beginPath(); c.moveTo(x, 0); c.lineTo(x, canvas.height); c.stroke();
  };

  /* ---- summary / deltas ---- */
  const mval = (side, keys) => num(readMetric(metrics[side], keys));
  const endB = mval('baseline', ['endurance_min', 'endurance']),
    endI = mval('improved', ['endurance_min', 'endurance']),
    rngB = mval('baseline', ['range_km', 'range']), rngI = mval('improved', ['range_km', 'range']),
    wkB = mval('baseline', ['wh_per_km', 'whkm', 'energy_per_km']),
    wkI = mval('improved', ['wh_per_km', 'whkm', 'energy_per_km']);
  const d = (a, b) => (a == null || b == null ? null : a - b);
  const summary = {
    baseline: { endurance_min: endB, range_km: rngB, wh_per_km: wkB, metrics: metrics.baseline },
    improved: { endurance_min: endI, range_km: rngI, wh_per_km: wkI, metrics: metrics.improved },
    deltas: { endurance_min: d(endI, endB), range_km: d(rngI, rngB), wh_per_km: d(wkI, wkB) },
    provenance: 'modelled mission replay — all values estimated, not flight-tested',
  };
  const gapText = summary.deltas.endurance_min == null
    ? 'endurance delta: unknown'
    : `improved: ${summary.deltas.endurance_min >= 0 ? '+' : ''}${summary.deltas.endurance_min.toFixed(1)} min endurance`;

  /* ---- animation loop ---- */
  let t = 0, playing = false, speed = O.speed, last = performance.now(), completed = false;
  let fps = 60, fpsAcc = 0, fpsN = 0, fpsT = 0;
  const upV = new THREE.Vector3(), fwd = new THREE.Vector3(), tmpA = new THREE.Vector3(),
    tmpB = new THREE.Vector3(), mtx = new THREE.Matrix4(), side = new THREE.Vector3();

  const poseAt = (arr, group, tt) => {
    const s = lerpS(arr, tt);
    const p = FRD(s.pos);
    group.position.set(p.x, p.y, p.z + group.userData.dz);
    // heading + pitch from the path tangent (sampled slightly ahead)
    const ahead = lerpS(arr, Math.min(T, tt + 0.25));
    fwd.copy(FRD(ahead.pos)).sub(p);
    if (fwd.lengthSq() < 1e-6) fwd.set(1, 0, 0);
    fwd.normalize();
    // bank: roll > 0 == right wing down, about the forward axis
    upV.set(0, 1, 0).applyAxisAngle(fwd, -s.roll);
    side.crossVectors(upV, fwd).normalize();
    upV.crossVectors(fwd, side).normalize();
    // model's local +X is nose, +Y is up, +Z is right wing
    mtx.makeBasis(fwd, upV, side.negate());
    group.quaternion.setFromRotationMatrix(mtx);
    return s;
  };
  gImp.userData.dz = 0; gBase.userData.dz = -off;

  let follow = O.follow !== false;
  const camOff = new THREE.Vector3();
  const applyFrame = (tt) => {
    const si = poseAt(I, gImp, tt), sb = poseAt(B, gBase, tt);
    sun.target.position.copy(gImp.position);
    sun.position.copy(gImp.position).add(sunOff);
    if (follow) {
      // keep whatever orbit the user has dragged to: move the target, carry the camera with it
      camOff.copy(camera.position).sub(controls.target);
      // snap on a scrub/jump, ease during playback
      const far = controls.target.distanceTo(gImp.position) > 120;
      controls.target.lerp(gImp.position, far ? 1 : 0.14);
      camera.position.copy(controls.target).add(camOff);
    }
    uiT.textContent = tt.toFixed(1) + ' s';
    uiSB.textContent = fmt(sb.speed, 1); uiSI.textContent = fmt(si.speed, 1);
    uiPB.textContent = fmt(sb.power, 0); uiPI.textContent = fmt(si.power, 0);
    uiEB.textContent = fmt(sb.wh, 1); uiEI.textContent = fmt(si.wh, 1);
    uiGap.textContent = gapText;
    clock.textContent = `${tt.toFixed(1)} / ${T.toFixed(0)} s`;
    if (document.activeElement !== slider) slider.value = String(tt);
    blitPlayhead(cP, bufP, tt); blitPlayhead(cE, bufE, tt);
    emit('tick', { t: tt, baseline: sb, improved: si });
  };

  const resize = () => {
    const w = root.clientWidth || 1280, h = root.clientHeight || 720;
    renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize); ro.observe(root); resize();

  let raf = 0;
  const loop = (now) => {
    raf = requestAnimationFrame(loop);
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    fpsAcc += dt; fpsN++;
    if (fpsAcc - fpsT > 0.5) { fps = fpsN / (fpsAcc - fpsT); fpsN = 0; fpsT = fpsAcc; fpsEl.textContent = fps.toFixed(0) + ' fps'; }
    if (playing) {
      t += dt * speed;
      if (t >= T) {
        t = T; playing = false; btnPP.textContent = 'Replay';
        if (!completed) { completed = true; applyFrame(t); emit('complete', { summary }); }
      }
      applyFrame(t);
    }
    controls.update();
    renderer.render(scene, camera);
  };
  applyFrame(0);
  raf = requestAnimationFrame(loop);

  /* ---- transport wiring ---- */
  const api = {
    play() { if (t >= T) { t = 0; completed = false; } playing = true; btnPP.textContent = 'Pause'; last = performance.now(); return api; },
    pause() { playing = false; btnPP.textContent = 'Play'; return api; },
    seek(v) { t = Math.max(0, Math.min(T, Number(v) || 0)); if (t < T) completed = false; applyFrame(t); return api; },
    setSpeed(x) {
      speed = Number(x) || 1;
      tc.querySelectorAll('.dbf-sp').forEach((b) => b.setAttribute('aria-pressed', String(Number(b.dataset.x) === speed)));
      return api;
    },
    on(ev, cb) { (listeners[ev] ||= []).push(cb); return api; },
    get duration() { return T; },
    get summary() { return summary; },
    dispose() {
      disposed = true;
      cancelAnimationFrame(raf); ro.disconnect(); controls.dispose();
      scene.traverse((o) => { o.geometry?.dispose?.(); if (o.material) [].concat(o.material).forEach((m) => m.dispose()); });
      renderer.dispose();
      root.remove();
    },
  };
  const setFollow = (v) => {
    follow = v;
    btnFL.setAttribute('aria-pressed', String(v));
    btnFL.textContent = v ? 'Follow' : 'Whole route';
    if (!v) wholeRoute();
    else { // snap in behind the aircraft at a readable stand-off
      const d = new THREE.Vector3(-0.8, 0.42, 0.75).normalize().multiplyScalar(110);
      controls.target.copy(gImp.position);
      camera.position.copy(gImp.position).add(d);
    }
  };
  btnFL.onclick = () => setFollow(!follow);
  setFollow(follow);
  btnPP.onclick = () => (playing ? api.pause() : api.play());
  slider.oninput = (e) => api.seek(e.target.value);
  tc.querySelectorAll('.dbf-sp').forEach((b) => { b.onclick = () => api.setSpeed(Number(b.dataset.x)); });
  api.setSpeed(speed);
  if (O.autoplay) api.play(); else api.pause();
  return api;
}

window.DroneBenchFlight = { mount, makeMockData, FRD_NOTE: 'three.x=frd.x, three.y=-frd.z, three.z=frd.y' };
export { mount, makeMockData };
