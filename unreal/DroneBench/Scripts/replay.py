"""Unreal editor telemetry replay. Not a plant: no forces, no 6DOF, no drag."""

from __future__ import annotations

import json
import math
import os

try:
    import unreal as _unreal_mod
except ImportError:
    _unreal_mod = None

# Repo folder `unreal/` is a namespace package on sys.path; require engine APIs.
if _unreal_mod is not None and any(
    hasattr(_unreal_mod, name)
    for name in ("get_editor_subsystem", "EditorActorSubsystem", "Vector", "Actor")
):
    unreal = _unreal_mod
else:
    unreal = None

# Visual only. Not a servo ratio and not a value from telemetry.
AILERON_DISPLAY_GAIN = 0.4
MPC_SCALAR = "LoadFactor"
_REL_CAD = "../../../../fixtures/c/titan_avenger_cad/simulation_run.json"
_REL_SYN = "../../../../fixtures/c/synthetic_vtail_demo/simulation_run.json"
_PART_HINTS = (
    "aileron",
    "wing",
    "fuse",
    "vtail",
    "taileron",
    "canopy",
    "motor",
)

_STATE = {
    "path": None,
    "run": None,
    "frames": [],
    "dt_s": None,
    "fidelity_tier": None,
    "playing": False,
    "rate": 1.0,
    "t": 0.0,
    "airframe": None,
    "aileron_L": None,
    "aileron_R": None,
    "aileron_rest": {},
    "mpc": None,
    "errors": [],
}


def ned_to_ue_cm(n, e, d):
    """NED metres -> Unreal left-handed Z-up centimetres: X north, Y east, Z up.

    Must match packages/sim/frames.py.
    """
    return (float(n) * 100.0, float(e) * 100.0, -float(d) * 100.0)


def apply_frame(frame):
    """Pose actors from one telemetry frame. Does not integrate."""
    if not isinstance(frame, dict):
        _error("apply_frame: frame is not an object")
        return
    if "t" in frame and frame["t"] is not None:
        _STATE["t"] = float(frame["t"])
    if unreal is None:
        return
    if _STATE.get("airframe") is None:
        _bind_scene()
    pos = frame.get("pos_ned")
    quat = frame.get("quat")
    actor = _STATE.get("airframe")
    if actor is not None and _is_vec3(pos) and _is_quat(quat):
        loc = ned_to_ue_cm(pos[0], pos[1], pos[2])
        _set_world_pose(actor, loc, quat)
    if "load_factor_n" in frame and frame["load_factor_n"] is not None:
        _set_mpc_load_factor(frame["load_factor_n"])
    if _is_quat(quat):
        _apply_aileron_display(quat)


def play():
    _STATE["playing"] = True
    _ensure_tick()


def pause():
    _STATE["playing"] = False


def scrub(t):
    frames = _STATE["frames"]
    if not frames:
        _error("scrub: no frames loaded")
        return
    t0 = float(frames[0]["t"])
    t1 = float(frames[-1]["t"])
    _STATE["t"] = min(t1, max(t0, float(t)))
    _STATE["playing"] = False
    apply_frame(_frame_at(_STATE["t"]))


def set_rate(rate):
    _STATE["rate"] = float(rate)


def load():
    """Load simulation_run.json and bind level actors. Re-run safe."""
    _STATE["errors"] = []
    _STATE["playing"] = False
    _STATE["airframe"] = None
    _STATE["aileron_L"] = None
    _STATE["aileron_R"] = None
    _STATE["aileron_rest"] = {}
    _STATE["mpc"] = None
    path = _resolve_run_path()
    with open(path, "r", encoding="utf-8") as handle:
        run = json.load(handle)
    if not isinstance(run, dict):
        raise ValueError("simulation_run.json must be an object")
    frames = run.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ValueError("simulation_run.json has no frames")
    meta = run.get("meta") if isinstance(run.get("meta"), dict) else {}
    _STATE["path"] = path
    _STATE["run"] = run
    _STATE["frames"] = frames
    _STATE["dt_s"] = meta.get("dt_s")
    _STATE["fidelity_tier"] = meta.get("fidelity_tier")
    _STATE["t"] = float(frames[0].get("t") or 0.0)
    _STATE["rate"] = 1.0
    if unreal is not None:
        _bind_scene()
        apply_frame(frames[0])
    return _summary()


