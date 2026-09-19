"""Render a self-contained HTML inspector from Team A's artifacts.

Everything the page needs (geometry, manifest, features, fit report, edit result) is embedded
in one file. Only the three.js ES modules are fetched from a CDN through an importmap, so the
page also works from `file://` as long as the machine has network access.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Union

__all__ = ["render_inspector", "FRD_TO_GLTF", "TEMPLATE_PATH"]

TEMPLATE_PATH = Path(__file__).with_name("assets") / "inspector_template.html"

#: FRD (x forward, y right, z down) -> glTF (x right, y up, z back), metres in both.
FRD_TO_GLTF = (
    (0.0, 1.0, 0.0),
    (0.0, 0.0, -1.0),
    (-1.0, 0.0, 0.0),
)

JsonLike = Union[str, Path, Mapping[str, Any], Any]


def _as_jsonable(value: JsonLike, what: str) -> Any:
    """Accept a path, a JSON string, a pydantic model or a plain mapping."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):                     # pydantic v2 contract model
        return json.loads(value.model_dump_json())
    if isinstance(value, Path):
        return json.loads(value.read_text(encoding="utf-8"))
    if isinstance(value, str):
        stripped = value.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return json.loads(value)
        return json.loads(Path(value).read_text(encoding="utf-8"))
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{what}: expected a path, JSON text, mapping or pydantic model, got {type(value)!r}")


def _embed_json(payload: Any) -> str:
    """JSON that is safe to place inside a <script> element.

    Escaping `<`, `>` and `&` keeps a literal ``</script>`` in any string value from closing the
    element early, while leaving the text valid JSON for ``JSON.parse``.
    """
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


def _read_glb(path: Optional[Union[str, Path]], label: str) -> Optional[str]:
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"{label} GLB not found: {p}")
    data = p.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"{label} artifact is not a binary GLB (bad magic): {p}")
    return base64.b64encode(data).decode("ascii")


def render_inspector(
    manifest_json: JsonLike,
    glb_paths: Mapping[str, Optional[Union[str, Path]]],
    out_html: Union[str, Path],
    features_json: JsonLike = None,
    fit_report: JsonLike = None,
    edit_result: JsonLike = None,
) -> Path:
    """Write one self-contained inspector HTML file and return its path.

    Args:
        manifest_json: DesignManifest as a path, JSON text, mapping or pydantic model.
        glb_paths: ``{"reference": path, "reconstruction": path | None}``. The reference GLB is
            required; without a reconstruction the toggle and overlay are disabled in the page.
        out_html: destination file (parent directories are created).
        features_json: optional GeometryFeatures.
        fit_report: optional dict with ``rms_m``, ``max_m`` and ``per_part``
            (list of ``{part_id, rms_m, max_m}`` or a mapping keyed by part_id).
        edit_result: optional CadEditResult, rendered as a change ledger.
    """
    manifest = _as_jsonable(manifest_json, "manifest_json")
    if not isinstance(manifest, Mapping) or "parts" not in manifest:
        raise ValueError("manifest_json does not look like a DesignManifest (no 'parts')")

    reference = glb_paths.get("reference")
    if reference is None:
        raise ValueError("glb_paths['reference'] is required: the inspector always shows the reference mesh")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "manifest": manifest,
        "features": _as_jsonable(features_json, "features_json"),
        "fit_report": _as_jsonable(fit_report, "fit_report"),
        "edit_result": _as_jsonable(edit_result, "edit_result"),
        "glb": {
            "reference": _read_glb(reference, "reference"),
            "reconstruction": _read_glb(glb_paths.get("reconstruction"), "reconstruction"),
        },
        "frd_to_gltf": [list(r) for r in FRD_TO_GLTF],
    }

    title = str(manifest.get("title") or manifest.get("design_id") or "DroneBench inspector")
    html = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = html.replace("__TITLE__", _escape_html(title)).replace("__PAYLOAD__", _embed_json(payload))

    out = Path(out_html)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
