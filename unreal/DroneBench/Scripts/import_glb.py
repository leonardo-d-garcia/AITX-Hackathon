"""Import print-archive GLB into the current level. Never fuse meshes."""

from __future__ import annotations

import json
import os
import traceback

try:
    import unreal
except ImportError as exc:
    print(json.dumps({"ok": False, "script": "import_glb.py", "errors": [str(exc)]}))
    raise SystemExit(1)

GLB = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "apps",
        "web",
        "public",
        "titan_avenger.glb",
    )
)
DEST = "/Game/DroneBench/Airframe"


def _err(errors, where, exc):
    errors.append(
        {
            "where": where,
            "type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    )


def _set(obj, name, value, errors, required=True):
    try:
        obj.set_editor_property(name, value)
        return True
    except Exception as exc:
        if required:
            _err(errors, "set %s" % name, exc)
        return False


def _soft(obj):
    return unreal.SoftObjectPath(obj.get_path_name())


def _dup_pipeline(src, dest, errors):
    lib = unreal.EditorAssetLibrary
    try:
        if lib.does_asset_exist(dest):
            loaded = unreal.load_asset(dest)
            if loaded is not None:
                return loaded
    except Exception as exc:
        _err(errors, "load %s" % dest, exc)
    try:
        copied = lib.duplicate_asset(src, dest)
        if copied is not None:
            return copied
    except Exception as exc:
        _err(errors, "duplicate %s" % src, exc)
    return None


def _import():
    result = {
        "ok": False,
        "script": "import_glb.py",
        "glb": GLB,
        "glb_exists": os.path.isfile(GLB),
        "dest": DEST,
        "combine": "DO_NOT_COMBINE",
        "errors": [],
    }
    errors = result["errors"]
    if not result["glb_exists"]:
        errors.append({"where": "glb", "error": "missing %s" % GLB})
        return result

    try:
        manager = unreal.InterchangeManager.get_interchange_manager_scripted()
    except Exception as exc:
        _err(errors, "get_interchange_manager_scripted", exc)
        return result

    try:
        source = unreal.InterchangeManager.create_source_data(GLB)
    except Exception as exc:
        _err(errors, "create_source_data", exc)
        return result

    try:
        assets = _dup_pipeline(
            "/Interchange/Pipelines/DefaultGLTFSceneAssetsPipeline.DefaultGLTFSceneAssetsPipeline",
            "/Game/DroneBench/Pipelines/TitanGLTFAssets",
            errors,
        )
        if assets is None:
            assets = unreal.InterchangeGenericAssetsPipeline()
        result["assets_path"] = assets.get_path_name()
        _set(assets, "import_offset_translation", unreal.Vector(0.0, 0.0, 0.0), errors, required=False)
        _set(assets, "import_offset_rotation", unreal.Rotator(0.0, 0.0, 0.0), errors, required=False)
        _set(assets, "import_offset_uniform_scale", 1.0, errors, required=False)
        _set(assets, "asset_type_sub_folders", False, errors, required=False)
        _set(assets, "scene_name_sub_folder", False, errors, required=False)
        mesh_pipe = assets.get_editor_property("mesh_pipeline")
        if not _set(
            mesh_pipe,
            "combine_static_meshes_behavior",
            unreal.InterchangeCombineStaticMeshesBehavior.DO_NOT_COMBINE,
            errors,
            required=True,
        ):
            return result
        common = assets.get_editor_property("common_meshes_properties")
        if common is not None:
            _set(
                common,
                "combine_static_meshes_behavior",
                unreal.InterchangeCombineStaticMeshesBehavior.DO_NOT_COMBINE,
                errors,
                required=False,
            )
        try:
            unreal.EditorAssetLibrary.save_loaded_asset(assets)
        except Exception:
            pass
    except Exception as exc:
        _err(errors, "assets pipeline", exc)
        return result

    try:
        level = _dup_pipeline(
            "/Interchange/Pipelines/DefaultSceneLevelPipeline.DefaultSceneLevelPipeline",
            "/Game/DroneBench/Pipelines/TitanLevel",
            errors,
        )
        if level is None:
            level = unreal.InterchangeGenericLevelPipeline()
        result["level_path"] = level.get_path_name()
        _set(
            level,
            "scene_hierarchy_type",
            unreal.InterchangeSceneHierarchyType.CREATE_LEVEL_ACTORS,
            errors,
        )
        try:
            unreal.EditorAssetLibrary.save_loaded_asset(level)
        except Exception:
            pass
    except Exception as exc:
        _err(errors, "level pipeline", exc)
        return result

    try:
        params = unreal.ImportAssetParameters()
        params.set_editor_property("is_automated", True)
        params.set_editor_property("force_show_dialog", False)
        try:
            params.override_pipelines.append(_soft(assets))
            params.override_pipelines.append(_soft(level))
        except Exception as exc:
            _err(errors, "override_pipelines.append", exc)
            return result
    except Exception as exc:
        _err(errors, "ImportAssetParameters", exc)
        return result

    try:
        n_pipelines = len(params.override_pipelines)
    except Exception as exc:
        _err(errors, "override_pipelines", exc)
        return result
    if n_pipelines < 2:
        errors.append(
            {
                "where": "override_pipelines",
                "error": "assets and level pipelines not both attached; refusing import_scene",
            }
        )
        return result

    try:
        ok = manager.import_scene(DEST, source, params)
        result["import_scene"] = bool(ok)
    except Exception as exc:
        _err(errors, "import_scene", exc)
        return result

    result["ok"] = bool(result.get("import_scene")) and not errors
    return result


payload = _import()
print(json.dumps(payload, indent=2, default=str))
