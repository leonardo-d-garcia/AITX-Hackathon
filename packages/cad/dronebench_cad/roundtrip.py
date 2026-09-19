"""Export acceptance: reimport the STEP in a fresh process and compare semantics.

Architecture §6: "Reimport it in a fresh worker; check solids, bounds, placements and
sidecar identity coverage... Compare semantic geometry, not STEP byte hashes."

The worker is a separate process on purpose. A malformed STEP can abort the OCCT reader
inside the C++ layer, which no `try:` in this process would survive, and a pathological file
can spin for minutes; both are contained here as a failed check with a readable detail.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

__all__ = ["reimport_check", "DEFAULT_TOLERANCES", "WORKER_TIMEOUT_S"]

WORKER_TIMEOUT_S = 120.0

DEFAULT_TOLERANCES = {
    "placement_m": 1e-4,        # 0.1 mm — demo validation setting, not a manufacturing tolerance
    "bounds_m": 1e-4,           # 0.1 mm
    "volume_relative": 1e-4,
    "volume_absolute_m3": 1e-12,
}


def _failed(name: str, detail: str) -> list[dict[str, Any]]:
    return [{"name": name, "passed": False, "detail": detail}]


def reimport_check(
    step_path: str | Path,
    expected: Any,
    tolerances: Optional[dict[str, float]] = None,
    timeout_s: float = WORKER_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """Return a list of `RoundTripCheck`-shaped dicts. Never raises for a bad STEP.

    `expected` is a part_map: a `CadModel`, a part_map dict, or a path to `part_map.json`.
    """
    # The worker runs with its own cwd, so a path relative to *our* cwd would not resolve
    # there. Resolve before handing anything over.
    step_path = Path(step_path).resolve()
    part_map = _as_part_map(expected)

    if not step_path.exists():
        return _failed("step_readable", f"no such file: {step_path}")

    request = json.dumps(
        {
            "step_path": str(step_path),
            "part_map": part_map,
            "tolerances": {**DEFAULT_TOLERANCES, **(tolerances or {})},
        }
    )

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "dronebench_cad._reimport_worker"],
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(Path(__file__).resolve().parents[1]),
        )
    except subprocess.TimeoutExpired:
        return _failed(
            "reimport_worker",
            f"reimport worker exceeded {timeout_s:.0f} s and was killed; STEP not accepted",
        )

    if not proc.stdout.strip():
        return _failed(
            "reimport_worker",
            f"worker produced no result (exit {proc.returncode}): "
            f"{(proc.stderr or '').strip()[-400:]}",
        )

    try:
        resp = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _failed("reimport_worker", f"unparseable worker output: {proc.stdout[:400]}")

    checks = resp.get("checks") or _failed("reimport_worker", "worker returned no checks")
    if proc.returncode != 0:
        checks = list(checks) + _failed(
            "reimport_worker_exit", f"worker exited {proc.returncode}"
        )
    return checks


def _as_part_map(expected: Any) -> dict[str, Any]:
    if hasattr(expected, "part_map"):
        return expected.part_map()
    if isinstance(expected, (str, Path)):
        return json.loads(Path(expected).resolve().read_text(encoding="utf-8"))
    if isinstance(expected, dict) and "parts" in expected:
        return expected
    raise TypeError(
        "expected must be a CadModel, a part_map dict, or a path to part_map.json"
    )
