"""The optional language-model adapter (architecture section 4).

One provider interface, one function: ``propose(context, allowed_operations) -> Recommendation[]``.

What this module is careful about:

* **The deterministic generator is the real path.** :class:`NullProvider` is the default and returns
  nothing. An installation with no API key loses explanatory polish, not functionality.
* **A provider proposes inside the same schema.** It cannot invent an operation, and its output
  goes through :mod:`dronebench_recommend.validate` exactly like a deterministic candidate.
* **A predicted gain is never a result.** ``expected_gain_note`` is kept as text and is never ranked
  on. Section 7 step 5: never substitute an LLM's predicted gain for computed results.
* **The model does not see the graph.** It sees a :class:`ProposalContext` of compact descriptors.
  Section 4 also warns that filenames and supplier descriptions are evidence data, not agent
  instructions, so context text is passed as data and the adapter asks for structured output only.

Deliberately not implemented: shelling out to a developer's interactive Claude session. Section 4
forbids it. A real provider is configured through its own environment variables and called over its
own SDK inside :meth:`propose`.
"""

from __future__ import annotations

import os
from typing import Protocol

from dronebench_contracts import (
    MAX_PROVIDER_CALLS,
    ProposalContext,
    Recommendation,
)

#: The operation names a provider is permitted to emit. Anything else fails validation.
ALLOWED_OPERATIONS: tuple[str, ...] = (
    "translate_component",
    "resize_spar",
    "set_wing_tip_extension",
    "replace_catalog_component",
)


class Provider(Protocol):
    name: str

    def propose(
        self, context: ProposalContext, allowed_operations: list[str]
    ) -> list[Recommendation]:
        ...


class NullProvider:
    """The default. Produces no candidates, so the deterministic path stands alone."""

    name = "none"

    def propose(
        self, context: ProposalContext, allowed_operations: list[str]
    ) -> list[Recommendation]:
        return []


class ExplanationOnlyProvider:
    """A provider that may rewrite rationale text but may not author operations.

    A useful middle setting: the explanations get better without the model gaining any ability to
    move geometry. ``propose`` returns nothing; :meth:`explain` is called separately on candidates
    that have already been validated and previewed.
    """

    name = "explanation-only"

    def __init__(self, delegate: Provider | None = None) -> None:
        self._delegate = delegate

    def propose(
        self, context: ProposalContext, allowed_operations: list[str]
    ) -> list[Recommendation]:
        return []

    def explain(self, recommendation: Recommendation) -> str:
        """Return a plain-language restatement of an already-computed proposal.

        The default implementation is deterministic: it is a summary of computed numbers, not a
        generated narrative, so the product reads the same with or without a model configured.
        """
        preview = recommendation.preview
        if preview is None or preview.evaluation is None:
            return (
                f"{recommendation.title}. This candidate has not been evaluated, so no result is "
                "claimed for it."
            )
        worsening = [t for t in recommendation.tradeoffs if t.direction == "worsens"]
        improving = [t for t in recommendation.tradeoffs if t.direction == "improves"]
        parts = [recommendation.title + "."]
        if improving:
            parts.append(
                "Improves: " + ", ".join(f"{t.metric} ({t.unit})" for t in improving) + "."
            )
        if worsening:
            parts.append(
                "Costs: " + ", ".join(f"{t.metric} ({t.unit})" for t in worsening) + "."
            )
        parts.append(
            "Feasible within the implemented model."
            if preview.evaluation.verified_feasible
            else "Does not reach a verified-feasible result."
        )
        return " ".join(parts)


class ProviderBudget:
    """Enforces the section 7 limit of at most two provider calls per proposal refresh."""

    def __init__(self, limit: int = MAX_PROVIDER_CALLS) -> None:
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


def default_provider() -> Provider:
    """Resolve the configured provider.

    ``DRONEBENCH_PROVIDER`` selects it; anything unrecognised falls back to the null provider
    rather than failing, because no installation should be unable to generate proposals just
    because a model is unavailable.
    """
    configured = os.environ.get("DRONEBENCH_PROVIDER", "none").strip().lower()
    if configured in ("", "none", "off", "false"):
        return NullProvider()
    if configured in ("explanation", "explanation-only"):
        return ExplanationOnlyProvider()
    return NullProvider()


def build_context(
    *,
    design_id: str,
    revision_id: str,
    mission_hash: str,
    objective: str,
    parts,
    evaluation,
    catalog,
    evidence_notes: list[str],
) -> ProposalContext:
    """Assemble the only input surface a provider gets.

    Compact descriptors, not geometry. A part contributes one line; a mesh contributes nothing.
    """
    editable: dict[str, list[str]] = {}
    summaries: list[str] = []
    for occurrence in parts.occurrences:
        if occurrence.edit_capabilities and not occurrence.locked:
            editable[occurrence.part_id] = list(occurrence.edit_capabilities)
        mass = occurrence.mass_kg.number()
        summaries.append(
            f"{occurrence.part_id} ({occurrence.role}): "
            + (f"{mass:.3f} kg" if mass is not None else "mass unknown")
            + f", at x={occurrence.transform.translation[0]:+.3f} m"
            + (" [locked]" if occurrence.locked else "")
        )

    return ProposalContext(
        design_id=design_id,
        revision_id=revision_id,
        mission_hash=mission_hash,
        objective=objective,
        failing_checks=[c.check_id for c in evaluation.failing()],
        unknown_checks=[c.check_id for c in evaluation.checks if c.status == "unknown"],
        editable_parts=editable,
        part_summaries=summaries,
        metrics=dict(evaluation.metrics),
        catalog_item_ids=[item.catalog_item_id for item in catalog.items],
        evidence_notes=evidence_notes[:20],
    )
