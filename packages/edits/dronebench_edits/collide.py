"""Interference and propeller-clearance checks for an edited reconstruction (A3c).

Implements the `Collider` protocol in `api.py`. One `RoundTripCheck` per rule:

| name | meaning |
|---|---|
| `collision_declared_engagement` | mating/nesting depth for pairs that are *allowed* to overlap. Always `passed=True` — it is evidence, not a verdict. |
| `collision_undeclared_interference` | two parts that nobody declared may overlap actually do, deeper than the tolerance. `passed=False` blocks the edit. |
| `propeller_clearance` | minimum distance from the propeller swept volume to every airframe part. `passed=False` below `prop_clearance_min_m`. |
| `verified_movement_unknown` | an *evidence* gap, not a geometric one: a moved part whose retention / harness / mount interface is not known, so "it still fits and stays put" cannot be verified. |
| `collision_geometry_unusable` | a part could not be tessellated, or its mesh is degenerate / not closed, so it was excluded from the measurements. |
| `collision_check_error` | the check itself could not run. Returned instead of raising. |

Architecture §6: collision checks distinguish intended mating engagement from unintended
interference, the propeller swept volume is checked against the airframe, and an unknown
retention / harness / structural interface blocks a verified-movement claim. Nothing here
invents a mating pair from proximity — a pair is declared or it is not.

The Avenger is a **pusher**. The propeller axis is taken from the motor/prop envelope in
`params` (or from the prop part's own parameters), never assumed.
"""
from __future__ import annotations

import fnmatch
import math
from typing import Any, Iterable, Optional

import numpy as np

from dronebench_contracts.models import RoundTripCheck

__all__ = ["check", "clear_cache", "cache_stats"]

# ---------------------------------------------------------------- defaults

DEFAULT_INTERFERENCE_TOLERANCE_M = 0.0005
DEFAULT_PROP_CLEARANCE_MIN_M = 0.005
_MAX_SURFACE_SAMPLES = 400
_MAX_VERTEX_SAMPLES = 1500
_SAMPLE_SEED = 20260919
_CACHE_LIMIT = 256

# A cadquery solid in this project is built in millimetres; the API speaks metres.
_CQ_TO_M = 1e-3

# Categories that are not airframe structure for the propeller sweep check.
_PROP_EXEMPT_CATEGORIES = {"prop", "propeller"}

_CACHE: dict[tuple[str, str], Any] = {}
_CACHE_HITS = 0
_CACHE_MISSES = 0


def clear_cache() -> None:
    """Drop the tessellation cache (tests, or a new design)."""
    global _CACHE_HITS, _CACHE_MISSES
    _CACHE.clear()
    _CACHE_HITS = _CACHE_MISSES = 0


def cache_stats() -> dict[str, int]:
    return {"entries": len(_CACHE), "hits": _CACHE_HITS, "misses": _CACHE_MISSES}


# ---------------------------------------------------------------- part adapters

class _Part:
    """One tessellated part: id, category, trimesh in metres, or why there is none."""

    __slots__ = ("part_id", "category", "mesh", "problem")

    def __init__(self, part_id: str, category: str, mesh: Any, problem: str = ""):
        self.part_id = part_id
        self.category = category
        self.mesh = mesh
        self.problem = problem

    @property
    def usable(self) -> bool:
        return self.mesh is not None and not self.problem


def _model_parts(model: Any) -> list[Any]:
    if model is None:
        return []
    parts = getattr(model, "parts", None)
    if parts is None and isinstance(model, dict):
        parts = model.get("parts")
    if parts is None:
        parts = model
    if isinstance(parts, dict):
        return list(parts.values())
    if isinstance(parts, (list, tuple)):
        return list(parts)
    return []


def _part_id_of(raw: Any) -> str:
    for attr in ("part_id", "id", "name"):
        v = getattr(raw, attr, None)
        if isinstance(v, str) and v:
            return v
    if isinstance(raw, dict):
        for key in ("part_id", "id", "name"):
            v = raw.get(key)
            if isinstance(v, str) and v:
                return v
    return f"part_{id(raw):x}"


def _category_of(raw: Any) -> str:
    v = getattr(raw, "category", None)
    if v is None and isinstance(raw, dict):
        v = raw.get("category")
    return str(v or "other")


