/**
 * The aircraft schematic.
 *
 * Every surface here is the contract's own geometry: bounds and placements for equipment, the
 * lofted planform from `wing_stations` for the wings, and the declared cant and area for the
 * V-tail. Nothing is modelled for looks. If the battery moves 45 mm forward in the design, it
 * moves 45 mm forward here, because both read the same transform.
 *
 * Team A owns `packages/cad` and will ship tessellated geometry. This is the B-owned stand-in, and
 * it lives outside `features/cad/` so A's directory stays theirs.
 *
 * Interaction is deliberately small: orbit, pan, zoom, hover, click to select. Selection is shared
 * state, so picking here moves the tree, the inspector, and the dependency graph with it.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import type { GeometryFeatures, PartOccurrence } from "@/lib/contracts.gen";
import { buildBox, buildVTailPanel, buildWing, fitCamera, frdToThree } from "./geometry";

export interface SchematicPart {
  partId: string;
  name: string;
  role: string;
  size: [number, number, number];
  localCentre: [number, number, number];
  translation: [number, number, number];
  massKnown: boolean;
  locked: boolean;
  editable: boolean;
  mirrorOf: string | null;
}

export interface ScenePalette {
  background: string;
  surface: string;
  line: string;
  accent: string;
  unknown: string;
  locked: string;
  ground: string;
}

interface Props {
  parts: SchematicPart[];
  features: GeometryFeatures | null;
  selectedPartId: string | null;
  onSelect: (partId: string | null) => void;
  palette: ScenePalette;
}

/** Roles whose real shape comes from geometry_features, not from their bounding box. */
const LOFTED_ROLES = new Set(["wing", "tail_panel"]);

