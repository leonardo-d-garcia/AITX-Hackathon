"""Thin CLI over cad.titan_archive.convert_archive.

Does not fuse meshes. Does not invent mass or material. Unreal is not involved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cad import convert_archive, find_archive_zip
from cad.titan_archive import BASELINE_WING3, CAD_FIXTURE_DIR, WING3_16MM

MESH_DIR = CAD_FIXTURE_DIR / "meshes"
DEFAULT_GLB_12MM = MESH_DIR / "titan_avenger.glb"
DEFAULT_GLB_16MM = MESH_DIR / "titan_avenger_16mm.glb"
EXPECTED_NODE_COUNT = 30


def default_out(wing3: str) -> Path:
    if wing3 == WING3_16MM:
        return DEFAULT_GLB_16MM
    return DEFAULT_GLB_12MM


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="convert_titan")
    parser.add_argument(
        "--zip",
        type=Path,
        default=None,
        help="Titan print-archive zip (default: cad.find_archive_zip())",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "Destination GLB (default: fixtures/c/titan_avenger_cad/meshes/"
            "titan_avenger.glb, or titan_avenger_16mm.glb when --wing3 is "
            f"{WING3_16MM})"
        ),
    )
    parser.add_argument(
        "--wing3",
        default=BASELINE_WING3,
        help=f"Wing3 STL stem (default: {BASELINE_WING3})",
    )
    parser.add_argument(
        "--stl-root",
        type=Path,
        default=None,
        dest="stl_root",
        help="Extracted STL root; skip zip extract when set",
    )
    args = parser.parse_args(argv)

    zip_path = args.zip if args.zip is not None else find_archive_zip()
    dest_glb = args.out if args.out is not None else default_out(args.wing3)
    report = convert_archive(
        zip_path,
        dest_glb=dest_glb,
        wing3=args.wing3,
        stl_root=args.stl_root,
    )
    summary = {
        "node_count": report["node_count"],
        "triangles": report["triangles"],
        "span_m": report["span_m"],
        "length_m": report["length_m"],
        "glb": report["glb"],
    }
    print(json.dumps(summary, indent=2))
    if int(report["node_count"]) != EXPECTED_NODE_COUNT:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
