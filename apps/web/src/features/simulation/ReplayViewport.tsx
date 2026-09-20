import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { Grid, OrbitControls, useGLTF } from "@react-three/drei";
import {
  Component,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  Color,
  Group,
  Matrix4,
  Mesh,
  Object3D,
  Quaternion,
  type MeshStandardMaterial,
} from "three";
import { nedToThree, type Frame } from "../../telemetry";

/** Vite public dir is apps/web/public/ (serves /titan_avenger.glb). Archive mesh: fixtures/c/titan_avenger_cad/meshes/titan_avenger.glb */
const DEFAULT_MODEL_URL = "/titan_avenger.glb";

/** NED → three.js: (n,e,d) → (e, −d, −n). Same M as sim.frames.quat_frd_ned_to_three. */
const NED_TO_THREE = new Matrix4().set(
  0, 1, 0, 0,
  0, 0, -1, 0,
  -1, 0, 0, 0,
  0, 0, 0, 1,
);

/** Print-archive GLB is glTF Y-up (fwd −Z). Mᵀ maps that local frame to FRD so root M*R is valid. */
const GLTF_TO_FRD = new Quaternion().setFromRotationMatrix(
  new Matrix4().set(
    0, 0, -1, 0,
    1, 0, 0, 0,
    0, -1, 0, 0,
    0, 0, 0, 1,
  ),
);

const _r = new Matrix4();
const _qNed = new Quaternion();
const _qThree = new Quaternion();
const _heat = new Color();

const VIRIDIS: readonly [number, number, number][] = [
  [0x44 / 255, 0x01 / 255, 0x54 / 255],
  [0x46 / 255, 0x32 / 255, 0x7e / 255],
  [0x36 / 255, 0x5c / 255, 0x8d / 255],
  [0x27 / 255, 0x7f / 255, 0x8e / 255],
  [0x1f / 255, 0xa1 / 255, 0x87 / 255],
  [0x4a / 255, 0xc1 / 255, 0x6d / 255],
  [0x90 / 255, 0xd7 / 255, 0x43 / 255],
  [0xfe / 255, 0xe8 / 255, 0x25 / 255],
];

export type ReplayViewportProps = {
  frame: Frame | null;
  modelUrl?: string;
  onPartPick?: (part_id: string) => void;
};

/** Body-to-NED quat (w,x,y,z) → body-to-three.js via M * R. */
function quatFrdNedToThree(
  quat: [number, number, number, number],
  out: Quaternion,
): Quaternion {
  const [w, x, y, z] = quat;
  _qNed.set(x, y, z, w);
  _r.makeRotationFromQuaternion(_qNed);
  _r.multiplyMatrices(NED_TO_THREE, _r);
  return out.setFromRotationMatrix(_r);
}

function applyReplayPose(group: Group, frame: Frame): void {
  const [x, y, z] = nedToThree(frame.pos_ned);
  group.position.set(x, y, z);
  quatFrdNedToThree(frame.quat, _qThree);
  group.quaternion.copy(_qThree);
}

/** Dark purple at n=1 to yellow at n>=1.15. Driven by load_factor_n only. */
function viridisLike(loadFactorN: number, out: Color): Color {
  const t = Math.min(1, Math.max(0, (loadFactorN - 1) / 0.15));
  const last = VIRIDIS.length - 1;
  const pos = t * last;
  const lo = Math.floor(pos);
  const hi = Math.min(lo + 1, last);
  const f = pos - lo;
  const a = VIRIDIS[lo];
  const b = VIRIDIS[hi];
  return out.setRGB(
    a[0] + (b[0] - a[0]) * f,
    a[1] + (b[1] - a[1]) * f,
    a[2] + (b[2] - a[2]) * f,
  );
}

function partIdFromObject(obj: Object3D): string | null {
  let cur: Object3D | null = obj;
  while (cur) {
    if (cur.name) return cur.name;
    cur = cur.parent;
  }
  return null;
}

function isWingPart(partId: string): boolean {
  return partId.startsWith("wing_");
}

function paintWingMaterials(colors: Color[], loadFactorN: number): void {
  viridisLike(loadFactorN, _heat);
  for (const color of colors) color.copy(_heat);
}

