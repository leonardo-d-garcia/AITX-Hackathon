"""Put `packages/viewer` and `packages/contracts` on the path without a root install."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for pkg in ("viewer", "contracts"):
    p = str(ROOT / "packages" / pkg)
    if p not in sys.path:
        sys.path.insert(0, p)
