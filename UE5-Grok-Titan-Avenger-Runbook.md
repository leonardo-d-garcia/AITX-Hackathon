# UE5 × Grok — Titan Avenger demo runbook

DroneBench Lane C. Revised 2026-09-19 with the measured contents of `Titan_Avenger__Fixed_Wing___VTOL_on_Profile___1_.zip`. Supersedes `UE5-Grok-Integration-Runbook.md`.

Everything in §2 was measured from the archive directly, not inferred. Section 2.6 lists what the archive does **not** contain, which matters more than what it does.

---

## 0. Three rules. Violating any of them costs you the project.

**Rule 1 — exactly one agent may talk to port 30010.** The editor is a single process with a single Python interpreter. Two agents POSTing concurrently interleave mid-script and half-build the scene. Editor access is a lock with one holder.

**Rule 2 — only the editor-lane agent may touch `Content/`.** `.uasset` files are binary and cannot be merged. Two branches that both modified a level produce a conflict with no resolution except picking one and losing the other.

**Rule 3 — never restart the editor to clear an error.** Report it. Only a human restarts.

**Rule 4 (new, from the archive) — never fuse the parts.** The demo's entire value is per-part identity. The moment anything merges 30 occurrences into one mesh, picking dies, the heatmap dies, and the Supabase write-back has nothing to key on.

---

## 1. Phase 0 — serial bootstrap

One agent, no parallelism, 25 minutes. Nothing else starts until the gate passes.

### 1.1 Engine and plugins

```bash
ls "C:/Program Files/Epic Games/" | grep UE_
ls "C:/Program Files/Epic Games/UE_5.x/Engine/Plugins/" -R | grep -i -E "python|remotecontrol|gltf|interchange"
```

Enable in the `.uproject` (JSON, so edit it directly — verify folder names against the output above, they drift between versions):

```json
{
  "Plugins": [
    { "Name": "PythonScriptPlugin", "Enabled": true },
    { "Name": "RemoteControl", "Enabled": true },
    { "Name": "GLTFImporter", "Enabled": true },
    { "Name": "InterchangeEditor", "Enabled": true }
  ]
}
```

**Datasmith is not needed for this archive.** The Datasmith CAD importer handles STEP/IGES/CATIA. This archive is 24 binary STLs, and STL is not a native Unreal import format at all. §2.7 covers the conversion.

### 1.2 Config

`Config/DefaultRemoteControl.ini` — a separate file on purpose; `URemoteControlSettings` is `UCLASS(config = RemoteControl)`, so these keys do nothing in `DefaultEngine.ini`:

```ini
[/Script/RemoteControlCommon.RemoteControlSettings]
bAutoStartWebServer=True
bAutoStartWebSocketServer=True
RemoteControlHttpServerPort=30010
bEnableRemotePythonExecution=True
bAllowAnyRemoteFunctionCall=False
+CustomAllowedRemoteFunctionCalls=(ClassPath="/Script/PythonScriptPlugin.PythonScriptLibrary")
bAllowConsoleCommandRemoteExecution=False
```

`bEnableRemotePythonExecution` and the allowed-call entry are two independent gates that fail with different errors.

Append to `Config/DefaultEngine.ini`:

```ini
[/Script/UnrealEd.EditorPerformanceSettings]
bThrottleCPUWhenNotForeground=False

[/Script/PythonScriptPlugin.PythonScriptPluginSettings]
bDeveloperMode=True
```

Without the throttle setting the editor crawls the entire time an agent drives it from a terminal.

### 1.3 Client

`tools/ue.py`:

```python
import sys, json, requests
ENDPOINT = "http://127.0.0.1:30010/remote/object/call"

def run(code: str, timeout: int = 180):
    r = requests.put(ENDPOINT, timeout=timeout, json={
        "objectPath": "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
        "functionName": "ExecutePythonCommandEx",
        "parameters": {"PythonCommand": code,
                       "ExecutionMode": "ExecuteFile",
                       "FileExecutionScope": "Public"},
    })
    r.raise_for_status()
    return r.json()

if __name__ == "__main__":
    print(json.dumps(run(sys.stdin.read()), indent=2))
```

### 1.4 GATE — both must pass

```bash
echo "import unreal; print(unreal.SystemLibrary.get_engine_version())" | python tools/ue.py
echo "import unreal; print([m for m in dir(unreal.EditorActorSubsystem) if not m.startswith('_')])" | python tools/ue.py
```

