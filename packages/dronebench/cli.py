"""CLI stub. Wave 2 fills evaluate/simulate."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dronebench")
    parser.add_argument(
        "command",
        choices=["evaluate", "simulate", "doctor"],
        help="evaluate geometry, simulate a mission, or report solver status",
    )
    parser.parse_args(argv)
    print("not implemented", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
