# Unreal editor Python. Idempotent. Prints one JSON object to stdout.
# Consumes MPC scalar LoadFactor only. Does not compute stress.

import json
import traceback

try:
    import unreal
except ImportError as exc:
    print(
        json.dumps(
            {
                "script": "build_heatmap_material.py",
                "ok": False,
                "errors": [
                    {
                        "stage": "import_unreal",
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                ],
            },
            indent=2,
        )
    )
    raise SystemExit(1)


SCRIPT = "build_heatmap_material.py"
MPC_NAME = "MPC_LoadFactor"
MPC_PATH = "/Game/Materials/MPC_LoadFactor"
MATERIAL_NAME = "M_Heatmap"
MATERIAL_PATH = "/Game/Materials/M_Heatmap"
PACKAGE_DIR = "/Game/Materials"
SCALAR_NAME = "LoadFactor"
SCALAR_DEFAULT = 1.0
VERIFY_VALUES = (1.0, 3.5)
READBACK_EPS = 1.0e-3
# Display mapping only: level-flight LoadFactor -> viridis start, VERIFY high -> viridis end.
# Not a structural or aerodynamic limit.
DISPLAY_MIN = 1.0
DISPLAY_MAX = 3.5
# matplotlib viridis listed colormap, 5 stops. Published colormap, not aircraft data.
VIRIDIS_SRGB = (
    (0.267004, 0.004874, 0.329415),
    (0.229739, 0.322361, 0.545706),
    (0.127568, 0.566949, 0.550556),
    (0.369214, 0.788888, 0.382914),
    (0.993248, 0.906157, 0.143936),
)
VIRIDIS_HLSL = """
float t = saturate(T);
float3 c0 = float3(0.267004, 0.004874, 0.329415);
float3 c1 = float3(0.229739, 0.322361, 0.545706);
float3 c2 = float3(0.127568, 0.566949, 0.550556);
float3 c3 = float3(0.369214, 0.788888, 0.382914);
float3 c4 = float3(0.993248, 0.906157, 0.143936);
float3 col = lerp(c0, c1, saturate(t / 0.25));
col = lerp(col, c2, saturate((t - 0.25) / 0.25));
col = lerp(col, c3, saturate((t - 0.50) / 0.25));
col = lerp(col, c4, saturate((t - 0.75) / 0.25));
return col;
""".strip()


def _json_default(obj):
    return str(obj)


def _err(result, stage, exc):
    result.setdefault("errors", []).append(
        {
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
    )


def _try_set(obj, names, value):
    last = None
    if isinstance(names, str):
        names = (names,)
    for name in names:
        try:
            obj.set_editor_property(name, value)
            return name
        except Exception as exc:
            last = exc
    raise RuntimeError("set_editor_property %s failed: %s" % (list(names), last))


def _try_get(obj, names, default=None):
    for name in names:
        try:
            return obj.get_editor_property(name)
        except Exception:
            continue
    return default


def _cls(*names):
    for name in names:
        found = getattr(unreal, name, None)
        if found is not None:
            return found
    return None


def _enum_value(enum_cls, *member_names):
    if enum_cls is None:
        return None
    for member in member_names:
        if hasattr(enum_cls, member):
            return getattr(enum_cls, member)
    return None


def _editor_world():
    # dir(unreal.UnrealEditorSubsystem)  # get_editor_world
    ue_subsys_cls = _cls("UnrealEditorSubsystem")
    if ue_subsys_cls is not None:
        try:
            subsys = unreal.get_editor_subsystem(ue_subsys_cls)
            if subsys is not None:
                return subsys.get_editor_world()
        except Exception:
            pass
    # dir(unreal.EditorLevelLibrary)  # get_editor_world
    ell = _cls("EditorLevelLibrary")
    if ell is not None and hasattr(ell, "get_editor_world"):
        return ell.get_editor_world()
    raise RuntimeError("no editor world (UnrealEditorSubsystem / EditorLevelLibrary)")


def _ensure_dir(path):
    # dir(unreal.EditorAssetLibrary)  # does_directory_exist, make_directory
    eal = unreal.EditorAssetLibrary
    if hasattr(eal, "does_directory_exist") and eal.does_directory_exist(path):
        return False
    if hasattr(eal, "make_directory"):
        eal.make_directory(path)
        return True
    return False


def _asset_exists(path):
    # dir(unreal.EditorAssetLibrary)  # does_asset_exist
    return bool(unreal.EditorAssetLibrary.does_asset_exist(path))


def _load_asset(path):
    # dir(unreal.EditorAssetLibrary)  # load_asset
    return unreal.EditorAssetLibrary.load_asset(path)


def _save_asset(asset, path):
    # dir(unreal.EditorAssetLibrary)  # save_loaded_asset, save_asset
    eal = unreal.EditorAssetLibrary
    if asset is not None and hasattr(eal, "save_loaded_asset"):
        return bool(eal.save_loaded_asset(asset))
    if hasattr(eal, "save_asset"):
        return bool(eal.save_asset(path))
    return False


def _create_asset(name, package_path, asset_class, factory):
    # dir(unreal.AssetToolsHelpers)  # get_asset_tools
    # dir(unreal.AssetTools)  # create_asset
    if factory is not None:
        try:
            _try_set(factory, ("edit_after_new", "EditAfterNew"), False)
        except Exception:
            pass
        try:
            _try_set(factory, ("create_new", "CreateNew"), True)
        except Exception:
            pass
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    return tools.create_asset(name, package_path, asset_class, factory)


def _name_str(value):
    if value is None:
        return ""
    return str(value)


def _mpc_scalar_names(mpc):
    # dir(unreal.MaterialParameterCollection)  # get_scalar_parameter_names
    if hasattr(mpc, "get_scalar_parameter_names"):
        return [_name_str(n) for n in mpc.get_scalar_parameter_names()]
    params = _try_get(mpc, ("scalar_parameters", "ScalarParameters"), []) or []
    return [_name_str(_try_get(p, ("parameter_name", "ParameterName"), "")) for p in params]


def _mpc_scalar_default(mpc, name):
    # dir(unreal.MaterialParameterCollection)  # get_scalar_parameter_default_value
    if hasattr(mpc, "get_scalar_parameter_default_value"):
        raw = mpc.get_scalar_parameter_default_value(name)
        if isinstance(raw, (tuple, list)):
            return float(raw[0])
        if isinstance(raw, dict) and "parameter_found" in raw:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    params = _try_get(mpc, ("scalar_parameters", "ScalarParameters"), []) or []
    for param in params:
        if _name_str(_try_get(param, ("parameter_name", "ParameterName"), "")) == name:
            return float(_try_get(param, ("default_value", "DefaultValue"), 0.0))
    return None


def _list_scalars(mpc):
    names = _mpc_scalar_names(mpc)
    rows = []
    for name in names:
        rows.append({"name": name, "default_value": _mpc_scalar_default(mpc, name)})
    return rows


def _new_guid():
    # dir(unreal.GuidLibrary)  # new_guid
    gl = _cls("GuidLibrary")
    if gl is not None and hasattr(gl, "new_guid"):
        return gl.new_guid()
    guid_cls = _cls("Guid")
    if guid_cls is None:
        return None
    try:
        import uuid

        n = uuid.uuid4().int
        return guid_cls(
            (n >> 96) & 0xFFFFFFFF,
            (n >> 64) & 0xFFFFFFFF,
            (n >> 32) & 0xFFFFFFFF,
            n & 0xFFFFFFFF,
        )
    except Exception:
        return guid_cls()


def _ensure_mpc(result):
    info = {
        "name": MPC_NAME,
        "path": MPC_PATH,
        "created": False,
        "existed": False,
        "scalar_parameters": [],
    }
    result["mpc"] = info
    _ensure_dir(PACKAGE_DIR)

    if _asset_exists(MPC_PATH):
        mpc = _load_asset(MPC_PATH)
        info["existed"] = True
        info["created"] = False
    else:
        factory_cls = _cls(
            "MaterialParameterCollectionFactoryNew",
            "MaterialParameterCollectionFactory",
        )
        if factory_cls is None:
            raise RuntimeError(
                "no MaterialParameterCollection factory "
                "(MaterialParameterCollectionFactoryNew)"
            )
        mpc = _create_asset(
            MPC_NAME,
            PACKAGE_DIR,
            unreal.MaterialParameterCollection,
            factory_cls(),
        )
        if mpc is None:
            raise RuntimeError("create_asset returned None for %s" % MPC_PATH)
        info["created"] = True
        info["existed"] = False

    names = _mpc_scalar_names(mpc)
    if SCALAR_NAME not in names:
        param_cls = _cls("CollectionScalarParameter")
        if param_cls is None:
            raise RuntimeError("unreal.CollectionScalarParameter missing")
        param = param_cls()
        _try_set(param, ("parameter_name", "ParameterName"), SCALAR_NAME)
        _try_set(param, ("default_value", "DefaultValue"), float(SCALAR_DEFAULT))
        guid = _new_guid()
        if guid is not None:
            try:
                _try_set(param, ("id", "Id"), guid)
            except Exception:
                pass
        existing = list(_try_get(mpc, ("scalar_parameters", "ScalarParameters"), []) or [])
        existing.append(param)
        _try_set(mpc, ("scalar_parameters", "ScalarParameters"), existing)

    info["scalar_parameters"] = _list_scalars(mpc)
    _save_asset(mpc, MPC_PATH)
    info["scalar_parameters"] = _list_scalars(mpc)
    return mpc


def _expression_count(material):
    exprs = _try_get(material, ("expressions", "Expressions"), None)
    if exprs is None:
        return 0
    try:
        return len(list(exprs))
    except Exception:
        return 0


def _create_expr(material, class_name, x, y):
    # dir(unreal.MaterialEditingLibrary)  # create_material_expression
    cls = _cls(class_name)
    if cls is None:
        raise RuntimeError("missing expression class %s" % class_name)
    expr = unreal.MaterialEditingLibrary.create_material_expression(material, cls, x, y)
    if expr is None:
        raise RuntimeError("create_material_expression returned None for %s" % class_name)
    return expr


def _connect(from_expr, to_expr, to_names, from_out=""):
    # dir(unreal.MaterialEditingLibrary)  # connect_material_expressions
    if isinstance(to_names, str):
        to_names = (to_names,)
    last = None
    for name in to_names:
        try:
            ok = unreal.MaterialEditingLibrary.connect_material_expressions(
                from_expr, from_out, to_expr, name
            )
            if ok:
                return name
        except Exception as exc:
            last = exc
    raise RuntimeError(
        "connect %s -> %s inputs %s failed: %s"
        % (from_expr.get_class().get_name() if hasattr(from_expr, "get_class") else from_expr,
           to_expr.get_class().get_name() if hasattr(to_expr, "get_class") else to_expr,
           list(to_names),
           last)
    )


def _connect_property(from_expr, prop, from_out=""):
    # dir(unreal.MaterialEditingLibrary)  # connect_material_property
    # dir(unreal.MaterialProperty)  # MP_EMISSIVE_COLOR, MP_BASE_COLOR
    ok = unreal.MaterialEditingLibrary.connect_material_property(from_expr, from_out, prop)
    if not ok:
        raise RuntimeError("connect_material_property %s failed" % prop)
    return True


def _find_lut():
    # dir(unreal.EditorAssetLibrary)  # list_assets
    eal = unreal.EditorAssetLibrary
    if not hasattr(eal, "list_assets"):
        return None
    try:
        assets = eal.list_assets("/Game", recursive=True, include_folder=False)
    except TypeError:
        assets = eal.list_assets("/Game", True, False)
    except Exception:
        return None
    preferred = []
    fallback = []
    for path in assets or []:
        lower = str(path).lower()
        if "viridis" in lower:
            preferred.append(str(path))
        elif "turbo" in lower or "heatmap_lut" in lower or "colormap_lut" in lower:
            fallback.append(str(path))
    tex_cls = _cls("Texture2D", "Texture")
    for path in preferred + fallback:
        try:
            asset = _load_asset(path)
        except Exception:
            continue
        if asset is None:
            continue
        if tex_cls is None or isinstance(asset, tex_cls):
            return asset
    return None


def _wire_collection_parameter(material, mpc, x, y):
    expr = _create_expr(material, "MaterialExpressionCollectionParameter", x, y)
    _try_set(expr, ("collection", "Collection"), mpc)
    _try_set(expr, ("parameter_name", "ParameterName"), SCALAR_NAME)
    try:
        _try_set(expr, ("desc", "Desc"), "MPC LoadFactor")
    except Exception:
        pass
    params = _try_get(mpc, ("scalar_parameters", "ScalarParameters"), []) or []
    for param in params:
        if _name_str(_try_get(param, ("parameter_name", "ParameterName"), "")) == SCALAR_NAME:
            guid = _try_get(param, ("id", "Id"), None)
            if guid is not None:
                try:
                    _try_set(expr, ("parameter_id", "ParameterId"), guid)
                except Exception:
                    pass
            break
    return expr


def _scalar_param(material, name, default, x, y, group="Display"):
    expr = _create_expr(material, "MaterialExpressionScalarParameter", x, y)
    _try_set(expr, ("parameter_name", "ParameterName"), name)
    _try_set(expr, ("default_value", "DefaultValue"), float(default))
    try:
        _try_set(expr, ("group", "Group"), group)
    except Exception:
        pass
    return expr


def _const(material, value, x, y):
    expr = _create_expr(material, "MaterialExpressionConstant", x, y)
    _try_set(expr, ("r", "R"), float(value))
    return expr


def _const3(material, rgb, x, y):
    expr = _create_expr(material, "MaterialExpressionConstant3Vector", x, y)
    color_cls = _cls("LinearColor")
    _try_set(expr, ("constant", "Constant"), color_cls(rgb[0], rgb[1], rgb[2], 1.0))
    return expr


def _binop(material, class_name, a, b, x, y):
    expr = _create_expr(material, class_name, x, y)
    _connect(a, expr, ("A", "a", ""))
    _connect(b, expr, ("B", "b"))
    return expr


def _saturate(material, inp, x, y):
    expr = _create_expr(material, "MaterialExpressionSaturate", x, y)
    _connect(inp, expr, ("", "Input", "input"))
    return expr


def _remap_load_factor(material, mpc):
    load = _wire_collection_parameter(material, mpc, -1400, 0)
    vmin = _scalar_param(material, "DisplayLoadFactorMin", DISPLAY_MIN, -1400, 180)
    vmax = _scalar_param(material, "DisplayLoadFactorMax", DISPLAY_MAX, -1400, 360)
    numer = _binop(material, "MaterialExpressionSubtract", load, vmin, -1100, 0)
    denom = _binop(material, "MaterialExpressionSubtract", vmax, vmin, -1100, 220)
    eps = _const(material, 1.0e-4, -1100, 400)
    denom_safe = _binop(material, "MaterialExpressionMax", denom, eps, -900, 220)
    divided = _binop(material, "MaterialExpressionDivide", numer, denom_safe, -700, 0)
    return _saturate(material, divided, -500, 0)


def _build_lut_graph(material, t_expr, lut):
    half = _const(material, 0.5, -300, 200)
    append = _create_expr(material, "MaterialExpressionAppendVector", -200, 0)
    _connect(t_expr, append, ("A", "a", ""))
    _connect(half, append, ("B", "b"))
    sample = _create_expr(material, "MaterialExpressionTextureSample", 0, 0)
    _try_set(sample, ("texture", "Texture"), lut)
    _connect(append, sample, ("Coordinates", "UVs", "UV", "UVCoords", ""))
    return sample, "RGB"


def _build_custom_viridis(material, t_expr):
    custom = _create_expr(material, "MaterialExpressionCustom", 0, 0)
    _try_set(custom, ("description", "Description"), "Viridis")
    out_t = _enum_value(_cls("CustomMaterialOutputType"), "CMOT_FLOAT3", "FLOAT3")
    if out_t is not None:
        _try_set(custom, ("output_type", "OutputType"), out_t)
    _try_set(custom, ("code", "Code"), VIRIDIS_HLSL)
    inp_cls = _cls("CustomInput")
    if inp_cls is None:
        raise RuntimeError("unreal.CustomInput missing")
    try:
        inp = inp_cls(input_name="T")
    except Exception:
        inp = inp_cls()
        _try_set(inp, ("input_name", "InputName"), "T")
    _try_set(custom, ("inputs", "Inputs"), [inp])
    _connect(t_expr, custom, ("T", "t", ""))
    return custom, ""


def _sat_div(material, t_expr, offset, span, x, y):
    if offset == 0.0:
        shifted = t_expr
        sx = x
    else:
        off = _const(material, offset, x - 200, y + 80)
        shifted = _binop(material, "MaterialExpressionSubtract", t_expr, off, x - 80, y)
        sx = x + 40
    span_c = _const(material, span, sx - 40, y + 80)
    divided = _binop(material, "MaterialExpressionDivide", shifted, span_c, sx + 80, y)
    return _saturate(material, divided, sx + 240, y)


def _lerp(material, a, b, alpha, x, y):
    expr = _create_expr(material, "MaterialExpressionLinearInterpolate", x, y)
    _connect(a, expr, ("A", "a", ""))
    _connect(b, expr, ("B", "b"))
    _connect(alpha, expr, ("Alpha", "alpha"))
    return expr


def _build_lerp_viridis(material, t_expr):
    colors = []
    for i, rgb in enumerate(VIRIDIS_SRGB):
        colors.append(_const3(material, rgb, -200, 200 + i * 140))
    col = colors[0]
    for i in range(4):
        alpha = _sat_div(material, t_expr, 0.25 * i, 0.25, 0, 200 + i * 140)
        col = _lerp(material, col, colors[i + 1], alpha, 400, 200 + i * 140)
    return col, ""


def _set_unlit(material):
    # dir(unreal.MaterialShadingModel)  # MSM_UNLIT
    model = _enum_value(_cls("MaterialShadingModel"), "MSM_UNLIT", "UNLIT")
    if model is not None:
        _try_set(material, ("shading_model", "ShadingModel"), model)
    try:
        _try_set(material, ("two_sided", "TwoSided"), True)
    except Exception:
        pass


def _clear_expressions(material):
    # dir(unreal.MaterialEditingLibrary)  # delete_all_material_expressions
    if hasattr(unreal.MaterialEditingLibrary, "delete_all_material_expressions"):
        unreal.MaterialEditingLibrary.delete_all_material_expressions(material)


def _finish_graph(material, color_expr, from_out, result):
    _set_unlit(material)
    # dir(unreal.MaterialProperty)  # MP_EMISSIVE_COLOR
    emissive = _enum_value(_cls("MaterialProperty"), "MP_EMISSIVE_COLOR", "EMISSIVE_COLOR")
    if emissive is None:
        raise RuntimeError("MaterialProperty.MP_EMISSIVE_COLOR missing")
    _connect_property(color_expr, emissive, from_out)
    # dir(unreal.MaterialEditingLibrary)  # layout_material_expressions, recompile_material
    try:
        if hasattr(unreal.MaterialEditingLibrary, "layout_material_expressions"):
            unreal.MaterialEditingLibrary.layout_material_expressions(material)
    except Exception as exc:
        _err(result, "material_layout", exc)
    unreal.MaterialEditingLibrary.recompile_material(material)


def _build_graph(material, mpc, result):
    mat_info = result["material"]
    lut = _find_lut()
    if lut is not None:
        mat_info["lut_path"] = (
            str(lut.get_path_name()) if hasattr(lut, "get_path_name") else str(lut)
        )

    attempts = []
    if lut is not None:
        attempts.append(("lut_texture", lambda t: _build_lut_graph(material, t, lut)))
    attempts.append(("custom_hlsl_viridis", lambda t: _build_custom_viridis(material, t)))
    attempts.append(("lerp_viridis_stops", lambda t: _build_lerp_viridis(material, t)))

    last_exc = None
    for method, builder in attempts:
        try:
            _clear_expressions(material)
            t_expr = _remap_load_factor(material, mpc)
            mat_info["mpc_bound"] = True
            color_expr, from_out = builder(t_expr)
            _finish_graph(material, color_expr, from_out, result)
            mat_info["graph_method"] = method
            mat_info["colormap"] = "viridis"
            mat_info["not_rainbow"] = True
            mat_info["graph_complete"] = True
            mat_info["human_finish_required"] = False
            mat_info["human_finish_message"] = None
            return method
        except Exception as exc:
            last_exc = exc
            _err(result, "material_graph_%s" % method, exc)
            try:
                _clear_expressions(material)
            except Exception as cleanup_exc:
                _err(result, "material_graph_%s_cleanup" % method, cleanup_exc)
            mat_info["mpc_bound"] = False

    raise last_exc if last_exc is not None else RuntimeError("material graph failed")


def _ensure_material(result, mpc):
    info = {
        "name": MATERIAL_NAME,
        "path": MATERIAL_PATH,
        "created": False,
        "existed": False,
        "colormap": "viridis",
        "not_rainbow": True,
        "graph_complete": False,
        "graph_method": None,
        "mpc_bound": False,
        "human_finish_required": True,
        "human_finish_message": "material graph must be finished by a human",
        "lut_path": None,
        "display_mapping": {
            "min_parameter": "DisplayLoadFactorMin",
            "max_parameter": "DisplayLoadFactorMax",
            "min": DISPLAY_MIN,
            "max": DISPLAY_MAX,
            "note": "display mapping only; not a structural limit",
        },
        "consumes": "MPC_LoadFactor.LoadFactor",
        "computes_stress": False,
    }
    result["material"] = info
    _ensure_dir(PACKAGE_DIR)

    created_this_run = False
    if _asset_exists(MATERIAL_PATH):
        material = _load_asset(MATERIAL_PATH)
        info["existed"] = True
        info["created"] = False
    else:
        factory_cls = _cls("MaterialFactoryNew")
        if factory_cls is None:
            raise RuntimeError("unreal.MaterialFactoryNew missing")
        material = _create_asset(
            MATERIAL_NAME,
            PACKAGE_DIR,
            unreal.Material,
            factory_cls(),
        )
        if material is None:
            raise RuntimeError("create_asset returned None for %s" % MATERIAL_PATH)
        info["created"] = True
        info["existed"] = False
        created_this_run = True

    if _expression_count(material) > 0 and not created_this_run:
        info["graph_complete"] = True
        info["graph_method"] = "preexisting"
        info["human_finish_required"] = False
        info["human_finish_message"] = None
        info["mpc_bound"] = None
        return material

    try:
        _build_graph(material, mpc, result)
    except Exception as exc:
        _err(result, "material_graph", exc)
        if created_this_run:
            try:
                # dir(unreal.MaterialEditingLibrary)  # delete_all_material_expressions
                unreal.MaterialEditingLibrary.delete_all_material_expressions(material)
            except Exception as cleanup_exc:
                _err(result, "material_graph_cleanup", cleanup_exc)
        info["graph_complete"] = False
        info["human_finish_required"] = True
        info["human_finish_message"] = (
            "material graph must be finished by a human; "
            "MPC_LoadFactor.LoadFactor is set. Wire CollectionParameter "
            "LoadFactor through a viridis (not rainbow) gradient to Emissive."
        )

    _save_asset(material, MATERIAL_PATH)
    return material


def _verify_load_factor(mpc, result):
    rows = []
    method = "instance"
    world = None
    try:
        world = _editor_world()
    except Exception as exc:
        _err(result, "verify_world", exc)
        method = "asset_default"

    for target in VERIFY_VALUES:
        row = {"set": target, "readback": None, "match": False, "method": method}
        try:
            if method == "instance":
                # dir(unreal.MaterialLibrary)  # set_scalar_parameter_value, get_scalar_parameter_value
                unreal.MaterialLibrary.set_scalar_parameter_value(
                    world, mpc, SCALAR_NAME, float(target)
                )
                readback = float(
                    unreal.MaterialLibrary.get_scalar_parameter_value(
                        world, mpc, SCALAR_NAME
                    )
                )
            else:
                params = list(_try_get(mpc, ("scalar_parameters", "ScalarParameters"), []) or [])
                updated = []
                found = False
                for param in params:
                    if _name_str(_try_get(param, ("parameter_name", "ParameterName"), "")) == SCALAR_NAME:
                        _try_set(param, ("default_value", "DefaultValue"), float(target))
                        found = True
                    updated.append(param)
                if not found:
                    raise RuntimeError("LoadFactor missing on MPC during asset_default verify")
                _try_set(mpc, ("scalar_parameters", "ScalarParameters"), updated)
                _save_asset(mpc, MPC_PATH)
                readback = _mpc_scalar_default(mpc, SCALAR_NAME)
            row["readback"] = readback
            row["match"] = (
                readback is not None and abs(float(readback) - float(target)) <= READBACK_EPS
            )
        except Exception as exc:
            _err(result, "verify_set_%s" % target, exc)
            row["error"] = str(exc)
        rows.append(row)

    result["verify"] = rows
    result["verify_load_factor_1_0"] = rows[0] if rows else None
    result["verify_load_factor_3_5"] = rows[1] if len(rows) > 1 else None
    return rows


def main():
    result = {
        "script": SCRIPT,
        "ok": False,
        "computes_stress": False,
        "consumes": "load_factor_only",
        "mpc": None,
        "material": None,
        "verify": [],
        "errors": [],
    }
    mpc = None
    try:
        mpc = _ensure_mpc(result)
    except Exception as exc:
        _err(result, "mpc", exc)

    if mpc is not None:
        try:
            _ensure_material(result, mpc)
        except Exception as exc:
            _err(result, "material", exc)
            if result.get("material") is None:
                result["material"] = {
                    "name": MATERIAL_NAME,
                    "path": MATERIAL_PATH,
                    "created": False,
                    "graph_complete": False,
                    "human_finish_required": True,
                    "human_finish_message": (
                        "material graph must be finished by a human; "
                        "still set MPC_LoadFactor"
                    ),
                }
        try:
            _verify_load_factor(mpc, result)
        except Exception as exc:
            _err(result, "verify", exc)

    verify_ok = bool(result.get("verify")) and all(
        row.get("match") for row in result.get("verify") or []
    )
    mpc_ok = (
        mpc is not None
        and result.get("mpc") is not None
        and any(
            p.get("name") == SCALAR_NAME
            for p in (result["mpc"].get("scalar_parameters") or [])
        )
    )
    result["ok"] = bool(mpc_ok and verify_ok)
    if result.get("material") and result["material"].get("human_finish_required"):
        result["human_finish_required"] = True
        result["human_finish_message"] = result["material"].get("human_finish_message")
    else:
        result["human_finish_required"] = False

    print(json.dumps(result, indent=2, default=_json_default))
    return result


try:
    main()
except Exception as exc:
    print(
        json.dumps(
            {
                "script": SCRIPT,
                "ok": False,
                "errors": [
                    {
                        "stage": "main",
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                ],
            },
            indent=2,
            default=_json_default,
        )
    )
