"""The ``dronebench`` CLI (architecture section 9).

"Emit JSON on stdout and logs on stderr; nonzero exit on invalid input/tool failure; modeled
infeasibility is a valid report distinguished from execution failure."

That last clause is the one worth reading the exit codes for:

===  ===========================================================================================
  0  the command did what was asked
  2  invalid input - a bad id, an unsupported edit, a malformed request
  3  tool failure - a worker crashed, a solver is missing, an artifact does not verify
  4  modelled infeasibility - the command ran correctly and the answer is that the design does not
     satisfy its constraints. This is a *result*, not an error, and a script can tell it apart.
===  ===========================================================================================

Built on argparse rather than a CLI framework: no third-party dependency, and the whole surface is
one file a teammate can read in a sitting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dronebench_contracts import (
    CONTRACT_VERSION,
    DecisionRequest,
    DroneBenchError,
    EXIT_INFEASIBLE,
    EXIT_INVALID_INPUT,
    EXIT_OK,
    EXIT_TOOL_FAILURE,
    canonical_json,
)

from .service import ClaimEntry, ConfirmRequest, Workbench, build_workbench

DEFAULT_ROOT = Path(os.environ.get("DRONEBENCH_ROOT", "artifacts/workbench"))


def out(payload: Any) -> None:
    """JSON on stdout, always. Nothing else is ever written there."""
    print(json.dumps(_plain(payload), indent=2, sort_keys=True, allow_nan=False))


def log(message: str) -> None:
    """Human-readable progress on stderr, so stdout stays machine-parseable."""
    print(message, file=sys.stderr)


def _plain(payload: Any) -> Any:
    from pydantic import BaseModel

    if isinstance(payload, BaseModel):
        return payload.model_dump(mode="json")
    if isinstance(payload, dict):
        return {key: _plain(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_plain(value) for value in payload]
    return payload


# ---------------------------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------------------------


def cmd_doctor(bench: Workbench, args: argparse.Namespace) -> int:
    report = bench.doctor()
    out(report)
    if report["capabilities_absent"]:
        log("absent capabilities:")
        for note in report["capabilities_absent"]:
            log(f"  - {note}")
    return EXIT_OK


def cmd_ingest(bench: Workbench, args: argparse.Namespace) -> int:
    job = bench.jobs.wait(bench.import_fixture(args.fixture).job_id)
    if job.status != "succeeded":
        out({"job": job})
        return EXIT_TOOL_FAILURE
    design_id = job.design_id
    out(
        {
            "job": job,
            "design_id": design_id,
            "active_revision_id": bench.active_revision(design_id),
        }
    )
    log(f"imported {design_id}; confirm units, frame, and the reconstruction before any metrics")
    return EXIT_OK


def cmd_confirm(bench: Workbench, args: argparse.Namespace) -> int:
    entries: list[ClaimEntry] = []
    for raw in args.claim or []:
        # part_id:quantity=value:unit:source_kind:evidence_id
        try:
            target, rest = raw.split("=", 1)
            part_id, quantity = target.split(":", 1)
            value, unit, source_kind, evidence_id = rest.split(":", 3)
        except ValueError:
            log(
                f"could not parse --claim {raw!r}; expected "
                "part_id:quantity=value:unit:source_kind:evidence_id"
            )
            return EXIT_INVALID_INPUT
        entries.append(
            ClaimEntry(
                part_id=part_id,
                quantity=quantity,
                value=float(value),
                unit=unit,
                source_kind=source_kind,
                evidence_id=evidence_id,
            )
        )

    manifest = bench.confirm(
        args.design_id,
        ConfirmRequest(
            units_confirmed=not args.units_unconfirmed,
            frame_confirmed=not args.frame_unconfirmed,
            reconstruction_confirmed=args.reconstruction_confirmed,
            variant_decisions={},
            claim_entries=entries,
        ),
    )
    out(manifest)
    return EXIT_OK


def cmd_parts(bench: Workbench, args: argparse.Namespace) -> int:
    revision_id = _revision(bench, args)
    parts = bench.get_parts(revision_id)
    rows = []
    for occurrence in parts.occurrences:
        mass = occurrence.mass_kg.number()
        rows.append(
            {
                "part_id": occurrence.part_id,
                "name": occurrence.name,
                "role": occurrence.role,
                "mass_kg": mass,
                "mass_status": occurrence.mass_kg.status,
                "mass_source": occurrence.mass_kg.source_kind,
                "locked": occurrence.locked,
                "edit_capabilities": occurrence.edit_capabilities,
                "x_m": occurrence.transform.translation[0],
            }
        )
    unknown = [r["part_id"] for r in rows if r["mass_kg"] is None]
    out({"revision_id": revision_id, "occurrences": rows, "unknown_mass": unknown})
    if unknown:
        log(f"{len(unknown)} occurrence(s) have no mass evidence: {', '.join(unknown)}")
    return EXIT_OK


def cmd_graph(bench: Workbench, args: argparse.Namespace) -> int:
    revision_id = _revision(bench, args)
    if args.part_id:
        out(bench.get_neighborhood(revision_id, args.part_id, radius=args.radius))
    else:
        graph = bench.get_graph(revision_id)
        out(
            {
                "revision_id": graph.revision_id,
                "nodes": len(graph.nodes),
                "edges": len(graph.edges),
                "unknown_relationships": graph.unknown_relationships,
            }
        )
    return EXIT_OK


def cmd_explain(bench: Workbench, args: argparse.Namespace) -> int:
    out(bench.explain(_revision(bench, args), args.part_id, args.question))
    return EXIT_OK


def cmd_evaluate(bench: Workbench, args: argparse.Namespace) -> int:
    revision_id = _revision(bench, args)
    _, evaluation = bench.evaluate(revision_id, fidelity=args.fidelity)
    assert evaluation is not None
    out(evaluation)
    blocking = evaluation.blocking()
    if blocking:
        for check in blocking:
            log(f"{check.status.upper():8s} {check.check_id}: {check.reason}")
        # The command succeeded; the design did not. Different exit code, deliberately.
        return EXIT_INFEASIBLE
    log(f"verified feasible within the implemented model ({evaluation.ui_claim})")
    return EXIT_OK


def cmd_recommend(bench: Workbench, args: argparse.Namespace) -> int:
    revision_id = _revision(bench, args)
    result = bench.recommend(revision_id, preview_all=not args.no_preview)
    out(result)
    for request in result.evidence_requests:
        log(f"missing evidence: {request.title} -> blocks {', '.join(request.blocked_check_ids)}")
    for proposal in result.displayed():
        log(f"{proposal.proposal_id}: {proposal.display_label} [{proposal.state}]")
    if result.evidence_requests and not result.generated:
        return EXIT_INFEASIBLE
    return EXIT_OK


def cmd_preview(bench: Workbench, args: argparse.Namespace) -> int:
    proposal = bench.preview(args.proposal_id)
    out(proposal)
    if proposal.preview is None or not proposal.preview.cad_ok:
        return EXIT_INFEASIBLE
    return EXIT_OK


def cmd_accept(bench: Workbench, args: argparse.Namespace) -> int:
    proposal = bench.repository.get_proposal(args.proposal_id)
    if proposal.preview is None:
        log("this proposal has no preview; run `dronebench preview` first")
        return EXIT_INVALID_INPUT
    outcome = bench.decide(
        DecisionRequest(
            proposal_id=args.proposal_id,
            decision="accept",
            expected_active_revision_id=args.expected or bench.active_revision(proposal.design_id),
            preview_hash=args.preview_hash or proposal.preview.preview_hash,
            idempotency_key=args.idempotency_key,
        )
    )
    out(outcome)
    return EXIT_OK


def cmd_decline(bench: Workbench, args: argparse.Namespace) -> int:
    proposal = bench.repository.get_proposal(args.proposal_id)
    outcome = bench.decide(
        DecisionRequest(
            proposal_id=args.proposal_id,
            decision="decline",
            expected_active_revision_id=args.expected or bench.active_revision(proposal.design_id),
            idempotency_key=args.idempotency_key,
            reason=args.reason,
        )
    )
    out(outcome)
    return EXIT_OK


def cmd_undo(bench: Workbench, args: argparse.Namespace) -> int:
    target = bench.undo(args.design_id, to_revision_id=args.to)
    out({"design_id": args.design_id, "active_revision_id": target})
    return EXIT_OK


def cmd_simulate(bench: Workbench, args: argparse.Namespace) -> int:
    revision_id = _revision(bench, args)
    _, run = bench.simulate(revision_id)
    assert run is not None
    out(
        {
            "run_id": run.run_id,
            "revision_id": run.revision_id,
            "fidelity": run.fidelity,
            "flight_model_tier": run.flight_model_tier,
            "completed_route": run.completed_route,
            "termination_reason": run.termination_reason,
            "duration_s": run.duration_s(),
            "samples": len(run.samples),
            "assumptions": run.assumptions,
        }
    )
    if not run.completed_route:
        log("the route was not completed on usable energy; this is a result, not a failure")
        return EXIT_INFEASIBLE
    return EXIT_OK


def cmd_export(bench: Workbench, args: argparse.Namespace) -> int:
    out(bench.export(_revision(bench, args)))
    return EXIT_OK


def cmd_history(bench: Workbench, args: argparse.Namespace) -> int:
    out(
        {
            "design_id": args.design_id,
            "active_revision_id": bench.active_revision(args.design_id),
            "revisions": bench.history(args.design_id),
        }
    )
    return EXIT_OK


def cmd_events(bench: Workbench, args: argparse.Namespace) -> int:
    out({"events": bench.events(args.design_id, args.after)})
    return EXIT_OK


def cmd_schema(bench: Workbench, args: argparse.Namespace) -> int:
    from dronebench_contracts.schema import write_bundle, bundle_hash

    target = write_bundle(Path(args.outdir))
    out({"written": str(target), "bundle_sha256": bundle_hash()})
    return EXIT_OK


# ---------------------------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------------------------


def _revision(bench: Workbench, args: argparse.Namespace) -> str:
    if getattr(args, "revision_id", None):
        return args.revision_id
    design_id = getattr(args, "design_id", None)
    if not design_id:
        designs = bench.repository.list_designs()
        if len(designs) != 1:
            raise DroneBenchError.of(
                "INVALID_REQUEST",
                "name a --revision-id or --design-id; this store holds "
                f"{len(designs)} designs",
            )
        design_id = designs[0]["design_id"]
    return bench.active_revision(design_id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dronebench",
        description="DroneBench Studio - JSON on stdout, logs on stderr.",
        epilog=(
            "exit codes: 0 ok, 2 invalid input, 3 tool failure, "
            "4 modelled infeasibility (a valid report, not an error)"
        ),
    )
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="workbench storage root")
    parser.add_argument("--version", action="version", version=f"dronebench {CONTRACT_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    def revision_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--revision-id")
        p.add_argument("--design-id")

    p = sub.add_parser("doctor", help="what is installed and what is absent")
    p.set_defaults(handler=cmd_doctor)

    p = sub.add_parser("ingest", help="stage a checked-in fixture as a new design")
    p.add_argument("--fixture", default="b")
    p.set_defaults(handler=cmd_ingest)

    p = sub.add_parser("confirm", help="confirm units, frame, reconstruction, and supply claims")
    p.add_argument("design_id")
    p.add_argument("--units-unconfirmed", action="store_true")
    p.add_argument("--frame-unconfirmed", action="store_true")
    p.add_argument("--reconstruction-confirmed", action="store_true")
    p.add_argument(
        "--claim",
        action="append",
        metavar="part_id:quantity=value:unit:source_kind:evidence_id",
        help="supply a previously unknown value with its provenance; repeatable",
    )
    p.set_defaults(handler=cmd_confirm)

    p = sub.add_parser("parts", help="installed occurrences, claims, and capabilities")
    revision_args(p)
    p.set_defaults(handler=cmd_parts)

    p = sub.add_parser("graph", help="the typed graph, or a bounded neighbourhood")
    revision_args(p)
    p.add_argument("--part-id")
    p.add_argument("--radius", type=int, default=2)
    p.set_defaults(handler=cmd_graph)

    p = sub.add_parser("explain", help="answer one narrow evidence question")
    revision_args(p)
    p.add_argument("part_id")
    p.add_argument(
        "question",
        choices=["mass_evidence", "what_fails_if_moved", "affected_by_edit", "fitting_alternatives"],
    )
    p.set_defaults(handler=cmd_explain)

    p = sub.add_parser("evaluate", help="run the checks against the locked mission")
    revision_args(p)
    p.add_argument("--fidelity", default="analytic", choices=["analytic", "vspaero_informed"])
    p.set_defaults(handler=cmd_evaluate)

    p = sub.add_parser("recommend", help="generate, preview, and rank bounded proposals")
    revision_args(p)
    p.add_argument("--no-preview", action="store_true", help="skip real previews")
    p.set_defaults(handler=cmd_recommend)

    p = sub.add_parser("preview", help="build one proposal's isolated child revision")
    p.add_argument("proposal_id")
    p.set_defaults(handler=cmd_preview)

    p = sub.add_parser("accept", help="commit precisely the reviewed preview")
    p.add_argument("proposal_id")
    p.add_argument("--idempotency-key", required=True)
    p.add_argument("--expected", help="the active revision you believe you are accepting against")
    p.add_argument("--preview-hash")
    p.set_defaults(handler=cmd_accept)

    p = sub.add_parser("decline", help="record a decision without changing anything")
    p.add_argument("proposal_id")
    p.add_argument("--idempotency-key", required=True)
    p.add_argument("--expected")
    p.add_argument("--reason")
    p.set_defaults(handler=cmd_decline)

    p = sub.add_parser("undo", help="switch back to a revision the design was in")
    p.add_argument("design_id")
    p.add_argument("--to")
    p.set_defaults(handler=cmd_undo)

    p = sub.add_parser("simulate", help="reduced-order mission run for an exact revision")
    revision_args(p)
    p.set_defaults(handler=cmd_simulate)

    p = sub.add_parser("export", help="export the editable assembly, if the round trip passes")
    revision_args(p)
    p.set_defaults(handler=cmd_export)

    p = sub.add_parser("history", help="the states this design was actually in")
    p.add_argument("design_id")
    p.set_defaults(handler=cmd_history)

    p = sub.add_parser("events", help="the audit log")
    p.add_argument("design_id")
    p.add_argument("--after", type=int, default=0)
    p.set_defaults(handler=cmd_events)

    p = sub.add_parser("schema", help="regenerate the JSON Schema bundle")
    p.add_argument("--outdir", default="schema")
    p.set_defaults(handler=cmd_schema)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    bench = build_workbench(Path(args.root))
    try:
        return args.handler(bench, args)
    except DroneBenchError as exc:
        out(exc.envelope)
        log(f"{exc.envelope.code}: {exc.envelope.message}")
        return exc.envelope.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        log("interrupted")
        return EXIT_TOOL_FAILURE
    except Exception as exc:  # noqa: BLE001
        out({"code": "INTERNAL", "message": str(exc), "retryable": False})
        log(f"INTERNAL: {exc}")
        return EXIT_TOOL_FAILURE
    finally:
        bench.close()


if __name__ == "__main__":
    raise SystemExit(main())