def _signature(raw: Any) -> str:
    """A cheap shape signature: the same solid must hash the same, a regenerated one must not."""
    solid = getattr(raw, "solid", None)
    if solid is not None:
        # Volume and centroid, never the bounding box: tessellating a shape attaches a
        # triangulation to it and OCCT then reports a *different* (tighter) box, which would
        # invalidate the cache entry the tessellation just filled.
        try:
            c = solid.Center()
            return "cq:" + ":".join(f"{v:.9g}" for v in (solid.Volume(), c.x, c.y, c.z))
        except Exception:  # pragma: no cover - broken solid, handled downstream
            return f"cq:unreadable:{id(solid):x}"
    mesh = _raw_trimesh(raw)
    if mesh is not None:
        try:
            return "tm:" + ":".join(
                f"{v:.9g}" for v in (float(len(mesh.faces)), *np.asarray(mesh.bounds).ravel().tolist())
            )
        except Exception:  # pragma: no cover
            return f"tm:unreadable:{id(mesh):x}"
    return f"obj:{id(raw):x}"


def _raw_trimesh(raw: Any) -> Any:
    import trimesh

    for attr in ("placed_mesh", "mesh", "trimesh"):
        v = getattr(raw, attr, None)
        if callable(v):
            try:
                v = v()
            except Exception:
                v = None
        if isinstance(v, trimesh.Trimesh):
            return v
    if isinstance(raw, trimesh.Trimesh):
        return raw
    return None


def _tessellate(raw: Any) -> tuple[Any, str]:
    """(trimesh in metres, problem). Never raises."""
    import trimesh

    existing = _raw_trimesh(raw)
    if existing is not None:
        mesh = existing.copy()
        return _validate(mesh)

    solid = getattr(raw, "solid", None)
    if solid is None:
        return None, "no solid and no mesh on the part"
    try:
        verts, tris = solid.tessellate(0.1)   # 0.1 mm chord deviation
    except Exception as exc:
        return None, f"tessellation failed: {exc}"
    if not verts or not tris:
        return None, "tessellation produced an empty mesh"
    try:
        v = np.asarray([[p.x, p.y, p.z] for p in verts], dtype=float) * _CQ_TO_M
        f = np.asarray(tris, dtype=np.int64)
        mesh = trimesh.Trimesh(vertices=v, faces=f, process=True)
    except Exception as exc:
        return None, f"mesh assembly failed: {exc}"
    return _validate(mesh)


def _validate(mesh: Any) -> tuple[Any, str]:
    try:
        if len(mesh.faces) == 0 or len(mesh.vertices) == 0:
            return None, "empty mesh (no faces)"
        if not np.isfinite(mesh.vertices).all():
            return None, "mesh has non-finite vertices"
        extent = float(np.max(mesh.extents)) if mesh.extents is not None else 0.0
        if not math.isfinite(extent) or extent <= 0.0:
            return None, "degenerate mesh (zero extent)"
    except Exception as exc:
        return None, f"mesh inspection failed: {exc}"
    return mesh, ""


def _collect(model: Any) -> list[_Part]:
    global _CACHE_HITS, _CACHE_MISSES
    out: list[_Part] = []
    for raw in _model_parts(model):
        pid = _part_id_of(raw)
        key = (pid, _signature(raw))
        if key in _CACHE:
            _CACHE_HITS += 1
            mesh, problem = _CACHE[key]
        else:
            _CACHE_MISSES += 1
            mesh, problem = _tessellate(raw)
            if len(_CACHE) >= _CACHE_LIMIT:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = (mesh, problem)
        out.append(_Part(pid, _category_of(raw), mesh, problem))
    return out


# ---------------------------------------------------------------- manifest adapters

def _manifest_occurrences(manifest: Any) -> dict[str, dict[str, Any]]:
    """part_id -> {allowed_overlap_with, material_status, mass_status, labels, category}."""
    parts: Iterable[Any] = ()
    if manifest is None:
        return {}
    got = getattr(manifest, "parts", None)
    if got is None and isinstance(manifest, dict):
        got = manifest.get("parts")
    if isinstance(got, dict):
        parts = list(got.values())
    elif isinstance(got, (list, tuple)):
        parts = got

    out: dict[str, dict[str, Any]] = {}
    for occ in parts:
        pid = _part_id_of(occ)
        out[pid] = {
            "allowed_overlap_with": list(_field(occ, "allowed_overlap_with") or []),
            "mirror_of": _field(occ, "mirror_of"),
            "category": _category_of(occ),
            "labels": dict(_field(occ, "labels") or {}),
            "material_status": _claim_status(_field(occ, "material")),
            "mass_status": _claim_status(_field(occ, "mass_kg")),
            "function_status": _claim_status(_field(occ, "function")),
        }
    return out


