/**
 * CadViewport — the Inspect-mode 3D viewport.
 *
 * Shows the original mesh reference, the editable reconstruction, or a translucent overlay of
 * the two, with part picking (hover + click) and an explode slider. The mode label is
 * persistent and never implicit: the caller renders it from `VIEW_MODE_LABEL[mode]`, and the
 * viewport reflects the same `mode` prop, so the two representations can never be confused.
 *
 * Controlled component: it owns no selection or revision state. Pass `mode`, `selectedPartId`
 * and `explode` down; take `onSelect` / `onHover` back up.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useThree, type ThreeEvent } from '@react-three/fiber';
import { OrbitControls, useGLTF, Bounds, Environment } from '@react-three/drei';
import * as THREE from 'three';

import {
  type ColourBy,
  type DesignManifest,
  type PartOccurrence,
  type ViewMode,
  NEUTRAL_COLOR,
  partColor,
} from './types';

export interface CadViewportProps {
  manifest: DesignManifest;
  /** URL of the reference GLB (node name per part_id). Required. */
  referenceUrl: string;
  /** URL of the reconstruction GLB, when A2 has produced one for this revision. */
  reconstructionUrl?: string | null;
  mode: ViewMode;
  colourBy?: ColourBy;
  /** 0 = assembled, 1 = fully exploded. */
  explode?: number;
  selectedPartId?: string | null;
  onSelect?: (partId: string | null) => void;
  onHover?: (partId: string | null) => void;
  /** Measured axis-aligned bounds of the selection, reported after each selection change. */
  onMeasure?: (dims: { length_x_m: number; width_y_m: number; height_z_m: number } | null) => void;
  className?: string;
}

const OVERLAY_REFERENCE_COLOR = '#8f97a1';

/** Walk up from a hit object until a node name matches a known part_id. */
function resolvePartId(object: THREE.Object3D, known: Set<string>): string | null {
  let node: THREE.Object3D | null = object;
  while (node) {
    if (node.name && known.has(node.name)) return node.name;
    node = node.parent;
  }
  return null;
}

interface ModelProps {
  url: string;
  kind: 'reference' | 'reconstruction';
  manifest: DesignManifest;
  mode: ViewMode;
  colourBy: ColourBy;
  explode: number;
  selectedPartId?: string | null;
  hoveredPartId: string | null;
  onSelect?: (partId: string | null) => void;
  onHover: (partId: string | null) => void;
  onMeasure?: CadViewportProps['onMeasure'];
}

