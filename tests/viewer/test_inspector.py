"""Tests for the standalone static inspector (deliverable A4).

The page is checked as a document: the payload must survive embedding, the geometry must decode
back to the same part ids, and nothing in the data may be able to terminate the script element.
"""
from __future__ import annotations

import base64
import copy
import io
import json
import re
from pathlib import Path

import pytest
import trimesh

from dronebench_viewer import render_inspector
from dronebench_viewer.mock import build_mock_artifacts

PAYLOAD_RE = re.compile(
    r'<script type="application/json" id="dronebench-payload">(.*?)</script>', re.DOTALL
)


@pytest.fixture(scope="module")
def mocks(tmp_path_factory) -> dict[str, Path]:
    return build_mock_artifacts(tmp_path_factory.mktemp("mock"))


@pytest.fixture(scope="module")
def page(mocks, tmp_path_factory) -> str:
    out = tmp_path_factory.mktemp("html") / "inspector.html"
    written = render_inspector(
        mocks["design_manifest"],
        {"reference": mocks["reference_glb"], "reconstruction": mocks["reconstruction_glb"]},
        out,
        features_json=mocks["geometry_features"],
        fit_report=mocks["fit_report"],
        edit_result=mocks["cad_edit_result"],
    )
    assert written == out and out.is_file()
    return out.read_text(encoding="utf-8")


def payload_of(html: str) -> dict:
    m = PAYLOAD_RE.search(html)
    assert m, "no embedded payload script found"
    return json.loads(m.group(1))


# ------------------------------------------------------------------ structure

def test_page_renders_and_is_self_contained(page):
    assert page.lstrip().startswith("<!doctype html>")
    assert "Original mesh reference" in page
    assert "Editable reconstruction" in page
    # no local file references: everything but the CDN modules is inline
    assert 'src="' not in page.replace('<script type="module">', "")
    assert "reference.glb" not in page


def test_importmap_pins_three_r160_modules(page):
    assert '<script type="importmap">' in page
    assert "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js" in page
    assert "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/" in page
    assert "three/addons/loaders/GLTFLoader.js" in page
    assert "three/addons/controls/OrbitControls.js" in page


def test_embedded_json_parses_and_carries_every_part(page, mocks):
    payload = payload_of(page)
    manifest = json.loads(mocks["design_manifest"].read_text())
    assert payload["manifest"] == manifest
    assert payload["features"]["surfaces"], "geometry features were dropped"
    assert payload["fit_report"]["per_part"]
    assert payload["edit_result"]["operation"] == "translate_component"


def test_embedded_glb_decodes_with_all_node_names(page, mocks):
    payload = payload_of(page)
    for key, artifact in (("reference", "reference_glb"), ("reconstruction", "reconstruction_glb")):
        raw = base64.b64decode(payload["glb"][key])
        assert raw == Path(mocks[artifact]).read_bytes(), f"{key} GLB was altered"
        scene = trimesh.load(io.BytesIO(raw), file_type="glb", force="scene")
        names = set(scene.geometry)
        assert names, f"{key} GLB decoded to nothing"
        source = trimesh.load(mocks[artifact], force="scene")
        assert names == set(source.geometry)

    manifest = json.loads(mocks["design_manifest"].read_text())
    part_ids = {p["part_id"] for p in manifest["parts"]}
    ref = trimesh.load(io.BytesIO(base64.b64decode(payload["glb"]["reference"])),
                       file_type="glb", force="scene")
    assert set(ref.geometry) == part_ids, "reference nodes and manifest part ids disagree"


# ------------------------------------------------------------------ unknown handling

def test_unknown_claims_are_shown_as_unknown_not_zero(page, mocks):
    payload = payload_of(page)
    unknown_parts = [
        p for p in payload["manifest"]["parts"] if p["mass_kg"]["status"] == "unknown"
    ]
    assert unknown_parts, "the mock should carry unknown masses"
    for p in unknown_parts:
        assert p["mass_kg"]["value"] is None, "an unknown claim must stay null, never 0"
    # the page renders the words rather than a number
    assert "unknown — needs evidence" in page
    assert "frame UNCONFIRMED" in page or "frame unconfirmed" in page


def test_status_legend_is_text_not_colour_only(page):
    for status in ("known", "estimated", "unknown", "conflicted"):
        assert f'chip ${{esc(status)}}' in page or status in page
    assert "Colour = claim status" in page
    assert "aria-pressed" in page and 'aria-label="Search parts"' in page


