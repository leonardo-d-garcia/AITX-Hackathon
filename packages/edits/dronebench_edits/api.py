"""Frozen interface between the three A3 modules. Do not change without telling the lead.

store.py   (A3a) owns revisions, the active pointer, idempotency, and the CLI.
operations.py / policy.py (A3b) own the typed edits, their bounds and regeneration.
collide.py (A3c) owns interference + propeller clearance checks.

Flow of one edit:
    apply_edit(design_dir, request)                      # A3b entry point
      -> policy.check_bounds(request, manifest, params)  # A3b, raises EditBlocked
      -> store.create_preview(design_dir, parent, cause, build)   # A3a
             build(workdir) -> BuildResult               # A3b regenerates + exports
      -> collide.check(model, manifest, policy, params)  # A3c, list[RoundTripCheck]
      -> CadEditResult                                   # A3b assembles
Any failure leaves no revision directory and no change to the active pointer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from dronebench_contracts.models import (Artifact, CadEditRequest, CadEditResult, ErrorCode,
                                         ErrorEnvelope, RevisionManifest, RoundTripCheck)


class EditBlocked(Exception):
    """A bound, capability or check refused the edit. Carries a typed envelope."""

    def __init__(self, envelope: ErrorEnvelope):
        super().__init__(envelope.message)
        self.envelope = envelope

    @classmethod
    def of(cls, code: ErrorCode, message: str, **details: Any) -> "EditBlocked":
        return cls(ErrorEnvelope(code=code, message=message, details=details))


@dataclass
class BuildResult:
    """What A3b's build callback returns to A3a's store."""
    artifacts: list[Artifact]
    changes: list[dict[str, Any]]            # {part_id, field, before, after, unit}
    checks: list[RoundTripCheck]
    affected_part_ids: list[str] = field(default_factory=list)
    content: dict[str, Any] = field(default_factory=dict)   # canonical inputs for the content hash
    model: Any = None                                        # CadModel, for A3c; not serialised


class Store(Protocol):
    """A3a. All paths are absolute; design_dir is the ingest design folder."""

    def create_preview(self, design_dir: Path, parent_revision_id: str, cause: str,
                       build: Callable[[Path], BuildResult],
                       idempotency_key: Optional[str] = None) -> RevisionManifest: ...

    def commit(self, design_dir: Path, preview_revision_id: str,
               expected_active: Optional[str]) -> RevisionManifest: ...

    def decline(self, design_dir: Path, preview_revision_id: str, reason: str) -> RevisionManifest: ...

    def active_revision(self, design_dir: Path) -> str: ...

    def history(self, design_dir: Path) -> list[RevisionManifest]: ...


class Collider(Protocol):
    """A3c. Returns one RoundTripCheck per rule; `passed=False` blocks the edit."""

    def check(self, model: Any, manifest: Any, params: Any, policy: dict[str, Any],
              changed_part_ids: Optional[list[str]] = None) -> list[RoundTripCheck]: ...


def apply_edit(design_dir: Path, request: CadEditRequest) -> CadEditResult:  # A3b
    raise NotImplementedError
