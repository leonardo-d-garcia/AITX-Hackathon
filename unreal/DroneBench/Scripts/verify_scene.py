"""Read-only Unreal editor dump of the current level.

Prints one JSON object (never the word "done"). Does not spawn, destroy,
tag, move, or save. Missing values are null.

U-A: where an API name is guessed, a dir() comment sits above the call.
"""

import json
import traceback


def _err(errors, where, exc):
    tb = traceback.format_exc()
    if not tb or tb.strip() == "NoneType: None":
        tb = ""
    errors.append(
        {
            "where": where,
            "type": type(exc).__name__,
            "error": str(exc),
            "traceback": tb,
        }
    )


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _vec(obj):
    if obj is None:
        return None
    if isinstance(obj, dict) and "x" in obj and "y" in obj and "z" in obj:
        x, y, z = _finite(obj["x"]), _finite(obj["y"]), _finite(obj["z"])
        if None in (x, y, z):
            return None
        return {"x": x, "y": y, "z": z}
    if isinstance(obj, (tuple, list)) and len(obj) >= 3:
        x, y, z = _finite(obj[0]), _finite(obj[1]), _finite(obj[2])
        if None in (x, y, z):
            return None
        return {"x": x, "y": y, "z": z}
    x = _finite(getattr(obj, "x", None))
    if x is None:
        x = _finite(getattr(obj, "X", None))
    y = _finite(getattr(obj, "y", None))
    if y is None:
        y = _finite(getattr(obj, "Y", None))
    z = _finite(getattr(obj, "z", None))
    if z is None:
        z = _finite(getattr(obj, "Z", None))
    if None in (x, y, z):
        return None
    return {"x": x, "y": y, "z": z}


def _name_str(value):
    if value is None:
        return ""
    to_string = getattr(value, "to_string", None)
    if callable(to_string):
        try:
            text = to_string()
            if text is not None:
                return str(text)
        except Exception:
            pass
    try:
        text = str(value)
    except Exception:
        return ""
    if text in ("None", "none", "NAME_None"):
        return ""
    return text


def _label(actor):
    # dir(actor)  # get_actor_label, actor_label, get_actor_name, get_name
    for method_name in ("get_actor_label", "get_actor_name", "get_name"):
        method = getattr(actor, method_name, None)
        if not callable(method):
            continue
        try:
            text = method()
        except Exception:
            continue
        if text:
            return str(text)
    label = getattr(actor, "actor_label", None)
    if label:
        return str(label)
    return "<unknown>"


def _tags(actor):
    # dir(actor)  # tags, get_editor_property
    raw = None
    try:
        raw = actor.tags
    except Exception:
        try:
            raw = actor.get_editor_property("tags")
        except Exception:
            return []
    if raw is None:
        return []
    try:
        items = list(raw)
    except Exception:
        items = [raw]
    out = []
    for item in items:
        text = _name_str(item).strip()
        if text:
            out.append(text)
    return out


def _location(actor):
    # dir(actor)  # get_actor_location
    method = getattr(actor, "get_actor_location", None)
    if not callable(method):
        return None
    try:
        return _vec(method())
    except Exception:
        return None


def _unpack_origin_extent(pair):
    if pair is None:
        return None, None
    origin = extent = None
    if isinstance(pair, (tuple, list)) and len(pair) >= 2:
        origin, extent = pair[0], pair[1]
    else:
        origin = getattr(pair, "origin", None)
        extent = getattr(pair, "box_extent", None) or getattr(pair, "extent", None)
    origin = _vec(origin)
    extent = _vec(extent)
    if origin is None or extent is None:
        return None, None
    mn = {
        "x": origin["x"] - extent["x"],
        "y": origin["y"] - extent["y"],
        "z": origin["z"] - extent["z"],
    }
    mx = {
        "x": origin["x"] + extent["x"],
        "y": origin["y"] + extent["y"],
        "z": origin["z"] + extent["z"],
    }
    return mn, mx


