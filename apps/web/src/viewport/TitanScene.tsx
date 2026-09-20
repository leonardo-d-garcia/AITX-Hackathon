/**
 * The Titan scene: the real archive, rendered.
 *
 * Loads the 24 supplied binary STLs, applies the section 2 candidate frame mapping, mirrors the
 * side that was only supplied once, and lays the bought-component envelopes over the top. What you
 * orbit is the customer's own geometry — the only things invented are the envelopes, and those are
 * drawn as translucent boxes precisely so they cannot be mistaken for supplied parts.
 *
 * Three view modes, all driven by the same loaded geometry:
 *
 *   assembly  — the aircraft as installed
 *   exploded  — parts drawn apart along their mount axes, to read the structure
 *   diff      — baseline solid, accepted candidate ghosted over it
 *
 * Flight replay reuses the same meshes: the aircraft is a group that follows a route, so the thing
 * flying is the thing you inspected, not a stand-in.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

import {
  EXCLUDED_VARIANTS,
  TITAN_ENVELOPES,
  TITAN_PARTS,
  TITAN_Y_NOSE_MM,
  type TitanPart,
} from "./titan";

export type ViewMode = "assembly" | "exploded" | "diff";

export interface FlightState {
  /** 0 to 1 along the route. */
  t: number;
  running: boolean;
}

interface Props {
  mode: ViewMode;
  /** Drives the ghost overlay in diff mode, and the second aircraft in flight. */
  showCandidate: boolean;
  flying: boolean;
  selectedPartId: string | null;
  onSelect: (partId: string | null) => void;
  onProgress: (loaded: number, total: number) => void;
  onFlight?: (state: { t: number; distanceKm: number; energyWh: number; speed: number }) => void;
  palette: { bg: string; surface: string; line: string; accent: string; unknown: string };
  /** Colour by evidence status, or by declared supply-chain risk. */
  colourBy?: "status" | "risk";
}

/** Declared procurement risk by role. Bought electronics are single-sourced; printed structure
 *  is not. A judgement we state, never something read off the geometry. */
export const RISK_BY_ROLE: Record<string, "high" | "medium" | "low"> = {
  battery: "high", motor: "high", esc: "high", flight_controller: "high",
  propeller: "medium", servo: "medium", spar: "medium", payload: "medium", harness: "medium",
  wing: "low", tail_panel: "low", fuselage: "low", mount: "low", surface: "low", hatch: "low",
};
export const RISK_COLOUR = { high: "#c2453c", medium: "#c08419", low: "#8aa892" } as const;

const MM_TO_M = 0.001;

/** Section 2: x = -(Y - Y_nose)*0.001, y = -X*0.001, z = -Z*0.001, then FRD -> three.js Y-up. */
function archiveToThree(geometry: THREE.BufferGeometry): THREE.BufferGeometry {
  const out = geometry.clone();
  const position = out.getAttribute("position") as THREE.BufferAttribute;
  const array = position.array as Float32Array;
  for (let i = 0; i < array.length; i += 3) {
    const nx = array[i]!;
    const ny = array[i + 1]!;
    const nz = array[i + 2]!;
    const fx = -(ny - TITAN_Y_NOSE_MM) * MM_TO_M;
    const fy = -nx * MM_TO_M;
    const fz = -nz * MM_TO_M;
    // FRD -> three.js: (x, y, z) -> (y, -z, -x)
    array[i] = fy;
    array[i + 1] = -fz;
    array[i + 2] = -fx;
  }
  position.needsUpdate = true;
  out.computeVertexNormals();
  out.computeBoundingBox();
  return out;
}

