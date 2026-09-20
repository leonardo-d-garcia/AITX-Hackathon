"""Standalone static CAD inspector for DroneBench Studio (Team A, deliverable A4).

`render_inspector` turns a DesignManifest plus one or two GLB artifacts into a single
self-contained HTML file that runs from `file://` with no server: geometry and JSON are
embedded, only the three.js ES modules come from a CDN via an importmap.

The inspector never confuses the two geometry representations (architecture §2): the mode
label, the toggle and the overlay always say which one you are looking at.
"""
from __future__ import annotations

from .inspector import FRD_TO_GLTF, render_inspector

__all__ = ["render_inspector", "FRD_TO_GLTF"]
