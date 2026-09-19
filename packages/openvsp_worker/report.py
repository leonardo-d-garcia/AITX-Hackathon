"""C4 validation markdown. Numbers only; no 'looks reasonable'."""

from __future__ import annotations

from typing import Any


def format_validation_markdown(result: dict[str, Any]) -> str:
    checks = list(result.get("validation", {}).get("checks") or [])
    versions = result.get("versions") or result.get("solver_versions") or {}
    error = result.get("error")
    lines = [
        "# C4 OpenVSP generate / alpha sweep / validate",
        "",
        "Aircraft generated from `fixtures/c/synthetic_vtail_demo/geometry_features.json`.",
        "OpenVSP parameterized wing + V-tail; triangle meshes were not imported.",
        "",
        "## Environment",
        "",
        f"- OpenVSP: `{versions.get('openvsp')}`",
        f"- VSPAERO: `{versions.get('vspaero')}`",
        f"- interpreter: `{versions.get('interpreter')}`",
        f"- python: `{versions.get('python_version')}`",
        f"- geometry_hash: `{result.get('geometry_hash')}`",
        "",
        "## Model choices (not invented aero numbers)",
        "",
    ]
    for note in result.get("notes") or []:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## Sweep",
            "",
            f"- alphas_deg: `{result.get('alphas_deg')}`",
            f"- Vinf_mps: `{result.get('Vinf')}`",
            f"- altitude_m: `{result.get('altitude_m')}`",
            f"- Rho: `{result.get('Rho')}`",
            f"- Alpha unit: `{result.get('alpha_unit')}` — {result.get('alpha_unit_evidence')}",
            "",
            "## Validation",
            "",
            "| check | result | numbers |",
            "|---|---|---|",
        ]
    )
    if not checks:
        status = "FAIL"
        detail = error or "no checks recorded"
        lines.append(f"| generate | {status} | { _cell(detail) } |")
    for check in checks:
        name = check.get("name", "")
        status = "PASS" if check.get("pass") else "FAIL"
        numbers = check.get("numbers", "")
        if isinstance(numbers, dict):
            numbers = ", ".join(f"{k}={_fmt(v)}" for k, v in numbers.items())
        lines.append(f"| {name} | {status} | { _cell(str(numbers)) } |")
    if error:
        lines.extend(["", f"Error: `{_cell(error)}`", ""])
    polar = result.get("polar") or []
    if polar:
        lines.extend(
            [
                "",
                "## Polar (VSPAERO, last wake iteration)",
                "",
                "| alpha_deg | CL | CDi | CStot | CMxtot |",
                "|---|---|---|---|---|",
            ]
        )
        for row in polar:
            lines.append(
                "| {alpha} | {cl} | {cdi} | {cy} | {cll} |".format(
                    alpha=_fmt(row.get("alpha_deg")),
                    cl=_fmt(row.get("CL")),
                    cdi=_fmt(row.get("CDi")),
                    cy=_fmt(row.get("CY")),
                    cll=_fmt(row.get("Cl_rolling")),
                )
            )
    mesh = result.get("mesh_delta") or {}
    if mesh:
        lines.extend(
            [
                "",
                "## Refined-mesh point",
                "",
                "Single point. **Not a convergence study.**",
                "",
                f"- alpha_deg: `{_fmt(mesh.get('alpha_deg'))}`",
                f"- tess_u baseline/refined: `{mesh.get('tess_u_baseline')}` / `{mesh.get('tess_u_refined')}`",
                f"- tess_w baseline/refined: `{mesh.get('tess_w_baseline')}` / `{mesh.get('tess_w_refined')}`",
                f"- CL baseline/refined/delta: `{_fmt(mesh.get('CL_baseline'))}` / `{_fmt(mesh.get('CL_refined'))}` / `{_fmt(mesh.get('dCL'))}`",
                f"- CDi baseline/refined/delta: `{_fmt(mesh.get('CDi_baseline'))}` / `{_fmt(mesh.get('CDi_refined'))}` / `{_fmt(mesh.get('dCDi'))}`",
            ]
        )
    paths = result.get("raw") or result.get("paths") or {}
    if paths:
        lines.extend(["", "## Artifact paths", ""])
        for key, path in paths.items():
            lines.append(f"- {key}: `{path}`")
    lines.append("")
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")
