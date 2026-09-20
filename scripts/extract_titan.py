"""Stage the supplied aircraft archive for the web viewport.

The archive is **not in this repository**, and deliberately so. Architecture section 2: the ZIP
contains no licence document, so the original asset stays outside a public repository until reuse
terms are established. This script puts it where the dev server can read it, locally, on the
machine that already has a copy.

    python scripts/extract_titan.py [path/to/archive.zip]

With no argument it looks for the archive in the usual download locations. It writes the 24 binary
STL meshes to ``apps/web/public/titan/`` (git-ignored) plus a manifest recording each file's size
and SHA-256, so a later run can prove it staged the same bytes.
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "apps" / "web" / "public" / "titan"

CANDIDATES = [
    Path.home() / "Downloads" / "Titan+Avenger+(Fixed+Wing)+(VTOL+on+Profile).zip",
    ROOT / "vendor_assets" / "Titan+Avenger+(Fixed+Wing)+(VTOL+on+Profile).zip",
    ROOT / "vendor_assets" / "avenger.zip",
]


def find_archive(argv: list[str]) -> Path | None:
    if argv:
        candidate = Path(argv[0]).expanduser()
        return candidate if candidate.is_file() else None
    for candidate in CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    archive = find_archive(args)

    if archive is None:
        print(
            "Could not find the aircraft archive.\n\n"
            "It is not committed: the ZIP carries no licence document, so it stays out of a public\n"
            "repository (architecture section 2). Pass its path explicitly:\n\n"
            "    python scripts/extract_titan.py path/to/archive.zip\n\n"
            "Without it the workbench still runs — the 3D viewport simply reports that it has no\n"
            "geometry to draw, which is the honest state rather than a substitute model.",
            file=sys.stderr,
        )
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []

    with zipfile.ZipFile(archive) as zf:
        names = [name for name in zf.namelist() if name.lower().endswith(".stl")]
        if not names:
            print(f"{archive} contains no STL files", file=sys.stderr)
            return 2
        for name in sorted(names):
            data = zf.read(name)
            flat = name.split("/")[-1]
            (OUT / flat).write_bytes(data)
            manifest.append(
                {
                    "file": flat,
                    "source": name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    total = sum(int(entry["bytes"]) for entry in manifest)
    print(
        json.dumps(
            {
                "archive": str(archive),
                "staged_to": str(OUT.relative_to(ROOT)).replace("\\", "/"),
                "meshes": len(manifest),
                "bytes": total,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