export function Schematic({ parts, features, selectedPartId, onSelect, palette }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const sceneRef = useRef<{
    meshes: Map<string, THREE.Mesh>;
    edges: Map<string, THREE.LineSegments>;
  } | null>(null);

  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Rebuild only when the geometry actually changes, never on a selection change.
  const signature = useMemo(
    () =>
      [
        parts.map((p) => `${p.partId}@${p.translation.join(",")}:${p.size.join(",")}`).join("|"),
        (features?.wing_stations ?? [])
          .map((s) => `${s.span_y_m},${s.chord_m},${s.leading_edge_x_m}`)
          .join("|"),
      ].join("::"),
    [parts, features],
  );

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || parts.length === 0) return undefined;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    } catch {
      setFailed("This browser could not start WebGL, so the schematic cannot be drawn.");
      return undefined;
    }

    const width = mount.clientWidth || 800;
    const height = mount.clientHeight || 600;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.style.display = "block";
    renderer.domElement.tabIndex = 0;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(palette.background);

    const camera = new THREE.PerspectiveCamera(36, width / height, 0.02, 200);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI * 0.495;

    scene.add(new THREE.HemisphereLight(0xffffff, 0xd8d8d4, 1.05));
    const key = new THREE.DirectionalLight(0xffffff, 1.45);
    key.position.set(2.4, 3.6, 2.2);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0008;
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xffffff, 0.42);
    rim.position.set(-2.6, 1.1, -2.0);
    scene.add(rim);

    // -- build -------------------------------------------------------------------------------
    const meshes = new Map<string, THREE.Mesh>();
    const edges = new Map<string, THREE.LineSegments>();
    const group = new THREE.Group();

    const addSurface = (
      partId: string,
      geometry: THREE.BufferGeometry,
      position: THREE.Vector3 | null,
      massKnown: boolean,
    ) => {
      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(massKnown ? palette.surface : palette.unknown),
        roughness: 0.68,
        metalness: 0.02,
        transparent: !massKnown,
        opacity: massKnown ? 1 : 0.55,
        side: THREE.DoubleSide,
      });
      const mesh = new THREE.Mesh(geometry, material);
      if (position) mesh.position.copy(position);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.partId = partId;
      group.add(mesh);
      meshes.set(partId, mesh);

      // Hairline edges: what makes a pale model readable against a pale ground.
      const line = new THREE.LineSegments(
        new THREE.EdgesGeometry(geometry, 22),
        new THREE.LineBasicMaterial({
          color: new THREE.Color(palette.line),
          transparent: true,
          opacity: 0.5,
        }),
      );
      if (position) line.position.copy(position);
      group.add(line);
      edges.set(partId, line);
    };

    for (const part of parts) {
      const lofted = features && LOFTED_ROLES.has(part.role);

      if (lofted && part.role === "wing") {
        const side: 1 | -1 = part.translation[1] >= 0 ? 1 : -1;
        const geometry = buildWing(features, side);
        if (geometry) {
          addSurface(part.partId, geometry, null, part.massKnown);
          continue;
        }
      }

      if (lofted && part.role === "tail_panel") {
        const panel = features.vtail_panels?.find((entry) => entry.part_id === part.partId);
        if (panel) {
          const side: 1 | -1 = part.translation[1] >= 0 ? 1 : -1;
          addSurface(
            part.partId,
            buildVTailPanel(panel, part.translation, side),
            null,
            part.massKnown,
          );
          continue;
        }
      }

      const { geometry, position } = buildBox(part);
      addSurface(part.partId, geometry, position, part.massKnown);
    }
    scene.add(group);

    // -- frame the whole assembly, from the geometry that was actually built ------------------
    const bounds = new THREE.Box3().setFromObject(group);
    const { target, distance } = fitCamera(camera, bounds);
    controls.target.copy(target);
    controls.minDistance = distance * 0.25;
    controls.maxDistance = distance * 3.5;
    // A three-quarter view from above: the angle an engineer would pick up a model at.
    const direction = new THREE.Vector3(0.62, 0.46, 0.64).normalize();
    camera.position.copy(target).addScaledVector(direction, distance);
    camera.updateProjectionMatrix();
    controls.update();

    const extent = bounds.getSize(new THREE.Vector3());
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(extent.length() * 3, extent.length() * 3),
      new THREE.ShadowMaterial({ opacity: 0.12 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.y = bounds.min.y - extent.y * 0.4;
    ground.receiveShadow = true;
    scene.add(ground);

    key.shadow.camera.near = 0.1;
    key.shadow.camera.far = distance * 4;
    const shadowSpan = extent.length();
    key.shadow.camera.left = -shadowSpan;
    key.shadow.camera.right = shadowSpan;
    key.shadow.camera.top = shadowSpan;
    key.shadow.camera.bottom = -shadowSpan;
    key.shadow.camera.updateProjectionMatrix();

    // -- picking -------------------------------------------------------------------------------
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let dragged = false;

    const pick = (event: PointerEvent): string | null => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects([...meshes.values()], false)[0];
      return hit ? (hit.object.userData.partId as string) : null;
    };

    const onMove = (event: PointerEvent) => {
      dragged = true;
      const id = pick(event);
      setHovered((previous) => (previous === id ? previous : id));
      renderer.domElement.style.cursor = id ? "pointer" : "grab";
    };
    const onDown = () => {
      dragged = false;
    };
    const onUp = (event: PointerEvent) => {
      if (dragged) return; // a drag is an orbit, not a selection
      onSelectRef.current(pick(event));
    };

    renderer.domElement.addEventListener("pointermove", onMove);
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.style.cursor = "grab";

    const observer = new ResizeObserver(() => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      // Re-fit on resize: a framing that only holds at one aspect ratio is not a framing.
      const refit = fitCamera(camera, bounds);
      controls.maxDistance = refit.distance * 3.5;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    observer.observe(mount);

    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();
    setReady(true);
    sceneRef.current = { meshes, edges };

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      renderer.domElement.removeEventListener("pointermove", onMove);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      controls.dispose();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
          object.geometry.dispose();
          const material = object.material;
          if (Array.isArray(material)) material.forEach((m) => m.dispose());
          else material.dispose();
        }
      });
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      sceneRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature, palette.background, palette.surface, palette.line, palette.unknown]);

  // Selection and hover are material updates on the live scene, never a rebuild.
  useEffect(() => {
    const current = sceneRef.current;
    if (!current) return;
    for (const part of parts) {
      const mesh = current.meshes.get(part.partId);
      const line = current.edges.get(part.partId);
      if (!mesh || !line) continue;

      const isSelected = part.partId === selectedPartId;
      const isHovered = part.partId === hovered;
      const material = mesh.material as THREE.MeshStandardMaterial;
      const lineMaterial = line.material as THREE.LineBasicMaterial;

      material.color.set(isSelected ? palette.accent : part.massKnown ? palette.surface : palette.unknown);
      material.emissive.set(isHovered && !isSelected ? palette.accent : "#000000");
      material.emissiveIntensity = isHovered && !isSelected ? 0.12 : 0;
      material.opacity = part.massKnown ? 1 : isSelected ? 0.9 : 0.55;

      lineMaterial.color.set(isSelected ? palette.accent : palette.line);
      lineMaterial.opacity = isSelected ? 1 : isHovered ? 0.8 : 0.5;
    }
  }, [selectedPartId, hovered, parts, palette]);

  const hoveredPart = parts.find((part) => part.partId === hovered);

  return (
    <div className="schematic">
      <div ref={mountRef} className="schematic-canvas" />

      {failed ? <p className="schematic-state">{failed}</p> : null}
      {!failed && !ready ? <p className="schematic-state">Building the assembly…</p> : null}
      {!failed && ready && parts.length === 0 ? (
        <p className="schematic-state">This revision has no placed geometry.</p>
      ) : null}

      {hoveredPart ? (
        <div className="schematic-readout" aria-live="polite">
          <span className="readout-name">{hoveredPart.name}</span>
          <span className="readout-meta">
            {hoveredPart.role.replace(/_/g, " ")}
            {hoveredPart.massKnown ? "" : " · mass unknown"}
          </span>
        </div>
      ) : null}

      {ready && !failed ? (
        <p className="schematic-hint">Drag to orbit · scroll to zoom · click a part to select it</p>
      ) : null}
    </div>
  );
}

