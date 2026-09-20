"""CLI: write print-archive CAD fixture JSON via cad.build_fixture.write_fixture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_PACKAGES = Path(__file__).resolve().parents[1] / "packages"
if str(_PACKAGES) not in sys.path:
    sys.path.insert(0, str(_PACKAGES))

from cad.build_fixture import write_fixture  # noqa: E402

DEFAULT_DEST = Path("fixtures/c/titan_avenger_cad")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write print-archive CAD fixture JSON.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="Output directory (default: fixtures/c/titan_avenger_cad)",
    )
    args = parser.parse_args(argv)
    dest = write_fixture(Path(args.dest))
    print(dest)
    for path in sorted(p for p in dest.iterdir() if p.is_file()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
