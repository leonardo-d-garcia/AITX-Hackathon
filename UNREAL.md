# UNREAL.md

Path 2 standing rules. Unreal renders. It does not simulate. R3F remains the shipping fallback.

## Engine (UE 5.8)

- Install: `C:\Program Files\Epic Games\UE_5.8`
- Delivery: Mode A, second window. No Pixel Streaming.
- `.uproject` plugins: `PythonScriptPlugin`, `RemoteControl`, `InterchangeEditor`.
  Do not enable `GLTFImporter` — that name is stale. Interchange owns glTF in 5.8.
- Datasmith CAD is installed and unused. The archive is STL, not STEP/IGES/CATIA.

## Remote Control

- Port `30010` on `127.0.0.1` only. Localhost RCE. Never bind beyond loopback.
- Keys live in `Config/DefaultRemoteControl.ini`. They do nothing in `DefaultEngine.ini`
  (`URemoteControlSettings` is `UCLASS(config = RemoteControl)`).
- Two independent gates, both required:
  `bEnableRemotePythonExecution=True` and
  `+CustomAllowedRemoteFunctionCalls=(ClassPath="/Script/PythonScriptPlugin.PythonScriptLibrary")`.
- In `DefaultEngine.ini`:
  `[/Script/UnrealEd.EditorPerformanceSettings] bThrottleCPUWhenNotForeground=False`.
  Without it the editor crawls while an agent drives it from a terminal.

## Lock

- Only the U-A session may call `tools/ue.py` or port 30010.
- Only U-A writes `Content/`. Binary `.uasset` cannot be merged.
- Never restart the editor. Report the error. Only a human restarts it.
- Introspect before you write. Confirm a method exists with `dir()` before calling it.
- Verify by reading state back, not by absence of an exception.
- No Blueprints. Logic goes in C++ or Python.
- Timeboxes are hard stops.

## Replay

- Unreal replays `simulation_run.json`. No flight dynamics, no aerodynamic forces, no integrators.
- Python replay first. C++ `ATelemetryReplayActor` is stretch.
- Frame conversion NED/FRD metres → Unreal left-handed Z-up centimetres exists in exactly one place:
  `ned_to_ue_cm` / `quat_frd_ned_to_ue` in `packages/sim/frames.py`. Do not duplicate it in Blueprints or Unreal Python.
- Test with a nonzero translation and a non-identity rotation. A right turn must bank right.

## Geometry

- Never fuse or combine the 30 part meshes. Per-part identity is the product.
- Parts are pre-assembled. Import with identity transforms. No combine, no auto-centre, no fit-to-grid.

## Archive unknowns

The print archive has no mass, material, motor, battery, spar tube, or VTOL hardware.
Write null. Never fill an unknown with a plausible number.

## Kill Path 2

Abandon Unreal. Do not debug it. R3F never stopped working.

- Phase 0 gate has not passed after 45 minutes.
- Two writers have touched `Content/` and scene state is unknown.
- Aircraft is inverted after two frame-conversion attempts.
- Anyone has started writing physics inside Unreal.
- Pixel Streaming is attempted or required.
- T−45 min before the demo.

Record a labelled screen capture as soon as the scene looks good.