function collectWingColors(root: Object3D): Color[] {
  const colors: Color[] = [];
  root.traverse((obj) => {
    if (!(obj instanceof Mesh)) return;
    const id = obj.name || obj.parent?.name || "";
    if (!isWingPart(id)) return;
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    for (const mat of mats) {
      if (mat && "color" in mat && mat.color instanceof Color) {
        colors.push(mat.color);
      }
    }
  });
  return colors;
}

function cloneScenePreserveNodes(scene: Object3D): Group {
  const cloned = scene.clone(true);
  cloned.traverse((obj) => {
    if (!(obj instanceof Mesh)) return;
    obj.castShadow = true;
    obj.receiveShadow = true;
    if (Array.isArray(obj.material)) {
      obj.material = obj.material.map((m) => m.clone());
    } else if (obj.material) {
      obj.material = obj.material.clone();
    }
  });
  return cloned as Group;
}

type BoundaryProps = {
  children: ReactNode;
  fallback: ReactNode;
  resetKey: string;
};

type BoundaryState = { error: boolean };

class GltfErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { error: false };

  static getDerivedStateFromError(): BoundaryState {
    return { error: true };
  }

  componentDidUpdate(prev: BoundaryProps): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: false });
    }
  }

  render(): ReactNode {
    if (this.state.error) return this.props.fallback;
    return this.props.children;
  }
}

function useGltfPresent(url: string): boolean {
  const [present, setPresent] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setPresent(false);
    fetch(url, { method: "HEAD" })
      .then((res) => {
        if (cancelled) return;
        if (res.ok) {
          setPresent(true);
          return;
        }
        if (res.status === 405 || res.status === 501) {
          return fetch(url).then((getRes) => {
            if (!cancelled) setPresent(getRes.ok);
          });
        }
        setPresent(false);
      })
      .catch(() => {
        if (!cancelled) setPresent(false);
      });
    return () => {
      cancelled = true;
    };
  }, [url]);
  return present;
}

function PlaceholderAircraft({
  frame,
  onPartPick,
}: {
  frame: Frame;
  onPartPick?: (part_id: string) => void;
}) {
  const ref = useRef<Group>(null);
  const wingMat = useRef<MeshStandardMaterial>(null);

  useFrame(() => {
    if (!ref.current) return;
    applyReplayPose(ref.current, frame);
    if (wingMat.current) viridisLike(frame.load_factor_n, wingMat.current.color);
  });

  const handlePick = useCallback(
    (ev: ThreeEvent<MouseEvent>) => {
      if (!onPartPick) return;
      ev.stopPropagation();
      const id = partIdFromObject(ev.object);
      if (id) onPartPick(id);
    },
    [onPartPick],
  );

  return (
    <group ref={ref} onClick={handlePick}>
      <mesh name="fuse_1" position={[0, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.06, 0.09, 1.0, 12]} />
        <meshStandardMaterial color="#c5c1b5" metalness={0.4} roughness={0.45} />
      </mesh>
      <mesh name="wing_1" position={[0, 0.02, 0]}>
        <boxGeometry args={[2.2, 0.04, 0.22]} />
        <meshStandardMaterial ref={wingMat} color="#440154" />
      </mesh>
      <mesh name="spar_L" position={[0, 0.02, 0]} rotation={[0.7, 0, 0]}>
        <boxGeometry args={[0.04, 0.02, 0.55]} />
        <meshStandardMaterial color="#d9d3c4" />
      </mesh>
      <mesh
        name="vtail_L"
        position={[0.35, 0.18, -0.42]}
        rotation={[0.7, 0.2, 0.6]}
      >
        <boxGeometry args={[0.35, 0.02, 0.12]} />
        <meshStandardMaterial color="#d9d3c4" />
      </mesh>
      <mesh
        name="vtail_R"
        position={[-0.35, 0.18, -0.42]}
        rotation={[0.7, -0.2, -0.6]}
      >
        <boxGeometry args={[0.35, 0.02, 0.12]} />
        <meshStandardMaterial color="#d9d3c4" />
      </mesh>
    </group>
  );
}

