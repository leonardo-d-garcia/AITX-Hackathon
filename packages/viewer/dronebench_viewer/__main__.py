"""`python -m dronebench_viewer` — build the static inspector from artifacts on disk.

A1's CLI can shell out to this, or import `render_inspector` directly for `dronebench-a viewer`.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .inspector import render_inspector
from .mock import build_mock_artifacts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="dronebench_viewer", description=__doc__)
    ap.add_argument("--manifest", type=Path, help="design_manifest.json")
    ap.add_argument("--reference", type=Path, help="reference GLB (original mesh representation)")
    ap.add_argument("--reconstruction", type=Path, default=None, help="reconstruction GLB")
    ap.add_argument("--features", type=Path, default=None, help="geometry_features.json")
    ap.add_argument("--fit-report", type=Path, default=None, help="fit_report.json")
    ap.add_argument("--edit-result", type=Path, default=None, help="cad_edit_result.json")
    ap.add_argument("--out", type=Path, default=Path("artifacts/inspector.html"))
    ap.add_argument("--mock", action="store_true",
                    help="regenerate the mock artifacts first and render those")
    args = ap.parse_args(argv)

    if args.mock:
        m = build_mock_artifacts()
        args.manifest = args.manifest or m["design_manifest"]
        args.reference = args.reference or m["reference_glb"]
        args.reconstruction = args.reconstruction or m["reconstruction_glb"]
        args.features = args.features or m["geometry_features"]
        args.fit_report = args.fit_report or m["fit_report"]
        args.edit_result = args.edit_result or m["cad_edit_result"]

    if not args.manifest or not args.reference:
        ap.error("--manifest and --reference are required (or pass --mock)")

    out = render_inspector(
        args.manifest,
        {"reference": args.reference, "reconstruction": args.reconstruction},
        args.out,
        features_json=args.features,
        fit_report=args.fit_report,
        edit_result=args.edit_result,
    )
    print(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