def _field(obj: Any, name: str) -> Any:
    v = getattr(obj, name, None)
    if v is None and isinstance(obj, dict):
        v = obj.get(name)
    return v


def _claim_status(claim: Any) -> str:
    if claim is None:
        return "unknown"
    status = _field(claim, "status")
    if status is None:
        return "unknown"
    return str(getattr(status, "value", status))


# ---------------------------------------------------------------- declared pairs

def _policy_number(policy: dict[str, Any], key: str, default: float) -> float:
    """`key` at the top level, or under `clearance:` — A3b's `edit_policy.yaml` nests it there."""
    for holder in (policy, policy.get("clearance") or {}, policy.get("collision") or {}):
        if isinstance(holder, dict) and holder.get(key) is not None:
            try:
                return float(holder[key])
            except (TypeError, ValueError):
                break
    return float(default)


def _declared_pattern_pairs(policy: dict[str, Any]) -> list[tuple[str, str]]:
    policy = policy or {}
    raw = policy.get("declared_overlaps")
    if raw is None:
        # `edit_policy.yaml` spells it `declared_overlap_pairs`; both are accepted.
        raw = policy.get("declared_overlap_pairs")
    raw = raw or []
    pairs: list[tuple[str, str]] = []
    for entry in raw:
        if isinstance(entry, dict):
            a, b = entry.get("a"), entry.get("b")
            if a is None or b is None:
                both = entry.get("parts") or entry.get("pair") or []
                if len(both) >= 2:
                    a, b = both[0], both[1]
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            a, b = entry[0], entry[1]
        else:
            continue
        if isinstance(a, str) and isinstance(b, str):
            pairs.append((a, b))
    return pairs


def _is_declared(a: str, b: str, occs: dict[str, dict[str, Any]],
                 patterns: list[tuple[str, str]]) -> tuple[bool, str]:
    for x, y in ((a, b), (b, a)):
        allowed = occs.get(x, {}).get("allowed_overlap_with", [])
        for entry in allowed:
            if entry == y or fnmatch.fnmatch(y, entry):
                return True, f"{x}.allowed_overlap_with matches {y}"
    for pa, pb in patterns:
        if (fnmatch.fnmatch(a, pa) and fnmatch.fnmatch(b, pb)) or \
           (fnmatch.fnmatch(b, pa) and fnmatch.fnmatch(a, pb)):
            return True, f"policy.declared_overlaps [{pa}, {pb}]"
    return False, ""


# ---------------------------------------------------------------- geometry measurement

def _aabb_gap(a: Any, b: Any) -> float:
    """Separation between two AABBs: 0 when they overlap, else the largest axis gap."""
    lo_a, hi_a = a.bounds
    lo_b, hi_b = b.bounds
    gaps = np.maximum(lo_a - hi_b, lo_b - hi_a)
    return float(max(0.0, gaps.max()))


def _sample_points(mesh: Any, n_surface: int = _MAX_SURFACE_SAMPLES) -> np.ndarray:
    verts = np.asarray(mesh.vertices, dtype=float)
    if len(verts) > _MAX_VERTEX_SAMPLES:
        idx = np.linspace(0, len(verts) - 1, _MAX_VERTEX_SAMPLES).astype(int)
        verts = verts[idx]
    try:
        import trimesh.sample as _s

        surf, _ = _s.sample_surface(mesh, n_surface, seed=_SAMPLE_SEED)
        return np.vstack([verts, np.asarray(surf, dtype=float)])
    except Exception:
        return verts


def _closed(mesh: Any) -> bool:
    try:
        return bool(mesh.is_watertight and mesh.is_volume)
    except Exception:
        return False


def _one_way_depth(a: Any, b: Any) -> Optional[float]:
    """Deepest point of A inside B, in metres. None when B is not a closed volume."""
    if not _closed(b):
        return None
    pts = _sample_points(a)
    try:
        inside = np.asarray(b.contains(pts), dtype=bool)
    except Exception:
        return None
    if not inside.any():
        return 0.0
    try:
        from trimesh.proximity import closest_point

        _, dist, _ = closest_point(b, pts[inside])
        return float(np.max(dist))
    except Exception:
        return None


