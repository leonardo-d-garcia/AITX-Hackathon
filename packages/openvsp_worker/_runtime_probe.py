"""Live OpenVSP probe. Enumerates analysis inputs at runtime; no hardcoded names."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback

VSPAERO_BIN_CANDIDATES = (
    "/opt/OpenVSP/vspaero",
)


def _vspaero_banner(bin_path: str) -> tuple[str | None, str | None]:
    try:
        proc = subprocess.run(
            [bin_path],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        return None, repr(exc)
    text = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    first = text.splitlines()[0].strip() if text else None
    return first or None, text or None


def probe(*, run_example: bool = False) -> dict:
    result: dict = {
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
        "error": None,
    }
    try:
        import openvsp as vsp  # type: ignore
    except Exception:
        result["error"] = traceback.format_exc()
        return result

    result["available"] = True
    result["openvsp_module"] = getattr(vsp, "__file__", None)
    try:
        result["openvsp_version"] = vsp.GetVSPVersion()
    except Exception as exc:  # noqa: BLE001
        result["openvsp_version"] = None
        result["error"] = "GetVSPVersion: " + repr(exc)

    try:
        result["vspaero_path"] = vsp.GetVSPAEROPath()
    except Exception as exc:  # noqa: BLE001
        result["vspaero_path"] = None
        result.setdefault("warnings", []).append("GetVSPAEROPath: " + repr(exc))

    vspaero_bin = None
    candidates = list(VSPAERO_BIN_CANDIDATES)
    packaged = os.path.join(os.path.dirname(vsp.__file__), "vspaero")
    candidates.append(packaged)
    stored = result.get("vspaero_path") or ""
    if stored:
        candidates.append(stored)
        candidates.append(os.path.join(stored, "vspaero"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            vspaero_bin = candidate
            break
    result["vspaero_bin"] = vspaero_bin
    if vspaero_bin:
        banner, raw = _vspaero_banner(vspaero_bin)
        result["vspaero_version"] = banner
        result["vspaero_version_raw"] = raw

    analyses = list(vsp.ListAnalysis())
    result["analyses"] = analyses
    inputs: dict[str, list[str]] = {}
    for name in analyses:
        try:
            inputs[name] = list(vsp.GetAnalysisInputNames(name))
        except Exception as exc:  # noqa: BLE001
            inputs[name] = []
            result.setdefault("warnings", []).append(
                f"GetAnalysisInputNames({name!r}): {exc!r}"
            )
    result["analysis_inputs"] = inputs

    example = None
    site_example = os.path.join(os.path.dirname(vsp.__file__), "tests", "test.py")
    for candidate in (
        "/opt/OpenVSP/python/openvsp/openvsp/tests/test.py",
        site_example,
    ):
        if os.path.isfile(candidate):
            example = candidate
            break
    result["shipped_example"] = example

    if run_example:
        if not example:
            result["error"] = "shipped example not found in this build"
            result["shipped_example_ran"] = False
        else:
            proc = subprocess.run(
                [sys.executable, example],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            result["shipped_example_returncode"] = proc.returncode
            result["shipped_example_stdout"] = (proc.stdout or "")[-4000:]
            result["shipped_example_stderr"] = (proc.stderr or "")[-4000:]
            result["shipped_example_ran"] = proc.returncode == 0
            if proc.returncode != 0:
                result["error"] = f"shipped example exit {proc.returncode}"
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    run_example = "--run-example" in args
    payload = probe(run_example=run_example)
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if not payload.get("available"):
        return 1
    if run_example and not payload.get("shipped_example_ran"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
