"""``dronebench-edit`` — inspect revisions, propose an edit, accept or decline a preview.

JSON goes to stdout, human logs to stderr. Exit codes: ``0`` success, ``2`` usage error, ``1``
execution failure. A *blocked* edit is a successful report, not a failure: the tool did its job by
refusing, so it prints a typed ``CadEditResult``/``ErrorEnvelope`` and exits ``0``.

``propose``/``preview`` delegate to :func:`dronebench_edits.apply_edit`, which is imported lazily
inside the command so that this module (and ``history``/``active``/``accept``/``decline``) works
whether or not the edit operations are installed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from dronebench_contracts.models import ErrorCode, ErrorEnvelope

from .api import EditBlocked
from .store import edit_status, store

PROG = "dronebench-edit"


def _emit(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _log(message: str) -> None:
    print(message, file=sys.stderr)


def _emit_error(code: ErrorCode, message: str, **details: Any) -> None:
    _log(f"{code.value}: {message}")
    _emit(ErrorEnvelope(code=code, message=message, details=details))


# ------------------------------------------------------------------ commands

def _cmd_history(args) -> int:
    revisions = store.history(args.design_dir)
    if args.limit:
        revisions = revisions[: args.limit]
    active = store.active_or_none(args.design_dir)
    _log(f"{len(revisions)} revision(s); active is {active or 'unset'}")
    _emit({
        "design_dir": str(args.design_dir),
        "active_revision_id": active,
        "revisions": [{**r.model_dump(mode="json"),
                       "edit_status": edit_status(args.design_dir, r.revision_id)}
                      for r in revisions],
    })
    return 0


def _cmd_active(args) -> int:
    active = store.active_revision(args.design_dir)
    revision = next((r for r in store.history(args.design_dir) if r.revision_id == active), None)
    _emit({
        "design_dir": str(args.design_dir),
        "active_revision_id": active,
        "revision": revision.model_dump(mode="json") if revision else None,
    })
    return 0


def _cmd_accept(args) -> int:
    manifest = store.commit(args.design_dir, args.revision_id, args.expected_active)
    _log(f"active is now {manifest.revision_id}")
    _emit(manifest)
    return 0


def _cmd_decline(args) -> int:
    manifest = store.decline(args.design_dir, args.revision_id, args.reason)
    _log(f"declined {manifest.revision_id}; active unchanged")
    _emit({
        "declined_revision_id": manifest.revision_id,
        "reason": args.reason,
        "active_revision_id": store.active_or_none(args.design_dir),
        "revision": manifest.model_dump(mode="json"),
    })
    return 0


def _cmd_decisions(args) -> int:
    _emit({"design_dir": str(args.design_dir), "decisions": store.decisions(args.design_dir)})
    return 0


def _load_apply_edit():
    """Import A3b's entry point only when an edit is actually asked for.

    ``api.apply_edit`` is a ``NotImplementedError`` stub, so an import that resolves to it counts
    as "not available" rather than as a working edit path.
    """
    try:
        from .apply import apply_edit as fn       # A3b's module
    except ImportError:
        import dronebench_edits
        fn = getattr(dronebench_edits, "apply_edit", None)
        if fn is None:
            raise ImportError("dronebench_edits.apply_edit is not defined")
    if getattr(fn, "__module__", "") == "dronebench_edits.api":
        raise ImportError("apply_edit is still the api.py stub")
    return fn


def _cmd_propose(args) -> int:
    from dronebench_contracts.models import CadEditRequest

    # The command line is checked before anything is loaded: a typo is a usage error (2), not a
    # report about a missing edit module.
    try:
        parameters = json.loads(args.params) if args.params else {}
    except json.JSONDecodeError as exc:
        _log(f"--params is not valid JSON: {exc}")
        return 2
    if not isinstance(parameters, dict):
        _log("--params must be a JSON object")
        return 2

    try:
        apply_edit = _load_apply_edit()
    except (ImportError, AttributeError, NotImplementedError) as exc:
        _emit_error(ErrorCode.UNSUPPORTED_EDIT,
                    "edit operations are not available in this installation "
                    "(dronebench_edits.apply_edit is missing); "
                    "history, active, accept and decline still work",
                    reason=str(exc))
        return 1

    base = args.base or store.active_revision(args.design_dir)
    request = CadEditRequest(base_revision_id=base, operation=args.operation,
                             target_part_ids=list(args.target or []), parameters=parameters,
                             idempotency_key=args.idempotency_key)
    _log(f"{args.operation} on {base} -> preview")
    result = apply_edit(Path(args.design_dir), request)

    if args.accept and getattr(result, "status", None) == "ok" and result.preview_revision_id:
        manifest = store.commit(args.design_dir, result.preview_revision_id, base)
        _log(f"accepted; active is now {manifest.revision_id}")
        _emit({"result": result.model_dump(mode="json"),
               "committed": manifest.model_dump(mode="json")})
        return 0
    _emit(result)
    return 0


# ------------------------------------------------------------------ parser

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description=__doc__.splitlines()[0])
    subs = parser.add_subparsers(dest="command", required=True)

    def design_arg(sub):
        sub.add_argument("design_dir", type=Path, help="the ingest design directory")

    p = subs.add_parser("history", help="every revision, newest first")
    design_arg(p)
    p.add_argument("--limit", type=int, default=0, help="show only the newest N")
    p.set_defaults(func=_cmd_history)

    p = subs.add_parser("active", help="the revision metrics are measured against")
    design_arg(p)
    p.set_defaults(func=_cmd_active)

    p = subs.add_parser("accept", help="commit a preview: compare-and-swap the active pointer")
    design_arg(p)
    p.add_argument("revision_id", help="the preview revision to commit")
    p.add_argument("--expected-active", default=None,
                   help="the revision you believe is active; omit to waive the staleness check")
    p.set_defaults(func=_cmd_accept)

    p = subs.add_parser("decline", help="record a decision against a preview; changes nothing")
    design_arg(p)
    p.add_argument("revision_id")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=_cmd_decline)

    p = subs.add_parser("decisions", help="the accept/decline log, oldest first")
    design_arg(p)
    p.set_defaults(func=_cmd_decisions)

    for name, help_text in (("propose", "run a typed edit and stage a preview revision"),
                            ("preview", "alias of propose")):
        p = subs.add_parser(name, help=help_text)
        design_arg(p)
        p.add_argument("--operation", required=True,
                       help="translate_component | resize_spar | set_wing_tip_extension")
        p.add_argument("--target", action="append", default=[], metavar="PART_ID",
                       help="target part id; repeatable")
        p.add_argument("--params", default="{}", help="JSON object of SI parameters")
        p.add_argument("--base", default=None, help="base revision id (default: the active one)")
        p.add_argument("--idempotency-key", default=None)
        p.add_argument("--accept", action="store_true",
                       help="commit the preview immediately if it is ok")
        p.set_defaults(func=_cmd_propose)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except EditBlocked as exc:
        # A refusal is a report. The tool worked; the edit did not.
        _log(f"{exc.envelope.code.value}: {exc.envelope.message}")
        _emit(exc.envelope)
        return 0
    except BrokenPipeError:                        # piped into head, less, ...
        import os
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except FileNotFoundError as exc:
        _emit_error(ErrorCode.MISSING_EVIDENCE, str(exc))
        return 1
    except Exception as exc:                       # anything unexpected is an execution failure
        envelope = getattr(exc, "envelope", None)
        if isinstance(envelope, ErrorEnvelope):
            _log(f"{envelope.code.value}: {envelope.message}")
            _emit(envelope)
            return 1
        _emit_error(ErrorCode.GEOMETRY_INVALID, f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