def _box_minmax(box):
    if box is None:
        return None, None
    mn = _vec(getattr(box, "min", None))
    if mn is None:
        mn = _vec(getattr(box, "min_value", None))
    mx = _vec(getattr(box, "max", None))
    if mx is None:
        mx = _vec(getattr(box, "max_value", None))
    if mn is not None and mx is not None:
        return mn, mx
    get_min = getattr(box, "get_minimum", None)
    get_max = getattr(box, "get_maximum", None)
    if callable(get_min) and callable(get_max):
        try:
            return _vec(get_min()), _vec(get_max())
        except Exception:
            return None, None
    return None, None


def _actor_aabb(actor):
    """World AABB in UE units (cm). Non-colliding first: imported meshes often have no collision."""
    # dir(actor)  # get_components_bounding_box, get_actor_bounds
    method = getattr(actor, "get_components_bounding_box", None)
    if callable(method):
        for args in ((True, True), (True,), (False, True), (False,)):
            try:
                mn, mx = _box_minmax(method(*args))
            except TypeError:
                continue
            except Exception:
                break
            if mn is not None and mx is not None:
                return mn, mx, "get_components_bounding_box"

    method = getattr(actor, "get_actor_bounds", None)
    if callable(method):
        for args in ((False, True), (False,), (False, False)):
            try:
                mn, mx = _unpack_origin_extent(method(*args))
            except TypeError:
                continue
            except Exception:
                break
            if mn is not None and mx is not None:
                return mn, mx, "get_actor_bounds"
        try:
            import unreal

            origin = unreal.Vector()
            extent = unreal.Vector()
            # Older bindings take origin/extent as out-params rather than returning them.
            try:
                method(False, origin, extent, True)
            except TypeError:
                method(False, origin, extent)
            mn, mx = _unpack_origin_extent((origin, extent))
            if mn is not None and mx is not None:
                return mn, mx, "get_actor_bounds"
        except Exception:
            pass

    loc = _location(actor)
    if loc is not None:
        return loc, loc, "get_actor_location"
    return None, None, None


def _expand(acc_min, acc_max, mn, mx):
    if mn is None or mx is None:
        return acc_min, acc_max
    if acc_min is None or acc_max is None:
        return dict(mn), dict(mx)
    return (
        {
            "x": min(acc_min["x"], mn["x"]),
            "y": min(acc_min["y"], mn["y"]),
            "z": min(acc_min["z"], mn["z"]),
        },
        {
            "x": max(acc_max["x"], mx["x"]),
            "y": max(acc_max["y"], mx["y"]),
            "z": max(acc_max["z"], mx["z"]),
        },
    )


def _engine_version(unreal, errors):
    # dir(unreal.SystemLibrary)  # get_engine_version
    try:
        library = unreal.SystemLibrary
        getter = getattr(library, "get_engine_version", None)
        if callable(getter):
            version = getter()
            if version is not None and str(version):
                return str(version)
    except Exception as exc:
        _err(errors, "SystemLibrary.get_engine_version", exc)
    return None


def _all_actors(unreal, errors):
    # dir(unreal.EditorActorSubsystem)  # get_all_level_actors
    try:
        getter = getattr(unreal, "get_editor_subsystem", None)
        subsystem_type = getattr(unreal, "EditorActorSubsystem", None)
        if callable(getter) and subsystem_type is not None:
            subsystem = getter(subsystem_type)
            method = getattr(subsystem, "get_all_level_actors", None)
            if callable(method):
                actors = method()
                if actors is not None:
                    return [actor for actor in list(actors) if actor is not None]
    except Exception as exc:
        _err(errors, "EditorActorSubsystem.get_all_level_actors", exc)

    # dir(unreal.EditorLevelLibrary)  # get_all_level_actors
    try:
        library = getattr(unreal, "EditorLevelLibrary", None)
        method = getattr(library, "get_all_level_actors", None) if library else None
        if callable(method):
            actors = method()
            if actors is not None:
                return [actor for actor in list(actors) if actor is not None]
    except Exception as exc:
        _err(errors, "EditorLevelLibrary.get_all_level_actors", exc)

    errors.append(
        {
            "where": "list actors",
            "type": "RuntimeError",
            "error": "no EditorActorSubsystem or EditorLevelLibrary get_all_level_actors",
            "traceback": "",
        }
    )
    return None