# --- mapped-basis quat (must match packages/sim/frames.py) ---


def _quat_frd_ned_to_ue(quat):
    """Body-to-NED quat -> Unreal FRu scalar-first quat.

    Maps FRD forward/right/down through NED into UE forward/right/up.
    Must match packages/sim/frames.py quat_frd_ned_to_ue.
    """
    r_bn = _rot_from_quat(quat)
    fwd_n = _mv(r_bn, (1.0, 0.0, 0.0))
    right_n = _mv(r_bn, (0.0, 1.0, 0.0))
    down_n = _mv(r_bn, (0.0, 0.0, 1.0))
    fwd_ue = (fwd_n[0], fwd_n[1], -fwd_n[2])
    right_ue = (right_n[0], right_n[1], -right_n[2])
    up_ue = (-down_n[0], -down_n[1], down_n[2])
    r_ue = (
        (fwd_ue[0], right_ue[0], up_ue[0]),
        (fwd_ue[1], right_ue[1], up_ue[1]),
        (fwd_ue[2], right_ue[2], up_ue[2]),
    )
    return _quat_from_rot(r_ue)


def _mapped_basis_ue(quat):
    r_bn = _rot_from_quat(quat)
    fwd_n = _mv(r_bn, (1.0, 0.0, 0.0))
    right_n = _mv(r_bn, (0.0, 1.0, 0.0))
    down_n = _mv(r_bn, (0.0, 0.0, 1.0))
    fwd_ue = (fwd_n[0], fwd_n[1], -fwd_n[2])
    right_ue = (right_n[0], right_n[1], -right_n[2])
    up_ue = (-down_n[0], -down_n[1], down_n[2])
    return fwd_ue, right_ue, up_ue


def _euler_321(quat):
    """phi, theta, psi from scalar-first quat. Must match packages/sim/attitude.py."""
    w, x, y, z = (float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    phi = math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    sinp = 2.0 * (w * y - z * x)
    if sinp >= 1.0:
        theta = math.pi / 2.0
    elif sinp <= -1.0:
        theta = -math.pi / 2.0
    else:
        theta = math.asin(sinp)
    psi = math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return phi, theta, psi


def _rot_from_quat(quat):
    w, x, y, z = (float(quat[0]), float(quat[1]), float(quat[2]), float(quat[3]))
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return (
        (1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy)),
        (2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx)),
        (2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy)),
    )


def _mv(r, v):
    return (
        r[0][0] * v[0] + r[0][1] * v[1] + r[0][2] * v[2],
        r[1][0] * v[0] + r[1][1] * v[1] + r[1][2] * v[2],
        r[2][0] * v[0] + r[2][1] * v[1] + r[2][2] * v[2],
    )