# ------------------------------------------------------------------ injection safety

def test_script_close_tag_in_data_cannot_break_the_page(mocks, tmp_path):
    manifest = json.loads(Path(mocks["design_manifest"]).read_text())
    hostile = "</script><script>window.__pwned=1</script><!--"
    manifest["parts"][0]["name"] = f"Nose {hostile}"
    manifest["title"] = f"Titan {hostile}"
    manifest["warnings"].append(hostile)
    manifest["evidence"][0]["note"] = hostile

    out = render_inspector(manifest, {"reference": mocks["reference_glb"]}, tmp_path / "hostile.html")
    html = out.read_text(encoding="utf-8")

    # the hostile text never appears as live markup, only escaped or \u-encoded
    assert "<script>window.__pwned" not in html
    assert "</script><script>" not in html
    assert html.count("<script") == 3      # importmap, payload, module — no injected fourth
    payload = payload_of(html)                      # the payload element still closes where we put it
    assert payload["manifest"]["parts"][0]["name"] == f"Nose {hostile}"
    assert payload["manifest"]["evidence"][0]["note"] == hostile
    # the <title> is escaped rather than embedded raw
    assert "&lt;/script&gt;" in html


def test_json_escape_covers_line_separators(mocks, tmp_path):
    manifest = json.loads(Path(mocks["design_manifest"]).read_text())
    manifest["parts"][0]["name"] = "Nose \u2028 line sep \u2029 para sep & <tag>"
    out = render_inspector(manifest, {"reference": mocks["reference_glb"]}, tmp_path / "sep.html")
    html = out.read_text(encoding="utf-8")
    payload = payload_of(html)
    assert payload["manifest"]["parts"][0]["name"] == manifest["parts"][0]["name"]
    assert "\u2028" not in PAYLOAD_RE.search(html).group(1)


# ------------------------------------------------------------------ API contract

def test_reconstruction_is_optional(mocks, tmp_path):
    out = render_inspector(mocks["design_manifest"], {"reference": mocks["reference_glb"]},
                           tmp_path / "ref_only.html")
    payload = payload_of(out.read_text(encoding="utf-8"))
    assert payload["glb"]["reconstruction"] is None
    assert payload["glb"]["reference"]


def test_reference_glb_is_required(mocks, tmp_path):
    with pytest.raises(ValueError, match="reference"):
        render_inspector(mocks["design_manifest"], {"reconstruction": mocks["reconstruction_glb"]},
                         tmp_path / "bad.html")


def test_manifest_accepts_pydantic_model(mocks, tmp_path):
    from dronebench_contracts.models import DesignManifest

    model = DesignManifest.model_validate_json(Path(mocks["design_manifest"]).read_text())
    out = render_inspector(model, {"reference": mocks["reference_glb"]}, tmp_path / "model.html")
    payload = payload_of(out.read_text(encoding="utf-8"))
    assert payload["manifest"]["design_id"] == model.design_id


def test_non_glb_artifact_is_rejected(mocks, tmp_path):
    fake = tmp_path / "not.glb"
    fake.write_bytes(b"solid ascii stl\n")
    with pytest.raises(ValueError, match="not a binary GLB"):
        render_inspector(mocks["design_manifest"], {"reference": fake}, tmp_path / "bad2.html")


def test_mock_manifest_validates_against_the_contract(mocks):
    from dronebench_contracts.models import CadEditResult, DesignManifest, GeometryFeatures

    DesignManifest.model_validate_json(Path(mocks["design_manifest"]).read_text())
    GeometryFeatures.model_validate_json(Path(mocks["geometry_features"]).read_text())
    CadEditResult.model_validate_json(Path(mocks["cad_edit_result"]).read_text())


def test_mock_claims_cover_every_status(mocks):
    manifest = json.loads(Path(mocks["design_manifest"]).read_text())
    seen = set()
    for p in manifest["parts"]:
        for field in ("mass_kg", "local_com_m", "material", "function"):
            seen.add(p[field]["status"])
    assert {"known", "estimated", "unknown", "conflicted"} <= seen


def test_render_does_not_mutate_the_caller_manifest(mocks, tmp_path):
    manifest = json.loads(Path(mocks["design_manifest"]).read_text())
    before = copy.deepcopy(manifest)
    render_inspector(manifest, {"reference": mocks["reference_glb"]}, tmp_path / "nomutate.html")
    assert manifest == before
