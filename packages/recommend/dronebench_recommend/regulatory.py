"""Regulatory applicability for one jurisdiction and operation profile (architecture section 7).

The section is unusually specific about what *not* to do, and each warning has a corresponding
guard here:

* "aircraft registration is not governed by a blanket 250 g exemption; that exemption belongs to
  qualifying recreational operation" - the 250 g threshold is consulted only on the recreational
  profile, never on Part 107.
* "Remote ID generally follows whether registration is required or the aircraft is registered, with
  operational exceptions such as FRIAs" - Remote ID is derived from the registration finding plus
  the FRIA fact, not from mass.
* "Do not infer compliance from a CAD box labeled 'Remote ID.' Check equipment declarations and
  operation facts." - nothing here reads a part name. A missing equipment declaration yields
  ``unknown``, not a pass.

These findings explain design and operation constraints and name missing evidence. They do not
certify the aircraft, and ``does_not_apply`` is never rendered as compliance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from dronebench_contracts import Mission, PartsDocument

Applicability = Literal["applies", "does_not_apply", "unknown"]

#: 49 U.S.C. 44809 recreational carve-out threshold, in kilograms (0.55 lb).
RECREATIONAL_MASS_THRESHOLD_KG = 0.25

REGISTRATION_EVIDENCE = "ev_faa-registration"
REMOTE_ID_EVIDENCE = "ev_faa-remote-id"


@dataclass(frozen=True)
class RegulatoryFinding:
    """One applicability determination, with what it rests on and what is missing."""

    rule_id: str
    title: str
    applicability: Applicability
    jurisdiction: str
    operation: str
    rationale: str
    evidence_ids: tuple[str, ...] = ()
    missing_context: tuple[str, ...] = ()
    affected_part_ids: tuple[str, ...] = ()
    disclaimer: str = (
        "Applicability only. This is not a compliance determination and does not certify the "
        "aircraft or the operation."
    )


@dataclass
class RegulatoryReport:
    findings: list[RegulatoryFinding] = field(default_factory=list)

    def by_id(self, rule_id: str) -> RegulatoryFinding | None:
        for finding in self.findings:
            if finding.rule_id == rule_id:
                return finding
        return None

    def unknown_findings(self) -> list[RegulatoryFinding]:
        return [f for f in self.findings if f.applicability == "unknown"]


def assess(
    *,
    mission: Mission,
    parts: PartsDocument,
    total_mass_kg: float | None,
    remote_id_equipment_declared: bool | None = None,
) -> RegulatoryReport:
    """Evaluate the profile's rules.

    ``total_mass_kg`` is ``None`` when any occurrence has unknown mass. On the recreational profile
    that makes the registration question unknown rather than defaulting either way.

    ``remote_id_equipment_declared`` is an explicit equipment fact supplied by the operator. It is
    deliberately *not* inferred from the parts document; a body named "Remote ID" proves nothing.
    """
    profile = mission.regulatory
    registration = _registration(mission, total_mass_kg)
    findings = [registration, _remote_id(mission, registration, remote_id_equipment_declared)]

    avionics = tuple(
        o.part_id for o in parts.occurrences if o.role in ("flight_controller", "receiver", "gps")
    )
    findings = [
        f if f.rule_id != "remote_id" else _with_parts(f, avionics) for f in findings
    ]
    return RegulatoryReport(findings=findings)


def _with_parts(finding: RegulatoryFinding, part_ids: tuple[str, ...]) -> RegulatoryFinding:
    return RegulatoryFinding(
        rule_id=finding.rule_id,
        title=finding.title,
        applicability=finding.applicability,
        jurisdiction=finding.jurisdiction,
        operation=finding.operation,
        rationale=finding.rationale,
        evidence_ids=finding.evidence_ids,
        missing_context=finding.missing_context,
        affected_part_ids=part_ids,
    )


def _registration(mission: Mission, total_mass_kg: float | None) -> RegulatoryFinding:
    profile = mission.regulatory
    common = {
        "rule_id": "registration",
        "title": "Aircraft registration",
        "jurisdiction": profile.jurisdiction,
        "operation": profile.operation,
        "evidence_ids": (REGISTRATION_EVIDENCE,),
    }

    if profile.operation == "part_107_commercial":
        # The 250 g figure is not consulted here on purpose: it belongs to the recreational
        # carve-out, and reading it on a Part 107 operation is exactly the error section 7 names.
        return RegulatoryFinding(
            **common,
            applicability="applies",
            rationale=(
                "Registration applies to aircraft operated under Part 107 regardless of mass. The "
                "250 g figure is the recreational carve-out threshold and does not apply to this "
                "operation profile."
            ),
        )

    # Recreational operation under 49 U.S.C. 44809.
    if total_mass_kg is None:
        return RegulatoryFinding(
            **common,
            applicability="unknown",
            rationale=(
                "Under the recreational exception the registration question turns on take-off "
                "mass, and the aircraft mass is not established because at least one component "
                "has no mass evidence."
            ),
            missing_context=("total take-off mass (one or more component masses are unknown)",),
        )

    if total_mass_kg > RECREATIONAL_MASS_THRESHOLD_KG:
        return RegulatoryFinding(
            **common,
            applicability="applies",
            rationale=(
                f"Take-off mass {total_mass_kg:.3f} kg exceeds the "
                f"{RECREATIONAL_MASS_THRESHOLD_KG} kg recreational threshold, so registration "
                "applies even for qualifying recreational operation."
            ),
        )

    return RegulatoryFinding(
        **common,
        applicability="does_not_apply",
        rationale=(
            f"Take-off mass {total_mass_kg:.3f} kg is at or below the "
            f"{RECREATIONAL_MASS_THRESHOLD_KG} kg threshold and the declared operation is "
            "recreational, so the carve-out is available. Whether the operation actually qualifies "
            "as recreational is an operational fact, not a design property."
        ),
        missing_context=("confirmation that the flight qualifies as recreational operation",),
    )


def _remote_id(
    mission: Mission,
    registration: RegulatoryFinding,
    equipment_declared: bool | None,
) -> RegulatoryFinding:
    profile = mission.regulatory
    common = {
        "rule_id": "remote_id",
        "title": "Remote identification",
        "jurisdiction": profile.jurisdiction,
        "operation": profile.operation,
        "evidence_ids": (REMOTE_ID_EVIDENCE, REGISTRATION_EVIDENCE),
    }

    if profile.in_friaa is True:
        return RegulatoryFinding(
            **common,
            applicability="does_not_apply",
            rationale=(
                "The declared operation is within an FAA-Recognized Identification Area, which is "
                "one of the operational exceptions to the Remote ID broadcast requirement."
            ),
            missing_context=("confirmation that the FRIA authorisation covers this flight",),
        )

    if profile.in_friaa is None:
        return RegulatoryFinding(
            **common,
            applicability="unknown",
            rationale=(
                "Remote ID follows the registration status, subject to operational exceptions such "
                "as operating within a FRIA. Whether this flight is inside a FRIA has not been "
                "stated."
            ),
            missing_context=("whether the operation takes place within a FRIA",),
        )

    if registration.applicability == "unknown":
        return RegulatoryFinding(
            **common,
            applicability="unknown",
            rationale=(
                "Remote ID follows the registration status, and registration is itself unknown for "
                "this aircraft."
            ),
            missing_context=registration.missing_context,
        )

    if registration.applicability == "does_not_apply":
        return RegulatoryFinding(
            **common,
            applicability="does_not_apply",
            rationale=(
                "Registration is not required for this operation and the aircraft is not stated to "
                "be registered, so the broadcast requirement is not triggered."
            ),
            missing_context=("confirmation that the aircraft is not in fact registered",),
        )

    missing: tuple[str, ...] = ()
    if equipment_declared is None:
        missing = (
            "an explicit Remote ID equipment declaration; this cannot be inferred from a CAD body "
            "name or a part labelled 'Remote ID'",
        )
    elif equipment_declared is False:
        missing = ("a compliant standard Remote ID aircraft or a broadcast module",)

    return RegulatoryFinding(
        **common,
        applicability="applies",
        rationale=(
            "Registration applies to this operation, so the Remote ID broadcast requirement "
            "applies with it. "
            + (
                "Compliant equipment has been declared."
                if equipment_declared
                else "No compliant equipment has been established."
            )
        ),
        missing_context=missing,
    )
