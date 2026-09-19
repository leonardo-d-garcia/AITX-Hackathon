"""Read/write simulation_run.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Union

from .validate import validate_simulation_run

PathLike = Union[str, Path]


def write_simulation_run(path: PathLike, run: Mapping[str, Any]) -> None:
    validate_simulation_run(run)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(run, handle, allow_nan=False)
        handle.write("\n")
