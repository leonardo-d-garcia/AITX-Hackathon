"""CLI for exporting our design artifacts into Lane C's schema shapes.

Usage:
    dronebench-export lanec --design DESIGN_DIR [--revision REV] [--out OUTDIR] \\
        [--mission mission.json] [--spar spar.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .validate import validate_lanec


def _load_json(path: str | None) -> Any:
    if path is None:
        return None
    return json.loads(Path(path).read_text())


def _run_lanec(args: argparse.Namespace) -> int:
    try:
        from dronebench_ingest.revisions import load_manifest, load_features
    except ImportError as exc:
        print(f"error: dronebench_ingest is not importable ({exc})", file=sys.stderr)
        return 2

    design_dir = Path(args.design)
    if not design_dir.is_dir():
        print(f"error: design dir not found: {design_dir}", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else design_dir / "lanec_export" / (args.revision or "latest")
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = load_manifest(design_dir, args.revision)
    features = load_features(design_dir, args.revision)
    mission = _load_json(args.mission)
    spar = _load_json(args.spar)

    try:
        from dronebench_adapters.geometry import to_lanec_geometry
    except ImportError as exc:
        print(
            "error: dronebench_adapters.geometry.to_lanec_geometry is not available yet "
            f"({exc})",
            file=sys.stderr,
        )
        return 2

    try:
        from dronebench_adapters.parts import to_lanec_parts, to_lanec_design_manifest
    except ImportError as exc:
        print(
            "error: dronebench_adapters.parts.to_lanec_parts/to_lanec_design_manifest is not "
            f"available yet ({exc})",
            file=sys.stderr,
        )
        return 2

    lanec_geometry = to_lanec_geometry(features, mission=mission, spar=spar)
    lanec_parts = to_lanec_parts(manifest)
    lanec_design_manifest = to_lanec_design_manifest(manifest)

    outputs = {
        "geometry_features": ("geometry_features.json", lanec_geometry),
        "parts": ("parts.json", lanec_parts),
        "design_manifest": ("design_manifest.json", lanec_design_manifest),
    }

    written = []
    errors: dict[str, list[str]] = {}
    for kind, (filename, doc) in outputs.items():
        errs = validate_lanec(kind, doc)
        if errs:
            errors[kind] = errs
        out_path = out_dir / filename
        out_path.write_text(json.dumps(doc, indent=2, sort_keys=True))
        written.append(str(out_path))

    summary = {"written": written, "valid": not errors, "errors": errors}
    print(json.dumps(summary, indent=2))
    if errors:
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dronebench-export")
    subparsers = parser.add_subparsers(dest="command", required=True)

    lanec = subparsers.add_parser("lanec", help="export a design revision to Lane C's schemas")
    lanec.add_argument("--design", required=True, help="path to the design directory")
    lanec.add_argument("--revision", default=None, help="revision id (default: latest confirmed)")
    lanec.add_argument("--out", default=None, help="output directory (default: <design>/lanec_export/<revision>/)")
    lanec.add_argument("--mission", default=None, help="path to a mission.json override")
    lanec.add_argument("--spar", default=None, help="path to a spar.json override")
    lanec.set_defaults(func=_run_lanec)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
