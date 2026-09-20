"""One-shot void + import + forward translation. Renderer only. No plant."""

from __future__ import annotations

import json
import os
import runpy
import traceback

SCRIPTS = os.path.dirname(os.path.abspath(__file__))


def _exec(name):
    # Child scripts self-run at import time (ExecuteFile). run_name="__main__"
    # so that path matches ExecuteFile; do not use a private run_name.
    path = os.path.join(SCRIPTS, name)
    return runpy.run_path(path, run_name="__main__")


def run():
    result = {"ok": False, "script": "demo_basic.py", "steps": [], "errors": []}
    try:
        _exec("demo_void.py")
        result["steps"].append("demo_void.py ran")
    except Exception as exc:
        result["errors"].append({"where": "demo_void", "error": str(exc), "traceback": traceback.format_exc()})
        print(json.dumps(result, indent=2, default=str))
        return result
    try:
        _exec("import_glb.py")
        result["steps"].append("import_glb.py ran")
    except Exception as exc:
        result["errors"].append({"where": "import_glb", "error": str(exc), "traceback": traceback.format_exc()})
        print(json.dumps(result, indent=2, default=str))
        return result
    try:
        _exec("demo_forward.py")
        result["steps"].append("demo_forward.py ran")
        result["ok"] = True
    except Exception as exc:
        result["errors"].append({"where": "demo_forward", "error": str(exc), "traceback": traceback.format_exc()})
    print(json.dumps(result, indent=2, default=str))
    return result


run()