The second gate matters more than it looks. Once the agent can introspect the `unreal` API it stops writing method names from memory, which is otherwise the dominant failure mode.

---

## 2. The aircraft — measured spec

### 2.1 Archive inventory

24 binary STL files, **580,404 triangles**, 11,241,502 compressed / 29,022,216 uncompressed bytes. All 24 declared triangle counts match their file lengths exactly. That is a format check, not a manifoldness or assembly check.

Per-part bounds, volumes, and hashes are in the companion `titan_avenger_inventory.json`.

### 2.2 The parts are already assembled

This is the finding that saves you an hour. The STLs are **not** each sitting at the origin — they are pre-positioned in a shared coordinate system, and the seams are exact:

- Wing segments tile in X at **70.00 → 308.09 → 548.09 → 788.09 → 1028.09 → 1112.25**
- Fuselage sections butt in Y at **−403.07 → −230.0 → 10.0 → 250.0 → 490.0 → 588.18**
- Canopy sections tile at −352.9 → −230.0 → −109.2; hatches at 135.3 → 250.0 → 365.6

Import every part with an identity transform and the aircraft assembles itself. Do not write assembly logic. Do not let the agent "helpfully" center parts on import — that destroys the assembly.

### 2.3 Native frame

Native units are **millimetres**. Axes, confirmed against the geometry:

| Axis | Meaning | Evidence |
|---|---|---|
| X | Spanwise, one side only | Wings run 70 → 1112.25; fuselage symmetric about X=0 (−82.4 to +82.4) |
| Y | Longitudinal, **increases aft** | Nose at −403.07; motor mount at +588.2 to +598.3 |
| Z | Vertical, up | Canopy sits at Z 17.9–77.3 above fuselage Z −43.4 to +43.4 |

Global bounds: X −82.37 → 1112.25, Y −403.07 → 598.27, Z −43.43 → 151.11.

Derived: **span 2.2245 m**, **fuselage length 0.9913 m**. The motor mount at the extreme aft end means this is a **pusher** configuration.

Because the frame is right-handed with Y aft and Z up, positive native X is the aircraft's **left** side. That is a hypothesis worth one look in the viewer; it only matters for asymmetric parts like the belly camera.

### 2.4 Wing planform — measured, and remarkably clean

| Segment | X span (mm) | LE (mm) | TE (mm) | Chord (mm) | Max thickness | Projected planform (mm²) |
|---|---|---|---|---|---|---|
| wing1 | 70.00 – 308.09 | 3.6 | 217.5 | 213.9 | 31.7 | 62,753 |
| wing2 | 308.09 – 548.09 | 16.1 | 209.2 | 193.1 | 26.8 | 57,599 |
| wing3 + aileron | 548.09 – 788.09 | 28.7 | 200.8 | 172.1 | 22.5 | 42,777 |
| wing4 | 788.09 – 1028.09 | 41.3 | 192.4 | 151.2 | 18.2 | 36,120 |
| wing5 | 1028.09 – 1112.25 | 53.9 | 184.1 | 130.2 | 13.9 | 10,690 |

The taper is **linear**: chords step 213.9 → 193.1 → 172.1 → 151.2 → 130.2, a uniform −20.9 mm per 240 mm segment. The leading edge steps +12.55 mm per segment, giving **≈2.99° leading-edge sweep**. Extrapolating to centreline gives a root chord of **220.0 mm** with the leading edge at Y ≈ 0.

Chord law: `c(x) = 220.0 − 0.0871·x` mm, for x in mm from centreline.

Measured exposed planform (both sides, projected): **0.4199 m²**, giving **AR ≈ 11.8**. Note this excludes carry-through area inside the fuselage — declare your reference area convention once, in one place, per the architecture doc's rule, and never set it twice.

The 240 mm segment length is a print-bed constraint, not an aerodynamic one.

### 2.5 V-tail

| Part | X | Y | Z |
|---|---|---|---|
| vtail1 | 49.6 – 254.6 | 428.4 – 536.6 | 5.8 – 132.7 |
| vtail2 | 249.8 – 289.3 | 477.3 – 570.5 | 124.4 – 151.1 |
| taileron | 50.2 – 253.3 | 535.2 – 578.5 | 10.9 – 132.3 |