def _penetration_depth(a: _Part, b: _Part) -> tuple[Optional[float], str]:
    """Symmetric penetration depth in metres, plus a note when it is unmeasurable."""
    da = _one_way_depth(a.mesh, b.mesh)
    db = _one_way_depth(b.mesh, a.mesh)
    measured = [d for d in (da, db) if d is not None]
    if not measured:
        open_ones = [p.part_id for p, d in ((a, da), (b, db)) if d is None]
        return None, f"depth unmeasurable: {', '.join(sorted(set(open_ones)))} is not a closed volume"
    note = ""
    if len(measured) == 1:
        note = "depth measured in one direction only (the other part is not a closed volume)"
    return max(measured), note


def _min_distance(a: Any, b: Any) -> float:
    """Minimum surface distance in metres (0.0 when the meshes touch or interpenetrate)."""
    from trimesh.proximity import closest_point

    best = math.inf
    for src, dst in ((a, b), (b, a)):
        pts = _sample_points(src, n_surface=_MAX_SURFACE_SAMPLES)
        try:
            _, dist, _ = closest_point(dst, pts)
            best = min(best, float(np.min(dist)))
        except Exception:
            continue
    if not math.isfinite(best):
        return _aabb_gap(a, b)
    return best


def _mm(v: Optional[float]) -> str:
    return "unknown" if v is None else f"{v * 1000.0:.3f} mm"


# ---------------------------------------------------------------- propeller envelope

def _prop_geometry(params: Any, parts: list[_Part], model: Any) -> tuple[Optional[dict[str, Any]], str]:
    """Centre, axis, diameter and thickness of the propeller swept volume, in metres.

    The axis is derived from the motor -> prop offset in the envelope parameters (a pusher
    puts the disc aft of the motor, a tractor forward of it). It is never assumed.
    """
    motor = _field(params, "motor") if params is not None else None
    prop_raw = None
    for raw in _model_parts(model):
        if _category_of(raw) in _PROP_EXEMPT_CATEGORIES:
            prop_raw = raw
            break

    prop_params = _field(prop_raw, "parameters") if prop_raw is not None else None
    prop_params = prop_params if isinstance(prop_params, dict) else {}

    diameter = prop_params.get("prop_diameter_m")
    thickness = prop_params.get("prop_thickness_m")
    if diameter is None and motor is not None:
        diameter = _field(motor, "prop_diameter_m")
    if thickness is None and motor is not None:
        thickness = _field(motor, "prop_thickness_m")
    if not diameter or not thickness:
        return None, "no propeller envelope in params or in the model"

    prop_x = prop_params.get("x_m")
    prop_z = prop_params.get("z_m", 0.0)
    motor_x = _field(motor, "x_m") if motor is not None else None
    motor_z = _field(motor, "z_m") if motor is not None else 0.0
    if prop_x is None and motor is not None:
        length = _field(motor, "length_m") or 0.0
        gap = _field(motor, "prop_clearance_m") or 0.0
        prop_x = float(motor_x) - float(length) - float(gap)
    if prop_x is None:
        return None, "propeller station is unknown"

    if motor_x is None:
        # No motor to orient against: fall back to the prop part's own extrusion axis.
        axis = np.array([-1.0, 0.0, 0.0])
        orientation = "assumed from the prop envelope (no motor in params)"
    else:
        offset = np.array([float(prop_x) - float(motor_x), 0.0, float(prop_z) - float(motor_z or 0.0)])
        norm = float(np.linalg.norm(offset))
        if norm < 1e-9:
            axis = np.array([-1.0, 0.0, 0.0])
            orientation = "prop coincident with the motor; axis assumed"
        else:
            axis = offset / norm
            orientation = "pusher (disc aft of the motor)" if offset[0] < 0 else "tractor (disc forward of the motor)"

    return (
        {
            "center": np.array([float(prop_x), 0.0, float(prop_z or 0.0)]),
            "axis": axis,
            "diameter_m": float(diameter),
            "thickness_m": float(thickness),
            "orientation": orientation,
        },
        "",
    )


def _swept_volume(geom: dict[str, Any]) -> Any:
    """The swept disc as a closed cylinder, oriented on the real prop axis."""
    import trimesh

    cyl = trimesh.creation.cylinder(
        radius=geom["diameter_m"] / 2.0,
        height=max(geom["thickness_m"], 1e-4),
        sections=64,
    )
    axis = np.asarray(geom["axis"], dtype=float)
    axis = axis / max(float(np.linalg.norm(axis)), 1e-12)
    rot = trimesh.geometry.align_vectors(np.array([0.0, 0.0, 1.0]), axis)
    if rot is None:
        rot = np.eye(4)
    cyl.apply_transform(rot)
    cyl.apply_translation(np.asarray(geom["center"], dtype=float))
    return cyl


