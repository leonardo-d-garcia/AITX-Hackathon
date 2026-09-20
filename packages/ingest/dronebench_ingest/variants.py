"""Variant detection from filename stems. Nothing is ever selected automatically.

A group is a set of source files whose stems share the same ``<word><digits>`` head and differ only
in a trailing ``_suffix`` — ``wing3_12mm_hole`` / ``wing3_16mm_hole`` / ``wing3_no_hole``, or
``fuse3`` / ``fuse3_belly_cam`` / ``fuse3_clean``. Loading two options of one group would double
count mass and area, so ``selected`` stays ``None`` until a human confirms a choice.
"""
from __future__ import annotations

import re
from collections import defaultdict

from dronebench_contracts.models import SourceFile, VariantGroup

_HEAD = re.compile(r"^([A-Za-z]+\d*)(?:[_\-].*)?$")


def group_key(source_path: str) -> str:
    stem = re.split(r"[/\\]", source_path)[-1].rsplit(".", 1)[0]
    m = _HEAD.match(stem)
    return m.group(1).lower() if m else stem.lower()


def detect_variants(sources: list[SourceFile]) -> list[VariantGroup]:
    """Mutually exclusive alternatives among the staged meshes, in group order, none selected."""
    groups: dict[str, list[str]] = defaultdict(list)
    for s in sources:
        groups[group_key(s.source_path)].append(s.source_path)
    out = []
    for key in sorted(groups):
        options = sorted(groups[key])
        if len(options) < 2:
            continue
        out.append(VariantGroup(
            group_id=key,
            options=options,
            selected=None,
            reason=f"{len(options)} files share the stem head {key!r} and differ only by suffix; "
                   "exactly one is installed — nothing is selected until confirmed",
        ))
    return out


def selection_errors(variants: list[VariantGroup]) -> list[str]:
    """Group ids with no choice made."""
    return [v.group_id for v in variants if v.selected is None]


def excluded_sources(variants: list[VariantGroup]) -> list[str]:
    out: list[str] = []
    for v in variants:
        out += [o for o in v.options if o != v.selected]
    return sorted(out)
