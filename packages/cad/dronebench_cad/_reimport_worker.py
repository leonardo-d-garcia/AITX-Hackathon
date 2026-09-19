"""Reimport a STEP file and compare it with an expected part map. Runs as its own process.

It is launched by `roundtrip.reimport_check` with a JSON request on stdin and answers with a
JSON response on stdout. Everything the OCCT reader can do to a process — segfault, abort,
hang, eat the heap on a corrupt file — happens here, not in the caller.

Request:  {"step_path": str, "part_map": {...}, "tolerances": {...}}
Response: {"ok": bool, "checks": [{"name", "passed", "detail"}, ...], "measured": {...}}
"""
from __future__ import annotations

import json
import sys
from typing import Any

MM = 1000.0


def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _bounds_m(shape) -> list[list[float]]:
    bb = shape.BoundingBox()
    return [
        [bb.xmin / MM, bb.ymin / MM, bb.zmin / MM],
        [bb.xmax / MM, bb.ymax / MM, bb.zmax / MM],
    ]


def _flatten(assy, prefix: str = "") -> list[tuple[str, Any]]:
    """(name, located solid) for every solid in the imported assembly tree."""
    out: list[tuple[str, Any]] = []
    name = assy.name or prefix or "unnamed"
    if assy.obj is not None:
        for solid in assy.obj.Solids():
            out.append((name, solid.located(assy.loc) if assy.loc is not None else solid))
    for child in assy.children:
        out.extend(_flatten(child, name))
    return out


def run(req: dict[str, Any]) -> dict[str, Any]:
    import cadquery as cq
    from cadquery.occ_impl.importers.assembly import importStep

    tol = req.get("tolerances") or {}
    place_tol = float(tol.get("placement_m", 1e-4))       # 0.1 mm
    bounds_tol = float(tol.get("bounds_m", 1e-4))         # 0.1 mm
    vol_rel_tol = float(tol.get("volume_relative", 1e-4))
    vol_abs_tol = float(tol.get("volume_absolute_m3", 1e-12))

    expected = {p["part_id"]: p for p in req["part_map"]["parts"]}
    checks: list[dict[str, Any]] = []

    try:
        assy = cq.Assembly(name="reimported")
        importStep(assy, req["step_path"])
    except Exception as exc:  # noqa: BLE001 - the whole point is to report, not to raise
        return {
            "ok": False,
            "checks": [_check("step_readable", False, f"{type(exc).__name__}: {exc}")],
            "measured": {},
        }
    checks.append(_check("step_readable", True, "STEP assembly reimported"))

    found = _flatten(assy)
    checks.append(
        _check(
            "solid_count",
            len(found) == len(expected),
            f"reimported {len(found)} solids, part_map declares {len(expected)}",
        )
    )

    # Match by STEP label first; fall back to nearest centroid for anything unnamed.
    by_name: dict[str, Any] = {}
    unmatched: list[tuple[str, Any]] = []
    for name, solid in found:
        key = name.split("/")[-1]
        if key in expected and key not in by_name:
            by_name[key] = solid
        else:
            unmatched.append((key, solid))

    if unmatched:
        remaining = [pid for pid in expected if pid not in by_name]
        for key, solid in unmatched:
            if not remaining:
                break
            c = solid.Center()
            centroid = (c.x / MM, c.y / MM, c.z / MM)
            best = min(
                remaining,
                key=lambda pid: sum(
                    (a - b) ** 2 for a, b in zip(centroid, expected[pid]["centroid_m"])
                ),
            )
            by_name[best] = solid
            remaining.remove(best)

    missing = sorted(set(expected) - set(by_name))
    checks.append(
        _check(
            "part_map_id_coverage",
            not missing,
            "every part_map id matched a reimported solid"
            if not missing
            else f"no solid for: {missing}",
        )
    )

    named = sum(1 for name, _ in found if name.split("/")[-1] in expected)
    checks.append(
        _check(
            "step_labels_preserved",
            named == len(found) and named > 0,
            f"{named}/{len(found)} solids carry a part_map id as their STEP label",
        )
    )

    invalid, nonfinite, bad_bounds, bad_place, bad_vol = [], [], [], [], []
    measured: dict[str, Any] = {}
    for pid, solid in by_name.items():
        exp = expected[pid]
        try:
            valid = bool(solid.isValid())
            vol = solid.Volume() / MM**3
            bounds = _bounds_m(solid)
            c = solid.Center()
            centroid = [c.x / MM, c.y / MM, c.z / MM]
        except Exception as exc:  # noqa: BLE001
            invalid.append(f"{pid}: {type(exc).__name__}: {exc}")
            continue

        measured[pid] = {"volume_m3": vol, "bounds_m": bounds, "centroid_m": centroid}
        if not valid:
            invalid.append(pid)
        if not (vol == vol and vol not in (float("inf"), float("-inf")) and vol > 0):
            nonfinite.append(f"{pid}: volume={vol}")

        for i, (got_row, exp_row) in enumerate(zip(bounds, exp["bounds_m"])):
            for got, want in zip(got_row, exp_row):
                if abs(got - want) > bounds_tol:
                    bad_bounds.append(f"{pid}[{i}] {got:.6f} vs {want:.6f}")

        for got, want in zip(centroid, exp["centroid_m"]):
            if abs(got - want) > place_tol:
                bad_place.append(f"{pid} centroid {got:.6f} vs {want:.6f}")

        want_v = exp["volume_m3"]
        denom = max(abs(want_v), vol_abs_tol)
        if abs(vol - want_v) / denom > vol_rel_tol and abs(vol - want_v) > vol_abs_tol:
            bad_vol.append(f"{pid} {vol:.9e} vs {want_v:.9e} (rel {abs(vol - want_v)/denom:.2e})")

    checks.append(_check("all_solids_valid", not invalid, "; ".join(invalid[:5]) or "all isValid()"))
    checks.append(
        _check(
            "finite_positive_volume",
            not nonfinite,
            "; ".join(nonfinite[:5]) or "every solid has a finite positive volume",
        )
    )
    checks.append(
        _check(
            "bounds_within_tolerance",
            not bad_bounds,
            "; ".join(bad_bounds[:5]) or f"all bounds within {bounds_tol * MM:.3g} mm",
        )
    )
    checks.append(
        _check(
            "placement_match",
            not bad_place,
            "; ".join(bad_place[:5]) or f"all centroids within {place_tol * MM:.3g} mm",
        )
    )
    checks.append(
        _check(
            "volume_relative_difference",
            not bad_vol,
            "; ".join(bad_vol[:5]) or f"all volumes within {vol_rel_tol:.0e} relative",
        )
    )

    return {"ok": all(c["passed"] for c in checks), "checks": checks, "measured": measured}


def main() -> int:
    try:
        req = json.loads(sys.stdin.read())
        resp = run(req)
    except Exception as exc:  # noqa: BLE001
        resp = {
            "ok": False,
            "checks": [_check("worker", False, f"{type(exc).__name__}: {exc}")],
            "measured": {},
        }
    sys.stdout.write(json.dumps(resp))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