# ---------------------------------------------------------------- the entry point

def check(model: Any, manifest: Any, params: Any, policy: dict[str, Any],
          changed_part_ids: Optional[list[str]] = None) -> list[RoundTripCheck]:
    """Interference + propeller clearance for a regenerated model.

    Returns one `RoundTripCheck` per rule; `passed=False` blocks the edit. Never raises:
    bad input comes back as a failed `collision_check_error`.
    """
    try:
        return _check(model, manifest, params, policy or {}, changed_part_ids)
    except Exception as exc:  # the check itself must never take the edit down with it
        return [RoundTripCheck(
            name="collision_check_error", passed=False,
            detail=f"collision check could not run: {type(exc).__name__}: {exc}",
        )]


def _check(model: Any, manifest: Any, params: Any, policy: dict[str, Any],
           changed_part_ids: Optional[list[str]]) -> list[RoundTripCheck]:
    tol = _policy_number(policy, "interference_tolerance_m", DEFAULT_INTERFERENCE_TOLERANCE_M)
    clear_min = _policy_number(policy, "prop_clearance_min_m", DEFAULT_PROP_CLEARANCE_MIN_M)
    occs = _manifest_occurrences(manifest)
    patterns = _declared_pattern_pairs(policy)
    changed = set(changed_part_ids or [])

    parts = _collect(model)
    checks: list[RoundTripCheck] = []

    if not parts:
        return [RoundTripCheck(
            name="collision_check_error", passed=False,
            detail="no parts in the model: nothing could be checked",
        )]

    unusable = [p for p in parts if not p.usable]
    usable = [p for p in parts if p.usable]
    if unusable:
        checks.append(RoundTripCheck(
            name="collision_geometry_unusable", passed=False,
            detail="; ".join(f"{p.part_id}: {p.problem}" for p in unusable)
            + f" | {len(usable)} of {len(parts)} parts were measurable",
        ))

    # ---------------------------------------------- pairwise interference
    declared_lines: list[str] = []
    fail_lines: list[str] = []
    notes: list[str] = []
    tested = skipped_unchanged = prefiltered = 0

    for i in range(len(usable)):
        for j in range(i + 1, len(usable)):
            a, b = usable[i], usable[j]
            if changed and a.part_id not in changed and b.part_id not in changed:
                skipped_unchanged += 1
                continue
            if _aabb_gap(a.mesh, b.mesh) > tol:
                prefiltered += 1
                continue
            tested += 1
            declared, why = _is_declared(a.part_id, b.part_id, occs, patterns)
            depth, note = _penetration_depth(a, b)
            if note:
                notes.append(f"{a.part_id}/{b.part_id}: {note}")
            if declared:
                declared_lines.append(f"{a.part_id}+{b.part_id} engagement {_mm(depth)} ({why})")
            elif depth is not None and depth > tol:
                fail_lines.append(f"{a.part_id} x {b.part_id} interference {_mm(depth)}")

    scope = (f"changed parts {sorted(changed)}; {skipped_unchanged} pair(s) untouched by this "
             f"edit were not retested" if changed else "all parts")
    budget = f"{tested} pair(s) measured, {prefiltered} rejected on bounding box"

    checks.append(RoundTripCheck(
        name="collision_declared_engagement", passed=True,
        detail=(("; ".join(declared_lines) or "no declared mating pair is in contact")
                + f" | {scope} | {budget}"),
    ))

    interference_detail = "; ".join(fail_lines) if fail_lines else \
        f"no undeclared interference deeper than {_mm(tol)}"
    if notes:
        interference_detail += " | " + "; ".join(notes)
    checks.append(RoundTripCheck(
        name="collision_undeclared_interference", passed=not fail_lines,
        detail=f"{interference_detail} | tolerance {_mm(tol)} | {scope} | {budget}",
    ))

    # ---------------------------------------------- propeller swept volume
    checks.append(_prop_check(model, params, usable, occs, patterns, clear_min))

    # ---------------------------------------------- unknown interfaces
    unknown = _unknown_interface_check(occs, changed, usable)
    if unknown is not None:
        checks.append(unknown)

    return checks