function GltfAircraft({
  frame,
  modelUrl,
  onPartPick,
}: {
  frame: Frame;
  modelUrl: string;
  onPartPick?: (part_id: string) => void;
}) {
  const { scene } = useGLTF(modelUrl);
  const root = useMemo(() => cloneScenePreserveNodes(scene), [scene]);
  const wingColors = useMemo(() => collectWingColors(root), [root]);
  const ref = useRef<Group>(null);

  useFrame(() => {
    if (!ref.current) return;
    applyReplayPose(ref.current, frame);
    paintWingMaterials(wingColors, frame.load_factor_n);
  });

  const handlePick = useCallback(
    (ev: ThreeEvent<MouseEvent>) => {
      if (!onPartPick) return;
      ev.stopPropagation();
      const id = partIdFromObject(ev.object);
      if (id) onPartPick(id);
    },
    [onPartPick],
  );

  return (
    <group ref={ref} onClick={handlePick}>
      <group quaternion={GLTF_TO_FRD}>
        <primitive object={root} />
      </group>
    </group>
  );
}

/** Mission altitude is ~120 m NED-down; keep the camera on the airframe, not the origin. */
const CHASE_OFFSET = [4.5, 2.0, 5.5] as const;

function ChaseRig({ frame }: { frame: Frame | null }) {
  const controls = useRef<any>(null);
  const { camera } = useThree();
  const seeded = useRef(false);
  const last = useRef<[number, number, number] | null>(null);

  useFrame(() => {
    if (!frame || !controls.current) return;
    const [x, y, z] = nedToThree(frame.pos_ned);
    const prev = last.current;
    if (!seeded.current) {
      camera.position.set(
        x + CHASE_OFFSET[0],
        y + CHASE_OFFSET[1],
        z + CHASE_OFFSET[2],
      );
      seeded.current = true;
    } else if (prev) {
      camera.position.x += x - prev[0];
      camera.position.y += y - prev[1];
      camera.position.z += z - prev[2];
    }
    last.current = [x, y, z];
    controls.current.target.set(x, y, z);
    controls.current.update();
  });

  return <OrbitControls ref={controls} makeDefault />;
}

function FollowKeyLight({ frame }: { frame: Frame | null }) {
  const [x, y, z] = frame ? nedToThree(frame.pos_ned) : [0, 120, 0];
  return (
    <directionalLight
      position={[x + 8, y + 12, z + 6]}
      intensity={1.4}
      castShadow
    />
  );
}

function FollowGrid({ frame }: { frame: Frame | null }) {
  const [x, y, z] = frame ? nedToThree(frame.pos_ned) : [0, 0, 0];
  return (
    <Grid
      position={[x, y - 2, z]}
      args={[80, 80]}
      cellColor="#2a3124"
      sectionColor="#3d4a32"
      cellSize={2}
      sectionSize={10}
      infiniteGrid
      fadeDistance={80}
    />
  );
}

function ReplayAircraft({
  frame,
  modelUrl,
  onPartPick,
}: {
  frame: Frame;
  modelUrl: string;
  onPartPick?: (part_id: string) => void;
}) {
  const present = useGltfPresent(modelUrl);
  const fallback = (
    <PlaceholderAircraft frame={frame} onPartPick={onPartPick} />
  );
  if (!present) return fallback;
  return (
    <GltfErrorBoundary resetKey={modelUrl} fallback={fallback}>
      <Suspense fallback={fallback}>
        <GltfAircraft
          frame={frame}
          modelUrl={modelUrl}
          onPartPick={onPartPick}
        />
      </Suspense>
    </GltfErrorBoundary>
  );
}

export function ReplayViewport({
  frame,
  modelUrl = DEFAULT_MODEL_URL,
  onPartPick,
}: ReplayViewportProps) {
  return (
    <Canvas camera={{ position: [10, 124, 10], fov: 42 }} shadows>
      <color attach="background" args={["#0c0f0b"]} />
      <hemisphereLight args={["#d7e7ff", "#1a1810", 1.0]} />
      <FollowKeyLight frame={frame} />
      <FollowGrid frame={frame} />
      {frame ? (
        <ReplayAircraft
          frame={frame}
          modelUrl={modelUrl}
          onPartPick={onPartPick}
        />
      ) : null}
      <ChaseRig frame={frame} />
    </Canvas>
  );
}