def _dump():
    result = {
        "ok": False,
        "read_only": True,
        "engine_version": None,
        "actor_count": None,
        "actors": [],
        "tagged_part_count": 0,
        "untagged_labels": [],
        "wing_fuse_bounds": [],
        "span_cm": None,
        "span_axis": None,
        "span_min": None,
        "span_max": None,
        "span_x_cm": None,
        "span_y_cm": None,
        "errors": [],
    }
    errors = result["errors"]

    try:
        import unreal
    except Exception as exc:
        _err(errors, "import unreal", exc)
        result["error"] = "unreal module is not available (run inside the Unreal editor)"
        return result

    result["engine_version"] = _engine_version(unreal, errors)

    try:
        actors = _all_actors(unreal, errors)
    except Exception as exc:
        _err(errors, "list actors", exc)
        actors = None

    if actors is None:
        result["actor_count"] = None
        result["ok"] = False
        return result

    result["actor_count"] = len(actors)

    wing_min = wing_max = None
    wing_count = 0

    for index, actor in enumerate(actors):
        try:
            label = _label(actor)
        except Exception as exc:
            _err(errors, "actor[%s].label" % index, exc)
            label = "<unknown>"

        try:
            location = _location(actor)
        except Exception as exc:
            _err(errors, "actor[%s].location (%s)" % (index, label), exc)
            location = None

        try:
            tags = _tags(actor)
        except Exception as exc:
            _err(errors, "actor[%s].tags (%s)" % (index, label), exc)
            tags = []

        result["actors"].append({"label": label, "location": location, "tags": tags})

        if tags:
            result["tagged_part_count"] += 1
        else:
            result["untagged_labels"].append(label)

        lowered = label.lower()
        wants_bounds = ("wing_" in lowered) or ("fuse_" in lowered)
        if not wants_bounds:
            continue

        try:
            mn, mx, source = _actor_aabb(actor)
        except Exception as exc:
            _err(errors, "actor[%s].bounds (%s)" % (index, label), exc)
            mn, mx, source = None, None, None

        result["wing_fuse_bounds"].append(
            {
                "label": label,
                "min": mn,
                "max": mx,
                "source": source,
            }
        )

        if "wing_" in lowered and mn is not None and mx is not None:
            wing_min, wing_max = _expand(wing_min, wing_max, mn, mx)
            wing_count += 1

    if wing_min is not None and wing_max is not None and wing_count > 0:
        x_extent = wing_max["x"] - wing_min["x"]
        y_extent = wing_max["y"] - wing_min["y"]
        result["span_x_cm"] = x_extent
        result["span_y_cm"] = y_extent
        # Span is the larger of world X and Y on wing_* actors. Z is vertical in UE.
        if x_extent >= y_extent:
            result["span_axis"] = "X"
            result["span_cm"] = x_extent
            result["span_min"] = wing_min["x"]
            result["span_max"] = wing_max["x"]
        else:
            result["span_axis"] = "Y"
            result["span_cm"] = y_extent
            result["span_min"] = wing_min["y"]
            result["span_max"] = wing_max["y"]

    result["ok"] = result["actor_count"] is not None
    return result


def main():
    try:
        payload = _dump()
    except Exception as exc:
        payload = {
            "ok": False,
            "read_only": True,
            "engine_version": None,
            "actor_count": None,
            "actors": [],
            "tagged_part_count": 0,
            "untagged_labels": [],
            "wing_fuse_bounds": [],
            "span_cm": None,
            "span_axis": None,
            "span_min": None,
            "span_max": None,
            "span_x_cm": None,
            "span_y_cm": None,
            "error": "%s: %s" % (type(exc).__name__, exc),
            "traceback": traceback.format_exc(),
            "errors": [],
        }
    try:
        text = json.dumps(payload, indent=2, sort_keys=False, allow_nan=False)
    except Exception as exc:
        text = json.dumps(
            {
                "ok": False,
                "error": "json.dumps failed: %s: %s" % (type(exc).__name__, exc),
                "traceback": traceback.format_exc(),
            },
            indent=2,
        )
    print(text)


main()
