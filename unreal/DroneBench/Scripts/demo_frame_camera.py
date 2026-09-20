"""Frame the editor viewport on all StaticMeshActors. ExecuteFile. No Content write."""
import json, math, traceback
try:
    import unreal as _ue
except ImportError:
    _ue = None
unreal = _ue if _ue is not None and hasattr(_ue, "Vector") else None
# 3/4 view (-X, +Y, +Z). Distance is 4x max XY AABB size (cm).
_DIR = (-1.0, 1.0, 0.75)
def _xyz(obj, keys=("x", "y", "z")):
    try:
        return {k: float(getattr(obj, k)) for k in keys}
    except Exception:
        return None

def _is_sm(actor):
    try:
        if unreal is not None and isinstance(actor, unreal.StaticMeshActor):
            return True
    except Exception:
        pass
    try:
        return "staticmeshactor" in str(actor.get_class().get_name()).lower()
    except Exception:
        return "staticmeshactor" in type(actor).__name__.lower()

def _actors():
    try:
        # dir(unreal.EditorActorSubsystem)  # get_all_level_actors
        return [a for a in list(unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() or []) if a]
    except Exception:
        return [a for a in list(unreal.EditorLevelLibrary.get_all_level_actors() or []) if a]

def _aabb(actor):
    # dir(unreal.Actor)  # get_actor_bounds
    try:
        origin, box_extent = actor.get_actor_bounds(False)
        o, e = _xyz(origin), _xyz(box_extent)
        if o and e:
            return {k: o[k] - e[k] for k in o}, {k: o[k] + e[k] for k in o}
    except Exception:
        pass
    return None, None
def _union(lo, hi, a, b):
    if a is None or b is None:
        return lo, hi
    if lo is None:
        return dict(a), dict(b)
    return ({k: min(lo[k], a[k]) for k in ("x", "y", "z")}, {k: max(hi[k], b[k]) for k in ("x", "y", "z")})

def _look_at(origin, target):
    dx, dy, dz = target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]
    return unreal.Rotator(math.degrees(math.atan2(dz, math.sqrt(dx * dx + dy * dy))), math.degrees(math.atan2(dy, dx)), 0.0)

def _set_cam(loc, rot):
    # dir(unreal.UnrealEditorSubsystem)  # set_level_viewport_camera_info
    try:
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(loc, rot)
        return True
    except Exception:
        try:
            unreal.EditorLevelLibrary.set_level_viewport_camera_info(loc, rot)
            return True
        except Exception:
            return False

def main():
    out = {"ok": False, "center": None, "extent": None, "camera": None}
    if unreal is None:
        return out
    lo = hi = None
    for actor in _actors():
        if _is_sm(actor):
            lo, hi = _union(lo, hi, *_aabb(actor))
    if not lo or not hi:
        return out
    center = {k: 0.5 * (lo[k] + hi[k]) for k in ("x", "y", "z")}
    extent = {k: hi[k] - lo[k] for k in ("x", "y", "z")}
    dist, ln = 4.0 * max(extent["x"], extent["y"]), math.sqrt(sum(c * c for c in _DIR)) or 1.0
    from_xyz = tuple(center[k] + _DIR[i] / ln * dist for i, k in enumerate(("x", "y", "z")))
    loc, rot = unreal.Vector(*from_xyz), _look_at(from_xyz, (center["x"], center["y"], center["z"]))
    cam = {"location": _xyz(loc), "rotation": _xyz(rot, ("pitch", "yaw", "roll"))}
    if not _set_cam(loc, rot):
        return {**out, "center": center, "extent": extent}
    try:
        info = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_level_viewport_camera_info()
        if info:
            cam = {"location": _xyz(info[0]), "rotation": _xyz(info[1], ("pitch", "yaw", "roll"))}
    except Exception:
        pass
    return {"ok": True, "center": center, "extent": extent, "camera": cam}

try:
    payload = main()
except Exception as exc:
    payload = {"ok": False, "center": None, "extent": None, "camera": None,
               "error": "%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc())}
print(json.dumps(payload, indent=2, default=str), flush=True)

