"""Read-only ExecuteFile dump. Prints one JSON object. Does not write Content/."""
import json, traceback

try:
    import unreal as _u
except ImportError:
    _u = None
unreal = _u if _u is not None and hasattr(_u, "SystemLibrary") else None

def _label(a):
    for n in ("get_actor_label", "get_actor_name", "get_name"):
        g = getattr(a, n, None)
        try:
            t = g() if callable(g) else None
            if t:
                return str(t)
        except Exception:
            pass
    return ""

def _cls(a):
    try:
        g = getattr(a.get_class(), "get_name", None)
        return str(g()) if callable(g) else type(a).__name__
    except Exception:
        return type(a).__name__

def _xyz(v):
    try:
        return {"x": float(v.x), "y": float(v.y), "z": float(v.z)}
    except Exception:
        return None

def _loc(a):
    try:
        return _xyz(a.get_actor_location())
    except Exception:
        return None

def _kids(a):
    try:
        k = a.get_attached_actors(True, True)
        return len(list(k)) if k else 0
    except Exception:
        return 0

def _is_sm(a):
    try:
        if unreal is not None and isinstance(a, unreal.StaticMeshActor):
            return True
    except Exception:
        pass
    return "staticmeshactor" in _cls(a).lower()

def _aabb(a):
    try:
        b = a.get_components_bounding_box(True, True)
        lo, hi = _xyz(getattr(b, "min", None)), _xyz(getattr(b, "max", None))
        if lo and hi:
            return lo, hi
    except Exception:
        pass
    try:
        pair = a.get_actor_bounds(False)
        o, e = _xyz(pair[0]), _xyz(pair[1])
        if o and e:
            return {"x": o["x"] - e["x"], "y": o["y"] - e["y"], "z": o["z"] - e["z"]}, {"x": o["x"] + e["x"], "y": o["y"] + e["y"], "z": o["z"] + e["z"]}
    except Exception:
        pass
    p = _loc(a)
    return (p, p) if p else (None, None)

def _all():
    try:
        sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return [x for x in list(sub.get_all_level_actors() or []) if x]
    except Exception:
        return [x for x in list(unreal.EditorLevelLibrary.get_all_level_actors() or []) if x]

def dump():
    err, ver, recs, n_sm, lo, hi = [], None, [], 0, None, None
    if unreal is None:
        err.append("unreal editor APIs missing")
        actors = []
    else:
        try:
            ver = str(unreal.SystemLibrary.get_engine_version())
        except Exception as exc:
            err.append("engine_version: %s" % exc)
        try:
            actors = _all()
        except Exception as exc:
            err.append("get_all_level_actors: %s" % exc)
            actors = []
    for a in actors:
        recs.append({"label": _label(a), "class": _cls(a), "location": _loc(a), "attached_child_count": _kids(a)})
        if not _is_sm(a):
            continue
        n_sm += 1
        mn, mx = _aabb(a)
        if mn is None or mx is None:
            continue
        if lo is None:
            lo, hi = dict(mn), dict(mx)
        else:
            lo = {"x": min(lo["x"], mn["x"]), "y": min(lo["y"], mn["y"]), "z": min(lo["z"], mn["z"])}
            hi = {"x": max(hi["x"], mx["x"]), "y": max(hi["y"], mx["y"]), "z": max(hi["z"], mx["z"])}
    aabb = None
    if lo and hi:
        aabb = {"min": lo, "max": hi, "extent": {"x": hi["x"] - lo["x"], "y": hi["y"] - lo["y"], "z": hi["z"] - lo["z"]}, "unit": "cm"}
    listed = unreal is not None and not any("get_all_level_actors" in e for e in err)
    return {"ok": listed, "script": "demo_inspect.py", "engine_version": ver, "actor_count": None if not listed else len(actors),
            "actors": recs, "static_mesh_actor_count": n_sm, "aabb": aabb, "looks_fused": n_sm == 1, "errors": err}

try:
    payload = dump()
except Exception as exc:
    payload = {"ok": False, "script": "demo_inspect.py", "errors": ["%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc())]}
print(json.dumps(payload, indent=2, default=str), flush=True)