def _quat_from_rot(r):
    m00, m01, m02 = r[0]
    m10, m11, m12 = r[1]
    m20, m21, m22 = r[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = 0.5 / math.sqrt(trace + 1.0)
        w = 0.25 / s
        x = (m21 - m12) * s
        y = (m02 - m20) * s
        z = (m10 - m01) * s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * math.sqrt(max(1e-15, 1.0 + m00 - m11 - m22))
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * math.sqrt(max(1e-15, 1.0 + m11 - m00 - m22))
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = 2.0 * math.sqrt(max(1e-15, 1.0 + m22 - m00 - m11))
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    return (w / n, x / n, y / n, z / n)


def _ue_rotator_from_frd_quat(quat):
    """FRD/NED quat -> Unreal Rotator via mapped basis.

    Must match packages/sim/frames.py. Euler dump is fallback only; Unreal is
    left-handed so a naive phi->roll map can invert bank.
    """
    fwd, right, up = _mapped_basis_ue(quat)
    try:
        # dir(unreal.MathLibrary)  # make_rotation_from_axes
        return unreal.MathLibrary.make_rotation_from_axes(
            unreal.Vector(fwd[0], fwd[1], fwd[2]),
            unreal.Vector(right[0], right[1], right[2]),
            unreal.Vector(up[0], up[1], up[2]),
        )
    except Exception:
        pass
    try:
        w, x, y, z = _quat_frd_ned_to_ue(quat)
        # dir(unreal.Quat)  # rotator; ctor is (x, y, z, w)
        return unreal.Quat(x, y, z, w).rotator()
    except Exception:
        pass
    # Fallback Euler (phi, theta, psi). Must match packages/sim/frames.py.
    phi, theta, psi = _euler_321(quat)
    return unreal.Rotator(
        math.degrees(theta),
        math.degrees(psi),
        math.degrees(phi),
    )


# --- playback ---


def _on_tick(*args):
    if not _STATE["playing"]:
        return
    frames = _STATE["frames"]
    if not frames:
        _STATE["playing"] = False
        return
    dt = float(args[0]) if args else 0.0
    t_end = float(frames[-1]["t"])
    _STATE["t"] = min(t_end, _STATE["t"] + dt * _STATE["rate"])
    apply_frame(_frame_at(_STATE["t"]))
    if _STATE["t"] >= t_end:
        _STATE["playing"] = False


def _ensure_tick():
    if unreal is None:
        _error("play: unreal module missing")
        return
    handle = getattr(unreal, "_dronebench_replay_tick", None)
    if handle is not None:
        return
    try:
        # dir(unreal)  # register_slate_post_tick_callback
        handle = unreal.register_slate_post_tick_callback(_on_tick)
        setattr(unreal, "_dronebench_replay_tick", handle)
    except Exception as exc:
        _error("register_slate_post_tick_callback: %s" % exc)


def _drop_stashed_tick():
    if unreal is None:
        return
    handle = getattr(unreal, "_dronebench_replay_tick", None)
    if handle is None:
        return
    try:
        # dir(unreal)  # unregister_slate_post_tick_callback
        unreal.unregister_slate_post_tick_callback(handle)
    except Exception:
        pass
    setattr(unreal, "_dronebench_replay_tick", None)


def _frame_at(t):
    frames = _STATE["frames"]
    if t <= float(frames[0]["t"]):
        return frames[0]
    if t >= float(frames[-1]["t"]):
        return frames[-1]
    lo = 0
    hi = len(frames) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if float(frames[mid]["t"]) <= t:
            lo = mid
        else:
            hi = mid
    a = frames[lo]
    b = frames[hi]
    span = float(b["t"]) - float(a["t"])
    if span <= 0.0:
        return b
    return _lerp_frame(a, b, (t - float(a["t"])) / span)


def _lerp_frame(a, b, u):
    frame = {"t": float(a["t"]) + (float(b["t"]) - float(a["t"])) * u}
    if _is_vec3(a.get("pos_ned")) and _is_vec3(b.get("pos_ned")):
        pa, pb = a["pos_ned"], b["pos_ned"]
        frame["pos_ned"] = [
            pa[0] + (pb[0] - pa[0]) * u,
            pa[1] + (pb[1] - pa[1]) * u,
            pa[2] + (pb[2] - pa[2]) * u,
        ]
    if _is_quat(a.get("quat")) and _is_quat(b.get("quat")):
        frame["quat"] = _slerp(a["quat"], b["quat"], u)
    for key in ("Va", "alpha", "beta", "load_factor_n", "power_w", "energy_wh_remaining"):
        if key in a and key in b and a[key] is not None and b[key] is not None:
            frame[key] = a[key] + (b[key] - a[key]) * u
    return frame


def _slerp(q0, q1, u):
    w0, x0, y0, z0 = (float(q0[0]), float(q0[1]), float(q0[2]), float(q0[3]))
    w1, x1, y1, z1 = (float(q1[0]), float(q1[1]), float(q1[2]), float(q1[3]))
    dot = w0 * w1 + x0 * x1 + y0 * y1 + z0 * z1
    if dot < 0.0:
        w1, x1, y1, z1 = -w1, -x1, -y1, -z1
        dot = -dot
    if dot > 0.9995:
        w = w0 + (w1 - w0) * u
        x = x0 + (x1 - x0) * u
        y = y0 + (y1 - y0) * u
        z = z0 + (z1 - z0) * u
    else:
        theta = math.acos(min(1.0, dot))
        s = math.sin(theta)
        a = math.sin((1.0 - u) * theta) / s
        b = math.sin(u * theta) / s
        w = w0 * a + w1 * b
        x = x0 * a + x1 * b
        y = y0 * a + y1 * b
        z = z0 * a + z1 * b
    n = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    return [w / n, x / n, y / n, z / n]


# --- path / scene ---


def _script_dir():
    here = globals().get("__file__")
    if isinstance(here, str) and os.path.isfile(here):
        return os.path.dirname(os.path.abspath(here))
    if unreal is not None:
        try:
            # dir(unreal.Paths)  # project_dir, convert_relative_path_to_full
            proj = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
            scripts = os.path.join(proj, "Scripts")
            if os.path.isdir(scripts):
                return os.path.abspath(scripts)
            return os.path.abspath(proj)
        except Exception:
            pass
    return os.getcwd()


def _resolve_run_path():
    env = os.environ.get("DRONEBENCH_RUN")
    if env:
        if os.path.isfile(env):
            return os.path.abspath(env)
        raise FileNotFoundError("DRONEBENCH_RUN is not a file: %s" % env)
    here = _script_dir()
    rels = (
        _REL_CAD,
        _REL_SYN,
        "../../../fixtures/c/titan_avenger_cad/simulation_run.json",
        "../../../fixtures/c/synthetic_vtail_demo/simulation_run.json",
        "../../fixtures/c/titan_avenger_cad/simulation_run.json",
        "../../fixtures/c/synthetic_vtail_demo/simulation_run.json",
    )
    seen = []
    for rel in rels:
        path = os.path.abspath(os.path.normpath(os.path.join(here, rel)))
        if path not in seen:
            seen.append(path)
        if os.path.isfile(path):
            return path
    cur = os.path.abspath(here)
    for _ in range(8):
        for name in (
            os.path.join("fixtures", "c", "titan_avenger_cad", "simulation_run.json"),
            os.path.join("fixtures", "c", "synthetic_vtail_demo", "simulation_run.json"),
        ):
            path = os.path.join(cur, name)
            if os.path.isfile(path):
                return os.path.abspath(path)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    raise FileNotFoundError(
        "simulation_run.json not found; set DRONEBENCH_RUN or add %s or %s (tried %s)"
        % (_REL_CAD, _REL_SYN, seen[:4])
    )


def _bind_scene():
    try:
        actors = _level_actors()
    except Exception as exc:
        _error("get_all_level_actors: %s" % exc)
        return
    _STATE["airframe"] = _find_airframe(actors)
    _STATE["aileron_L"] = _find_named(actors, "aileron_L")
    _STATE["aileron_R"] = _find_named(actors, "aileron_R")
    _STATE["aileron_rest"] = {}
    for key in ("aileron_L", "aileron_R"):
        obj = _STATE.get(key)
        if obj is None:
            continue
        rest = _get_rel_rot(obj)
        if rest is not None:
            _STATE["aileron_rest"][key] = rest
    try:
        _STATE["mpc"] = _find_mpc()
    except Exception as exc:
        _error("MPC: %s" % exc)
        _STATE["mpc"] = None
    if _STATE["airframe"] is None:
        _error("no actor named Airframe and no root with child parts")
    if _STATE["mpc"] is None:
        _error("no MaterialParameterCollection with LoadFactor")


def _level_actors():
    # dir(unreal)  # get_editor_subsystem
    # dir(unreal.EditorActorSubsystem)  # get_all_level_actors
    try:
        sub = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        return list(sub.get_all_level_actors())
    except Exception:
        # dir(unreal.EditorLevelLibrary)  # get_all_level_actors
        return list(unreal.EditorLevelLibrary.get_all_level_actors())


def _find_airframe(actors):
    for actor in actors:
        if _is_named(actor, "Airframe"):
            return actor
    best = None
    best_n = 0
    for actor in actors:
        kids = _attached(actor)
        n = 0
        for kid in kids:
            blob = " ".join(_tokens(kid)).lower()
            if any(hint in blob for hint in _PART_HINTS):
                n += 1
        if n > best_n:
            best = actor
            best_n = n
    if best is not None and best_n > 0:
        return best
    return None


def _find_named(actors, want):
    for actor in actors:
        if _is_named(actor, want):
            return actor
        try:
            # dir(unreal.Actor)  # get_components_by_class
            comps = actor.get_components_by_class(unreal.SceneComponent)
        except Exception:
            comps = []
        for comp in comps or []:
            if _is_named(comp, want):
                return comp
    return None


def _attached(actor):
    try:
        # dir(unreal.Actor)  # get_attached_actors
        kids = actor.get_attached_actors(True, True)
        return list(kids) if kids else []
    except Exception:
        return []


def _tokens(obj):
    bits = []
    for name in ("get_actor_label", "get_name"):
        getter = getattr(obj, name, None)
        if callable(getter):
            try:
                bits.append(str(getter()))
            except Exception:
                pass
    for attr in ("tags", "component_tags"):
        if hasattr(obj, attr):
            try:
                bits.extend(str(tag) for tag in getattr(obj, attr))
            except Exception:
                pass
    return bits


def _is_named(obj, want):
    want_l = want.lower()
    for bit in _tokens(obj):
        low = bit.lower()
        if low == want_l or low.startswith(want_l + "_") or low.endswith("_" + want_l):
            return True
    has_tag = getattr(obj, "actor_has_tag", None)
    if callable(has_tag):
        try:
            if has_tag(want):
                return True
        except Exception:
            pass
    return False


def _label(obj):
    if obj is None:
        return None
    bits = _tokens(obj)
    return bits[0] if bits else str(obj)


def _set_world_pose(actor, loc_cm, quat):
    vec = unreal.Vector(loc_cm[0], loc_cm[1], loc_cm[2])
    rot = _ue_rotator_from_frd_quat(quat)
    try:
        # dir(unreal.Actor)  # set_actor_location, set_actor_rotation
        actor.set_actor_location(vec, False, True)
        actor.set_actor_rotation(rot, True)
    except Exception as exc:
        _error("set pose: %s" % exc)


def _apply_aileron_display(quat):
    """Rotate aileron_L / aileron_R by DISPLAY gain times roll. Illustrative."""
    phi, _theta, _psi = _euler_321(quat)
    delta_deg = AILERON_DISPLAY_GAIN * math.degrees(phi)
    # Opposite signs: right-wing-down shows left TE up, right TE down.
    _set_aileron_pitch("aileron_L", -delta_deg)
    _set_aileron_pitch("aileron_R", delta_deg)


def _set_aileron_pitch(key, pitch_deg):
    obj = _STATE.get(key)
    rest = _STATE.get("aileron_rest", {}).get(key)
    if obj is None or rest is None:
        return
    try:
        _set_rel_rot(
            obj,
            unreal.Rotator(rest[0] + pitch_deg, rest[1], rest[2]),
        )
    except Exception as exc:
        _error("%s deflection: %s" % (key, exc))


def _get_rel_rot(obj):
    try:
        if hasattr(obj, "get_relative_rotation"):
            rot = obj.get_relative_rotation()
        elif hasattr(obj, "get_actor_relative_rotation"):
            rot = obj.get_actor_relative_rotation()
        else:
            return None
        return (float(rot.pitch), float(rot.yaw), float(rot.roll))
    except Exception:
        return None


def _set_rel_rot(obj, rot):
    if hasattr(obj, "set_relative_rotation"):
        obj.set_relative_rotation(rot)
        return
    if hasattr(obj, "set_actor_relative_rotation"):
        obj.set_actor_relative_rotation(rot)
        return
    raise AttributeError("no relative rotation setter")


def _editor_world():
    try:
        # dir(unreal.UnrealEditorSubsystem)  # get_editor_world
        return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    except Exception:
        pass
    try:
        return unreal.EditorLevelLibrary.get_editor_world()
    except Exception:
        return None


def _find_mpc():
    known = (
        "/Game/DroneBench/MPC_LoadFactor",
        "/Game/MPC_LoadFactor",
        "/Game/DroneBench/LoadFactor",
    )
    # dir(unreal.EditorAssetLibrary)  # load_asset, list_assets, does_asset_exist
    for path in known:
        try:
            if unreal.EditorAssetLibrary.does_asset_exist(path):
                asset = unreal.EditorAssetLibrary.load_asset(path)
                if asset is not None:
                    return asset
        except Exception:
            pass
    try:
        paths = unreal.EditorAssetLibrary.list_assets("/Game/", True, False)
    except Exception:
        return None
    fallback = None
    for path in paths or []:
        try:
            asset = unreal.EditorAssetLibrary.load_asset(path)
        except Exception:
            continue
        if asset is None:
            continue
        try:
            if not isinstance(asset, unreal.MaterialParameterCollection):
                continue
        except Exception:
            name = type(asset).__name__
            if "MaterialParameterCollection" not in name:
                continue
        blob = (str(asset.get_name()) + " " + str(path)).lower()
        if "loadfactor" in blob.replace("_", "") or "load_factor" in blob:
            return asset
        fallback = asset
    return fallback


def _set_mpc_load_factor(value):
    mpc = _STATE.get("mpc")
    if mpc is None or unreal is None:
        return
    world = _editor_world()
    try:
        # dir(unreal.MaterialLibrary)  # set_scalar_parameter_value
        if world is not None:
            unreal.MaterialLibrary.set_scalar_parameter_value(
                world, mpc, MPC_SCALAR, float(value)
            )
        else:
            unreal.MaterialLibrary.set_scalar_parameter_value(
                mpc, MPC_SCALAR, float(value)
            )
    except TypeError:
        try:
            unreal.MaterialLibrary.set_scalar_parameter_value(
                mpc, MPC_SCALAR, float(value)
            )
        except Exception as exc:
            _error("MPC LoadFactor: %s" % exc)
    except Exception as exc:
        _error("MPC LoadFactor: %s" % exc)


def _is_vec3(value):
    return isinstance(value, (list, tuple)) and len(value) == 3


def _is_quat(value):
    return isinstance(value, (list, tuple)) and len(value) == 4


def _error(message):
    if message not in _STATE["errors"]:
        _STATE["errors"].append(message)


def _conversion_samples():
    phi = math.radians(30.0)
    q_roll = [math.cos(phi * 0.5), math.sin(phi * 0.5), 0.0, 0.0]
    samples = {
        "ned_to_ue_cm": {
            "identity_origin": {
                "pos_ned_m": [0.0, 0.0, 0.0],
                "ue_cm": list(ned_to_ue_cm(0.0, 0.0, 0.0)),
            },
            "nonzero_translation": {
                "pos_ned_m": [1.0, 2.0, 3.0],
                "ue_cm": list(ned_to_ue_cm(1.0, 2.0, 3.0)),
            },
            "ned_down_negative_is_altitude": {
                "pos_ned_m": [0.0, 0.0, -120.0],
                "ue_cm": list(ned_to_ue_cm(0.0, 0.0, -120.0)),
            },
        },
        "quat_mapped_basis": {
            "identity": {
                "quat_frd_ned_wxyz": [1.0, 0.0, 0.0, 0.0],
                "quat_ue_wxyz": list(_quat_frd_ned_to_ue([1.0, 0.0, 0.0, 0.0])),
            },
            "right_wing_down_30deg": {
                "quat_frd_ned_wxyz": list(q_roll),
                "quat_ue_wxyz": list(_quat_frd_ned_to_ue(q_roll)),
                "note": "positive FRD roll must lower the +Y wing in Unreal Z",
            },
        },
    }
    frames = _STATE.get("frames") or []
    if frames:
        first = frames[0]
        pos = first.get("pos_ned")
        quat = first.get("quat")
        sample = {"t": first.get("t")}
        if _is_vec3(pos):
            sample["pos_ned_m"] = list(pos)
            sample["ue_cm"] = list(ned_to_ue_cm(pos[0], pos[1], pos[2]))
        if _is_quat(quat):
            sample["quat_frd_ned_wxyz"] = list(quat)
            sample["quat_ue_wxyz"] = list(_quat_frd_ned_to_ue(quat))
        samples["first_frame"] = sample
        turn = None
        for frame in frames:
            n = frame.get("load_factor_n")
            if n is not None and n > 1.0 and _is_quat(frame.get("quat")):
                turn = frame
                break
        if turn is not None:
            tpos = turn.get("pos_ned")
            tq = turn.get("quat")
            turn_sample = {
                "t": turn.get("t"),
                "load_factor_n": turn.get("load_factor_n"),
            }
            if _is_vec3(tpos):
                turn_sample["pos_ned_m"] = list(tpos)
                turn_sample["ue_cm"] = list(ned_to_ue_cm(tpos[0], tpos[1], tpos[2]))
            if _is_quat(tq):
                turn_sample["quat_frd_ned_wxyz"] = list(tq)
                turn_sample["quat_ue_wxyz"] = list(_quat_frd_ned_to_ue(tq))
                phi, theta, psi = _euler_321(tq)
                turn_sample["euler_321_rad"] = [phi, theta, psi]
            samples["first_load_factor_gt_1"] = turn_sample
    return samples


def _summary():
    frames = _STATE.get("frames") or []
    t0 = frames[0]["t"] if frames else None
    t1 = frames[-1]["t"] if frames else None
    return {
        "script": "replay.py",
        "path": _STATE.get("path"),
        "loaded_frames": len(frames),
        "dt_s": _STATE.get("dt_s"),
        "fidelity_tier": _STATE.get("fidelity_tier"),
        "t_range_s": [t0, t1],
        "airframe": _label(_STATE.get("airframe")),
        "aileron_L": _label(_STATE.get("aileron_L")),
        "aileron_R": _label(_STATE.get("aileron_R")),
        "mpc": _label(_STATE.get("mpc")),
        "notes": [
            "surface deflection is illustrative",
            "telemetry replay only; no 6DOF, no drag, no force integration",
        ],
        "conversion_samples": _conversion_samples(),
        "errors": list(_STATE.get("errors") or []),
    }


def _emit(payload):
    text = json.dumps(payload, indent=2)
    print(text)
    if unreal is not None:
        try:
            unreal.log(text)
        except Exception:
            pass


def _boot():
    _drop_stashed_tick()
    try:
        payload = load()
    except Exception as exc:
        payload = _summary()
        payload["errors"] = payload.get("errors") or []
        payload["errors"].append("%s: %s" % (type(exc).__name__, exc))
    _emit(payload)
    return payload


_boot()
