"""Editor utility: small hangar pad for DroneBench. Not an open world.

Idempotent — match by actor label, create only if missing.
Does not import the aircraft. Does not write physics / simulate.
Prints a JSON summary (actor counts by class, never a bare "done").
"""

from __future__ import annotations

import json
import math
import sys
import traceback

try:
    import unreal
except ImportError as exc:
    print(
        json.dumps(
            {
                "ok": False,
                "script": "build_scene.py",
                "errors": ["import unreal: {}: {}".format(type(exc).__name__, exc)],
                "actor_counts_by_class": {},
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    raise SystemExit(1)


# Visual layout only (Unreal units = cm). Not aerodynamic / mass properties.
CUBE_NATIVE_CM = 100.0
GROUND_CM = (1000.0, 1000.0, 10.0)  # 10 m x 10 m x 10 cm pad
AIRSTRIP_CM = (900.0, 300.0, 4.0)
HANGAR_CM = (500.0, 400.0, 280.0)
CHASE_ARM_CM = 500.0
FOLDER = "DroneBench/Scene"

LABEL_GROUND = "AirstripGround"
LABEL_STRIP = "Airstrip"
LABEL_HANGAR = "Hangar"
LABEL_CAM = "ChaseCam"
LABEL_SUN = "SceneSun"
LABEL_SKY_ATMO = "SkyAtmosphere"
LABEL_SKY_LIGHT = "SkyLight"

REQUIRED_LABELS = (LABEL_GROUND, LABEL_STRIP, LABEL_HANGAR, LABEL_CAM)

CUBE_PATHS = (
    "/Engine/BasicShapes/Cube.Cube",
    "/Engine/BasicShapes/Cube",
    "/Engine/EngineMeshes/Cube.Cube",
)

_ERRORS = []
_CREATED = []
_ALREADY = []
_NOTES = []


def _log_error(context, exc):
    msg = "{}: {}: {}".format(context, type(exc).__name__, exc)
    _ERRORS.append(msg)
    try:
        unreal.log_warning("[build_scene] " + msg)
    except Exception:
        print(msg, file=sys.stderr, flush=True)


def _note(msg):
    _NOTES.append(msg)


def _ue_cls(*names):
    """First matching attribute on unreal, else None. dir(unreal) for names."""
    # dir(unreal)
    for name in names:
        cls = getattr(unreal, name, None)
        if cls is not None:
            return cls
    return None


def _has_attr(obj, name):
    try:
        return obj is not None and hasattr(obj, name)
    except Exception:
        return False


def _api_probe():
    names = (
        "EditorActorSubsystem",
        "EditorLevelLibrary",
        "EditorAssetLibrary",
        "StaticMeshActor",
        "DirectionalLight",
        "SkyAtmosphere",
        "SkyLight",
        "ExponentialHeightFog",
        "AtmosphericFog",
        "VolumetricCloud",
        "Landscape",
        "CameraActor",
        "CineCameraActor",
        "SpringArmComponent",
        "CameraComponent",
        "Actor",
    )
    # dir(unreal)
    return {n: getattr(unreal, n, None) is not None for n in names}


def _actor_subsystem():
    # dir(unreal)  # get_editor_subsystem, EditorActorSubsystem
    getter = getattr(unreal, "get_editor_subsystem", None)
    cls = _ue_cls("EditorActorSubsystem")
    if getter is None or cls is None:
        return None
    try:
        return getter(cls)
    except Exception as exc:
        _log_error("get_editor_subsystem(EditorActorSubsystem)", exc)
        return None


_ACTOR_SYS_CACHE = []


def _actor_sys():
    if _ACTOR_SYS_CACHE:
        return _ACTOR_SYS_CACHE[0]
    subsystem = _actor_subsystem()
    _ACTOR_SYS_CACHE.append(subsystem)
    return subsystem


def _is_valid(obj):
    if obj is None:
        return False
    try:
        fn = getattr(unreal, "is_valid", None)
        if callable(fn):
            return bool(fn(obj))
    except Exception:
        pass
    try:
        if _has_attr(obj, "is_valid"):
            return bool(obj.is_valid())
    except Exception:
        return False
    return True


def _iter_level_actors():
    actors = None
    try:
        actor_sys = _actor_sys()
        if actor_sys is not None:
            # dir(unreal.EditorActorSubsystem)  # get_all_level_actors
            actors = actor_sys.get_all_level_actors()
        elif _has_attr(unreal, "EditorLevelLibrary"):
            # dir(unreal.EditorLevelLibrary)  # get_all_level_actors
            actors = unreal.EditorLevelLibrary.get_all_level_actors()
    except Exception as exc:
        _log_error("get_all_level_actors", exc)
        return
    if not actors:
        return
    for actor in actors:
        if _is_valid(actor):
            yield actor


def _label_of(actor):
    try:
        if _has_attr(actor, "get_actor_label"):
            return str(actor.get_actor_label())
    except Exception:
        pass
    try:
        if _has_attr(actor, "get_name"):
            return str(actor.get_name())
    except Exception:
        pass
    return ""


def _class_name(obj):
    try:
        if _has_attr(obj, "get_class"):
            cls = obj.get_class()
            if _has_attr(cls, "get_name"):
                return str(cls.get_name())
    except Exception:
        pass
    try:
        return type(obj).__name__
    except Exception:
        return "Unknown"


def _find_by_label(label):
    for actor in _iter_level_actors():
        if _label_of(actor) == label:
            return actor
    return None


def _set_prop(obj, name, value, context, required=False):
    if obj is None:
        return False

    def _fail(exc):
        msg = "{} set {} failed: {}".format(context, name, exc)
        if required:
            _log_error("{} set_editor_property({})".format(context, name), exc)
        else:
            _note(msg)

    try:
        if _has_attr(obj, "set_editor_property"):
            obj.set_editor_property(name, value)
            return True
    except Exception as exc:
        _fail(exc)
    try:
        setattr(obj, name, value)
        return True
    except Exception as exc:
        _fail(exc)
        return False


def _set_label(actor, label):
    try:
        if _has_attr(actor, "set_actor_label"):
            actor.set_actor_label(label)
    except Exception as exc:
        _log_error("set_actor_label({})".format(label), exc)
    try:
        if _has_attr(actor, "set_folder_path"):
            actor.set_folder_path(FOLDER)
    except Exception:
        pass
    try:
        if _has_attr(actor, "tags"):
            tag = unreal.Name("DroneBenchScene") if _has_attr(unreal, "Name") else "DroneBenchScene"
            tags = list(actor.tags) if actor.tags else []
            as_str = {str(t) for t in tags}
            if "DroneBenchScene" not in as_str:
                tags.append(tag)
                actor.tags = tags
    except Exception:
        pass


def _destroy(actor, context):
    if not _is_valid(actor):
        return
    try:
        actor_sys = _actor_sys()
        if actor_sys is not None and _has_attr(actor_sys, "destroy_actor"):
            # dir(unreal.EditorActorSubsystem)  # destroy_actor
            actor_sys.destroy_actor(actor)
            return
        if _has_attr(unreal, "EditorLevelLibrary") and _has_attr(
            unreal.EditorLevelLibrary, "destroy_actor"
        ):
            unreal.EditorLevelLibrary.destroy_actor(actor)
            return
        if _has_attr(actor, "destroy_actor"):
            actor.destroy_actor()
    except Exception as exc:
        _log_error("destroy_actor after {}".format(context), exc)


def _vec(*xyz):
    return unreal.Vector(float(xyz[0]), float(xyz[1]), float(xyz[2]))


def _rot(pitch, yaw, roll):
    return unreal.Rotator(float(pitch), float(yaw), float(roll))


def _look_at(from_v, to_v):
    dx = to_v.x - from_v.x
    dy = to_v.y - from_v.y
    dz = to_v.z - from_v.z
    yaw = math.degrees(math.atan2(dy, dx))
    hyp = math.sqrt(dx * dx + dy * dy)
    pitch = math.degrees(math.atan2(dz, hyp))
    return _rot(pitch, yaw, 0.0)


def _teleport_actor(actor, location, rotation):
    """Place without sweep. dir(actor) for set_actor_location / set_actor_transform."""
    moved = False
    try:
        if _has_attr(actor, "set_actor_transform") and _has_attr(unreal, "Transform"):
            scale = None
            try:
                scale = actor.get_actor_scale3d()
            except Exception:
                scale = _vec(1.0, 1.0, 1.0)
            actor.set_actor_transform(
                unreal.Transform(location=location, rotation=rotation, scale=scale),
                False,
                True,
            )
            return True
    except Exception as exc:
        _log_error("set_actor_transform", exc)
    try:
        if _has_attr(actor, "set_actor_location"):
            actor.set_actor_location(location, False, True)
            moved = True
    except TypeError:
        try:
            actor.set_actor_location(location, False)
            moved = True
        except Exception as exc:
            _log_error("set_actor_location", exc)
    except Exception as exc:
        _log_error("set_actor_location", exc)
    try:
        if _has_attr(actor, "set_actor_rotation"):
            actor.set_actor_rotation(rotation, False)
            moved = True
    except Exception as exc:
        _log_error("set_actor_rotation", exc)
    return moved


def _spawn_class_candidates(cls):
    yield cls
    fn = getattr(cls, "static_class", None)
    if callable(fn):
        try:
            sc = fn()
            if sc is not None and sc is not cls:
                yield sc
        except Exception:
            pass


def _spawn_from_class(cls, location, rotation):
    last = None
    for candidate in _spawn_class_candidates(cls):
        try:
            actor_sys = _actor_sys()
            if actor_sys is not None:
                # dir(unreal.EditorActorSubsystem)  # spawn_actor_from_class
                return actor_sys.spawn_actor_from_class(candidate, location, rotation)
            # dir(unreal.EditorLevelLibrary)  # spawn_actor_from_class
            return unreal.EditorLevelLibrary.spawn_actor_from_class(
                candidate, location, rotation
            )
        except Exception as exc:
            last = exc
            continue
    if last is not None:
        raise last
    raise RuntimeError("spawn_actor_from_class returned no actor")


def _spawn_from_object(obj, location, rotation):
    last = None
    try:
        actor_sys = _actor_sys()
        if actor_sys is not None and _has_attr(actor_sys, "spawn_actor_from_object"):
            # dir(unreal.EditorActorSubsystem)  # spawn_actor_from_object
            return actor_sys.spawn_actor_from_object(obj, location, rotation)
    except Exception as exc:
        last = exc
    try:
        if _has_attr(unreal, "EditorLevelLibrary") and _has_attr(
            unreal.EditorLevelLibrary, "spawn_actor_from_object"
        ):
            return unreal.EditorLevelLibrary.spawn_actor_from_object(
                obj, location, rotation
            )
    except Exception as exc:
        last = exc
    if last is not None:
        raise last
    raise RuntimeError("spawn_actor_from_object unavailable")


def _load_cube_mesh():
    # dir(unreal.EditorAssetLibrary)  # load_asset
    # Engine paths can fail does_asset_exist; try load instead of probing.
    eal = _ue_cls("EditorAssetLibrary")
    for path in CUBE_PATHS:
        try:
            mesh = None
            if eal is not None and _has_attr(eal, "load_asset"):
                mesh = eal.load_asset(path)
            elif _has_attr(unreal, "load_asset"):
                mesh = unreal.load_asset(path)
            elif _has_attr(unreal, "load_object"):
                mesh = unreal.load_object(None, path)
            if _is_valid(mesh):
                return mesh
        except Exception as exc:
            _log_error("load_cube_mesh {}".format(path), exc)
    return None


def _static_mesh_component(actor):
    smc = getattr(actor, "static_mesh_component", None)
    if _is_valid(smc):
        return smc
    smc_cls = _ue_cls("StaticMeshComponent")
    if smc_cls is not None and _has_attr(actor, "get_component_by_class"):
        try:
            smc = actor.get_component_by_class(smc_cls)
            if _is_valid(smc):
                return smc
        except Exception:
            pass
    return None


def _set_static_mobility(actor):
    smc = _static_mesh_component(actor)
    mobility_enum = _ue_cls("ComponentMobility")
    if smc is None or mobility_enum is None:
        return
    static = getattr(mobility_enum, "STATIC", None)
    if static is None:
        return
    try:
        if _has_attr(smc, "set_mobility"):
            smc.set_mobility(static)
        else:
            _set_prop(smc, "mobility", static, _label_of(actor) + ".mobility")
    except Exception as exc:
        _log_error("set_mobility STATIC on {}".format(_label_of(actor)), exc)


def _scale_from_cm(size_cm):
    return _vec(
        size_cm[0] / CUBE_NATIVE_CM,
        size_cm[1] / CUBE_NATIVE_CM,
        size_cm[2] / CUBE_NATIVE_CM,
    )


def _ensure_box(label, location, size_cm, rotation=None):
    existing = _find_by_label(label)
    if existing is not None:
        _ALREADY.append(label)
        return existing, "already_present"

    mesh = _load_cube_mesh()
    if mesh is None:
        _log_error("ensure_box({})".format(label), RuntimeError("engine Cube mesh not found"))
        return None, "failed"

    rotation = rotation or _rot(0.0, 0.0, 0.0)
    actor = None
    try:
        try:
            actor = _spawn_from_object(mesh, location, rotation)
        except Exception as exc:
            _note("spawn_actor_from_object({}): {}".format(label, exc))
            sm_cls = _ue_cls("StaticMeshActor")
            if sm_cls is None:
                raise
            actor = _spawn_from_class(sm_cls, location, rotation)
            smc = _static_mesh_component(actor)
            if smc is None or not _has_attr(smc, "set_static_mesh"):
                raise RuntimeError("no StaticMeshComponent.set_static_mesh")
            # dir(unreal.StaticMeshComponent)  # set_static_mesh
            if not smc.set_static_mesh(mesh):
                raise RuntimeError("set_static_mesh returned False")
        if not _is_valid(actor):
            raise RuntimeError("spawn returned invalid actor")
        _set_label(actor, label)
        try:
            actor.set_actor_scale3d(_scale_from_cm(size_cm))
        except Exception as exc:
            _log_error("set_actor_scale3d({})".format(label), exc)
        _set_static_mobility(actor)
        _CREATED.append(label)
        return actor, "created"
    except Exception as exc:
        _log_error("ensure_box({})".format(label), exc)
        _destroy(actor, label)
        return None, "failed"


def _add_component(actor, cls, name):
    """Best-effort component add. dir(actor) for add_component_by_class."""
    transform = unreal.Transform() if _has_attr(unreal, "Transform") else None
    add = getattr(actor, "add_component_by_class", None)
    if callable(add):
        attempts = []
        if transform is not None:
            attempts.extend(
                [
                    lambda: add(cls, False, transform, False),
                    lambda: add(cls, name, transform, False, False),
                    lambda: add(cls, unreal.Name(name) if _has_attr(unreal, "Name") else name, transform, False, False),
                ]
            )
        attempts.append(lambda: add(cls))
        for attempt in attempts:
            try:
                comp = attempt()
                if _is_valid(comp):
                    return comp
            except TypeError:
                continue
            except Exception as exc:
                _log_error("add_component_by_class({})".format(name), exc)
                break

    new_object = getattr(unreal, "new_object", None)
    if callable(new_object):
        try:
            kwargs = {"outer": actor}
            try:
                comp = new_object(cls, actor, name)
            except TypeError:
                comp = new_object(cls, **kwargs)
            if _is_valid(comp):
                if _has_attr(comp, "register_component"):
                    try:
                        comp.register_component()
                    except Exception as exc:
                        _log_error("register_component({})".format(name), exc)
                if _has_attr(actor, "add_instance_component"):
                    try:
                        actor.add_instance_component(comp)
                    except Exception as exc:
                        _log_error("add_instance_component({})".format(name), exc)
                return comp
        except Exception as exc:
            _log_error("new_object({})".format(name), exc)
    return None


def _attach(child, parent, socket=""):
    if child is None or parent is None:
        return False
    socket_name = unreal.Name(socket) if _has_attr(unreal, "Name") else socket
    rule = getattr(_ue_cls("AttachmentRule"), "SNAP_TO_TARGET", None)
    if _has_attr(child, "attach_to_component") and rule is not None:
        try:
            # dir(unreal.SceneComponent)  # attach_to_component
            child.attach_to_component(parent, socket_name, rule, rule, rule, False)
            return True
        except Exception as exc:
            _log_error("attach_to_component", exc)
    if _has_attr(child, "k2_attach_to"):
        try:
            child.k2_attach_to(parent, socket_name, 0, 0, 0, False)
            return True
        except Exception as exc:
            _log_error("k2_attach_to", exc)
    return False


def _try_spring_arm(cam_actor):
    """Attach SpringArmComponent if the type and add APIs exist. No collision/physics."""
    # dir(unreal)  # SpringArmComponent
    spring_cls = _ue_cls("SpringArmComponent")
    if spring_cls is None:
        _note("SpringArmComponent not in dir(unreal); ChaseCam is a plain camera")
        return False

    spring = _add_component(cam_actor, spring_cls, "SpringArm")
    if not _is_valid(spring):
        _note("could not add SpringArmComponent to ChaseCam")
        return False

    _set_prop(spring, "target_arm_length", float(CHASE_ARM_CM), "ChaseCam.spring")
    _set_prop(spring, "do_collision_test", False, "ChaseCam.spring")
    _set_prop(spring, "socket_offset", _vec(0.0, 0.0, 100.0), "ChaseCam.spring")

    root = getattr(cam_actor, "root_component", None)
    cam_comp = getattr(cam_actor, "camera_component", None)
    if not _is_valid(cam_comp):
        cam_cls = _ue_cls("CameraComponent")
        if cam_cls is not None and _has_attr(cam_actor, "get_component_by_class"):
            try:
                cam_comp = cam_actor.get_component_by_class(cam_cls)
            except Exception as exc:
                _log_error("ChaseCam get CameraComponent", exc)

    if _is_valid(root):
        _attach(spring, root, "")
    attached = False
    if _is_valid(cam_comp):
        attached = _attach(cam_comp, spring, "SpringEndpoint")
        if not attached:
            attached = _attach(cam_comp, spring, "")
    if not attached:
        _note("SpringArmComponent added but camera did not attach; using offset camera")
        return False
    _note("ChaseCam spring-arm target_arm_length={} cm".format(CHASE_ARM_CM))
    return True


def _ensure_ground():
    """Named pad: scaled cube 1000x1000x10 cm. Landscape spawn is not used (not an open world)."""
    # dir(unreal)  # Landscape — present on some builds, but a landscape actor is a world,
    # not a 10 m pad. Cube matches the specified extent exactly.
    if _ue_cls("Landscape") is not None:
        _note("Landscape in dir(unreal); using scaled cube for the 10 m pad instead")
    loc = _vec(0.0, 0.0, -GROUND_CM[2] / 2.0)
    return _ensure_box(LABEL_GROUND, loc, GROUND_CM)


def _ensure_airstrip():
    loc = _vec(0.0, 0.0, AIRSTRIP_CM[2] / 2.0 + 0.5)
    return _ensure_box(LABEL_STRIP, loc, AIRSTRIP_CM)


def _ensure_hangar():
    loc = _vec(0.0, 320.0, HANGAR_CM[2] / 2.0)
    return _ensure_box(LABEL_HANGAR, loc, HANGAR_CM)


def _ensure_sun():
    existing = _find_by_label(LABEL_SUN)
    if existing is not None:
        _ALREADY.append(LABEL_SUN)
        return existing, "already_present"
    cls = _ue_cls("DirectionalLight")
    if cls is None:
        _note("DirectionalLight not in dir(unreal); skipped")
        return None, "skipped"
    actor = None
    try:
        actor = _spawn_from_class(cls, _vec(0.0, 0.0, 400.0), _rot(-50.0, 35.0, 0.0))
        if not _is_valid(actor):
            raise RuntimeError("invalid DirectionalLight")
        _set_label(actor, LABEL_SUN)
        light = getattr(actor, "light_component", None) or getattr(
            actor, "directional_light_component", None
        )
        if _is_valid(light):
            _set_prop(light, "atmosphere_sun_light", True, LABEL_SUN)
        _CREATED.append(LABEL_SUN)
        return actor, "created"
    except Exception as exc:
        _log_error("ensure_sun", exc)
        _destroy(actor, LABEL_SUN)
        return None, "failed"


def _ensure_atmosphere():
    """Sky / atmosphere actors, only if the class is in dir(unreal)."""
    spawned = []
    specs = (
        (LABEL_SKY_ATMO, ("SkyAtmosphere",), _vec(0.0, 0.0, 0.0), _rot(0.0, 0.0, 0.0)),
        (LABEL_SKY_LIGHT, ("SkyLight",), _vec(0.0, 0.0, 100.0), _rot(0.0, 0.0, 0.0)),
    )
    for label, class_names, loc, rot in specs:
        if _find_by_label(label) is not None:
            _ALREADY.append(label)
            continue
        cls = _ue_cls(*class_names)
        if cls is None:
            _note("{} not in dir(unreal); skipped".format(class_names[0]))
            continue
        actor = None
        try:
            actor = _spawn_from_class(cls, loc, rot)
            if not _is_valid(actor):
                raise RuntimeError("invalid " + class_names[0])
            _set_label(actor, label)
            if label == LABEL_SKY_LIGHT:
                comp = getattr(actor, "light_component", None) or getattr(
                    actor, "sky_light_component", None
                )
                if _is_valid(comp) and _has_attr(comp, "recapture_sky"):
                    # dir(unreal.SkyLightComponent)  # recapture_sky
                    try:
                        comp.recapture_sky()
                    except Exception as exc:
                        _log_error("SkyLight.recapture_sky", exc)
            _CREATED.append(label)
            spawned.append(label)
        except Exception as exc:
            _log_error("ensure_atmosphere({})".format(label), exc)
            _destroy(actor, label)
    return spawned


def _ensure_chase_cam():
    existing = _find_by_label(LABEL_CAM)
    if existing is not None:
        _ALREADY.append(LABEL_CAM)
        return existing, "already_present"

    cam_cls = _ue_cls("CameraActor", "CineCameraActor")
    if cam_cls is None:
        _log_error("ensure_chase_cam", RuntimeError("CameraActor not in dir(unreal)"))
        return None, "failed"

    spring_cls = _ue_cls("SpringArmComponent")
    origin_loc = _vec(0.0, 0.0, 80.0)
    behind_loc = _vec(-CHASE_ARM_CM, 0.0, 180.0)
    look = _look_at(behind_loc, _vec(0.0, 0.0, 80.0))

    actor = None
    try:
        if spring_cls is not None:
            actor = _spawn_from_class(cam_cls, origin_loc, _rot(0.0, 0.0, 0.0))
        else:
            actor = _spawn_from_class(cam_cls, behind_loc, look)
        if not _is_valid(actor):
            raise RuntimeError("invalid CameraActor")
        _set_label(actor, LABEL_CAM)

        used_spring = False
        if spring_cls is not None:
            try:
                used_spring = _try_spring_arm(actor)
            except Exception as exc:
                _log_error("ChaseCam spring-arm", exc)
                used_spring = False

        if not used_spring:
            _teleport_actor(actor, behind_loc, look)
            _note(
                "ChaseCam at ({:.0f}, {:.0f}, {:.0f}) cm, no spring-arm".format(
                    behind_loc.x, behind_loc.y, behind_loc.z
                )
            )

        _CREATED.append(LABEL_CAM)
        return actor, "created"
    except Exception as exc:
        _log_error("ensure_chase_cam", exc)
        _destroy(actor, LABEL_CAM)
        return None, "failed"


def _counts_by_class():
    counts = {}
    listed = []
    for actor in _iter_level_actors():
        cls_name = _class_name(actor)
        counts[cls_name] = counts.get(cls_name, 0) + 1
        loc = None
        try:
            v = actor.get_actor_location()
            loc = [v.x, v.y, v.z]
        except Exception:
            loc = None
        listed.append(
            {
                "label": _label_of(actor),
                "class": cls_name,
                "location_cm": loc,
            }
        )
    listed.sort(key=lambda row: (row["class"], row["label"]))
    return counts, listed


def _engine_version():
    try:
        sl = _ue_cls("SystemLibrary")
        if sl is not None and _has_attr(sl, "get_engine_version"):
            # dir(unreal.SystemLibrary)  # get_engine_version
            return str(sl.get_engine_version())
    except Exception as exc:
        _log_error("get_engine_version", exc)
    return None


def _scene_owned():
    rows = []
    for label in (
        LABEL_GROUND,
        LABEL_STRIP,
        LABEL_HANGAR,
        LABEL_CAM,
        LABEL_SUN,
        LABEL_SKY_ATMO,
        LABEL_SKY_LIGHT,
    ):
        actor = _find_by_label(label)
        if actor is None:
            rows.append({"label": label, "present": False})
            continue
        loc = None
        scale = None
        try:
            v = actor.get_actor_location()
            loc = [v.x, v.y, v.z]
        except Exception:
            pass
        try:
            s = actor.get_actor_scale3d()
            scale = [s.x, s.y, s.z]
        except Exception:
            pass
        rows.append(
            {
                "label": label,
                "present": True,
                "class": _class_name(actor),
                "location_cm": loc,
                "scale": scale,
            }
        )
    return rows


def main():
    _ERRORS[:] = []
    _CREATED[:] = []
    _ALREADY[:] = []
    _NOTES[:] = []
    summary = {
        "ok": False,
        "script": "build_scene.py",
        "engine_version": _engine_version(),
        "api_probe": _api_probe(),
        "ground_kind": "scaled_cube",
        "ground_cm": list(GROUND_CM),
        "created": [],
        "already_present": [],
        "notes": [],
        "errors": [],
        "actor_counts_by_class": {},
        "scene_actors": [],
        "level_actors": [],
    }
    try:
        _ensure_sun()
        _ensure_atmosphere()
        _ensure_ground()
        _ensure_airstrip()
        _ensure_hangar()
        _ensure_chase_cam()
    except Exception as exc:
        _log_error("main", exc)
        _ERRORS.append(traceback.format_exc())

    counts, listed = _counts_by_class()
    present = {row["label"] for row in _scene_owned() if row.get("present")}
    summary["created"] = list(_CREATED)
    summary["already_present"] = list(_ALREADY)
    summary["notes"] = list(_NOTES)
    summary["errors"] = list(_ERRORS)
    summary["actor_counts_by_class"] = dict(sorted(counts.items()))
    summary["scene_actors"] = _scene_owned()
    summary["level_actors"] = listed
    summary["ok"] = all(label in present for label in REQUIRED_LABELS)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0 if summary["ok"] else 1


try:
    main()
except Exception as exc:
    print(
        json.dumps(
            {
                "ok": False,
                "script": "build_scene.py",
                "errors": [
                    "unhandled {}: {}".format(type(exc).__name__, exc),
                    traceback.format_exc(),
                ],
                "actor_counts_by_class": {},
            },
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
