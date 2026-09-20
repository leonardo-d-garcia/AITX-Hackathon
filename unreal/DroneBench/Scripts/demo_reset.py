"""Reset Titan to origin, slower -Y loop, side camera. Uses Public-scope demo_forward state."""

from __future__ import annotations

import json

import unreal

# Public scope from the previous ExecuteFile of demo_forward.py
try:
    stop()
except Exception:
    pass

SPEED_CM_S = 80.0
LOOP_S = 8.0

sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
root = None
for actor in sub.get_all_level_actors():
    if actor.get_actor_label() == "titan_avenger_scene_0":
        root = actor
        break
if root is not None:
    root.set_actor_location(unreal.Vector(0.0, 0.0, 0.0), False, True)

try:
    _STATE["t"] = 0.0
    _bind()
    start()
    playing = True
except Exception as exc:
    playing = False
    err = str(exc)
else:
    err = None

ues = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
cam = unreal.Vector(520.0, -280.0, 180.0)
target = unreal.Vector(0.0, -280.0, 20.0)
ues.set_level_viewport_camera_info(cam, unreal.MathLibrary.find_look_at_rotation(cam, target))

loc = None
if root is not None:
    v = root.get_actor_location()
    loc = {"x": v.x, "y": v.y, "z": v.z}

print(
    json.dumps(
        {
            "ok": root is not None and playing,
            "script": "demo_reset.py",
            "location": loc,
            "speed_cm_s": SPEED_CM_S,
            "error": err,
        },
        indent=2,
    )
)
