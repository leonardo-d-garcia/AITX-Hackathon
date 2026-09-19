"""CLI: evaluate geometry, simulate a mission, or report solver status."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"{path} is not a JSON object")
    return data


def cmd_evaluate(args: argparse.Namespace) -> int:
    from evaluate import evaluate_revision  # type: ignore

    geometry = _load_json(Path(args.geometry))
    parts_raw = json.loads(Path(args.parts).read_text(encoding="utf-8"))
    if isinstance(parts_raw, list):
        parts = parts_raw
    elif isinstance(parts_raw, dict):
        parts = parts_raw.get("occurrences", parts_raw.get("parts", parts_raw))
    else:
        raise SystemExit(f"{args.parts} must be a list or object")
    mission = _load_json(Path(args.mission)) if args.mission else geometry.get("mission")
    result = evaluate_revision(geometry, parts, mission=mission)
    text = json.dumps(result, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from sim import simulate_mission, write_simulation_run  # type: ignore

    geometry = _load_json(Path(args.geometry))
    parts_raw = json.loads(Path(args.parts).read_text(encoding="utf-8"))
    if isinstance(parts_raw, list):
        parts = parts_raw
    elif isinstance(parts_raw, dict):
        parts = parts_raw.get("occurrences", parts_raw.get("parts", parts_raw))
    else:
        raise SystemExit(f"{args.parts} must be a list or object")
    run = simulate_mission(geometry, parts)
    out = Path(args.out) if args.out else Path("simulation_run.json")
    write_simulation_run(out, run)
    print(str(out))
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    try:
        from openvsp_worker import available, status_dict  # type: ignore

        status = status_dict() if callable(status_dict) else {"available": available()}
    except Exception as exc:  # noqa: BLE001 — doctor must never crash
        status = {"available": False, "error": str(exc)}
    print(json.dumps(status, indent=2))
    return 0 if status.get("available") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dronebench")
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("evaluate", help="write evaluation.json")
    p_eval.add_argument("--geometry", required=True)
    p_eval.add_argument("--parts", required=True)
    p_eval.add_argument("--mission")
    p_eval.add_argument("--out")
    p_eval.set_defaults(func=cmd_evaluate)

    p_sim = sub.add_parser("simulate", help="write simulation_run.json")
    p_sim.add_argument("--geometry", required=True)
    p_sim.add_argument("--parts", required=True)
    p_sim.add_argument("--out")
    p_sim.set_defaults(func=cmd_simulate)

    p_doc = sub.add_parser("doctor", help="OpenVSP worker status")
    p_doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
