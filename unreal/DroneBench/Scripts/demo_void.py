"""Empty editor void + one light. No landscape, sky, hangar, or Content write."""
from __future__ import annotations
import json, math, traceback
try:
    import unreal as _ue
except ImportError:
    _ue = None
unreal = _ue if _ue is not None and hasattr(_ue, "Vector") else None
# Viewport framing only (cm). Imported airframe span is ~222 cm.
CAM_FROM, CAM_AT, LIGHT_LABEL = (-520.0, 410.0, 280.0), (0.0, 0.0, 20.0), "VoidSun"
_AIR = ("fuse", "wing", "titan", "airframe", "vtail", "taileron", "canopy", "motor", "hatch", "aileron")
_CLS_HIDE = ("skyatmosphere", "exponentialheightfog", "skylight", "volumetriccloud", "atmosphericfog", "landscape")
_LAB_HIDE = ("floor", "ground", "airstrip", "hangar", "fog", "cloud", "sky atmosphere", "sky light", "light source", "volumetric")

def _err(errors, where, exc):
    errors.append({"where": where, "type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()})

def _label(actor):
    # dir(actor)  # get_actor_label, get_name
    for name in ("get_actor_label", "get_actor_name", "get_name"):
        fn = getattr(actor, name, None)
        if callable(fn):
            try:
                text = fn()
                if text:
                    return str(text)
            except Exception:
                pass
    return ""

def _class_name(actor):
    try:
        return str(actor.get_class().get_name())
    except Exception:
        return type(actor).__name__

def _blob(actor):
    return (_label(actor) + " " + _class_name(actor)).lower()

def _is_airframe(actor):
    blob = _blob(actor)
    return any(h in blob for h in _AIR)

def _actor_sys():
    # dir(unreal)  # get_editor_subsystem, EditorActorSubsystem
    try:
        return unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    except Exception:
        return None

def _level_actors(errors):
    try:
        sub = _actor_sys()
        if sub is not None:
            # dir(unreal.EditorActorSubsystem)  # get_all_level_actors
            return [a for a in list(sub.get_all_level_actors() or []) if a]
    except Exception as exc:
        _err(errors, "EditorActorSubsystem.get_all_level_actors", exc)
    try:
        return [a for a in list(unreal.EditorLevelLibrary.get_all_level_actors() or []) if a]
    except Exception as exc:
        _err(errors, "EditorLevelLibrary.get_all_level_actors", exc)
        return []

def _hide(actor, errors):
    try:
        # dir(unreal.Actor)  # set_is_temporarily_hidden_in_editor
        actor.set_is_temporarily_hidden_in_editor(True)
    except Exception as exc:
        _err(errors, "hide %s" % _label(actor), exc)
    try:
        actor.set_actor_hidden_in_game(True)
    except Exception:
        pass

def _is_clutter(actor):
    if _is_airframe(actor) or LIGHT_LABEL.lower() in _blob(actor):
        return False
    cls, lab = _class_name(actor).lower(), _label(actor).lower()
    return any(k in cls for k in _CLS_HIDE) or any(k in lab for k in _LAB_HIDE)

def _spawn_light(errors):
    for actor in _level_actors(errors):
        if _label(actor) == LIGHT_LABEL:
            return actor, "already_present"
    cls = getattr(unreal, "DirectionalLight", None)
    if cls is None:
        _err(errors, "DirectionalLight", RuntimeError("not in dir(unreal)"))
        return None, "missing_class"
    loc = unreal.Vector(0.0, 0.0, 400.0)
    # stub Rotator.__init__(roll, pitch, yaw) — keywords only
    rot = unreal.Rotator(pitch=-50.0, yaw=35.0, roll=0.0)
    try:
        sub = _actor_sys()
        # dir(unreal.EditorActorSubsystem)  # spawn_actor_from_class
        # stub actor_class is UClass; Python type needs static_class()
        uclass = cls.static_class() if hasattr(cls, "static_class") else cls
        try:
            actor = sub.spawn_actor_from_class(uclass, loc, rot) if sub else unreal.EditorLevelLibrary.spawn_actor_from_class(uclass, loc, rot)
        except Exception:
            actor = sub.spawn_actor_from_class(cls, loc, rot) if sub else unreal.EditorLevelLibrary.spawn_actor_from_class(cls, loc, rot)
        if actor is None:
            raise RuntimeError("spawn returned None")
        try:
            actor.set_actor_label(LIGHT_LABEL, False)
        except Exception:
            pass
        light = getattr(actor, "light_component", None)
        if light is None:
            getter = getattr(actor, "get_editor_property", None)
            if callable(getter):
                for name in ("light_component", "directional_light_component"):
                    try:
                        light = getter(name)
                    except Exception:
                        light = None
                    if light is not None:
                        break
        mobility = getattr(getattr(unreal, "ComponentMobility", None), "MOVABLE", None)
        if light is not None and mobility is not None:
            try:
                light.set_mobility(mobility)
            except Exception:
                pass
        return actor, "created"
    except Exception as exc:
        _err(errors, "spawn DirectionalLight", exc)
        return None, "failed"

def _look_at(origin, target):
    dx, dy, dz = target[0] - origin[0], target[1] - origin[1], target[2] - origin[2]
    pitch = math.degrees(math.atan2(dz, math.sqrt(dx * dx + dy * dy)))
    yaw = math.degrees(math.atan2(dy, dx))
    return unreal.Rotator(pitch=pitch, yaw=yaw, roll=0.0)

def _xyz(obj, keys=("x", "y", "z")):
    try:
        return {k: float(getattr(obj, k)) for k in keys}
    except Exception:
        return None

def _set_camera(errors):
    loc, rot = unreal.Vector(*CAM_FROM), _look_at(CAM_FROM, CAM_AT)
    try:
        # dir(unreal.UnrealEditorSubsystem)  # set_level_viewport_camera_info
        unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).set_level_viewport_camera_info(loc, rot)
    except Exception as exc:
        _err(errors, "UnrealEditorSubsystem.set_level_viewport_camera_info", exc)
        try:
            unreal.EditorLevelLibrary.set_level_viewport_camera_info(loc, rot)
        except Exception as extra:
            _err(errors, "EditorLevelLibrary.set_level_viewport_camera_info", extra)
            return None
    try:
        info = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_level_viewport_camera_info()
        if info:
            return {"location": _xyz(info[0]), "rotation": _xyz(info[1], ("pitch", "yaw", "roll"))}
    except Exception:
        pass
    return {"location": _xyz(loc), "rotation": _xyz(rot, ("pitch", "yaw", "roll"))}

def main():
    result = {"ok": False, "actors": [], "camera": None, "errors": []}
    errors = result["errors"]
    if unreal is None:
        errors.append({"where": "import", "error": "unreal editor APIs missing"})
        return result
    if not any(_is_airframe(a) for a in _level_actors(errors)):
        try:
            # Unsaved untitled map. Do not call new_level(/Game/...) — that writes Content/.
            # dir(unreal.EditorLoadingAndSavingUtils)  # new_blank_map
            unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
        except Exception as exc:
            _err(errors, "EditorLoadingAndSavingUtils.new_blank_map", exc)
    for actor in list(_level_actors(errors)):
        if not _is_clutter(actor):
            continue
        _hide(actor, errors)
        if "landscape" in _class_name(actor).lower():
            try:
                sub = _actor_sys()
                (sub.destroy_actor(actor) if sub else actor.destroy_actor())
            except Exception as exc:
                _err(errors, "destroy landscape", exc)
    light, how = _spawn_light(errors)
    for actor in list(_level_actors(errors)):
        if "directionallight" in _class_name(actor).lower() and _label(actor) != LIGHT_LABEL:
            _hide(actor, errors)
    result["camera"] = _set_camera(errors)
    result["actors"] = [{"label": _label(a), "class": _class_name(a)} for a in _level_actors(errors)]
    result["light"] = how
    result["ok"] = light is not None and result["camera"] is not None
    return result

try:
    payload = main()
except Exception as exc:
    payload = {"ok": False, "actors": [], "camera": None, "errors": [{"where": "main", "type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()}]}
print(json.dumps(payload, indent=2, default=str), flush=True)
