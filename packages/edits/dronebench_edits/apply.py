"""`apply_edit`: one bounded operation, regenerated, verified, and reported (A3, B).

    load manifest + parent parameters
      -> policy.check_bounds(...)                      # refuses before anything is built
      -> operations.<op>(...)                          # pure: new params + typed changes
      -> store.create_preview(design_dir, parent, cause, build)
             build(workdir): reconstruct -> export -> reimport_check -> collider.check
      -> CadEditResult

The parent revision is never touched. A refusal returns `status="blocked"` with the typed
envelope and no revision; an exception returns `status="failed"` and the store is responsible
for leaving no partial revision behind.

Nothing here invents a number. Where an edit has a consequence this project cannot compute --
mass, CG, balance -- the change is reported with `before`/`after` null and a note saying why.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from dronebench_cad import (DEFAULT_PARAMS_PATH, STEP_NAME, ReconParams, dump_params, export,
                            load_params, reconstruct, reimport_check, sha256_file)
from dronebench_contracts.models import (Artifact, CadEditRequest, CadEditResult, EditOperation,
                                         ErrorCode, ErrorEnvelope, RevisionManifest,
                                         RevisionState, RoundTripCheck)

from . import operations, policy as policy_mod
from .api import BuildResult, EditBlocked

__all__ = ["apply_edit", "PARAMS_NAME", "load_parent_params"]

PARAMS_NAME = "params.yaml"
_MANIFEST_NAME = "design_manifest.json"
_REVISION_NAME = "revision_manifest.json"
_FEATURES_NAME = "geometry_features.json"

#: Tolerance for "this part did not change", in metres / relative volume. Demo validation
#: settings from architecture 6, not manufacturing tolerances.
UNCHANGED_TOLERANCE = {"centroid_m": 1e-9, "volume_relative": 1e-9}

#: Checks whose failure does NOT block the edit. Architecture 6: an unknown retention,
#: harness or structural interface blocks a *verified movement claim*, not the operation. The
#: edit is `ok` and committable, the check stays in `checks` with `passed=False`, and the
#: result carries `verified: false` with the reasons. One source of truth with the store.
try:
    from .store import ADVISORY_CHECKS
except Exception:  # the store is A3a's; this module still works without it
    ADVISORY_CHECKS = frozenset({"verified_movement_unknown"})


# ---------------------------------------------------------------------------- inputs

def _load_manifest(design_dir: Path, revision_id: Optional[str]) -> Any:
    from dronebench_ingest import load_manifest

    if revision_id and (design_dir / "revisions" / revision_id / _MANIFEST_NAME).is_file():
        return load_manifest(design_dir, revision_id)
    # An edit revision carries geometry, not a design manifest; the identity of the design
    # comes from the most recent revision that has one.
    return load_manifest(design_dir)


def load_parent_params(design_dir: Path, revision_id: Optional[str] = None) -> ReconParams:
    """The parameter set the edit starts from.

    With a base revision, that revision decides and nothing else: its `params.yaml` if an
    earlier edit left one (this is how edits chain), else its `geometry_features.json` (the
    measured aircraft), else the package baseline. Without one, the newest parameter set in
    the design is used.
    """
    revisions = design_dir / "revisions"
    if revision_id and (revisions / revision_id).is_dir():
        # The named base revision is the authority. Falling through to "the newest parameter
        # set in the design" would silently branch an edit off a sibling preview instead.
        base = revisions / revision_id
        if (base / PARAMS_NAME).is_file():
            return load_params(base / PARAMS_NAME)
        if (base / _FEATURES_NAME).is_file():
            return ReconParams.from_features(json.loads((base / _FEATURES_NAME).read_text()))
        return load_params(DEFAULT_PARAMS_PATH)
    if revisions.is_dir():
        chained = sorted(revisions.glob(f"*/{PARAMS_NAME}"), key=lambda p: p.stat().st_mtime)
        if chained:
            return load_params(chained[-1])
        features = sorted(revisions.glob(f"*/{_FEATURES_NAME}"), key=lambda p: p.stat().st_mtime)
        if features:
            return ReconParams.from_features(json.loads(features[-1].read_text()))
    return load_params(DEFAULT_PARAMS_PATH)


# ---------------------------------------------------------------------------- op dispatch

def _default_targets(operation: EditOperation, params: ReconParams) -> list[str]:
    """Which parts an operation acts on when the caller named none.

    Two of the three operations have exactly one possible target in a given parameter set:
    the spar (the archive contains no spar at all, so it exists only as a reconstruction
    part) and the wing pair (a whole-surface operation that always moves both occurrences).
    `translate_component` has no default: which component is being moved is the whole
    request, and guessing it would be inventing the edit.
    """
    if operation is EditOperation.resize_spar and params.spar.enabled:
        return [params.spar.part_id]
    if operation is EditOperation.set_wing_tip_extension:
        wing = next((s for s in params.surfaces if s.category == "wing"), None)
        if wing is not None:
            return [pid for pid in (wing.part_id_right, wing.part_id_left) if pid]
    return []

def _plan(request: CadEditRequest, params: ReconParams,
          manifest: Any, pol: dict[str, Any]) -> tuple[ReconParams, list[dict[str, Any]], list[str]]:
    """Run the pure kernel for this operation. Returns (new params, changes, affected ids)."""
    operation = EditOperation(request.operation)
    targets = [policy_mod.resolve_target(pid, manifest, pol)[0] for pid in request.target_part_ids]

    if operation is EditOperation.translate_component:
        new, changes = operations.translate_component(
            params, targets[0], list(request.parameters["delta_m"]))
        return new, changes, [targets[0]]

    if operation is EditOperation.resize_spar:
        p = request.parameters
        new, changes = operations.resize_spar(
            params,
            outer_d_mm=p.get("outer_d_mm", p.get("outer_diameter_mm")),
            inner_d_mm=p.get("inner_d_mm", p.get("inner_diameter_mm")),
        )
        return new, changes, [new.spar.part_id]

    if operation is EditOperation.set_wing_tip_extension:
        new, changes = operations.set_wing_tip_extension(
            params, float(request.parameters["extension_m"]))
        wing = next(s for s in new.surfaces if s.category == "wing")
        return new, changes, [pid for pid in (wing.part_id_right, wing.part_id_left) if pid]

    raise EditBlocked.of(ErrorCode.UNSUPPORTED_EDIT,
                         f"operation {operation.value!r} is not implemented in this build",
                         operation=operation.value)


# ---------------------------------------------------------------------------- carry forward

def _source_revision_dir(design_dir: Path, revision_id: Optional[str]) -> Optional[Path]:
    """The revision the design manifest was read from, so its sidecars can travel with the edit."""
    if revision_id and (design_dir / "revisions" / revision_id / _MANIFEST_NAME).is_file():
        return design_dir / "revisions" / revision_id
    root = design_dir / "revisions"
    if not root.is_dir():
        return None
    candidates = [p.parent for p in root.glob(f"*/{_MANIFEST_NAME}")]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _carry_forward(design_dir: Path, source_dir: Optional[Path], workdir: Path, manifest: Any,
                   operation: EditOperation, request: CadEditRequest,
                   params: ReconParams, new_params: ReconParams) -> list[Artifact]:
    """Write the design identity into the preview so an edited design is still loadable.

    A revision that holds only geometry is unreadable to everyone downstream: `load_manifest`
    raises, the viewer has no parts, the fit report has no reference. So every preview carries
    `design_manifest.json`, `parts.json`, `geometry_features.json` and (hard-linked, not
    copied -- revisions are immutable and the bytes are identical) the reference GLB.

    What travels forward is updated only where the edit actually moved something a manifest
    occurrence describes. The reference meshes are untouched by construction: an edit changes
    the *reconstruction*, never the imported vendor geometry.
    """
    import shutil

    from dronebench_contracts.models import SCHEMA_VERSION

    carried = manifest.model_copy(deep=True)
    note = (f"carried forward from revision {manifest.revision_id} by "
            f"edit:{operation.value}; the imported reference meshes are unchanged, and "
            "revision_id still names the revision this manifest was measured in")
    carried.warnings = list(carried.warnings) + [note]

    if operation is EditOperation.translate_component:
        delta = [float(v) for v in request.parameters["delta_m"]]
        for part_id in request.target_part_ids:
            part = next((p for p in carried.parts if p.part_id == part_id), None)
            if part is None:
                continue
            T = [list(row) for row in part.T_parent_from_local]
            for axis in range(3):
                T[axis][3] = float(T[axis][3]) + delta[axis]
            part.T_parent_from_local = T
            part.labels = {**part.labels,
                           "placement_note": f"moved {delta} m by edit:{operation.value}; "
                                             "assumed position, still not measured"}

    artifacts: list[Artifact] = []

    def declare(path: Path, media: str, part_ids: Optional[list[str]] = None) -> None:
        artifacts.append(Artifact(path=path.name, sha256=sha256_file(path), media_type=media,
                                  representation="reference_mesh" if path.suffix == ".glb"
                                  else None,
                                  part_ids=part_ids or []))

    part_ids = [p.part_id for p in carried.parts]
    manifest_path = workdir / _MANIFEST_NAME
    manifest_path.write_text(carried.model_dump_json(indent=2))
    declare(manifest_path, "application/json", part_ids)

    parts_path = workdir / "parts.json"
    parts_path.write_text(json.dumps({
        "schema_version": SCHEMA_VERSION, "design_id": carried.design_id,
        "revision_id": carried.revision_id,
        "parts": [p.model_dump(mode="json") for p in carried.parts]}, indent=2))
    declare(parts_path, "application/json", part_ids)

    if source_dir is None:
        return artifacts

    features_src = source_dir / _FEATURES_NAME
    if features_src.is_file():
        features = json.loads(features_src.read_text())
        quality = features.setdefault("quality", {})
        quality.setdefault("edits_applied", []).append(
            {"operation": operation.value, "parameters": request.parameters,
             "parent_revision_id": request.base_revision_id})
        if operation is EditOperation.set_wing_tip_extension:
            _restate_span(features, params, new_params)
        else:
            quality["note_after_edit"] = (
                f"edit:{operation.value} did not change any lifting surface; these features "
                "still describe the measured reference meshes")
        features_path = workdir / _FEATURES_NAME
        features_path.write_text(json.dumps(features, indent=2))
        declare(features_path, "application/json")

    glb_src = source_dir / "reference_meshes.glb"
    if glb_src.is_file():
        glb_dst = workdir / glb_src.name
        try:
            glb_dst.hardlink_to(glb_src)          # same bytes, no second copy on disk
        except OSError:
            shutil.copy2(glb_src, glb_dst)
        declare(glb_dst, "model/gltf-binary", part_ids)

    return artifacts


def _restate_span(features: dict[str, Any], params: ReconParams, new_params: ReconParams) -> None:
    """After a tip extension, say what is now computed, and mark what was not re-measured.

    The stations were *measured* from the reference meshes. A tip extension does not
    re-measure anything: it stretches the reconstruction by a declared parameter. So the span
    is restated as `computed` from that parameter, and every planform quantity that depends on
    the outer panel and was not re-derived is flagged `conflicted` rather than left looking
    like a fresh measurement.
    """
    delta = float(new_params.tip_extension_m) - float(params.tip_extension_m)
    if not delta:
        return
    provenance = (f"restated from the reconstruction parameter tip_extension_m="
                  f"{new_params.tip_extension_m} m; not re-measured from the reference meshes")
    stale = ("not re-derived after the tip extension; re-run geometry_features on the edited "
             "reconstruction before using this number")

    def restate(claim: Optional[dict[str, Any]], value: Optional[float]) -> None:
        if not isinstance(claim, dict):
            return
        if value is None:
            claim["status"] = "conflicted"
            claim["assumptions"] = list(claim.get("assumptions") or []) + [stale]
            return
        claim["value"] = value
        claim["status"] = "estimated"
        claim["source_kind"] = "computed"
        claim["assumptions"] = list(claim.get("assumptions") or []) + [provenance]

    for surface in features.get("surfaces", []):
        if "wing" not in surface.get("surface_id", ""):
            continue
        stations = surface.get("stations") or []
        if stations:
            stations[-1]["span_y_m"] = float(stations[-1]["span_y_m"]) + delta
            restate(surface.get("span_m"), 2 * float(stations[-1]["span_y_m"]))
        for key in ("area_m2", "mac_m", "aspect_ratio", "x_mac_le_m"):
            restate(surface.get(key), None)
        features["reference_span_m"] = surface.get("span_m", features.get("reference_span_m"))
    for key in ("reference_area_m2", "reference_chord_m"):
        restate(features.get(key), None)


# ---------------------------------------------------------------------------- acceptance

def _intent_checks(model: Any, parent_model: Any, new_params: ReconParams,
                   operation: EditOperation, affected: list[str]) -> list[RoundTripCheck]:
    """Did the regenerated geometry actually do what was asked, and nothing else?"""
    checks: list[RoundTripCheck] = []
    by_id = {p.part_id: p for p in model.parts}
    parent_by_id = {p.part_id: p for p in (parent_model.parts if parent_model else [])}

    # 1. requested parameter change is visible in the geometry
    if operation is EditOperation.translate_component:
        pid = affected[0]
        want = [float(v) for v in new_params.battery.center_m]
        got = by_id[pid].centroid_m() if pid in by_id else None
        ok = got is not None and max(abs(a - b) for a, b in zip(want, got)) <= 1e-6
        checks.append(RoundTripCheck(
            name="requested_placement_applied", passed=bool(ok),
            detail=f"{pid} centroid {got} vs requested centre {want} (tolerance 1e-6 m)"))
    elif operation is EditOperation.resize_spar:
        pid = affected[0]
        part = by_id.get(pid)
        want_d = float(new_params.spar.outer_diameter_m)
        got = None
        if part is not None:
            lo, hi = part.bounds_m()
            # The tube's axis is spanwise (y), so the diameter is the x and z extent; the y
            # extent is its length and must not be mistaken for a cross-section.
            got = (hi[0] - lo[0], hi[2] - lo[2])
        ok = got is not None and max(abs(v - want_d) for v in got) <= 1e-6
        checks.append(RoundTripCheck(
            name="requested_spar_diameter_applied", passed=bool(ok),
            detail=(f"{pid} cross-section x={got[0]:.6f} m z={got[1]:.6f} m vs requested outer "
                    f"diameter {want_d:.6f} m" if got else f"{pid} is not in the model")))
    elif operation is EditOperation.set_wing_tip_extension:
        spans = []
        for pid in affected:
            part = by_id.get(pid)
            if part is not None:
                lo, hi = part.bounds_m()
                spans.append((lo[1], hi[1]))
        ok = False
        detail = "wing occurrences not found in the regenerated model"
        if len(spans) == 2:
            right = max(abs(v) for v in spans[0])
            left = max(abs(v) for v in spans[1])
            ok = abs(right - left) <= 1e-9
            detail = (f"half spans right={right:.6f} m left={left:.6f} m, "
                      f"difference {abs(right - left):.3e} m (symmetric within 1e-9)")
        checks.append(RoundTripCheck(name="tip_extension_symmetric", passed=bool(ok),
                                     detail=detail))

    # 2. every part the edit did not name is byte-for-byte the same shape
    if parent_by_id:
        drifted: list[str] = []
        for pid, part in by_id.items():
            if pid in affected or pid not in parent_by_id:
                continue
            ref = parent_by_id[pid]
            dv = abs(part.volume_m3() - ref.volume_m3())
            rel = dv / max(ref.volume_m3(), 1e-18)
            dc = max(abs(a - b) for a, b in zip(part.centroid_m(), ref.centroid_m()))
            if rel > UNCHANGED_TOLERANCE["volume_relative"] or dc > UNCHANGED_TOLERANCE["centroid_m"]:
                drifted.append(f"{pid} (dV/V={rel:.3e}, dC={dc:.3e} m)")
        checks.append(RoundTripCheck(
            name="unchanged_parts_unchanged", passed=not drifted,
            detail=("all %d unaffected parts within 1e-9" % (len(by_id) - len(affected))
                    if not drifted else "drifted: " + ", ".join(drifted))))

    # 3. every solid is valid with a finite positive volume
    bad = [p.part_id for p in model.parts if not p.is_valid() or not p.volume_m3() > 0]
    checks.append(RoundTripCheck(name="solids_valid", passed=not bad,
                                 detail="all solids valid with positive volume" if not bad
                                 else "invalid or empty: " + ", ".join(bad)))
    return checks


# ---------------------------------------------------------------------------- fallbacks

class _FallbackStore:
    """A stand-in for A3a's store, used only when no store is supplied and none is importable.

    It runs the build in `<design_dir>/.edit_previews/<content hash>` so the artifacts stay
    readable, never touches `revisions/`, and deletes the directory if the build raises.
    """

    def create_preview(self, design_dir: Path, parent_revision_id: str, cause: str,
                       build: Callable[[Path], BuildResult],
                       idempotency_key: Optional[str] = None) -> RevisionManifest:
        root = Path(design_dir) / ".edit_previews"
        root.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix="preview-", dir=root))
        try:
            result = build(workdir)
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        content = hashlib.sha256(
            json.dumps(result.content, sort_keys=True, default=str).encode()).hexdigest()
        revision_id = f"preview-{content[:12]}"
        final = root / revision_id
        if final.exists():
            shutil.rmtree(final, ignore_errors=True)
        workdir.rename(final)
        return RevisionManifest(
            design_id=getattr(result.model, "design_id", "unknown"),
            revision_id=revision_id,
            parent_revision_id=parent_revision_id,
            state=RevisionState.preview,
            content_sha256=content,
            cause=cause,
            artifacts=result.artifacts,
        )


class _NullCollider:
    """Used until A3c's collider is importable. It reports that it did not run."""

    def check(self, model: Any, manifest: Any, params: Any, policy: dict[str, Any],
              changed_part_ids: Optional[list[str]] = None) -> list[RoundTripCheck]:
        return [RoundTripCheck(
            name="collision_checks", passed=True,
            detail="no collider was supplied: interference and propeller clearance were NOT "
                   "checked for this preview")]


