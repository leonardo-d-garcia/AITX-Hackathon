"""The interfaces B calls into Team A and Team C through (architecture sections 6, 7, 8).

Section 6: "B owns the recommendation/approval workflow but **calls A's CAD tools**." Section 8
gives C the evaluator. B therefore depends on these two Protocols and nothing else about their
implementations. A reference implementation of each lives in ``dronebench_api.stubs`` and labels
its output ``B-stub`` so a stub result can never be mistaken for a real one.

A port raises :class:`~dronebench_contracts.errors.DroneBenchError` for conditions the caller must
handle (``SOLVER_UNAVAILABLE``, ``GEOMETRY_INVALID``, ``UNSUPPORTED_EDIT``). It returns a result
object for outcomes that are merely negative, such as a valid edit that produces an infeasible
design.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .edits import CadEditResult, EditOperation
from .evaluate import Evaluation, FidelityTier
from .events import SimulationRun
from .mission import Mission
from .parts import GeometryFeatures, PartsDocument


@runtime_checkable
class CadPort(Protocol):
    """Team A's CAD execution surface."""

    #: Which team actually implements this instance. Stubs report "B-stub".
    owner: str

    def apply_edit(
        self,
        *,
        base_revision_id: str,
        parts: PartsDocument,
        features: GeometryFeatures,
        operation: EditOperation,
        work_dir: str,
    ) -> CadEditResult:
        """Apply one typed operation in an isolated working directory.

        Must not mutate ``parts`` or ``features``, and must not write outside ``work_dir``.
        """
        ...

    def edited_parts(
        self,
        *,
        parts: PartsDocument,
        features: GeometryFeatures,
        operation: EditOperation,
    ) -> tuple[PartsDocument, GeometryFeatures]:
        """Return the post-edit parts and features. Pure; no filesystem effects."""
        ...

    def export_step(
        self,
        *,
        revision_id: str,
        parts: PartsDocument,
        work_dir: str,
    ) -> CadEditResult:
        """Export the full editable assembly and verify the round trip before allowing download."""
        ...


@runtime_checkable
class EvaluatePort(Protocol):
    """Team C's evaluator."""

    owner: str

    def evaluate(
        self,
        *,
        revision_id: str,
        parts: PartsDocument,
        features: GeometryFeatures,
        mission: Mission,
        fidelity: FidelityTier,
    ) -> Evaluation:
        """Return a complete evaluation covering every check id in the mission registry.

        Requesting a tier the installed tooling cannot deliver must downgrade explicitly in the
        returned ``fidelity`` field rather than mislabel the result.
        """
        ...

    def available_tiers(self) -> list[FidelityTier]:
        """Which tiers this installation can actually produce, discovered rather than assumed."""
        ...


@runtime_checkable
class SimulatePort(Protocol):
    """Team C's reduced-order mission model and replay."""

    owner: str

    def simulate(
        self,
        *,
        revision_id: str,
        evaluation: Evaluation,
        mission: Mission,
        run_id: str,
    ) -> SimulationRun:
        """Integrate distance and energy along the declared route. Never mutates the design."""
        ...


@runtime_checkable
class ProviderPort(Protocol):
    """The optional language-model adapter (architecture section 4).

    One function, one schema: ``propose(context, allowed_operations) -> Recommendation[]``. The
    deterministic candidate generator produces useful proposals without this, so every
    installation has a working path with no API access.
    """

    name: str

    def propose(self, context, allowed_operations: list[str]) -> list:  # noqa: ANN001
        """Return schema-valid recommendations. Output is validated exactly as strictly as
        deterministic candidates, and any predicted gain it states is kept as text only."""
        ...