export function toSchematicParts(
  occurrences: PartOccurrence[],
  capabilities: Record<string, string[]>,
): SchematicPart[] {
  const out: SchematicPart[] = [];
  for (const occurrence of occurrences) {
    const bounds = occurrence.bounds_local_m;
    if (!bounds) continue;
    const min = bounds.min_m;
    const max = bounds.max_m;
    const matrix = occurrence.transform?.matrix;
    out.push({
      partId: occurrence.part_id,
      name: occurrence.name,
      role: occurrence.role ?? "unknown",
      size: [max[0] - min[0], max[1] - min[1], max[2] - min[2]],
      localCentre: [(max[0] + min[0]) / 2, (max[1] + min[1]) / 2, (max[2] + min[2]) / 2],
      translation: [matrix?.[0]?.[3] ?? 0, matrix?.[1]?.[3] ?? 0, matrix?.[2]?.[3] ?? 0],
      massKnown: occurrence.mass_kg.value !== null && occurrence.mass_kg.value !== undefined,
      locked: Boolean(occurrence.locked),
      editable: (capabilities[occurrence.part_id] ?? []).length > 0,
      mirrorOf: occurrence.mirror_of ?? null,
    });
  }
  return out;
}

/** Read the scene colours out of the stylesheet, so there is one palette and not two. */
export function readPalette(element: HTMLElement): ScenePalette {
  const styles = getComputedStyle(element);
  const token = (name: string, fallback: string) => styles.getPropertyValue(name).trim() || fallback;
  return {
    background: token("--scene-bg", "#fbfbfa"),
    surface: token("--scene-surface", "#e4e4e1"),
    line: token("--scene-line", "#7d7d79"),
    accent: token("--scene-accent", "#2a52c9"),
    unknown: token("--scene-unknown", "#c08419"),
    locked: token("--scene-locked", "#bdbdb8"),
    ground: token("--scene-ground", "#f2f2f0"),
  };
}

export { frdToThree };