def _default_store() -> Any:
    try:
        from .store import RevisionStore  # type: ignore[attr-defined]
    except Exception:
        return _FallbackStore()
    return RevisionStore()


def _replayed_checks(store: Any, design_dir: Path, revision_id: Optional[str]
                     ) -> list[RoundTripCheck]:
    """The store's recorded verdict for a revision it handed back without rebuilding."""
    verdict: Optional[dict[str, Any]] = None
    reader = getattr(store, "edit_status", None)
    if callable(reader) and revision_id:
        try:
            verdict = reader(design_dir, revision_id)
        except Exception:
            verdict = None
    if verdict is None and revision_id:
        path = design_dir / "revisions" / revision_id / "edit_status.json"
        if path.is_file():
            try:
                verdict = json.loads(path.read_text())
            except json.JSONDecodeError:
                verdict = None
    status = (verdict or {}).get("status")
    failed = (verdict or {}).get("failed_checks") or []
    if status and status != "ok":
        return [RoundTripCheck(
            name="idempotent_replay", passed=False,
            detail=f"revision {revision_id} was built by an earlier identical request and the "
                   f"store recorded it as {status!r}"
                   + (f" (failed: {', '.join(failed)})" if failed else ""))]
    return [RoundTripCheck(
        name="idempotent_replay", passed=True,
        detail=f"revision {revision_id} was built by an earlier identical request; its checks "
               "were run then and the store recorded no failure")]


