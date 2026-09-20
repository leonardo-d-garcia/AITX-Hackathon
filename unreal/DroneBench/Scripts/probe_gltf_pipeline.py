"""Read-only load of DefaultGLTF Interchange pipelines. No GLB import. No Content write."""

from __future__ import annotations

import json
import traceback

try:
    import unreal as _u
except ImportError:
    _u = None
unreal = _u if _u is not None and hasattr(_u, "EditorAssetLibrary") else None

ASSETS_PATH = (
    "/Interchange/Pipelines/DefaultGLTFSceneAssetsPipeline.DefaultGLTFSceneAssetsPipeline"
)
LEVEL_PATH = (
    "/Interchange/Pipelines/DefaultSceneLevelPipeline.DefaultSceneLevelPipeline"
)
ASSETS_PATH_SHORT = "/Interchange/Pipelines/DefaultGLTFSceneAssetsPipeline"
LEVEL_PATH_SHORT = "/Interchange/Pipelines/DefaultSceneLevelPipeline"

COMBINE_KEYS = (
    "combine_static_meshes_behavior",
    "combine_skeletal_meshes_behavior",
    "combine_static_meshes",
)
OFFSET_KEYS = (
    "import_offset_translation",
    "import_offset_rotation",
    "import_offset_uniform_scale",
)


def _err(errors, where, exc):
    errors.append(
        {
            "where": where,
            "type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    )


def _class_name(obj):
    try:
        return str(obj.get_class().get_name())
    except Exception:
        return type(obj).__name__


def _class_path(obj):
    try:
        return str(obj.get_class().get_path_name())
    except Exception:
        return None


def _path_name(obj):
    try:
        return str(obj.get_path_name())
    except Exception:
        return None


def _jsonable(value):
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    name = getattr(value, "name", None)
    if isinstance(name, str) and name:
        return name
    pitch = getattr(value, "pitch", None)
    yaw = getattr(value, "yaw", None)
    roll = getattr(value, "roll", None)
    if pitch is not None and yaw is not None and roll is not None:
        try:
            return {"pitch": float(pitch), "yaw": float(yaw), "roll": float(roll)}
        except (TypeError, ValueError):
            pass
    x = getattr(value, "x", None)
    y = getattr(value, "y", None)
    z = getattr(value, "z", None)
    if x is not None and y is not None and z is not None:
        try:
            return {"x": float(x), "y": float(y), "z": float(z)}
        except (TypeError, ValueError):
            pass
    return str(value)


def _get_prop(obj, name, errors, where):
    # dir(obj)  # get_editor_property
    getter = getattr(obj, "get_editor_property", None)
    if callable(getter):
        try:
            return getter(name)
        except Exception as exc:
            _err(errors, "%s.get_editor_property %s" % (where, name), exc)
    try:
        return getattr(obj, name)
    except Exception as exc:
        _err(errors, "%s.%s" % (where, name), exc)
        return None


def _named_props(obj, names, errors, where):
    out = {}
    if obj is None:
        return out
    for name in names:
        out[name] = _jsonable(_get_prop(obj, name, errors, where))
    return out


def _combine_props(mesh_pipe, errors):
    out = {}
    if mesh_pipe is None:
        return out
    names = list(COMBINE_KEYS)
    # dir(mesh_pipe)  # combine_*
    try:
        extra = [
            n
            for n in dir(mesh_pipe)
            if "combine" in n.lower() and not n.startswith("_")
        ]
        for n in extra:
            if n not in names:
                names.append(n)
    except Exception as exc:
        _err(errors, "dir mesh_pipeline combine", exc)
    for name in names:
        out[name] = _jsonable(_get_prop(mesh_pipe, name, errors, "mesh_pipeline"))
    return out


def _offset_props(assets, errors):
    names = list(OFFSET_KEYS)
    try:
        extra = [
            n
            for n in dir(assets)
            if n.startswith("import_offset_") and not n.startswith("_")
        ]
        for n in extra:
            if n not in names:
                names.append(n)
    except Exception as exc:
        _err(errors, "dir assets import_offset", exc)
    return _named_props(assets, names, errors, "assets")


def _load_asset(path, errors):
    # dir(unreal.EditorAssetLibrary)  # load_asset
    lib = getattr(unreal, "EditorAssetLibrary", None)
    if lib is not None and hasattr(lib, "load_asset"):
        try:
            asset = lib.load_asset(path)
            if asset is not None:
                return asset
        except Exception as exc:
            _err(errors, "EditorAssetLibrary.load_asset %s" % path, exc)
    # dir(unreal)  # load_asset
    loader = getattr(unreal, "load_asset", None)
    if callable(loader):
        try:
            asset = loader(path)
            if asset is not None:
                return asset
        except Exception as exc:
            _err(errors, "unreal.load_asset %s" % path, exc)
    return None


def _load_pipeline(primary, fallback, errors, label):
    asset = _load_asset(primary, errors)
    if asset is None and fallback != primary:
        asset = _load_asset(fallback, errors)
    if asset is None:
        errors.append(
            {
                "where": "load %s" % label,
                "error": "load_asset returned None for %s" % primary,
            }
        )
        # Duplicate/save would write Content/. Load failed; report and stop.
        return None
    return asset


def probe():
    result = {
        "ok": False,
        "script": "probe_gltf_pipeline.py",
        "imported_glb": False,
        "wrote_content": False,
        "assets": None,
        "level": None,
        "errors": [],
    }
    errors = result["errors"]
    if unreal is None:
        errors.append({"where": "import", "error": "unreal editor APIs missing"})
        return result

    assets = _load_pipeline(ASSETS_PATH, ASSETS_PATH_SHORT, errors, "assets")
    if assets is not None:
        mesh_pipe = None
        try:
            mesh_pipe = assets.get_editor_property("mesh_pipeline")
        except Exception as exc:
            _err(errors, "assets.mesh_pipeline", exc)
        result["assets"] = {
            "path": _path_name(assets),
            "class": _class_name(assets),
            "class_path": _class_path(assets),
            "mesh_pipeline_class": _class_name(mesh_pipe) if mesh_pipe is not None else None,
            "mesh_pipeline_combine": _combine_props(mesh_pipe, errors),
            "import_offset": _offset_props(assets, errors),
        }

    level = _load_pipeline(LEVEL_PATH, LEVEL_PATH_SHORT, errors, "level")
    if level is not None:
        hierarchy = None
        has_hierarchy = False
        try:
            has_hierarchy = hasattr(level, "scene_hierarchy_type") or (
                "scene_hierarchy_type" in dir(level)
            )
        except Exception as exc:
            _err(errors, "dir level scene_hierarchy_type", exc)
        if has_hierarchy:
            hierarchy = _jsonable(
                _get_prop(level, "scene_hierarchy_type", errors, "level")
            )
        result["level"] = {
            "path": _path_name(level),
            "class": _class_name(level),
            "class_path": _class_path(level),
            "scene_hierarchy_type": hierarchy,
            "scene_hierarchy_type_present": bool(has_hierarchy),
        }

    result["ok"] = assets is not None and level is not None
    return result


try:
    payload = probe()
except Exception as exc:
    payload = {
        "ok": False,
        "script": "probe_gltf_pipeline.py",
        "imported_glb": False,
        "wrote_content": False,
        "assets": None,
        "level": None,
        "errors": [
            {
                "where": "probe",
                "type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        ],
    }
print(json.dumps(payload, indent=2, default=str), flush=True)
