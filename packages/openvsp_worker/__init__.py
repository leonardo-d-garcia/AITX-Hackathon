"""OpenVSP/VSPAERO worker. JSON in, artifacts out. Isolated native ABI.

C3 gate: bindings live in WSL Ubuntu 26.04 Python 3.14 (cp314), not Windows 3.11.
This adapter records install state and enumerates analysis inputs at runtime.
It does not generate aircraft geometry (C4).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# Official 3.51.3 Ubuntu 26.04 build, ABI-matched to WSL python3.14.
WSL_DISTRO = "Ubuntu"
WSL_PYTHON = "/root/openvsp-c3/venv/bin/python"
WSL_SHIPPED_EXAMPLE = "/opt/OpenVSP/python/openvsp/openvsp/tests/test.py"
WSL_SHIPPED_EXAMPLE_SITE = (
    "/root/openvsp-c3/venv/lib/python3.14/site-packages/openvsp/tests/test.py"
)
BUILD_PYTHON_ABI = "cp314"
BUILD_PACKAGE = "OpenVSP-3.51.3-Ubuntu-26.04_amd64.deb"

_PROBE_CACHE: dict[str, Any] | None = None
_LAST_ERROR: str | None = None


def _probe_script() -> Path:
    return Path(__file__).resolve().parent / "_runtime_probe.py"


def _to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    text = str(resolved)
    if len(text) >= 2 and text[1] == ":":
        drive = text[0].lower()
        rest = text[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return text.replace("\\", "/")


def _candidate_commands(*, run_example: bool) -> list[list[str]]:
    script = _probe_script()
    extra = ["--run-example"] if run_example else []
    cmds: list[list[str]] = []
    cmds.append([sys.executable, str(script), *extra])
    if Path(WSL_PYTHON).exists():
        cmds.append([WSL_PYTHON, str(script), *extra])
    wsl = shutil.which("wsl")
    if wsl:
        cmds.append(
            [wsl, "-d", WSL_DISTRO, "--", WSL_PYTHON, _to_wsl_path(script), *extra]
        )
    return cmds


def _run_probe(*, run_example: bool = False, refresh: bool = False) -> dict[str, Any]:
    global _PROBE_CACHE, _LAST_ERROR
    if _PROBE_CACHE is not None and not run_example and not refresh:
        return _PROBE_CACHE

    errors: list[str] = []
    for cmd in _candidate_commands(run_example=run_example):
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{cmd!r}: {exc!r}")
            continue
        stdout = (proc.stdout or "").strip()
        if not stdout:
            errors.append(
                f"{cmd!r} exit {proc.returncode} stderr={proc.stderr[-2000:]!r}"
            )
            continue
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            errors.append(
                f"{cmd!r} non-json stdout={stdout[-500]!r} stderr={proc.stderr[-500:]!r}"
            )
            continue
        if payload.get("available"):
            _LAST_ERROR = payload.get("error")
            if not run_example:
                _PROBE_CACHE = payload
            return payload
        errors.append(payload.get("error") or f"{cmd!r} available=false")

    _LAST_ERROR = " | ".join(errors) if errors else "openvsp probe produced no result"
    payload = {
        "available": False,
        "interpreter": sys.executable,
        "python_version": sys.version,
        "openvsp_module": None,
        "openvsp_version": None,
        "vspaero_version": None,
        "vspaero_path": None,
        "vspaero_bin": None,
        "shipped_example": None,
        "shipped_example_ran": False,
        "analyses": [],
        "analysis_inputs": {},
        "error": _LAST_ERROR,
        "build_python_abi": BUILD_PYTHON_ABI,
        "host": "none",
    }
    if not run_example:
        _PROBE_CACHE = payload
    return payload


def available() -> bool:
    return bool(_run_probe().get("available"))


def versions() -> dict[str, str | None]:
    payload = _run_probe()
    return {
        "openvsp": payload.get("openvsp_version"),
        "vspaero": payload.get("vspaero_version"),
        "interpreter": payload.get("interpreter"),
        "python_version": payload.get("python_version"),
        "abi": BUILD_PYTHON_ABI,
    }


def analysis_inputs() -> dict[str, list[str]]:
    """Analysis name -> input names, discovered via ListAnalysis/GetAnalysisInputNames."""
    payload = _run_probe()
    raw = payload.get("analysis_inputs") or {}
    return {str(k): [str(x) for x in v] for k, v in raw.items()}


def run_shipped_example() -> dict[str, Any]:
    """Run tests/test.py shipped with this OpenVSP 3.51.3 build."""
    return _run_probe(run_example=True, refresh=True)


def status_dict() -> dict[str, Any]:
    payload = _run_probe()
    ok = bool(payload.get("available"))
    return {
        "installed": ok,
        "available": ok,
        "host": "wsl-ubuntu" if ok else "none",
        "interpreter": payload.get("interpreter"),
        "python_version": payload.get("python_version"),
        "wheel_build_python_abi": BUILD_PYTHON_ABI,
        "build_package": BUILD_PACKAGE,
        "openvsp_version": payload.get("openvsp_version"),
        "vspaero_version": payload.get("vspaero_version"),
        "vspaero_bin": payload.get("vspaero_bin"),
        "shipped_example": payload.get("shipped_example") or WSL_SHIPPED_EXAMPLE,
        "shipped_example_site": WSL_SHIPPED_EXAMPLE_SITE,
        "shipped_example_ran": payload.get("shipped_example_ran"),
        "analyses": payload.get("analyses") or [],
        "analysis_inputs": payload.get("analysis_inputs") or {},
        "error": payload.get("error") or _LAST_ERROR,
        "openvsp_module": payload.get("openvsp_module"),
    }
