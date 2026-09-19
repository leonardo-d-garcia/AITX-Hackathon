"""``dronebench-a`` — ingest, inspect, confirm, and report on a mesh design.

JSON goes to stdout, human logs go to stderr. The exit code is non-zero only when the command
could not be carried out: an *unconfirmed* design is a valid report, not a failure, so
``features`` on it prints an ErrorEnvelope and exits 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dronebench_contracts.models import ErrorEnvelope

from .errors import IngestError
from .features import geometry_features
from .frame import propose_frame
from .glb import GLB_NAME, export_reference_glb
from .inspection import inspect_sources
from .revisions import confirm, load_manifest, preview_manifest, revision_dir
from .staging import load_staged, stage_archive
from .variants import detect_variants


def _emit(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _manifest_or_preview(args) -> Any:
    try:
        return load_manifest(args.design_dir, args.revision)
    except IngestError:
        _log("no confirmed revision; using an unconfirmed preview manifest")
        return preview_manifest(args.design_dir)


def _cmd_ingest(args) -> int:
    staged = stage_archive(args.archive, args.design_dir)
    _log(f"staged {len(staged.files)} files into {staged.root}")
    sources = inspect_sources(staged)
    _emit({
        "design_dir": str(args.design_dir),
        "staged": staged.model_dump(mode="json"),
        "sources": [s.model_dump(mode="json") for s in sources],
        "frame_proposal": propose_frame(sources).model_dump(mode="json"),
        "variants": [v.model_dump(mode="json") for v in detect_variants(sources)],
        "note": "nothing is confirmed: no metric may be published from this report",
    })
    return 0


def _cmd_inspect(args) -> int:
    staged = load_staged(args.design_dir)
    sources = inspect_sources(staged)
    _emit({
        "sources": [s.model_dump(mode="json") for s in sources],
        "frame_proposal": propose_frame(sources).model_dump(mode="json"),
        "variants": [v.model_dump(mode="json") for v in detect_variants(sources)],
        "not_watertight": [s.source_path for s in sources if not s.qa.watertight],
    })
    return 0


def _cmd_confirm(args) -> int:
    choices = {}
    for item in args.select or []:
        group, _, option = item.partition("=")
        choices[group.strip()] = option.strip()
    mirror: bool | str = args.mirror if args.mirror not in (None, "auto") else True
    if args.mirror == "none":
        mirror = False
    revision = confirm(args.design_dir, units=args.units, variants=choices, mirror=mirror,
                       mass_model=args.mass_model, confirmed_by=args.confirmed_by)
    _log(f"wrote revision {revision.revision_id} "
         f"({len(revision.artifacts)} artifacts) to {revision_dir(args.design_dir, revision.revision_id)}")
    _emit(revision)
    return 0


def _cmd_parts(args) -> int:
    manifest = _manifest_or_preview(args)
    _emit({"design_id": manifest.design_id, "revision_id": manifest.revision_id,
           "confirmed": manifest.frame.confirmed,
           "parts": [p.model_dump(mode="json") for p in manifest.parts],
           "excluded_sources": manifest.excluded_sources,
           "warnings": manifest.warnings})
    return 0


def _cmd_features(args) -> int:
    result = geometry_features(_manifest_or_preview(args))
    if isinstance(result, ErrorEnvelope):
        _log(f"{result.code.value}: {result.message}")
    _emit(result)
    return 0


def _cmd_export_reference(args) -> int:
    manifest = _manifest_or_preview(args)
    if args.out:
        out = Path(args.out)
    else:
        try:
            out = revision_dir(args.design_dir, args.revision) / GLB_NAME
        except IngestError:
            out = Path(args.design_dir) / GLB_NAME
    result = export_reference_glb(manifest, out)
    if isinstance(result, ErrorEnvelope):
        _log(f"{result.code.value}: {result.message}")
    else:
        _log(f"wrote {out}")
    _emit(result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dronebench-a", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_design_dir(p, revision=True):
        p.add_argument("--design-dir", required=True, type=Path)
        if revision:
            p.add_argument("--revision", default=None, help="revision id (default: the newest)")

    p = sub.add_parser("ingest", help="stage an archive or folder and report what is in it")
    p.add_argument("archive", type=Path)
    add_design_dir(p, revision=False)
    p.set_defaults(func=_cmd_ingest)

    p = sub.add_parser("inspect", help="per-mesh QA, frame proposal and variant groups")
    add_design_dir(p, revision=False)
    p.set_defaults(func=_cmd_inspect)

    p = sub.add_parser("confirm", help="record explicit choices and write a revision")
    add_design_dir(p, revision=False)
    p.add_argument("--units", required=True, choices=["mm", "m", "in"])
    p.add_argument("--select", action="append", metavar="GROUP=SOURCE_PATH",
                   help="variant choice; repeat once per detected group")
    p.add_argument("--mirror", default="auto",
                   help="'auto' (the proposed plane), 'none', or a plane such as 'x=0'")
    p.add_argument("--mass-model", default="none", choices=["none", "shell_estimate"])
    p.add_argument("--confirmed-by", default="user")
    p.set_defaults(func=_cmd_confirm)

    p = sub.add_parser("parts", help="installed occurrences of a revision")
    add_design_dir(p)
    p.set_defaults(func=_cmd_parts)

    p = sub.add_parser("features", help="measured geometry of a confirmed revision")
    add_design_dir(p)
    p.set_defaults(func=_cmd_features)

    p = sub.add_parser("export-reference", help="write the reference GLB")
    add_design_dir(p)
    p.add_argument("--out", default=None, type=Path)
    p.set_defaults(func=_cmd_export_reference)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except IngestError as exc:
        _log(f"{exc.envelope.code.value}: {exc.envelope.message}")
        _emit(exc.envelope)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