def _prop_check(model: Any, params: Any, usable: list[_Part], occs: dict[str, dict[str, Any]],
                patterns: list[tuple[str, str]], clear_min: float) -> RoundTripCheck:
    geom, problem = _prop_geometry(params, usable, model)
    if geom is None:
        return RoundTripCheck(
            name="propeller_clearance", passed=True,
            detail=f"not evaluated: {problem}. No propeller clearance claim is made.",
        )
    try:
        disc = _swept_volume(geom)
    except Exception as exc:
        return RoundTripCheck(
            name="propeller_clearance", passed=False,
            detail=f"the swept volume could not be built: {type(exc).__name__}: {exc}",
        )

    prop_ids = {p.part_id for p in usable if p.category in _PROP_EXEMPT_CATEGORIES}
    # The drivetrain the propeller is bolted to is not airframe: §6 asks for the swept volume
    # against the *airframe*. The ids come from the motor envelope, never from a hardcoded name.
    motor = _field(params, "motor") if params is not None else None
    drivetrain = {pid for pid in (_field(motor, "part_id"), _field(motor, "mount_part_id"))
                  if isinstance(pid, str)}

    lines: list[str] = []
    fails: list[str] = []
    worst: Optional[tuple[str, float]] = None
    for part in usable:
        if part.part_id in prop_ids:
            continue
        if part.part_id in drivetrain:
            gap = _min_distance(disc, part.mesh)
            lines.append(f"{part.part_id} {_mm(gap)} (drivetrain, not airframe)")
            continue
        declared = any(_is_declared(pid, part.part_id, occs, patterns)[0] for pid in prop_ids)
        if declared:
            lines.append(f"{part.part_id} declared to carry the prop (exempt)")
            continue
        gap = _aabb_gap(disc, part.mesh)
        if gap > clear_min * 10.0:
            # Far away: the bounding boxes already prove the clearance, no query needed.
            lines.append(f"{part.part_id} >= {_mm(gap)} (bounding box)")
            continue
        d = _min_distance(disc, part.mesh)
        lines.append(f"{part.part_id} {_mm(d)}")
        if worst is None or d < worst[1]:
            worst = (part.part_id, d)
        if d < clear_min:
            fails.append(f"{part.part_id} at {_mm(d)}")

    head = (f"minimum clearance {_mm(worst[1])} to {worst[0]}" if worst
            else "no airframe part is within range of the swept volume")
    detail = (f"{head} | required {_mm(clear_min)} | disc d={geom['diameter_m'] * 1000:.1f} mm "
              f"axis=({geom['axis'][0]:.3f}, {geom['axis'][1]:.3f}, {geom['axis'][2]:.3f}) "
              f"{geom['orientation']}")
    if fails:
        detail = f"below the minimum: {'; '.join(fails)} | " + detail
    if lines:
        detail += " | " + "; ".join(lines)
    return RoundTripCheck(name="propeller_clearance", passed=not fails, detail=detail)


def _unknown_interface_check(occs: dict[str, dict[str, Any]], changed: set[str],
                             usable: list[_Part]) -> Optional[RoundTripCheck]:
    """An evidence gap, not a geometric failure: A3b must be able to tell them apart."""
    if not changed:
        return None

    mated_by_others = set()
    for pid, occ in occs.items():
        for other in occ.get("allowed_overlap_with", []):
            mated_by_others.add(other)

    gaps: list[str] = []
    for pid in sorted(changed):
        occ = occs.get(pid)
        if occ is None:
            gaps.append(f"{pid}: no manifest occurrence, so its retention is unknown")
            continue
        reasons = []
        if not occ.get("allowed_overlap_with") and pid not in mated_by_others:
            reasons.append("no declared mating/retention partner")
        for label, key in (("mount", "mount"), ("harness", "harness"), ("retention", "retention")):
            v = occ.get("labels", {}).get(key)
            if v is not None and str(v).lower() in ("unknown", "", "none"):
                reasons.append(f"{label} claim is unknown")
        if occ.get("material_status") == "unknown":
            reasons.append("material claim is unknown")
        if occ.get("mass_status") == "unknown":
            reasons.append("mass claim is unknown")
        if reasons:
            gaps.append(f"{pid}: " + ", ".join(reasons))

    if not gaps:
        return RoundTripCheck(
            name="verified_movement_unknown", passed=True,
            detail=("every moved part has a declared retention interface and known mount, "
                    f"material and mass claims: {sorted(changed)}"),
        )
    return RoundTripCheck(
        name="verified_movement_unknown", passed=False,
        detail=("evidence gap, not a geometric interference: movement cannot be verified "
                "because the retention / harness / mount interface is unknown. "
                + "; ".join(gaps)),
    )
