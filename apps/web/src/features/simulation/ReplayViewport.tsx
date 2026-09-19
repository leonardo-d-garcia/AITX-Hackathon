import { Canvas, useFrame } from "@react-three/fiber";
import { Grid, OrbitControls } from "@react-three/drei";
import { useMemo, useRef } from "react";
import type { Group } from "three";
import { Quaternion } from "three";
import { nedToThree, type Frame } from "../../telemetry";

function PlaceholderAircraft({ frame }: { frame: Frame }) {
  const ref = useRef<Group>(null);
  const q = useMemo(() => new Quaternion(), []);

  useFrame(() => {
    if (!ref.current) return;
    const [x, y, z] = nedToThree(frame.pos_ned);
    ref.current.position.set(x, y, z);
    // FRD quat (w,x,y,z) — apply as-is into Y-up after the NED→Y-up position map.
    // Attitude conversion is a known follow-up; identity at t=0 is wings-level.
    q.set(frame.quat[1], frame.quat[2], frame.quat[3], frame.quat[0]);
    ref.current.quaternion.copy(q);
  });

  const heat = Math.min(1, Math.max(0, (frame.load_factor_n - 1) / 0.5));
  const spar = `rgb(${Math.round(40 + 200 * heat)}, ${Math.round(180 - 120 * heat)}, 40)`;

  return (
    <group ref={ref}>
      <mesh position={[0, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
        <cylinderGeometry args={[0.06, 0.09, 1.0, 12]} />
        <meshStandardMaterial color="#c5c1b5" metalness={0.4} roughness={0.45} />
      </mesh>
      <mesh position={[0, 0.02, 0]}>
        <boxGeometry args={[2.2, 0.04, 0.22]} />
        <meshStandardMaterial color="#d9d3c4" />
      </mesh>
      <mesh position={[0, 0.02, 0]} rotation={[0.7, 0, 0]}>
        <boxGeometry args={[0.04, 0.02, 0.55]} />
        <meshStandardMaterial color={spar} />
      </mesh>
      <mesh position={[0.35, 0.18, -0.42]} rotation={[0.7, 0.2, 0.6]}>
        <boxGeometry args={[0.35, 0.02, 0.12]} />
        <meshStandardMaterial color="#d9d3c4" />
      </mesh>
      <mesh position={[-0.35, 0.18, -0.42]} rotation={[0.7, -0.2, -0.6]}>
        <boxGeometry args={[0.35, 0.02, 0.12]} />
        <meshStandardMaterial color="#d9d3c4" />
      </mesh>
    </group>
  );
}

export function ReplayViewport({ frame }: { frame: Frame | null }) {
  return (
    <Canvas camera={{ position: [8, 6, 8], fov: 42 }} shadows>
      <color attach="background" args={["#0c0f0b"]} />
      <hemisphereLight args={["#d7e7ff", "#1a1810", 0.7]} />
      <directionalLight position={[6, 10, 4]} intensity={1.4} castShadow />
      <Grid
        args={[80, 80]}
        cellColor="#2a3124"
        sectionColor="#3d4a32"
        cellSize={2}
        sectionSize={10}
        infiniteGrid
        fadeDistance={70}
      />
      {frame ? <PlaceholderAircraft frame={frame} /> : null}
      <OrbitControls makeDefault />
    </Canvas>
  );
}
