"""Prescribed -Y translation of the imported airframe. Renderer only: no forces."""
from __future__ import annotations
import json, traceback
try:
    import unreal as _ue
except ImportError:
    _ue = None
unreal = _ue if _ue is not None and hasattr(_ue, "Vector") else None
# Visual only (cm/s). Not a flight-dynamics speed.
SPEED_CM_S, LOOP_S, _TICK = 200.0, 8.0, "_dronebench_demo_forward_tick"
_PART = ("fuse", "wing", "titan", "airframe", "vtail", "taileron", "canopy", "motor", "hatch", "aileron")
_SKIP = ("voidsun", "directionallight", "worldsettings", "playerstart")
_STATE = {"playing": False, "t": 0.0, "movers": [], "homes": [], "errors": []}

def _error(msg):
    if msg not in _STATE["errors"]:
        _STATE["errors"].append(msg)

def _tokens(obj):
    bits = []
    for name in ("get_actor_label", "get_name"):
        fn = getattr(obj, name, None)
        if callable(fn):
            try:
                bits.append(str(fn()))
            except Exception:
                pass
    for attr in ("tags", "component_tags"):
        if hasattr(obj, attr):
            try:
                bits.extend(str(t) for t in getattr(obj, attr))
            except Exception:
                pass
    return bits

def _label(obj):
    bits = _tokens(obj) if obj is not None else []
    return bits[0] if bits else None

def _is_named(obj, want):
    want_l = want.lower()
    return any(b.lower() == want_l or b.lower().startswith(want_l + "_") or b.lower().endswith("_" + want_l) for b in _tokens(obj))

def _is_part(obj):
    blob = " ".join(_tokens(obj)).lower()
    return "part_id=" in blob or any(h in blob for h in _PART)

def _level_actors():
    # dir(unreal.EditorActorSubsystem)  # get_all_level_actors
    try:
        return [a for a in list(unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() or []) if a]
    except Exception:
        try:
            return [a for a in list(unreal.EditorLevelLibrary.get_all_level_actors() or []) if a]
        except Exception as exc:
            _error("get_all_level_actors: %s" % exc)
            return []

def _attached(actor):
    try:
        kids = actor.get_attached_actors(True, True)
        return list(kids) if kids else []
    except Exception:
        return []

def _under(actor, root):
    seen, cur = set(), actor
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if cur is root:
            return True
        fn = getattr(cur, "get_attach_parent_actor", None)
        try:
            cur = fn() if callable(fn) else None
        except Exception:
            return False
    return False

def _find_airframe(actors):
    for actor in actors:
        if _is_named(actor, "Airframe") or _is_named(actor, "Titan"):
            return actor
    best, nbest = None, 0
    for actor in actors:
        n = sum(1 for kid in _attached(actor) if _is_part(kid))
        if n > nbest:
            best, nbest = actor, n
    if nbest:
        return best
    return next((a for a in actors if "titan" in " ".join(_tokens(a)).lower() or "airframe" in " ".join(_tokens(a)).lower()), None)

def _class_name(obj):
    try:
        return str(obj.get_class().get_name())
    except Exception:
        return type(obj).__name__

def _skip_fallback(actor):
    hay = (" ".join(_tokens(actor)) + " " + _class_name(actor)).lower()
    return any(k in hay for k in _SKIP)

def _has_static_mesh(actor):
    try:
        if isinstance(actor, unreal.StaticMeshActor):
            return True
    except Exception:
        pass
    if "staticmeshactor" in _class_name(actor).lower():
        return True
    try:
        # dir(actor)  # get_components_by_class
        comps = actor.get_components_by_class(unreal.StaticMeshComponent)
        return bool(list(comps or []))
    except Exception:
        return False

def _loc(actor):
    try:
        v = actor.get_actor_location()
        return (float(v.x), float(v.y), float(v.z))
    except Exception as exc:
        _error("get_actor_location: %s" % exc)
        return None

