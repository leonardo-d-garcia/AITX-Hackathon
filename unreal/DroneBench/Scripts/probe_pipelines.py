"""Live 5.8 Interchange pipeline probe. No import."""

from __future__ import annotations

import json
import traceback

import unreal

out = {"errors": []}


def _err(where, exc):
    out["errors"].append({"where": where, "error": str(exc), "traceback": traceback.format_exc()})


try:
    a = unreal.InterchangeGenericAssetsPipeline()
    out["assets_path"] = a.get_path_name()
    out["assets_class"] = a.get_class().get_path_name()
except Exception as exc:
    _err("assets pipeline", exc)
    a = None

try:
    sp = unreal.SoftObjectPath(a.get_path_name()) if a else None
    out["soft"] = str(sp)
    p = unreal.ImportAssetParameters()
    p.override_pipelines.append(sp)
    out["append_soft_ok"] = True
    out["override_len"] = len(p.override_pipelines)
except Exception as exc:
    _err("append_soft", exc)

try:
    factory = unreal.InterchangePipelineBaseFactory()
    out["factory"] = factory.get_class().get_name()
    out["factory_dir"] = [n for n in dir(factory) if not n.startswith("_")][:40]
except Exception as exc:
    _err("factory", exc)
    factory = None

try:
    lib = unreal.EditorAssetLibrary
    paths = []
    for root in ("/Interchange", "/Engine/Interchange", "/Game"):
        try:
            found = lib.list_assets(root, True, False)
            hits = [x for x in found if "pipeline" in x.lower()]
            if hits:
                paths.extend(hits[:40])
        except Exception as exc:
            _err("list " + root, exc)
    out["pipeline_assets"] = paths
except Exception as exc:
    _err("list_assets", exc)

try:
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    out["asset_tools"] = True
    if factory is not None:
        created = tools.create_asset(
            "ProbeAssetsPipeline",
            "/Game/DroneBench/Pipelines",
            unreal.InterchangeGenericAssetsPipeline,
            factory,
        )
        out["created"] = None if created is None else created.get_path_name()
except Exception as exc:
    _err("create_asset", exc)

print(json.dumps(out, indent=2, default=str))
