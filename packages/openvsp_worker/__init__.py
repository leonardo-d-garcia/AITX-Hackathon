"""OpenVSP/VSPAERO worker. JSON in, artifacts out. Isolated native ABI.

C3 gate: bindings live in WSL Ubuntu 26.04 Python 3.14 (cp314), not Windows 3.11.
C4: generate_and_sweep builds aircraft.vsp3 from geometry_features.json and runs
VSPAEROSweep in that same WSL interpreter.
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


def _run_script() -> Path:
    return Path(__file__).resolve().parent / "_vsp_run.py"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _geometry_hash(geometry: dict[str, Any]) -> str:
    from .geometry import geometry_hash as _hash

    return _hash(geometry)


def _candidate_run_commands(geometry_path: Path, out_dir: Path, geometry_hash: str) -> list[list[str]]:
    script = _run_script()
    cmds: list[list[str]] = []
    wsl = shutil.which("wsl")
    if wsl:
        cmds.append(
            [
                wsl,
                "-d",
                WSL_DISTRO,
                "--",
                WSL_PYTHON,
                _to_wsl_path(script),
                "--geometry",
                _to_wsl_path(geometry_path),
                "--out",
                _to_wsl_path(out_dir),
                "--hash",
                geometry_hash,
            ]
        )
    if Path(WSL_PYTHON).exists():
        cmds.append(
            [
                WSL_PYTHON,
                str(script),
                "--geometry",
                str(geometry_path),
                "--out",
                str(out_dir),
                "--hash",
                geometry_hash,
            ]
        )
    cmds.append(
        [
            sys.executable,
            str(script),
            "--geometry",
            str(geometry_path),
            "--out",
            str(out_dir),
            "--hash",
            geometry_hash,
        ]
    )
    return cmds


def _parse_c4_stdout(stdout: str) -> dict[str, Any] | None:
    text = stdout or ""
    start = text.find("C4_RESULT_BEGIN")
    end = text.find("C4_RESULT_END")
    if start >= 0 and end > start:
        blob = text[start + len("C4_RESULT_BEGIN") : end].strip()
        try:
            payload = json.loads(blob)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def _fail_result(*, geometry_hash: str | None, error: str) -> dict[str, Any]:
    return {
        "geometry_hash": geometry_hash,
        "alphas_deg": [],
        "CL": [],
        "CDi": [],
        "Sref": None,
        "bref": None,
        "cref": None,
        "mesh_delta": {},
        "raw": {},
        "versions": {},
        "error": error,
        "validation": {
            "all_passed": False,
            "checks": [{"name": "generate", "pass": False, "numbers": error.splitlines()[0]}],
        },
    }


def _write_docs(result: dict[str, Any]) -> None:
    from .report import format_validation_markdown

    docs = _repo_root() / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "openvsp-c4-validation.md").write_text(
        format_validation_markdown(result), encoding="utf-8"
    )
    summary = {
        "geometry_hash": result.get("geometry_hash"),
        "alphas_deg": result.get("alphas_deg"),
        "alphas_deg_result": result.get("alphas_deg_result"),
        "CL": result.get("CL"),
        "CDi": result.get("CDi"),
        "Sref": result.get("Sref"),
        "bref": result.get("bref"),
        "cref": result.get("cref"),
        "Vinf": result.get("Vinf"),
        "Rho": result.get("Rho"),
        "altitude_m": result.get("altitude_m"),
        "mesh_delta": {
            k: (result.get("mesh_delta") or {}).get(k)
            for k in (
                "alpha_deg",
                "tess_u_baseline",
                "tess_u_refined",
                "tess_w_baseline",
                "tess_w_refined",
                "CL_baseline",
                "CL_refined",
                "dCL",
                "CDi_baseline",
                "CDi_refined",
                "dCDi",
                "note",
                "error",
            )
        },
        "polar": [
            {k: v for k, v in row.items() if k != "result_id"}
            for row in (result.get("polar") or [])
            if isinstance(row, dict)
        ],
        "versions": result.get("versions") or result.get("solver_versions"),
        "alpha_unit": result.get("alpha_unit"),
        "validation": result.get("validation"),
        "error": result.get("error"),
        "raw": result.get("raw"),
        "notes": result.get("notes"),
    }
    text = json.dumps(summary, indent=2) + "\n"
    (docs / "openvsp-c4-sweep-summary.json").write_text(text, encoding="utf-8")
    (Path(__file__).resolve().parent / "c4_sweep_summary.json").write_text(text, encoding="utf-8")


def generate_and_sweep(
    geometry_path: str | Path, out_dir: str | Path, *, write_docs: bool = True
) -> dict[str, Any]:
    """Build aircraft.vsp3 from geometry_features.json and run the C4 alpha sweep.

    Returns a dict for evaluate_revision(solver_result=...): geometry_hash, alphas_deg,
    CL, CDi, Sref, bref, cref, mesh_delta, raw paths, versions.
    """
    geometry_path = Path(geometry_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        geometry = json.loads(geometry_path.read_text(encoding="utf-8"))
        if not isinstance(geometry, dict):
            raise TypeError(f"{geometry_path} is not a JSON object")
        ghash = _geometry_hash(geometry)
        from .geometry import load_spec

        load_spec(geometry)
    except Exception as exc:  # noqa: BLE001
        result = _fail_result(geometry_hash=None, error=f"{type(exc).__name__}: {exc}")
        if "ghash" in locals():
            result["geometry_hash"] = ghash
        if write_docs:
            _write_docs(result)
        return result

    errors: list[str] = []
    result_file = out_dir / "sweep_result.json"
    for cmd in _candidate_run_commands(geometry_path, out_dir, ghash):
        if result_file.is_file():
            result_file.unlink()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"{cmd!r}: {exc!r}")
            continue
        payload = None
        if result_file.is_file():
            try:
                loaded = json.loads(result_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError:
                payload = None
        if payload is None:
            payload = _parse_c4_stdout(proc.stdout or "")
        if payload is None:
            errors.append(
                f"{cmd!r} exit {proc.returncode} stdout={((proc.stdout or '')[-800:])!r} "
                f"stderr={((proc.stderr or '')[-800:])!r}"
            )
            continue
        err = str(payload.get("error") or "")
        import_miss = "No module named 'openvsp'" in err or "No module named openvsp" in err
        if import_miss and not payload.get("CL"):
            errors.append(err.splitlines()[0] if err else "openvsp import failed")
            continue
        payload.setdefault("geometry_hash", ghash)
        payload.setdefault("versions", payload.get("solver_versions") or {})
        if write_docs:
            _write_docs(payload)
        return payload

    result = _fail_result(
        geometry_hash=ghash,
        error=" | ".join(errors) if errors else "generate_and_sweep produced no result",
    )
    if write_docs:
        _write_docs(result)
    return result


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