def _set_loc(actor, xyz):
    vec = unreal.Vector(float(xyz[0]), float(xyz[1]), float(xyz[2]))
    try:
        # dir(unreal.Actor)  # set_actor_location
        actor.set_actor_location(vec, False, True)
    except TypeError:
        actor.set_actor_location(vec, False)

def _bind():
    _STATE["movers"], _STATE["homes"] = [], []
    if unreal is None:
        _error("unreal editor APIs missing")
        return
    actors = _level_actors()
    root = _find_airframe(actors)
    parts = [a for a in actors if _is_part(a)]
    movers = ([root] + [p for p in parts if p is not root and not _under(p, root)]) if root else list(parts)
    if not movers:
        movers = [a for a in actors if _has_static_mesh(a) and not _skip_fallback(a)]
    homes = [_loc(a) for a in movers]
    if any(h is None for h in homes):
        _error("missing location on a mover")
        movers = [a for a, h in zip(movers, homes) if h is not None]
        homes = [h for h in homes if h is not None]
    _STATE["movers"], _STATE["homes"] = movers, homes
    if not movers:
        _error("no actor named Airframe and no fuse/wing/titan/airframe parts")

def _on_tick(*args):
    if not _STATE["playing"]:
        return
    dt = max(0.0, min(float(args[0]) if args else 0.0, 0.25))
    _STATE["t"] = (_STATE["t"] + dt) % LOOP_S
    dx = SPEED_CM_S * _STATE["t"]
    for actor, home in zip(_STATE["movers"], _STATE["homes"]):
        try:
            # Nose is UE -Y (AABB length on Y, span on X). Prescribed, not a plant.
            _set_loc(actor, (home[0], home[1] - dx, home[2]))
        except Exception as exc:
            _error("set_actor_location: %s" % exc)

def _ensure_tick():
    if getattr(unreal, _TICK, None) is not None:
        return True
    try:
        # dir(unreal)  # register_slate_post_tick_callback
        setattr(unreal, _TICK, unreal.register_slate_post_tick_callback(_on_tick))
        return True
    except Exception as exc:
        _error("register_slate_post_tick_callback: %s" % exc)
        return False

def _drop_tick():
    handle = getattr(unreal, _TICK, None) if unreal is not None else None
    if handle is None:
        return
    try:
        unreal.unregister_slate_post_tick_callback(handle)
    except Exception:
        pass
    setattr(unreal, _TICK, None)  # dir(unreal)  # unregister_slate_post_tick_callback

def _summary():
    movers = _STATE["movers"]
    labels = [_label(a) for a in movers]
    loc = _loc(movers[0]) if movers else None
    return {
        "ok": bool(movers) and getattr(unreal, _TICK, None) is not None,
        "actor": labels[0] if len(labels) == 1 else (labels or None),
        "location": None if loc is None else {"x": loc[0], "y": loc[1], "z": loc[2]},
        "playing": _STATE["playing"],
        "errors": list(_STATE["errors"]),
    }

def start():
    """Editor-world tick. Does not start PIE. Prescribed +X only."""
    if not _STATE["movers"]:
        _STATE["errors"] = []
        _bind()
    _STATE["playing"] = bool(_STATE["movers"])
    _ensure_tick() if _STATE["playing"] else _error("start: no movers")
    payload = _summary()
    print(json.dumps(payload, indent=2, default=str), flush=True)
    return payload

def stop():
    _STATE["playing"] = False
    payload = _summary()
    payload["ok"] = True
    print(json.dumps(payload, indent=2, default=str), flush=True)
    return payload

_drop_tick()
_STATE.update({"playing": False, "t": 0.0, "errors": []})
try:
    _bind()
    start()
except Exception as exc:
    payload = _summary()
    payload["ok"] = False
    payload["errors"].append("%s: %s\n%s" % (type(exc).__name__, exc, traceback.format_exc()))
    print(json.dumps(payload, indent=2, default=str), flush=True)
