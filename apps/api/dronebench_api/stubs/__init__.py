"""Reference implementations of Team A's and Team C's ports, owned by Team B.

Architecture section 12 has B building the revision store, graph, and transaction machine in the
first four hours, against a synthetic fixture. That requires something on the other side of every
port, and A's kernel and C's evaluator do not exist yet.

Each stub is labelled ``B-stub`` in its output, reports only the fidelity tiers it can actually
deliver, and refuses rather than fakes where it cannot do the real thing - most visibly, the CAD
stub produces no STEP and leaves the export round trip unperformed, so nothing downloadable can be
presented as verified. Swapping in the real package is a one-line change in
``dronebench_api.service``.
"""

from .cad import ParametricCadPort
from .evaluate import AnalyticEvaluator
from .simulate import ReducedOrderSimulator

__all__ = ["ParametricCadPort", "AnalyticEvaluator", "ReducedOrderSimulator"]
