#!/usr/bin/env python3
"""Inline demo_data.json and the GLB assets into one distributable HTML file.

The dev page (dronebench_demo.html) fetches data/demo_data.json and assets/*.glb
relative to itself, which needs a server. This script bakes both into the page as
literals so the result opens from file:// on any laptop with no server at all.

    python3 demo/build_demo.py
    -> demo/dronebench_demo_standalone.html
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAGE = HERE / "dronebench_demo.html"
DATA = HERE / "data" / "demo_data.json"
ASSETS = HERE / "assets"
OUT = HERE / "dronebench_demo_standalone.html"
FLIGHT = HERE / "flight.js"

# Anchor: the injected block goes immediately before the first module script,
# so it is defined before anything reads it.
ANCHOR = '<script type="module">'


def human(n: int) -> str:
    mb = n / 1048576
    return f"{mb:.1f} MB" if mb >= 1 else f"{n / 1024:.0f} KB"


def main() -> int:
    if not PAGE.exists():
        print(f"missing page: {PAGE}", file=sys.stderr)
        return 1
    html = PAGE.read_text(encoding="utf-8")

    if DATA.exists():
        data = json.loads(DATA.read_text(encoding="utf-8"))
        print(f"data   {DATA.name}  {human(DATA.stat().st_size)}")
    else:
        print(f"data   {DATA.name} NOT FOUND — the page will fall back to its inline mock",
              file=sys.stderr)
        data = None

    assets: dict[str, str] = {}
    total = 0
    for glb in sorted(ASSETS.glob("*.glb")):
        raw = glb.read_bytes()
        total += len(raw)
        assets[glb.stem] = "data:model/gltf-binary;base64," + base64.b64encode(raw).decode("ascii")
        print(f"asset  {glb.name:<28} {human(len(raw))}")
    if not assets:
        print("assets none found — the page will fall back to placeholder geometry", file=sys.stderr)

    # Flight scene, if the third builder has landed it. Inlining it keeps the
    # standalone page to a single file.
    flight_js = FLIGHT.read_text(encoding="utf-8") if FLIGHT.exists() else None

    block = ["<script>\n/* --- baked in by build_demo.py --- */\n"]
    if data is not None:
        block.append("window.__DEMO_DATA__ = " + json.dumps(data, separators=(",", ":")) + ";\n")
    block.append("window.__DEMO_ASSETS__ = " + json.dumps(assets, separators=(",", ":")) + ";\n")
    block.append("</script>\n")
    if flight_js is not None:
        # </script> inside the source would close our wrapper early.
        block.append("<script>\n" + flight_js.replace("</script>", "<\\/script>") + "\n</script>\n")

    injected = "".join(block)

    # Drop the external flight.js tag; the inlined copy (if any) replaces it.
    html = html.replace(
        '<script src="flight.js" onerror="window.__flightMissing=true"></script>\n',
        "" if flight_js is not None else
        '<script src="flight.js" onerror="window.__flightMissing=true"></script>\n',
    )

    idx = html.find(ANCHOR)
    if idx < 0:
        print("could not find the module script anchor in the page", file=sys.stderr)
        return 1
    out = html[:idx] + injected + html[idx:]
    OUT.write_text(out, encoding="utf-8")

    print(f"\nwrote  {OUT.name}  {human(OUT.stat().st_size)}"
          f"  ({len(assets)} asset(s), {human(total)} raw)")
    if OUT.stat().st_size > 120 * 1024 * 1024:
        print("warning: over 120 MB — decimate the GLBs before handing this around",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