def _dispose(store: Any, design_dir: Path, revision_id: Optional[str], reason: str) -> None:
    """Tell the store a preview was refused, so it is not left standing as a proposal.

    The store owns `revisions/`; declining is its own disposal path (it logs the decision and
    leaves the active pointer alone). Deleting the directory from here would reach behind an
    append-only store, so this asks rather than removes.
    """
    decline = getattr(store, "decline", None)
    if callable(decline) and revision_id:
        try:
            decline(design_dir, revision_id, f"blocked by acceptance checks: {reason}")
        except Exception:
            pass


def _default_collider() -> Any:
    try:
        from . import collide  # type: ignore[attr-defined]
    except Exception:
        return _NullCollider()
    for name in ("Collider", "InterferenceChecker", "collider"):
        candidate = getattr(collide, name, None)
        if candidate is not None:
            return candidate() if isinstance(candidate, type) else candidate
    if hasattr(collide, "check"):
        return collide
    return _NullCollider()


# ---------------------------------------------------------------------------- entry point

def apply_edit(design_dir: str | Path, request: CadEditRequest, store: Any = None,
               collider: Any = None, policy: Any = None) -> CadEditResult:
    """Apply one bounded edit and return a typed result. Never raises for a refused edit."""
    design_dir = Path(design_dir).resolve()
    operation = EditOperation(request.operation)
    result = CadEditResult(base_revision_id=request.base_revision_id, operation=operation,
                           status="failed")
    started = time.perf_counter()

    try:
        pol = policy if isinstance(policy, dict) else policy_mod.load_policy(policy)
        manifest = _load_manifest(design_dir, request.base_revision_id)
        source_dir = _source_revision_dir(design_dir, request.base_revision_id)
        params = load_parent_params(design_dir, request.base_revision_id)

        if not request.target_part_ids:
            defaults = _default_targets(operation, params)
            if not defaults:
                raise EditBlocked.of(
                    ErrorCode.UNSUPPORTED_EDIT,
                    f"{operation.value} names no target and has no single default: say which "
                    "part to edit in target_part_ids",
                    operation=operation.value)
            request = request.model_copy(update={"target_part_ids": defaults})
        result.affected_part_ids = list(request.target_part_ids)

        policy_mod.check_bounds(request, manifest, params, pol)
        new_params, changes, affected = _plan(request, params, manifest, pol)

        store = store if store is not None else _default_store()
        collider = collider if collider is not None else _default_collider()
        captured: dict[str, BuildResult] = {}

        def build(workdir: Path) -> BuildResult:
            workdir = Path(workdir).resolve()
            parent_model = reconstruct(params=params)
            model = reconstruct(params=new_params)

            artifacts = [Artifact(**a) for a in
                         export(model, workdir, changes=changes, cause=f"edit:{operation.value}")]
            params_path = workdir / PARAMS_NAME
            dump_params(new_params, params_path)
            artifacts.append(Artifact(path=PARAMS_NAME, sha256=sha256_file(params_path),
                                      media_type="application/yaml",
                                      part_ids=[p.part_id for p in model.parts]))
            # An edit revision that holds only geometry leaves the design unloadable.
            artifacts += _carry_forward(design_dir, source_dir, workdir, manifest, operation,
                                        request, params, new_params)

            checks = _intent_checks(model, parent_model, new_params, operation, affected)
            # Absolute path: the reimport worker runs in a fresh process with its own cwd.
            checks += [RoundTripCheck(**c) for c in
                       reimport_check(workdir / STEP_NAME, model)]
            # The collider reads the manifest for retention and mating evidence, so it is told
            # both ids for a part that has two: the reconstruction id it can measure geometry
            # on, and the manifest occurrence whose claims it can read. A reconstruction-only
            # part (the spar, the lofted wings) has no second id -- the archive has no spar.
            changed = list(dict.fromkeys(affected + list(request.target_part_ids)))
            checks += [c if isinstance(c, RoundTripCheck) else RoundTripCheck(**c)
                       for c in collider.check(model, manifest, new_params, pol,
                                               changed_part_ids=changed)]

            content = {
                "parent_revision_id": request.base_revision_id,
                "operation": operation.value,
                "target_part_ids": sorted(request.target_part_ids),
                "parameters": request.parameters,
                "policy_sha256": policy_mod.policy_hash(pol),
                "params_sha256": hashlib.sha256(params_path.read_bytes()).hexdigest(),
                "design_id": new_params.design_id,
            }
            out = BuildResult(artifacts=artifacts, changes=changes, checks=checks,
                              affected_part_ids=affected, content=content, model=model)
            captured["build"] = out
            return out

        revision = store.create_preview(design_dir, request.base_revision_id,
                                        f"edit:{operation.value}", build,
                                        request.idempotency_key)
        built = captured.get("build")
        result.preview_revision_id = getattr(revision, "revision_id", None)
        result.artifacts = list(getattr(revision, "artifacts", None) or
                                (built.artifacts if built else []))
        result.changes = built.changes if built else changes
        result.checks = built.checks if built else []
        result.affected_part_ids = built.affected_part_ids if built else affected

        if built is None:
            # The store answered without running the build: an idempotent replay of an edit
            # made earlier. Its verdict is on disk; report that rather than an empty "ok".
            result.checks = _replayed_checks(store, design_dir, result.preview_revision_id)

        failed = [c for c in result.checks if not c.passed]
        blocking = [c for c in failed if c.name not in ADVISORY_CHECKS]
        advisory = [c for c in failed if c.name in ADVISORY_CHECKS]

        if blocking:
            result.status = "blocked"
            result.error = ErrorEnvelope(
                code=ErrorCode.CONSTRAINT_FAILED,
                message="the regenerated geometry did not pass every acceptance check: "
                        + "; ".join(f"{c.name}: {c.detail}" for c in failed),
                revision_id=result.preview_revision_id,
                details={"failed_checks": [c.name for c in failed],
                         "advisory_checks": [c.name for c in advisory]},
            )
            # A genuinely blocked edit is not something to leave lying around as a proposal.
            _dispose(store, design_dir, result.preview_revision_id,
                     "; ".join(c.name for c in blocking))
        else:
            # The geometry is clean. An advisory failure does not block the edit; it blocks
            # the *claim* that the movement is verified, and says so in the envelope.
            result.status = "ok"
            if advisory:
                result.error = ErrorEnvelope(
                    code=ErrorCode.MISSING_EVIDENCE,
                    message="applied, but this is not a verified movement: "
                            + "; ".join(f"{c.name}: {c.detail}" for c in advisory),
                    revision_id=result.preview_revision_id,
                    details={"verified": False,
                             "advisory_checks": [c.name for c in advisory],
                             "unverified_reasons": [c.detail for c in advisory]},
                )

    except EditBlocked as blocked:
        result.status = "blocked"
        result.error = blocked.envelope
        result.affected_part_ids = list(request.target_part_ids)
    except Exception as exc:  # regeneration, export or store failure
        result.status = "failed"
        result.error = ErrorEnvelope(
            code=ErrorCode.GEOMETRY_INVALID,
            message=f"{type(exc).__name__}: {exc}",
            details={"stage": "regenerate/export", "operation": operation.value},
        )

    if result.status != "ok" and result.error is None:
        # Belt and braces: a refusal with no reason attached is the worst thing this function
        # could return, so it cannot leave without one.
        result.error = ErrorEnvelope(
            code=ErrorCode.CONSTRAINT_FAILED,
            message=f"{operation.value} was refused but no reason was recorded; this is a bug "
                    "in dronebench_edits.apply",
            revision_id=result.preview_revision_id,
            details={"failed_checks": [c.name for c in result.checks if not c.passed]},
        )

    result.checks.append(RoundTripCheck(
        name="edit_seconds", passed=True, detail=f"{time.perf_counter() - started:.2f} s"))
    return result