Panel spans 239.7 mm in X while rising 145.3 mm in Z, giving a **cant of 31.2° from horizontal**. Two canted panels, as the architecture doc warned — conventional horizontal-plus-vertical tail heuristics do not apply here and must return `not_applicable`, never `fail`.

Tail arm from wing quarter-chord (Y ≈ 55) to V-tail quarter-chord (Y ≈ 455) is **≈0.40 m**.

### 2.6 Two things in this archive that hand you the demo

**The spar edit is already modelled.** `wing3` exists in three variants: `wing3_12mm_hole`, `wing3_16mm_hole`, and `wing3_no_hole`. The hole is the spar pass-through. Your architecture doc's `resize_spar` operation — 12 mm spar to 16 mm spar — has **real CAD geometry for both the before and the after state**, sitting in the archive right now. You do not have to reconstruct anything to demo that edit. Swap the mesh, regenerate the spar tube, recompute `I = π(Do⁴−Di⁴)/64`, and the heatmap changes for a reason the judges can inspect.

**Control surfaces are separate parts.** `aileron` (X 548.09–788.09, at wing3's station) and `taileron` (on the V-tail) are independent meshes. In the flyover you can deflect actual geometry from the autopilot's δa and δe outputs instead of animating a rigid model. A visibly deflecting aileron during the spiral is worth more than another postprocessing effect.

### 2.7 What the archive does not contain

State these as unknown in the UI. Do not let any agent fill them in.

- **No mass, density, material, or infill for any part.** The folder named `High Temp PETG or ABS or ASA` is evidence of a *suggestion*, not proof of what was used. Volume is not mass.
- **No motor, battery, ESC, servos, spar, avionics, or wiring.** A motor *mount* exists; no motor does.
- **No STEP, no feature history, no BOM, no assembly manifest, no mission profile.**
- **No airfoil identification.** Do not claim a UIUC match from a printed hollow section.
- **No license document.** Keep the original archive out of any public repository until reuse terms are established.
- **Nothing VTOL** despite the filename. There are no rotor booms, no lift motors, no tilt mechanism. It is a fixed-wing pusher. Do not let the filename's "VTOL on Profile" put a claim on your slide.

### 2.8 Variant decisions — required before import

Two choices must be made explicitly and recorded, or the aircraft double-counts mass and overlaps geometry:

| Group | Variants | Pick |
|---|---|---|
| `wing3` | `_12mm_hole`, `_16mm_hole`, `_no_hole` | **`_12mm_hole` as baseline.** `_16mm_hole` is the post-edit state for the spar demo. |
| `fuse3` | `fuse3`, `fuse3_belly_cam`, `fuse3_clean` | **`fuse3_clean` as baseline** unless the demo needs a payload story, then `fuse3_belly_cam`. |

Excluded alternates account for 106,066 triangles that must **not** be in the scene.

### 2.9 Installed set

| Group | Definitions | Occurrences | Triangles |
|---|---|---|---|
| Centreline (fuse1–5, canopy1–2, hatch1–2, motor_mount) | 10 | 10 | 341,118 |
| Mirrored (wing1–5, aileron, wing_bay_plate, vtail1–2, taileron) | 10 | 20 | 266,440 |
| **Installed total** | **20** | **30** | **607,558** |

607k triangles is nothing for UE5. Do not decimate; you have the budget.

Mirroring is about the X=0 plane: negate native X, **flip triangle winding**, then place. A reflection is not a rotation — if the agent applies a mirror as a transform without repairing winding, the mirrored wing renders inside-out and lights wrong.

### 2.10 Part ID scheme

```
fuse_1 … fuse_5, canopy_1, canopy_2, hatch_1, hatch_2, motor_mount
wing_1_L … wing_5_L, aileron_L, wing_bay_plate_L
wing_1_R … wing_5_R, aileron_R, wing_bay_plate_R
vtail_1_L, vtail_2_L, taileron_L
vtail_1_R, vtail_2_R, taileron_R
```

30 IDs. These are the keys for actor tags, the Supabase `part_result` rows, and the heatmap lookup. They must match whatever Lane A emits — confirm, do not assume.

### 2.11 STL → glTF conversion (Lane U-D owns this)

Unreal does not import STL. Convert to a single GLB with named nodes and let UE's glTF importer handle the handedness conversion. glTF is right-handed, Y-up, metres.

```python
# Scripts/convert_titan.py  —  runs OUTSIDE Unreal
import numpy as np, trimesh

Y_DATUM = 55.0   # mm, wing quarter-chord at centreline -> actor pivot near CG

def to_gltf(v_mm):
    """native mm (X=span/left, Y=aft, Z=up) -> glTF m (X=right, Y=up, Z=back)"""
    return np.column_stack([
        -v_mm[:, 0] / 1000.0,              # right  = -native X
         v_mm[:, 2] / 1000.0,              # up     =  native Z
        (v_mm[:, 1] - Y_DATUM) / 1000.0,   # back   =  native Y - datum
    ])

CENTRE = ["fuse1","fuse2","fuse3_clean","fuse4","fuse5",
          "canopy1","canopy2","hatch1","hatch2","motor_mount"]
MIRROR = ["wing1","wing2","wing3_12mm_hole","wing4","wing5",
          "aileron","wing_bay_plate","vtail1","vtail2","taileron"]

scene = trimesh.Scene()
for stl_path, part_id, mirror in plan():          # plan() yields the 30 occurrences
    m = trimesh.load(stl_path, process=False)     # process=False preserves triangles
    m.vertices = to_gltf(np.asarray(m.vertices))
    if mirror:
        m.vertices[:, 0] *= -1.0                  # reflect across centreline
        m.invert()                                # REPAIR WINDING — do not skip
    scene.add_geometry(m, node_name=part_id, geom_name=part_id)

scene.export("titan_avenger.glb")
```

Two things that will bite: `process=False` stops trimesh from merging vertices and silently changing triangle counts, and `invert()` after a reflection is mandatory or half the aircraft renders inside-out.

Verify after import, in this order: **30 actors**, **607,558 total triangles**, span ≈ 2.22 m, fuselage ≈ 0.99 m, canopy above the fuselage, motor mount at the aft end.

---

## 3. Lane map

| Lane | Owns | Editor? | `Content/`? | Blocks on |
|---|---|---|---|---|
| **U-A · Editor** | live scene, import, tagging, materials | **Exclusive :30010** | Yes, exclusively | Phase 0 |
| **U-B · C++** | `Source/**` | No | No | Phase 0 |
| **U-C · Scripts** | `Scripts/**` Python | No | No | Phase 0 |
| **U-D · Data** | GLB conversion, telemetry, part_map, LUT | No | No | **Nothing — start now** |
| **U-E · Harness** | `tools/`, verification, `UNREAL.md` | No | No | Phase 0 |

U-C writes Python scripts; U-A executes them. Separating authoring from execution is what makes this parallel at all.

---

## 4. Phase 1 — task blocks

### Lane U-D — start immediately, needs no Unreal

```
LANE U-D — DATA. Begin now, do not wait for Phase 0.

TASK D1 — Convert the Titan archive to titan_avenger.glb per runbook 2.11.
- 30 occurrences, exact part IDs from 2.10.
- Baseline variants: wing3_12mm_hole, fuse3_clean. EXCLUDE the other four
  alternates (106,066 triangles that must not appear).
- Mirror about X=0 with winding repair.
- Identity placement otherwise: the parts are ALREADY assembled. Do not
  centre, do not re-origin, do not auto-fit.
VERIFY and print: node count (expect 30), total triangles (expect 607,558),
overall bounding box in metres (expect span ~2.2245, length ~0.9913).
If any number differs, report it. Do not "fix" it silently.

TASK D2 — Also export titan_avenger_16mm.glb with wing3_16mm_hole in place
of wing3_12mm_hole, both sides. This is the post-edit state for the spar demo.

TASK D3 — part_map.json keyed by the 30 part IDs. Mass, material and density
are UNKNOWN in this archive — write null, never a guess. Include per-part
triangle count, volume in mm3 and bounding box from titan_avenger_inventory.json.

TASK D4 — simulation_run.json, one baked 60-second flight: straight, climb,
coordinated turn with load factor visibly above 1. Schema per Lane C.

TASK D5 — colormap LUT, 256x1 PNG, viridis or turbo. Not rainbow.
```

### Lane U-A — editor (exclusive lock)

```
LANE U-A — UNREAL EDITOR. You alone may call tools/ue.py or port 30010.
Never restart the editor. Introspect with dir() before writing any API call.

TASK A1 — Import titan_avenger.glb.
Import with transforms PRESERVED. The parts are pre-assembled; any "combine
meshes", "auto-centre" or "fit to grid" option destroys the assembly. Leave
them off.
VERIFY: print every actor label and world transform. Confirm 30 actors.
Confirm the aircraft is ~222 cm across in UE units, not 2.2 cm or 22 m.
Confirm the canopy is ABOVE the fuselage and the motor mount is at the AFT
end. If the aircraft is mirrored or inside-out, report it — do not flip
things until it looks right.

TASK A2 — Tag parts. Execute Scripts/tag_parts.py.
VERIFY: count of tagged actors (expect 30) and 5 sample (label, tag) pairs.
Report ANY untagged actor by name. Untagged parts break picking silently.

TASK A3 — Heatmap material. Execute Scripts/build_heatmap_material.py.
Creates the colormap material and a Material Parameter Collection with a
scalar LoadFactor.
VERIFY: set LoadFactor to 1.0, read it back, print. Set to 3.5, read back,
print. If readback does not match, stop and report.

TASK A4 — Scene. Execute Scripts/build_scene.py — landscape, airstrip,
hangar, lighting, camera rig. Keep the playable area small.
VERIFY: actor count by class. Screenshot to D:/tmp/scene.png for a HUMAN to
inspect. Do not interpret the screenshot yourself.

TASK A5 — Spar swap. Import titan_avenger_16mm.glb as a second variant and
wire a toggle that swaps the four wing3 meshes (L and R) between variants.
VERIFY: toggle both ways, print which mesh each wing3 actor is using.

Report between every task. Commit Content/ after each. You are its only writer.
```

### Lane U-B — C++

```
LANE U-B — SOURCE ONLY. Do not call tools/ue.py. Do not touch Content/.
Do not compile — the running editor holds the DLLs. Builds happen at Sync 2.

TASK B1 — ATelemetryReplayActor.
- Loads simulation_run.json at BeginPlay, path as UPROPERTY.
- ONE frame-conversion function, existing in exactly one place in the codebase.
- Interpolates position and attitude between frames. No snapping.
- Exposes load_factor_n as BlueprintReadOnly, pushed to the MPC each tick.
- Playback: play, pause, scrub, 0.5x/1x/2x.

DO NOT implement flight dynamics. DO NOT compute aerodynamic forces. This
actor replays telemetry. If you find yourself writing an integrator, stop.

TASK B2 — Control surface deflection. The archive has aileron and taileron
as separate parts (runbook 2.6). Rotate aileron_L/R about their hinge line
from the telemetry's delta_a, and taileron_L/R from delta_e. Hinge axis runs
spanwise; derive it from the part bounds, do not hardcode a guess.

TASK B3 — Part picking. Line trace under cursor, read the actor tag, POST the
part_id to the FastAPI backend. NEVER put Supabase credentials in Unreal.

TASK B4 — Test the frame conversion with a nonzero translation AND a
non-identity rotation. A right turn must bank right. Runs without the editor.
```

### Lane U-C — Python scripts

```
LANE U-C — SCRIPTS ONLY, written to Scripts/. Do not execute them.

  Scripts/tag_parts.py             — apply the 30 part IDs as actor tags
  Scripts/build_heatmap_material.py — colormap material + MPC scalar LoadFactor
  Scripts/build_scene.py           — landscape, airstrip, hangar, lights, cameras
  Scripts/verify_scene.py          — actor counts, tags, transforms as JSON

RULES:
- Each script prints a JSON summary. U-A's only verification is your output,
  so print counts, names and numbers, never "done".
- Each script is idempotent. Check before creating.
- You cannot test these, so wrap each operation in try/except and print the
  exception with context rather than dying halfway and leaving the scene in
  an unknown state.
- Where unsure of an API name, write the dir() introspection call as a comment
  above the line so U-A can verify it.

The heatmap material maps a normalised stress scalar through the LUT from
Lane U-D. Stress comes from Lane C's structure model — 21 spanwise stations,
sigma = M(Do/2)/I. Do NOT compute stress in Unreal.
```

### Lane U-E — harness

```
LANE U-E — TOOLING. Do not call tools/ue.py while U-A is working.

E1 — Harden tools/ue.py: clear errors on connection refused ("is the editor
running?"), on 403 (name which gate in DefaultRemoteControl.ini), on timeout.
Add --file to execute a script from disk.
E2 — Write UNREAL.md at repo root from runbook section 6.
E3 — tools/smoke.sh: engine version, plugin state, actor count (expect 30),
MPC readback. One command, nonzero exit on failure.
```

---

## 5. Sync points

**Sync 1 — after D1 and A1.** Did 30 named actors arrive at the right scale and orientation? If node names were mangled in conversion, tagging changes approach and U-C rewrites `tag_parts.py`. Do not let U-A proceed to A2 on bad geometry.

**Sync 2 — first C++ build.** U-A saves and closes the editor. A human runs:

```bash
"C:/Program Files/Epic Games/UE_5.x/Engine/Build/BatchFiles/Build.bat" \
  DroneBenchEditor Win64 Development \
  -project="D:/path/to/DroneBench.uproject" -waitmutex
```

Reopen; U-A resumes. Later C++ changes can use Live Coding, but the first build must be cold because that is when new classes register.

**Sync 3 — integration.** Replay actor in the built scene, telemetry loaded, heatmap tracking load factor, ailerons deflecting. Verify by watching: a right turn banks right.

---

## 6. Standing rules for `UNREAL.md`

```
Only the U-A session may call tools/ue.py or port 30010.
Only U-A writes to Content/. Binary .uasset cannot be merged.
Never restart the editor. Report the error. Only a human restarts it.
Introspect before you write. Confirm a method exists with dir() before calling it.
Verify by reading state back, not by absence of an exception.

Unreal renders. It does not simulate. No flight dynamics, no aerodynamic
forces, no integrators in Unreal. It replays simulation_run.json.

Never fuse or combine the 30 part meshes. Per-part identity is the product.

The archive has no mass, no material, no motor, no battery, no spar and no
VTOL hardware. Write null. Never fill an unknown with a plausible number.

No Blueprints. Logic goes in C++ or Python.
Port 30010 is localhost RCE. Never expose it beyond 127.0.0.1.
Timeboxes are hard stops.
```

---

## 7. Failure playbook

| Symptom | Cause | Action |
|---|---|---|
| Connection refused on 30010 | Editor down, or web server didn't start | Check Output Log for the listening line; confirm keys are in `DefaultRemoteControl.ini`, not `DefaultEngine.ini` |
| 403 / function not allowed | One of the two gates | Check `bEnableRemotePythonExecution` **and** the allowed-call entry separately |
| Aircraft in pieces, scattered | Something re-origined parts on import | Turn off combine/auto-centre; the archive is pre-assembled |
| Aircraft mirrored or inside-out | Reflection applied without winding repair | `invert()` after negating X in the converter |
| Aircraft 100× or 1/100 scale | mm/m/cm confusion | glTF is metres; UE is cm; the importer converts. Check span ≈ 222 cm |
| Triangle count ≠ 607,558 | An alternate variant got included, or trimesh merged vertices | Check for the four excluded alternates; use `process=False` |
| Clicking a part returns nothing | Untagged actor, or meshes were fused | A2's untagged report; Rule 4 |
| Editor crawls | CPU throttling | `bThrottleCPUWhenNotForeground=False` |
| "Modules cannot be compiled at runtime" | Editor holds the DLLs | Cold build at Sync 2 |

---

## 8. Kill criteria

Abandon the Unreal path, do not debug it, if:

- Phase 0's gate hasn't passed after 45 minutes.
- Two lanes have both written to `Content/` and scene state is unknown.
- Anyone has started writing physics inside Unreal.
- Less than 45 minutes remain before the demo.

Abandoning costs nothing because R3F never stopped working. The moment the Unreal scene looks good, record it. A labelled recording survives a crash on stage; nothing else does.

---

## 9. What the demo may claim

The archive supports: real printed-part geometry, a genuine 2.2245 m span, a measured linear-taper planform, a real 31.2° V-tail, and a spar-diameter change with actual CAD for both states.

It does not support: any mass, any material, any propulsion or battery claim, any VTOL capability, airworthiness, validated flight dynamics, or a physical bench test.

Say it plainly: measured geometry from the supplied archive, a reduced-order mission model with vortex-lattice aerodynamics where a real run exists, rendered in a game engine. Every part of that sentence is defensible, and it is a stronger claim than most of the room will be able to make.
