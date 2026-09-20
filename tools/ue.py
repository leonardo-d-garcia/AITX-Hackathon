"""Unreal Engine 5.8 Remote Control client. PUT Python to 127.0.0.1:30010."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:30010/remote/object/call"

_HTTP_403 = (
    "HTTP 403: enable bEnableRemotePythonExecution AND "
    "CustomAllowedRemoteFunctionCalls in Config/DefaultRemoteControl.ini "
    "(NOT DefaultEngine.ini)"
)


def run(code: str, timeout: int = 180, execution_mode: str = "ExecuteStatement") -> dict:
    payload = {
        "objectPath": "/Script/PythonScriptPlugin.Default__PythonScriptLibrary",
        "functionName": "ExecutePythonCommandEx",
        "parameters": {
            "PythonCommand": code,
            "ExecutionMode": execution_mode,
            "FileExecutionScope": "Public",
        },
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except TimeoutError as exc:
        raise SystemExit(
            f"timed out after {timeout}s waiting for Unreal Remote Control on 30010"
        ) from exc
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SystemExit(_HTTP_403) from exc
        raise
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            raise SystemExit(
                f"timed out after {timeout}s waiting for Unreal Remote Control on 30010"
            ) from exc
        raise SystemExit("is the editor running on 30010?") from exc


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Execute Python in Unreal Editor via Remote Control HTTP."
    )
    parser.add_argument(
        "--file",
        metavar="PATH",
        help="script on disk; default is to read Python from stdin",
    )
    args = parser.parse_args()
    if args.file:
        path = str(Path(args.file).resolve())
        print(json.dumps(run(path, execution_mode="ExecuteFile"), indent=2))
    else:
        print(json.dumps(run(sys.stdin.read(), execution_mode="ExecuteStatement"), indent=2))