function Model({
  url, kind, manifest, mode, colourBy, explode,
  selectedPartId, hoveredPartId, onSelect, onHover, onMeasure,
}: ModelProps) {
  const { scene } = useGLTF(url);
  const { invalidate } = useThree();
  const root = useMemo(() => scene.clone(true), [scene]);

  const partById = useMemo(
    () => new Map(manifest.parts.map((p) => [p.part_id, p] as const)),
    [manifest],
  );
  const knownIds = useMemo(() => new Set(partById.keys()), [partById]);

  /** part_id -> { meshes, home offsets, explode direction, measured size } */
  const entries = useMemo(() => {
    const map = new Map<string, {
      meshes: THREE.Mesh[];
      carrier: THREE.Object3D;
      home: THREE.Vector3;
      dir: THREE.Vector3;
      size: THREE.Vector3;
    }>();
    root.updateMatrixWorld(true);
    root.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh) return;
      const pid = resolvePartId(mesh, knownIds);
      if (!pid) return;
      // trimesh-exported GLBs frequently omit NORMAL; a lit material renders black without it
      if (!mesh.geometry.attributes.normal) mesh.geometry.computeVertexNormals();
      mesh.material = new THREE.MeshStandardMaterial({
        color: NEUTRAL_COLOR, roughness: 0.62, metalness: 0.06, transparent: true, opacity: 1,
      });
      mesh.userData.partId = pid;
      let carrier: THREE.Object3D = mesh;
      while (carrier.parent && carrier.parent !== root &&
             resolvePartId(carrier.parent, knownIds) === pid) carrier = carrier.parent;
      const existing = map.get(pid);
      if (existing) existing.meshes.push(mesh);
      else map.set(pid, {
        meshes: [mesh], carrier, home: carrier.position.clone(),
        dir: new THREE.Vector3(), size: new THREE.Vector3(),
      });
    });

    const whole = new THREE.Box3();
    const boxes = new Map<string, THREE.Box3>();
    for (const [pid, e] of map) {
      const box = new THREE.Box3();
      e.meshes.forEach((m) => box.expandByObject(m));
      boxes.set(pid, box);
      whole.union(box);
      box.getSize(e.size);
    }
    const origin = whole.getCenter(new THREE.Vector3());
    for (const [pid, e] of map) {
      boxes.get(pid)!.getCenter(e.dir).sub(origin);
      if (e.dir.lengthSq() < 1e-12) e.dir.set(0, 0.001, 0);
    }
    return map;
  }, [root, knownIds]);

  // materials: colour by claim status / category, translucency in overlay mode
  useEffect(() => {
    for (const [pid, e] of entries) {
      const part = partById.get(pid) as PartOccurrence | undefined;
      const selected = selectedPartId === pid;
      const hovered = hoveredPartId === pid;
      let color = part ? partColor(part, colourBy) : NEUTRAL_COLOR;
      let opacity = 1;
      if (mode === 'overlay') {
        if (kind === 'reference') { color = OVERLAY_REFERENCE_COLOR; opacity = 0.55; }
        else opacity = 0.42;
      }
      if (selected) opacity = Math.min(1, opacity + 0.35);
      for (const mesh of e.meshes) {
        const mat = mesh.material as THREE.MeshStandardMaterial;
        mat.color.set(color);
        mat.opacity = opacity;
        mat.transparent = opacity < 1;
        mat.depthWrite = opacity >= 0.99;
        mat.emissive.set(selected ? '#ffffff' : hovered ? '#8899aa' : '#000000');
        mat.emissiveIntensity = selected ? 0.32 : hovered ? 0.22 : 0;
        mat.needsUpdate = true;
      }
    }
    invalidate();
  }, [entries, partById, colourBy, mode, kind, selectedPartId, hoveredPartId, invalidate]);

  // explode
  useEffect(() => {
    for (const e of entries.values()) {
      e.carrier.position.copy(e.home).addScaledVector(e.dir, explode * 0.9);
    }
    invalidate();
  }, [entries, explode, invalidate]);

  // measured bounding box of the selection, in FRD-ish terms (GLB x=y_frd, y=-z_frd, z=-x_frd)
  useEffect(() => {
    if (!onMeasure) return;
    const e = selectedPartId ? entries.get(selectedPartId) : undefined;
    onMeasure(e ? { length_x_m: e.size.z, width_y_m: e.size.x, height_z_m: e.size.y } : null);
  }, [entries, selectedPartId, onMeasure]);

  const visible = mode === 'overlay' || mode === kind;

  return (
    <primitive
      object={root}
      visible={visible}
      onPointerMove={(ev: ThreeEvent<PointerEvent>) => {
        if (!visible) return;
        ev.stopPropagation();
        onHover(resolvePartId(ev.object, knownIds));
      }}
      onPointerOut={() => onHover(null)}
      onClick={(ev: ThreeEvent<MouseEvent>) => {
        if (!visible) return;
        ev.stopPropagation();
        onSelect?.(resolvePartId(ev.object, knownIds));
      }}
    />
  );
}

export function CadViewport({
  manifest,
  referenceUrl,
  reconstructionUrl,
  mode,
  colourBy = 'status',
  explode = 0,
  selectedPartId = null,
  onSelect,
  onHover,
  onMeasure,
  className,
}: CadViewportProps) {
  const [hovered, setHovered] = useState<string | null>(null);

  const handleHover = (pid: string | null) => {
    setHovered(pid);
    onHover?.(pid);
  };

  const effectiveMode: ViewMode = reconstructionUrl ? mode : 'reference';

  return (
    <div className={className} style={{ position: 'relative', width: '100%', height: '100%' }}>
      <Canvas
        frameloop="demand"
        dpr={[1, 2]}
        camera={{ fov: 45, position: [1.4, 1.0, 1.8], near: 0.01, far: 200 }}
        onPointerMissed={() => onSelect?.(null)}
      >
        <hemisphereLight intensity={1.8} groundColor="#4a5058" />
        <directionalLight position={[2.5, 4, 3]} intensity={1.7} />
        <directionalLight position={[-3, 1.5, -2.5]} intensity={0.5} />
        <Environment preset="city" background={false} />
        <Bounds fit clip observe margin={1.25}>
          <Model
            url={referenceUrl}
            kind="reference"
            manifest={manifest}
            mode={effectiveMode}
            colourBy={colourBy}
            explode={explode}
            selectedPartId={selectedPartId}
            hoveredPartId={hovered}
            onSelect={onSelect}
            onHover={handleHover}
            onMeasure={onMeasure}
          />
          {reconstructionUrl ? (
            <Model
              url={reconstructionUrl}
              kind="reconstruction"
              manifest={manifest}
              mode={effectiveMode}
              colourBy={colourBy}
              explode={explode}
              selectedPartId={selectedPartId}
              hoveredPartId={hovered}
              onSelect={onSelect}
              onHover={handleHover}
            />
          ) : null}
        </Bounds>
        <OrbitControls makeDefault enableDamping dampingFactor={0.08} />
      </Canvas>
    </div>
  );
}

/** Preload both representations so the mode toggle does not stutter mid-demo. */
CadViewport.preload = (referenceUrl: string, reconstructionUrl?: string | null) => {
  useGLTF.preload(referenceUrl);
  if (reconstructionUrl) useGLTF.preload(reconstructionUrl);
};

export default CadViewport;