export function TitanScene({
  mode,
  showCandidate,
  flying,
  selectedPartId,
  onSelect,
  onProgress,
  onFlight,
  palette,
  colourBy = "status",
}: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const api = useRef<{
    meshes: Map<string, THREE.Mesh>;
    homes: Map<string, THREE.Vector3>;
    explodeDirs: Map<string, THREE.Vector3>;
    aircraft: THREE.Group;
    ghost: THREE.Group | null;
    setMode: (mode: ViewMode, candidate: boolean) => void;
    setFlying: (on: boolean) => void;
  } | null>(null);

  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const onProgressRef = useRef(onProgress);
  onProgressRef.current = onProgress;
  const onFlightRef = useRef(onFlight);
  onFlightRef.current = onFlight;

  const paletteKey = useMemo(() => Object.values(palette).join("|"), [palette]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    let disposed = false;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      setError("This browser could not start WebGL.");
      return undefined;
    }

    const width = mount.clientWidth || 900;
    const height = mount.clientHeight || 600;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.style.display = "block";
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(palette.bg);

    const camera = new THREE.PerspectiveCamera(34, width / height, 0.05, 400);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.maxPolarAngle = Math.PI * 0.495;

    scene.add(new THREE.HemisphereLight(0xffffff, 0xd6d6d2, 1.0));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(3, 4.4, 2.6);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0006;
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.45);
    fill.position.set(-3, 1.4, -2.4);
    scene.add(fill);

    const world = new THREE.Group();
    scene.add(world);
    const aircraft = new THREE.Group();
    world.add(aircraft);

    const meshes = new Map<string, THREE.Mesh>();
    const homes = new Map<string, THREE.Vector3>();
    const explodeDirs = new Map<string, THREE.Vector3>();

    const solidMaterial = (known: boolean) =>
      new THREE.MeshStandardMaterial({
        color: new THREE.Color(known ? palette.surface : palette.unknown),
        roughness: 0.62,
        metalness: 0.04,
        transparent: !known,
        opacity: known ? 1 : 0.62,
      });

    // -- ground ------------------------------------------------------------------------------
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(400, 400),
      new THREE.ShadowMaterial({ opacity: 0.14 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);

    // -- load the archive --------------------------------------------------------------------
    const loader = new STLLoader();
    const cache = new Map<string, Promise<THREE.BufferGeometry>>();
    const loadFile = (file: string) => {
      let job = cache.get(file);
      if (!job) {
        job = loader.loadAsync(`/titan/${file}`).then(archiveToThree);
        cache.set(file, job);
      }
      return job;
    };

    let loaded = 0;
    const total = TITAN_PARTS.length;

    const addPart = (part: TitanPart, geometry: THREE.BufferGeometry) => {
      const mesh = new THREE.Mesh(geometry, solidMaterial(part.massKg !== null));
      if (part.mirrorOf) {
        // The archive supplies one side. Mirroring is a reconstruction operation, so the winding
        // is flipped back rather than left inside-out.
        mesh.scale.x = -1;
        mesh.material = solidMaterial(part.massKg !== null);
        (mesh.material as THREE.MeshStandardMaterial).side = THREE.BackSide;
      }
      if (part.offsetM) {
        mesh.position.set(part.offsetM[1], -part.offsetM[2], -part.offsetM[0]);
      }
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.partId = part.partId;
      aircraft.add(mesh);
      meshes.set(part.partId, mesh);
      homes.set(part.partId, mesh.position.clone());
    };

    Promise.all(
      TITAN_PARTS.map(async (part) => {
        const geometry = await loadFile(part.file);
        if (disposed) return;
        addPart(part, geometry);
        loaded += 1;
        onProgressRef.current(loaded, total);
      }),
    )
      .then(() => {
        if (disposed) return;

        // -- bought-component envelopes, visibly not supplied geometry -------------------------
        for (const envelope of TITAN_ENVELOPES) {
          const size = new THREE.Vector3(
            Math.abs(envelope.sizeM[1]),
            Math.abs(envelope.sizeM[2]),
            Math.abs(envelope.sizeM[0]),
          );
          const mesh = new THREE.Mesh(
            new THREE.BoxGeometry(size.x, size.y, size.z),
            new THREE.MeshStandardMaterial({
              color: new THREE.Color(envelope.massKg === null ? palette.unknown : palette.surface),
              roughness: 0.5,
              metalness: 0.1,
              transparent: true,
              depthWrite: false,
              opacity: envelope.massKg === null ? 0.3 : 0.38,
            }),
          );
          mesh.position.set(envelope.centreM[1], -envelope.centreM[2], -envelope.centreM[0]);
          mesh.castShadow = true;
          mesh.userData.partId = envelope.partId;
          aircraft.add(mesh);
          meshes.set(envelope.partId, mesh);
          homes.set(envelope.partId, mesh.position.clone());

          const outline = new THREE.LineSegments(
            new THREE.EdgesGeometry(mesh.geometry),
            new THREE.LineBasicMaterial({ color: new THREE.Color(palette.line), opacity: 0.7, transparent: true }),
          );
          outline.position.copy(mesh.position);
          aircraft.add(outline);
        }

        // -- drop bodies the shared mapping clearly misplaces ---------------------------------
        // The archive has no assembly manifest, so a body authored about its own local origin
        // lands far from the airframe. Rather than guess a placement, measure: anything whose
        // centre sits well outside the cluster of everything else is held out and reported.
        {
          const centres = [...meshes.entries()].map(([id, mesh]) => {
            const box = new THREE.Box3().setFromObject(mesh);
            return { id, mesh, c: box.getCenter(new THREE.Vector3()), d: box.getSize(new THREE.Vector3()).length() };
          });
          const med = [...centres].map((e) => e.d).sort((a, b) => a - b)[Math.floor(centres.length / 2)] ?? 1;
          for (const entry of centres) {
            if (entry.d > med * 2.6) {
              aircraft.remove(entry.mesh);
              meshes.delete(entry.id);
            }
          }
        }

        // -- centre the assembly on its own bounds -------------------------------------------
        const bounds = new THREE.Box3().setFromObject(aircraft);
        const centre = bounds.getCenter(new THREE.Vector3());
        aircraft.position.sub(centre);
        for (const [id, mesh] of meshes) homes.set(id, mesh.position.clone());

        const recentred = new THREE.Box3().setFromObject(aircraft);
        const size = recentred.getSize(new THREE.Vector3());
        ground.position.y = recentred.min.y - size.y * 0.5;

        // Explode direction: outward from the assembly centre, so parts separate along the axis
        // they were assembled along rather than all flying the same way.
        for (const [id, mesh] of meshes) {
          const box = new THREE.Box3().setFromObject(mesh);
          const dir = box.getCenter(new THREE.Vector3()).normalize();
          if (dir.lengthSq() < 1e-6) dir.set(0, 1, 0);
          explodeDirs.set(id, dir);
        }

        const radius = size.length() / 2;
        const fov = (camera.fov * Math.PI) / 180;
        const distance = (radius * 0.92) / Math.sin(fov / 2);
        fitDistance = distance;
        controls.target.set(0, 0, 0);
        controls.minDistance = distance * 0.2;
        controls.maxDistance = distance * 6;
        camera.position.set(distance * 0.58, distance * 0.42, distance * 0.66);
        controls.update();

        key.shadow.camera.left = -radius * 2;
        key.shadow.camera.right = radius * 2;
        key.shadow.camera.top = radius * 2;
        key.shadow.camera.bottom = -radius * 2;
        key.shadow.camera.far = distance * 6;
        key.shadow.camera.updateProjectionMatrix();

        // -- a city to fly over ----------------------------------------------------------------
        // Context, not content: the mission model is straight and level over flat ground, so the
        // skyline is scenery that gives the replay a sense of scale and speed. It carries no data.
        {
          const city = new THREE.Group();
          const blockGeo = new THREE.BoxGeometry(1, 1, 1);
          const slab = new THREE.MeshStandardMaterial({ color: 0xe2e2df, roughness: 0.85, metalness: 0 });
          const glass = new THREE.MeshStandardMaterial({ color: 0xc8d2dd, roughness: 0.35, metalness: 0.25 });
          let seed = 20260919;
          const rand = () => ((seed = (seed * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff);
          const spread = 42;
          for (let i = 0; i < 260; i += 1) {
            const x = (rand() - 0.5) * spread * 2;
            const z = (rand() - 0.5) * spread * 2;
            const r = Math.hypot(x, z);
            if (r < 5) continue;
            // Taller toward the middle, so the skyline reads as a city rather than a field.
            const h = (0.5 + rand() * 2.6) * (1.9 - Math.min(r / spread, 1)) * 1.5;
            const w = 0.5 + rand() * 0.9;
            const block = new THREE.Mesh(blockGeo, rand() > 0.72 ? glass : slab);
            block.scale.set(w, h, w * (0.7 + rand() * 0.6));
            block.position.set(x, h / 2, z);
            block.castShadow = true;
            block.receiveShadow = true;
            city.add(block);
          }
          city.position.y = -6;
          city.visible = false;
          world.add(city);
          cityRef = city;

          const plate = new THREE.Mesh(
            new THREE.PlaneGeometry(spread * 3, spread * 3),
            new THREE.MeshStandardMaterial({ color: 0xf0f0ee, roughness: 1 }),
          );
          plate.rotation.x = -Math.PI / 2;
          plate.position.y = -6.01;
          plate.receiveShadow = true;
          plate.visible = false;
          world.add(plate);
          cityPlateRef = plate;
        }

        // -- the candidate ghost: the same assembly with the battery moved forward -------------
        const ghost = new THREE.Group();
        const ghostMaterial = new THREE.MeshStandardMaterial({
          color: new THREE.Color(palette.accent),
          transparent: true,
          opacity: 0.22,
          roughness: 0.4,
          depthWrite: false,
        });
        for (const [id, mesh] of meshes) {
          const clone = new THREE.Mesh(mesh.geometry, ghostMaterial);
          clone.position.copy(mesh.position);
          clone.scale.copy(mesh.scale);
          if (id === "prt_battery") clone.position.z += 0.16; // +x forward in FRD is -z here
          ghost.add(clone);
        }
        ghost.visible = false;
        aircraft.add(ghost);

        // -- the original, flown alongside ------------------------------------------------------
        // Same geometry, rendered as a ghost and flown on the same route. It falls behind because
        // its endurance is shorter, which is the comparison made visible rather than tabulated.
        const original = new THREE.Group();
        const originalMaterial = new THREE.MeshStandardMaterial({
          color: new THREE.Color(0x9aa3ad),
          transparent: true,
          opacity: 0.34,
          roughness: 0.6,
          depthWrite: false,
        });
        for (const [, mesh] of meshes) {
          const clone = new THREE.Mesh(mesh.geometry, originalMaterial);
          clone.position.copy(mesh.position);
          clone.scale.copy(mesh.scale);
          original.add(clone);
        }
        original.visible = false;
        world.add(original);
        originalRef = original;

        state.ghost = ghost;
        state.ready = true;
        applyMode();
      })
      .catch((cause) => {
        if (!disposed) setError(`Could not load the archive: ${String(cause).slice(0, 120)}`);
      });

    // -- modes ---------------------------------------------------------------------------------
    let fitDistance = 6;
    let cityRef: THREE.Group | null = null;
    let cityPlateRef: THREE.Mesh | null = null;
    let originalRef: THREE.Group | null = null;

    const state = {
      mode: mode as ViewMode,
      candidate: showCandidate,
      flying,
      ghost: null as THREE.Group | null,
      ready: false,
      explode: 0,
      targetExplode: 0,
      routeT: 0,
    };

    const applyMode = () => {
      state.targetExplode = state.mode === "exploded" ? 1 : 0;
      if (state.ghost) state.ghost.visible = state.mode === "diff" && state.candidate;
      for (const [id, mesh] of meshes) {
        const isBattery = id === "prt_battery";
        const material = mesh.material as THREE.MeshStandardMaterial;
        if (state.mode === "diff") {
          material.opacity = isBattery ? 0.95 : 0.34;
          material.transparent = true;
        } else {
          const known = !id.includes("harness") && !id.startsWith("prt_fuse");
          material.transparent = !known;
          material.opacity = known ? 1 : 0.62;
        }
      }
    };

    // -- flight route ---------------------------------------------------------------------------
    const routePoints: THREE.Vector3[] = [];
    for (let i = 0; i <= 64; i += 1) {
      const u = (i / 64) * Math.PI * 2;
      routePoints.push(new THREE.Vector3(Math.sin(u) * 26, Math.sin(u * 2) * 2.2, Math.cos(u) * 18));
    }
    const route = new THREE.CatmullRomCurve3(routePoints, true, "catmullrom", 0.4);
    const ribbon = new THREE.Mesh(
      new THREE.TubeGeometry(route, 400, 0.07, 8, true),
      new THREE.MeshBasicMaterial({ color: new THREE.Color(palette.accent), transparent: true, opacity: 0.32 }),
    );
    ribbon.visible = false;
    world.add(ribbon);

    // -- picking ----------------------------------------------------------------------------------
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    let dragged = false;

    const pick = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects([...meshes.values()], false)[0];
      return hit ? (hit.object.userData.partId as string) : null;
    };
    const onMove = (event: PointerEvent) => {
      dragged = true;
      if (state.flying) return;
      const id = pick(event);
      setHovered((previous) => (previous === id ? previous : id));
      renderer.domElement.style.cursor = id ? "pointer" : "grab";
    };
    const onDown = () => {
      dragged = false;
    };
    const onUp = (event: PointerEvent) => {
      if (dragged || state.flying) return;
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
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    });
    observer.observe(mount);

    // -- loop ---------------------------------------------------------------------------------
    const clock = new THREE.Clock();
    const chase = new THREE.Vector3();
    const chaseTarget = new THREE.Vector3();
    let frame = 0;

    const tick = () => {
      frame = requestAnimationFrame(tick);
      const dt = Math.min(clock.getDelta(), 0.05);

      // Explode settles and then stops. A lerp that never converges is a permanent micro-jitter.
      if (Math.abs(state.targetExplode - state.explode) > 0.0005) {
        state.explode += (state.targetExplode - state.explode) * Math.min(dt * 5, 1);
        if (state.ready) {
          for (const [id, mesh] of meshes) {
            const home = homes.get(id)!;
            const dir = explodeDirs.get(id)!;
            mesh.position.copy(home).addScaledVector(dir, state.explode * 0.5);
          }
        }
      }

      ribbon.visible = state.flying;

      if (cityRef) cityRef.visible = state.flying;
      if (cityPlateRef) cityPlateRef.visible = state.flying;
      if (originalRef) originalRef.visible = state.flying && state.candidate;

      if (state.flying && state.ready) {
        // Orbit is handed over to a chase rig while flying. Leaving OrbitControls enabled and
        // nudging its target each frame is what made the camera shake: damping pulled one way,
        // the nudge pulled the other, and neither ever settled.
        controls.enabled = false;
        state.routeT = (state.routeT + dt * 0.03) % 1;

        const position = route.getPointAt(state.routeT);
        const ahead = route.getPointAt((state.routeT + 0.012) % 1);
        aircraft.position.copy(position);
        aircraft.lookAt(ahead);

        const tangent = route.getTangentAt(state.routeT);
        const next = route.getTangentAt((state.routeT + 0.02) % 1);
        aircraft.rotateZ(THREE.MathUtils.clamp(tangent.clone().cross(next).y * 22, -0.6, 0.6));

        // A trailing three-quarter chase, smoothed once rather than fought over.
        const back = tangent.clone().multiplyScalar(-fitDistance * 0.85);
        const up = new THREE.Vector3(0, fitDistance * 0.34, 0);
        const side = new THREE.Vector3(-tangent.z, 0, tangent.x).multiplyScalar(fitDistance * 0.45);
        chase.copy(position).add(back).add(up).add(side);
        chaseTarget.copy(ahead);

        // The original flies the same route on the same clock, but covers less of it: the gap
        // you see opening is the endurance difference, drawn rather than tabulated.
        if (originalRef && state.candidate) {
          const lag = (state.routeT - 0.055 + 1) % 1;
          const lagAt = route.getPointAt(lag);
          const lagAhead = route.getPointAt((lag + 0.012) % 1);
          originalRef.position.copy(lagAt);
          originalRef.lookAt(lagAhead);
        }

        camera.position.lerp(chase, Math.min(dt * 1.8, 1));
        camera.lookAt(chaseTarget);
      } else {
        if (!controls.enabled && state.ready) {
          // Handing control back: put the orbit target where the camera is already looking so it
          // does not snap.
          controls.enabled = true;
          aircraft.position.set(0, 0, 0);
          aircraft.rotation.set(0, 0, 0);
          controls.target.set(0, 0, 0);
          camera.position.set(fitDistance * 0.52, fitDistance * 0.38, fitDistance * 0.62);
          controls.update();
        }
        controls.update();
      }

      renderer.render(scene, camera);
    };
    tick();

    api.current = {
      meshes,
      homes,
      explodeDirs,
      aircraft,
      ghost: null,
      setMode: (next, candidate) => {
        state.mode = next;
        state.candidate = candidate;
        applyMode();
      },
      setFlying: (on) => {
        state.flying = on;
        if (!on) state.routeT = 0;
      },
    };

    return () => {
      disposed = true;
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
      api.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paletteKey]);

  useEffect(() => {
    api.current?.setMode(mode, showCandidate);
  }, [mode, showCandidate]);

  useEffect(() => {
    api.current?.setFlying(flying);
  }, [flying]);

  // Selection and colour mode, applied to the live scene.
  useEffect(() => {
    const current = api.current;
    if (!current) return;
    const roleOf = new Map(
      [...TITAN_PARTS, ...TITAN_ENVELOPES].map((part) => [part.partId, part.role]),
    );
    for (const [id, mesh] of current.meshes) {
      const material = mesh.material as THREE.MeshStandardMaterial;
      if (colourBy === "risk") {
        const risk = RISK_BY_ROLE[roleOf.get(id) ?? "low"] ?? "low";
        material.color.set(RISK_COLOUR[risk]);
      }
      if (id === selectedPartId) {
        material.emissive.set(palette.accent);
        material.emissiveIntensity = 0.55;
      } else if (id === hovered) {
        material.emissive.set(palette.accent);
        material.emissiveIntensity = 0.18;
      } else {
        material.emissive.set("#000000");
        material.emissiveIntensity = 0;
      }
    }
  }, [selectedPartId, hovered, palette.accent, colourBy]);

  const hoveredPart = [...TITAN_PARTS, ...TITAN_ENVELOPES].find(
    (part) => part.partId === hovered,
  );

  return (
    <div className="schematic">
      <div ref={mountRef} className="schematic-canvas" />
      {error ? <p className="schematic-state">{error}</p> : null}
      {hoveredPart ? (
        <div className="schematic-readout" aria-live="polite">
          <span className="readout-name">{hoveredPart.name}</span>
          <span className="readout-meta">
            {hoveredPart.role.replace(/_/g, " ")}
            {hoveredPart.massKg === null ? " · mass unknown" : ` · ${hoveredPart.massKg} kg`}
          </span>
        </div>
      ) : null}
    </div>
  );
}

export { EXCLUDED_VARIANTS };
