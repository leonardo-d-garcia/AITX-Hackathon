"""Build the frozen ``parametric_fixedwing`` fixture (architecture section 12).

Section 12's fallback line authorises exactly this: "If full Avenger reconstruction delays the
first edit, use a simpler clearly named parametric fixed-wing fixture." Team B needs it sooner than
that, because A's importer and C's evaluator do not exist yet and B's revision store, graph,
recommender, and transaction machine all need a design to operate on.

Everything here is **synthetic and clearly named**. It is not the Titan Avenger, it makes no claim
about any real aircraft, and no offer in its catalog names a real supplier. Section 8 asks for "a
fully specified synthetic engineering fixture" precisely so the demo can reach a verified result
inside the implemented model while listing the omitted validations openly.

The scenario is deliberately configured, not discovered: the battery sits aft enough to put the CG
outside the envelope, which gives the recommender a real failing check to answer. That is the
section 14 demo beat, and it is labelled a synthetic scenario wherever it surfaces.

Run ``python fixtures/b/build_fixture.py`` to regenerate. The output is committed; the hash is
asserted in ``tests/contract/test_fixture_frozen.py``.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "contracts"))

from dronebench_contracts import (  # noqa: E402
    AxisAlignedBox,
    CatalogItem,
    CatalogOffer,
    CatalogSnapshot,
    Claim,
    ClaimSet,
    DeclaredInterface,
    DesignManifest,
    Evidence,
    GeometryFeatures,
    Mission,
    PartDefinition,
    PartOccurrence,
    PartsDocument,
    RegulatoryProfile,
    Transform,
    TravelCorridor,
    VTailPanel,
    WingStation,
    canonical_json,
    content_hash,
)

OUT = Path(__file__).resolve().parent
COMMON = ROOT / "fixtures" / "common"

DESIGN_ID = "dsn_parametric-fixedwing"
FIXTURE_NAME = "parametric_fixedwing (synthetic demonstrator - not the Titan Avenger)"
CAPTURED_AT = datetime(2026, 9, 19, 12, 0, 0, tzinfo=timezone.utc)

# The fixture's revision id is derived from its own content at the end of the build, so the file
# on disk is self-consistent. This placeholder is replaced before anything is written.
PLACEHOLDER_REVISION = "rev_0000000000000000"


# ---------------------------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------------------------


def _evidence() -> list[Evidence]:
    def entry(eid: str, uri: str, kind, method: str, locator: str | None = None) -> Evidence:
        return Evidence(
            evidence_id=eid,
            source_uri=uri,
            source_kind=kind,
            accessed_at=CAPTURED_AT,
            locator=locator,
            extraction_method=method,
        )

    return [
        entry(
            "ev_fixture-spec",
            "fixtures/b/README.md",
            "manual",
            "fixture_specification",
            "parametric_fixedwing v1",
        ),
        entry(
            "ev_bom-battery",
            "fixtures/b/bom.yaml",
            "bom",
            "bom_entry",
            "battery_4s_5000",
        ),
        entry("ev_bom-motor", "fixtures/b/bom.yaml", "bom", "bom_entry", "motor_front"),
        entry("ev_bom-esc", "fixtures/b/bom.yaml", "bom", "bom_entry", "esc_main"),
        entry("ev_bom-avionics", "fixtures/b/bom.yaml", "bom", "bom_entry", "fc_rx_gps"),
        entry("ev_bom-servo", "fixtures/b/bom.yaml", "bom", "bom_entry", "servo_vtail"),
        entry("ev_bom-payload", "fixtures/b/bom.yaml", "bom", "bom_entry", "payload_block"),
        entry(
            "ev_spar-datasheet",
            "fixtures/b/materials.yaml",
            "manual",
            "datasheet_field",
            "pultruded CF tube, synthetic datasheet",
        ),
        entry(
            "ev_print-process",
            "fixtures/b/materials.yaml",
            "manual",
            "slicer_report",
            "LW-PLA, 15% infill, 2 walls",
        ),
        entry(
            "ev_recon-geometry",
            "fixtures/b/geometry_features.json",
            "cad",
            "parametric_authoring",
            "wing stations and V-tail panels",
        ),
        entry(
            "ev_catalog-snapshot",
            "fixtures/common/catalog.json",
            "catalog",
            "catalog_field",
            "synthetic snapshot 2026-09-19",
        ),
        entry(
            "ev_faa-registration",
            "https://www.faa.gov/uas/getting_started/register_drone",
            "manual",
            "regulatory_text",
            "aircraft registration",
        ),
        entry(
            "ev_faa-remote-id",
            "https://www.faa.gov/uas/getting_started/remote_id",
            "manual",
            "regulatory_text",
            "remote identification",
        ),
    ]


# ---------------------------------------------------------------------------------------------
# Geometry parameters
# ---------------------------------------------------------------------------------------------

SPAN_M = 2.00
ROOT_CHORD_M = 0.26
TIP_CHORD_M = 0.18
WING_AREA_M2 = 2 * ((ROOT_CHORD_M + TIP_CHORD_M) / 2) * (SPAN_M / 2)  # 0.44 m^2
MAC_M = (2 / 3) * ROOT_CHORD_M * (
    (1 + (TIP_CHORD_M / ROOT_CHORD_M) + (TIP_CHORD_M / ROOT_CHORD_M) ** 2)
    / (1 + (TIP_CHORD_M / ROOT_CHORD_M))
)
WING_QUARTER_CHORD_X_M = -0.32  # aft of the nose datum, so negative in FRD
SPAR_OUTER_D_M = 0.016
SPAR_INNER_D_M = 0.014
SPAR_LENGTH_M = 1.90
CF_DENSITY_KGM3 = 1550.0

VTAIL_AREA_EACH_M2 = 0.055
VTAIL_CANT_RAD = math.radians(37.0)
VTAIL_ARM_M = 0.78
VTAIL_CHORD_M = 0.15


def spar_mass_kg(outer_d: float, inner_d: float, length: float) -> float:
    area = math.pi * (outer_d**2 - inner_d**2) / 4.0
    return area * length * CF_DENSITY_KGM3


def _definitions() -> list[PartDefinition]:
    def claims(**kv: Claim) -> ClaimSet:
        return ClaimSet(claims=dict(kv))

    return [
        PartDefinition(
            definition_id="def_wing-panel",
            name="Parametric wing panel",
            representation="editable_reconstruction",
            role="wing",
            parameters={
                "root_chord_m": ROOT_CHORD_M,
                "tip_chord_m": TIP_CHORD_M,
                "semi_span_m": SPAN_M / 2,
                "tip_extension_m": 0.0,
            },
            claims=claims(
                airfoil=Claim.assumed(
                    "NACA 4412",
                    "1",
                    assumption=(
                        "declared assumed airfoil; no reliable match was attempted against a "
                        "printed section"
                    ),
                ),
                cl_max=Claim.assumed(
                    1.25,
                    "1",
                    assumption="2D section CLmax reduced for finite wing; not solver-derived",
                ),
                cd0=Claim.assumed(
                    0.035,
                    "1",
                    assumption=(
                        "zero-lift drag coefficient for the whole aircraft on the wing reference "
                        "area, covering profile, fuselage, and interference drag; a flat-plate "
                        "build-up estimate, not a solver result"
                    ),
                ),
                oswald_efficiency=Claim.assumed(
                    0.85,
                    "1",
                    assumption="span efficiency for a moderately tapered unswept wing",
                ),
            ),
        ),
        PartDefinition(
            definition_id="def_vtail-panel",
            name="Parametric V-tail panel",
            representation="editable_reconstruction",
            role="tail_panel",
            parameters={
                "area_m2": VTAIL_AREA_EACH_M2,
                "cant_rad": VTAIL_CANT_RAD,
                "chord_m": VTAIL_CHORD_M,
            },
        ),
        PartDefinition(
            definition_id="def_fuselage",
            name="Parametric fuselage boom and pod",
            representation="editable_reconstruction",
            role="fuselage",
            parameters={"length_m": 1.15, "width_m": 0.11, "height_m": 0.12},
        ),
        PartDefinition(
            definition_id="def_spar-tube",
            name="Pultruded CF spar tube",
            representation="editable_reconstruction",
            role="spar",
            parameters={
                "outer_diameter_m": SPAR_OUTER_D_M,
                "inner_diameter_m": SPAR_INNER_D_M,
                "length_m": SPAR_LENGTH_M,
            },
            claims=claims(
                density_kgm3=Claim.measured(
                    CF_DENSITY_KGM3, "kg/m^3", source_kind="manual",
                    evidence_ids=["ev_spar-datasheet"],
                ),
                allowable_stress_pa=Claim.measured(
                    6.0e8, "Pa", source_kind="manual", evidence_ids=["ev_spar-datasheet"]
                ),
                youngs_modulus_pa=Claim.measured(
                    1.2e11, "Pa", source_kind="manual", evidence_ids=["ev_spar-datasheet"]
                ),
            ),
        ),
        PartDefinition(
            definition_id="def_spar-mount",
            name="Printed spar mount",
            representation="generated",
            role="mount",
            parameters={"bore_m": SPAR_OUTER_D_M, "wall_m": 0.003},
        ),
        PartDefinition(
            definition_id="def_battery-4s5000",
            name="4S 5000 mAh pack envelope",
            representation="catalog_envelope",
            role="battery",
            parameters={"length_m": 0.155, "width_m": 0.049, "height_m": 0.036},
        ),
        PartDefinition(
            definition_id="def_motor-2216",
            name="2216 outrunner envelope",
            representation="catalog_envelope",
            role="motor",
        ),
        PartDefinition(
            definition_id="def_prop-12x6",
            name="12x6 propeller envelope",
            representation="catalog_envelope",
            role="propeller",
        ),
        PartDefinition(
            definition_id="def_esc-40a",
            name="40 A ESC envelope",
            representation="catalog_envelope",
            role="esc",
        ),
        PartDefinition(
            definition_id="def_servo-9g",
            name="9 g servo envelope",
            representation="catalog_envelope",
            role="servo",
        ),
        PartDefinition(
            definition_id="def_avionics",
            name="Flight controller / receiver / GPS stack",
            representation="catalog_envelope",
            role="flight_controller",
        ),
        PartDefinition(
            definition_id="def_payload",
            name="Mission payload block",
            representation="catalog_envelope",
            role="payload",
        ),
    ]


def _box(size: tuple[float, float, float]) -> AxisAlignedBox:
    half = tuple(v / 2 for v in size)
    return AxisAlignedBox(
        min_m=(-half[0], -half[1], -half[2]), max_m=(half[0], half[1], half[2])
    )


def _com_at_origin() -> tuple[Claim, Claim, Claim]:
    """A component whose mass distribution is taken as its envelope centre, explicitly assumed."""
    assumption = "mass taken as uniformly distributed in the component envelope"
    return (
        Claim.assumed(0.0, "m", assumption=assumption),
        Claim.assumed(0.0, "m", assumption=assumption),
        Claim.assumed(0.0, "m", assumption=assumption),
    )


#: Fuselage mass distribution assumption, cited by its local centre of mass.
_POD_HEAVY = (
    "pod-heavy mass distribution: the printed equipment pod carries most of the shell mass "
    "and the tail boom is a light tube; this is a declared approximation, not a measurement"
)

BATTERY_X_M = -0.515  # deliberately aft: this is the configured failing scenario
#: The free battery bay. Its forward limit is set by the spar web, not by the fuselage: a pack
#: pushed past it would foul the spar, so the corridor stops short of it.
BATTERY_CORRIDOR = (-0.53, -0.42)
#: Discrete mount positions along the corridor. The recommender may only propose these.
BATTERY_MOUNTS = [-0.515, -0.47, -0.44, -0.42]

#: Assumed neutral point, aft-positive station. Section 8 permits a documented synthetic
#: fixture to supply this for illustrating the workflow, provided the report says it is
#: assumed. It is not derived from the wing quarter-chord, which would be meaningless here.
NEUTRAL_POINT_STATION_M = 0.40


#: Intended mating and nesting partners of a wing panel. The root passes through the fuselage
#: and sits over the spar, its mounts, the battery bay, and the harness run; a bounding-box test
#: cannot distinguish that engagement from interference, so it is declared (architecture section 6).
_WING_CONTACTS = [
    "prt_fuselage",
    "prt_spar",
    "prt_spar-mount-left",
    "prt_spar-mount-right",
    "prt_battery",
    "prt_harness",
]


def _occurrences() -> list[PartOccurrence]:
    bom = lambda value, eid: Claim.measured(  # noqa: E731
        value, "kg", source_kind="bom", evidence_ids=[eid]
    )

    wing_mass_each = Claim(
        value=0.185,
        unit="kg",
        status="known",
        source_kind="manual",
        evidence_ids=["ev_print-process"],
        assumptions=["printed shell mass from the slicer report, not a filled bounding envelope"],
    )

    occurrences: list[PartOccurrence] = [
        PartOccurrence(
            part_id="prt_fuselage",
            definition_id="def_fuselage",
            name="Fuselage pod",
            role="fuselage",
            transform=Transform.translating((-0.60, 0.0, 0.0)),
            bounds_local_m=_box((1.15, 0.11, 0.12)),
            mass_kg=Claim(
                value=0.240,
                unit="kg",
                status="known",
                source_kind="manual",
                evidence_ids=["ev_print-process"],
                assumptions=["printed shell mass from the slicer report"],
            ),
            # Not the bounding-box centre. The equipment pod carries most of the shell mass and
            # the tail boom is a light tube, so the centre of mass sits well forward of the datum.
            local_com_m=(
                Claim.assumed(0.20, "m", assumption=_POD_HEAVY),
                Claim.assumed(0.0, "m", assumption=_POD_HEAVY),
                Claim.assumed(0.0, "m", assumption=_POD_HEAVY),
            ),
            allowed_contact_part_ids=[],
        ),
        PartOccurrence(
            part_id="prt_wing-left",
            definition_id="def_wing-panel",
            name="Wing panel, left",
            role="wing",
            transform=Transform.translating((WING_QUARTER_CHORD_X_M, -SPAN_M / 4, -0.01)),
            bounds_local_m=AxisAlignedBox(
                min_m=(-ROOT_CHORD_M * 0.75, -SPAN_M / 4, -0.02),
                max_m=(ROOT_CHORD_M * 0.25, SPAN_M / 4, 0.02),
            ),
            mass_kg=wing_mass_each,
            local_com_m=_com_at_origin(),
            edit_capabilities=["set_wing_tip_extension"],
            allowed_contact_part_ids=_WING_CONTACTS,
        ),
        PartOccurrence(
            part_id="prt_wing-right",
            definition_id="def_wing-panel",
            name="Wing panel, right",
            role="wing",
            mirror_of="prt_wing-left",
            transform=Transform.translating((WING_QUARTER_CHORD_X_M, SPAN_M / 4, -0.01)),
            bounds_local_m=AxisAlignedBox(
                min_m=(-ROOT_CHORD_M * 0.75, -SPAN_M / 4, -0.02),
                max_m=(ROOT_CHORD_M * 0.25, SPAN_M / 4, 0.02),
            ),
            mass_kg=wing_mass_each,
            local_com_m=_com_at_origin(),
            edit_capabilities=["set_wing_tip_extension"],
            allowed_contact_part_ids=_WING_CONTACTS,
        ),
        PartOccurrence(
            part_id="prt_spar",
            definition_id="def_spar-tube",
            name="Main spar",
            role="spar",
            transform=Transform.translating((WING_QUARTER_CHORD_X_M, 0.0, -0.005)),
            bounds_local_m=AxisAlignedBox(
                min_m=(-SPAR_OUTER_D_M / 2, -SPAR_LENGTH_M / 2, -SPAR_OUTER_D_M / 2),
                max_m=(SPAR_OUTER_D_M / 2, SPAR_LENGTH_M / 2, SPAR_OUTER_D_M / 2),
            ),
            mass_kg=Claim.computed(
                spar_mass_kg(SPAR_OUTER_D_M, SPAR_INNER_D_M, SPAR_LENGTH_M),
                "kg",
                assumptions=["tube volume times the datasheet density"],
                evidence_ids=["ev_spar-datasheet"],
            ),
            local_com_m=_com_at_origin(),
            edit_capabilities=["resize_spar"],
            allowed_contact_part_ids=["prt_wing-left", "prt_wing-right", "prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_spar-mount-left",
            definition_id="def_spar-mount",
            name="Spar mount, left",
            role="mount",
            transform=Transform.translating((WING_QUARTER_CHORD_X_M, -0.09, -0.005)),
            bounds_local_m=_box((0.03, 0.03, 0.03)),
            mass_kg=Claim(
                value=0.012,
                unit="kg",
                status="estimated",
                source_kind="computed",
                evidence_ids=["ev_print-process"],
                assumptions=["printed mount, slicer estimate"],
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_spar", "prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_spar-mount-right",
            definition_id="def_spar-mount",
            name="Spar mount, right",
            role="mount",
            mirror_of="prt_spar-mount-left",
            transform=Transform.translating((WING_QUARTER_CHORD_X_M, 0.09, -0.005)),
            bounds_local_m=_box((0.03, 0.03, 0.03)),
            mass_kg=Claim(
                value=0.012,
                unit="kg",
                status="estimated",
                source_kind="computed",
                evidence_ids=["ev_print-process"],
                assumptions=["printed mount, slicer estimate"],
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_spar", "prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_battery",
            definition_id="def_battery-4s5000",
            name="Main battery pack",
            role="battery",
            transform=Transform.translating((BATTERY_X_M, 0.0, 0.015)),
            bounds_local_m=_box((0.155, 0.049, 0.036)),
            mass_kg=bom(0.545, "ev_bom-battery"),
            claims=ClaimSet(
                claims={
                    "capacity_wh": Claim.measured(
                        74.0, "Wh", source_kind="bom", evidence_ids=["ev_bom-battery"]
                    ),
                    "nominal_voltage_v": Claim.measured(
                        14.8, "V", source_kind="bom", evidence_ids=["ev_bom-battery"]
                    ),
                    "continuous_current_a": Claim.measured(
                        100.0, "A", source_kind="bom", evidence_ids=["ev_bom-battery"]
                    ),
                }
            ),
            local_com_m=_com_at_origin(),
            edit_capabilities=["translate_component", "replace_catalog_component"],
            travel_corridor=TravelCorridor(
                axis="x",
                min_m=BATTERY_CORRIDOR[0],
                max_m=BATTERY_CORRIDOR[1],
                harness_allowance_m=Claim.measured(
                    0.15, "m", source_kind="bom", evidence_ids=["ev_bom-battery"]
                ),
                mount_positions_m=list(BATTERY_MOUNTS),
            ),
            allowed_contact_part_ids=["prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_motor",
            definition_id="def_motor-2216",
            name="Tractor motor",
            role="motor",
            transform=Transform.translating((-0.045, 0.0, 0.0)),
            bounds_local_m=_box((0.04, 0.028, 0.028)),
            mass_kg=bom(0.072, "ev_bom-motor"),
            claims=ClaimSet(
                claims={
                    "efficiency": Claim.assumed(
                        0.85,
                        "1",
                        assumption=(
                            "motor efficiency at the cruise operating point; a single figure "
                            "standing in for a curve, and not derivable from KV alone"
                        ),
                    ),
                }
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_prop",
            definition_id="def_prop-12x6",
            name="Propeller",
            role="propeller",
            transform=Transform.translating((-0.015, 0.0, 0.0)),
            bounds_local_m=_box((0.02, 0.305, 0.305)),
            mass_kg=bom(0.018, "ev_bom-motor"),
            claims=ClaimSet(
                claims={
                    "efficiency": Claim.assumed(
                        0.55,
                        "1",
                        assumption=(
                            "propeller efficiency at the cruise advance ratio; a single figure "
                            "standing in for a propeller map"
                        ),
                    ),
                }
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_motor"],
        ),
        PartOccurrence(
            part_id="prt_esc",
            definition_id="def_esc-40a",
            name="ESC",
            role="esc",
            transform=Transform.translating((-0.10, 0.0, 0.018)),
            bounds_local_m=_box((0.055, 0.026, 0.011)),
            mass_kg=bom(0.038, "ev_bom-esc"),
            claims=ClaimSet(
                claims={
                    "current_limit_a": Claim.measured(
                        40.0, "A", source_kind="bom", evidence_ids=["ev_bom-esc"]
                    ),
                    "efficiency": Claim.assumed(
                        0.95, "1", assumption="ESC conversion efficiency at cruise throttle"
                    ),
                }
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_avionics",
            definition_id="def_avionics",
            name="FC / RX / GPS stack",
            role="flight_controller",
            transform=Transform.translating((-0.17, 0.0, 0.020)),
            bounds_local_m=_box((0.05, 0.05, 0.022)),
            mass_kg=bom(0.061, "ev_bom-avionics"),
            claims=ClaimSet(
                claims={
                    "power_w": Claim.measured(
                        1.5, "W", source_kind="bom", evidence_ids=["ev_bom-avionics"]
                    ),
                }
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_servo-left",
            definition_id="def_servo-9g",
            name="V-tail servo, left",
            role="servo",
            transform=Transform.translating((-0.86, -0.03, 0.0)),
            bounds_local_m=_box((0.023, 0.012, 0.026)),
            mass_kg=bom(0.009, "ev_bom-servo"),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_fuselage", "prt_vtail-left"],
        ),
        PartOccurrence(
            part_id="prt_servo-right",
            definition_id="def_servo-9g",
            name="V-tail servo, right",
            role="servo",
            mirror_of="prt_servo-left",
            transform=Transform.translating((-0.86, 0.03, 0.0)),
            bounds_local_m=_box((0.023, 0.012, 0.026)),
            mass_kg=bom(0.009, "ev_bom-servo"),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_fuselage", "prt_vtail-right"],
        ),
        PartOccurrence(
            part_id="prt_vtail-left",
            definition_id="def_vtail-panel",
            name="V-tail panel, left",
            role="tail_panel",
            transform=Transform.translating(
                (WING_QUARTER_CHORD_X_M - VTAIL_ARM_M, -0.14, -0.08)
            ),
            bounds_local_m=AxisAlignedBox(
                min_m=(-VTAIL_CHORD_M * 0.75, -0.02, -0.16),
                max_m=(VTAIL_CHORD_M * 0.25, 0.02, 0.02),
            ),
            mass_kg=Claim(
                value=0.036,
                unit="kg",
                status="known",
                source_kind="manual",
                evidence_ids=["ev_print-process"],
                assumptions=["printed shell mass from the slicer report"],
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_vtail-right",
            definition_id="def_vtail-panel",
            name="V-tail panel, right",
            role="tail_panel",
            mirror_of="prt_vtail-left",
            transform=Transform.translating(
                (WING_QUARTER_CHORD_X_M - VTAIL_ARM_M, 0.14, -0.08)
            ),
            bounds_local_m=AxisAlignedBox(
                min_m=(-VTAIL_CHORD_M * 0.75, -0.02, -0.16),
                max_m=(VTAIL_CHORD_M * 0.25, 0.02, 0.02),
            ),
            mass_kg=Claim(
                value=0.036,
                unit="kg",
                status="known",
                source_kind="manual",
                evidence_ids=["ev_print-process"],
                assumptions=["printed shell mass from the slicer report"],
            ),
            local_com_m=_com_at_origin(),
            allowed_contact_part_ids=["prt_fuselage"],
        ),
        PartOccurrence(
            part_id="prt_payload",
            definition_id="def_payload",
            name="Mission payload block",
            role="payload",
            transform=Transform.translating((-0.25, 0.0, 0.030)),
            bounds_local_m=_box((0.08, 0.06, 0.04)),
            mass_kg=bom(0.250, "ev_bom-payload"),
            local_com_m=_com_at_origin(),
            locked=True,
            allowed_contact_part_ids=["prt_fuselage"],
        ),
        # One deliberately unknown mass. Section 10 wants "Unknown mass" to be actionable in the
        # inspector, and section 5 wants unknowns to stay null rather than be invented.
        PartOccurrence(
            part_id="prt_harness",
            definition_id="def_avionics",
            name="Wiring harness",
            role="harness",
            transform=Transform.translating((-0.35, 0.0, -0.030)),
            bounds_local_m=_box((0.55, 0.03, 0.01)),
            mass_kg=Claim.unknown(
                "kg",
                reason="no harness specification in the fixture BOM; enter a measured value",
            ),
            # The run is known even though its mass is not: the harness is routed along the
            # equipment shelf. Only the mass is missing, so only mass-dependent results go unknown.
            local_com_m=_com_at_origin(),
            # A harness touches every component it connects. Declaring those pairs is what keeps
            # the clearance check about unintended interference rather than about wiring.
            allowed_contact_part_ids=[
                "prt_fuselage", "prt_battery", "prt_esc", "prt_avionics",
                "prt_servo-left", "prt_servo-right",
            ],
        ),
    ]
    return occurrences


def _geometry_features(revision_id: str) -> GeometryFeatures:
    stations = [
        WingStation(
            span_y_m=0.0,
            leading_edge_x_m=WING_QUARTER_CHORD_X_M + 0.25 * ROOT_CHORD_M,
            chord_m=ROOT_CHORD_M,
            z_m=-0.01,
            twist_rad=0.0,
        ),
        WingStation(
            span_y_m=SPAN_M / 4,
            leading_edge_x_m=WING_QUARTER_CHORD_X_M + 0.25 * 0.22,
            chord_m=0.22,
            z_m=-0.008,
            twist_rad=math.radians(-0.5),
        ),
        WingStation(
            span_y_m=SPAN_M / 2,
            leading_edge_x_m=WING_QUARTER_CHORD_X_M + 0.25 * TIP_CHORD_M,
            chord_m=TIP_CHORD_M,
            z_m=-0.005,
            twist_rad=math.radians(-1.5),
        ),
    ]
    return GeometryFeatures(
        revision_id=revision_id,
        frame_confirmed=True,
        units_confirmed=True,
        nose_datum_note=(
            "Nose datum at the fuselage forward face of the synthetic demonstrator. Canonical FRD, "
            "X forward, so every station aft of the nose has negative x."
        ),
        wing_stations=stations,
        wing_reference_area_m2=Claim.measured(
            WING_AREA_M2, "m^2", source_kind="cad", evidence_ids=["ev_recon-geometry"]
        ),
        wing_span_m=Claim.measured(
            SPAN_M, "m", source_kind="cad", evidence_ids=["ev_recon-geometry"]
        ),
        wing_mac_m=Claim.measured(
            MAC_M, "m", source_kind="cad", evidence_ids=["ev_recon-geometry"]
        ),
        vtail_panels=[
            VTailPanel(
                part_id="prt_vtail-left",
                area_m2=VTAIL_AREA_EACH_M2,
                cant_rad=VTAIL_CANT_RAD,
                arm_m=VTAIL_ARM_M,
                mean_chord_m=VTAIL_CHORD_M,
            ),
            VTailPanel(
                part_id="prt_vtail-right",
                area_m2=VTAIL_AREA_EACH_M2,
                cant_rad=VTAIL_CANT_RAD,
                arm_m=VTAIL_ARM_M,
                mean_chord_m=VTAIL_CHORD_M,
            ),
        ],
        neutral_point_station_m=Claim.assumed(
            NEUTRAL_POINT_STATION_M,
            "m",
            assumption=(
                "assumed neutral point for this synthetic demonstrator; no stability method has "
                "produced one, and a wing quarter-chord guess is not valid for a V-tail aircraft"
            ),
        ),
        fit_error_m=Claim.computed(
            0.0,
            "m",
            assumptions=[
                "this fixture is authored parametrically, so there is no reference silhouette to "
                "deviate from; a real reconstruction reports a measured deviation here"
            ],
        ),
        reconstruction_confirmed=True,
        quality_limits=[
            "synthetic demonstrator; no correspondence to any manufactured aircraft",
            "no airfoil match attempted - the section is a declared assumption",
            "skin/spar load sharing is not modelled",
        ],
    )


def _mission() -> Mission:
    return Mission(
        mission_id="msn_cruise-demo",
        title="Straight-and-level cruise, synthetic demonstrator",
        objective="max_endurance",
        cruise_speed_mps=16.0,
        altitude_m=120.0,
        air_density_kgm3=1.2133,  # ISA at 120 m; declared, not silently assumed
        max_takeoff_mass_kg=2.0,
        payload_mass_kg=0.250,
        energy_reserve_fraction=0.20,
        route_length_km=12.0,
        load_factor_limit=3.0,
        # Derived from the assumed neutral point and MAC so the two checks cannot contradict
        # one another: s_CG = s_NP - SM * MAC over the static margin bounds below.
        cg_envelope_station_m=(
            round(NEUTRAL_POINT_STATION_M - 0.25 * MAC_M, 4),
            round(NEUTRAL_POINT_STATION_M - 0.08 * MAC_M, 4),
        ),
        static_margin_bounds=(0.08, 0.25),
        stall_margin_fraction=0.30,
        locked_part_ids=("prt_payload",),
        regulatory=RegulatoryProfile(
            jurisdiction="US",
            operation="part_107_commercial",
            over_people=False,
            beyond_visual_line_of_sight=False,
            in_friaa=False,
            evidence_ids=("ev_faa-registration", "ev_faa-remote-id"),
        ),
    )


# ---------------------------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------------------------


def _catalog() -> CatalogSnapshot:
    def synthetic_offer(price: float, basis: str = "each") -> CatalogOffer:
        return CatalogOffer(
            currency="USD",
            unit_price=price,
            quantity_basis=basis,  # type: ignore[arg-type]
            region="synthetic",
            stock_known=False,
            synthetic=True,
        )

    def bore(outer_m: float) -> DeclaredInterface:
        return DeclaredInterface(
            interface_id=f"if_bore_{int(round(outer_m * 1000))}mm",
            kind="mechanical_bore",
            dimensions_m={"diameter": outer_m},
        )

    def envelope(length: float, width: float, height: float, tag: str) -> DeclaredInterface:
        return DeclaredInterface(
            interface_id=f"if_envelope_{tag}",
            kind="mass_envelope",
            dimensions_m={"length_max": length, "width_max": width, "height_max": height},
        )

    def dc(vmin: float, vmax: float, amps: float, tag: str) -> DeclaredInterface:
        return DeclaredInterface(
            interface_id=f"if_dc_{tag}",
            kind="electrical_dc",
            voltage_v=(vmin, vmax),
            current_limit_a=amps,
        )

    catalog_evidence = ["ev_catalog-snapshot"]

    items = [
        CatalogItem(
            catalog_item_id="cat_bat_4s5000",
            category="battery",
            display_name="Synthetic 4S 5000 mAh LiPo",
            mass_kg=Claim.measured(
                0.545, "kg", source_kind="catalog", evidence_ids=catalog_evidence
            ),
            claims={
                "capacity_wh": Claim.measured(
                    74.0, "Wh", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "nominal_voltage_v": Claim.measured(
                    14.8, "V", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "continuous_current_a": Claim.measured(
                    100.0, "A", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[
                envelope(0.160, 0.052, 0.040, "bat_4s5000"),
                dc(12.0, 16.8, 100.0, "bat_4s5000"),
            ],
            offers=[synthetic_offer(48.0)],
            evidence_ids=catalog_evidence,
        ),
        CatalogItem(
            catalog_item_id="cat_bat_4s4000_light",
            category="battery",
            display_name="Synthetic 4S 4000 mAh LiPo, lighter",
            mass_kg=Claim.measured(
                0.430, "kg", source_kind="catalog", evidence_ids=catalog_evidence
            ),
            claims={
                "capacity_wh": Claim.measured(
                    59.2, "Wh", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "nominal_voltage_v": Claim.measured(
                    14.8, "V", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "continuous_current_a": Claim.measured(
                    80.0, "A", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[
                envelope(0.145, 0.048, 0.035, "bat_4s4000"),
                dc(12.0, 16.8, 80.0, "bat_4s4000"),
            ],
            offers=[synthetic_offer(41.0)],
            evidence_ids=catalog_evidence,
        ),
        CatalogItem(
            catalog_item_id="cat_bat_6s5000_oversize",
            category="battery",
            display_name="Synthetic 6S 5000 mAh LiPo (does not fit the bay)",
            mass_kg=Claim.measured(
                0.780, "kg", source_kind="catalog", evidence_ids=catalog_evidence
            ),
            claims={
                "capacity_wh": Claim.measured(
                    111.0, "Wh", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "nominal_voltage_v": Claim.measured(
                    22.2, "V", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "continuous_current_a": Claim.measured(
                    100.0, "A", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[
                envelope(0.190, 0.060, 0.048, "bat_6s5000"),
                dc(18.0, 25.2, 100.0, "bat_6s5000"),
            ],
            offers=[synthetic_offer(72.0)],
            evidence_ids=catalog_evidence,
        ),
        CatalogItem(
            catalog_item_id="cat_spar_16x14",
            category="spar",
            display_name="Synthetic CF tube 16 x 14 mm",
            mass_kg=Claim.computed(
                spar_mass_kg(0.016, 0.014, SPAR_LENGTH_M),
                "kg",
                assumptions=["tube volume times the catalog density"],
                evidence_ids=catalog_evidence,
            ),
            claims={
                "outer_diameter_m": Claim.measured(
                    0.016, "m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "inner_diameter_m": Claim.measured(
                    0.014, "m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "allowable_stress_pa": Claim.measured(
                    6.0e8, "Pa", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "density_kgm3": Claim.measured(
                    CF_DENSITY_KGM3, "kg/m^3", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[bore(0.016)],
            offers=[synthetic_offer(19.0, "per_metre")],
            evidence_ids=catalog_evidence,
        ),
        CatalogItem(
            catalog_item_id="cat_spar_18x16",
            category="spar",
            display_name="Synthetic CF tube 18 x 16 mm",
            mass_kg=Claim.computed(
                spar_mass_kg(0.018, 0.016, SPAR_LENGTH_M),
                "kg",
                assumptions=["tube volume times the catalog density"],
                evidence_ids=catalog_evidence,
            ),
            claims={
                "outer_diameter_m": Claim.measured(
                    0.018, "m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "inner_diameter_m": Claim.measured(
                    0.016, "m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "allowable_stress_pa": Claim.measured(
                    6.0e8, "Pa", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "density_kgm3": Claim.measured(
                    CF_DENSITY_KGM3, "kg/m^3", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[bore(0.018)],
            offers=[synthetic_offer(23.0, "per_metre")],
            evidence_ids=catalog_evidence,
        ),
        CatalogItem(
            catalog_item_id="cat_spar_20x17",
            category="spar",
            display_name="Synthetic CF tube 20 x 17 mm",
            mass_kg=Claim.computed(
                spar_mass_kg(0.020, 0.017, SPAR_LENGTH_M),
                "kg",
                assumptions=["tube volume times the catalog density"],
                evidence_ids=catalog_evidence,
            ),
            claims={
                "outer_diameter_m": Claim.measured(
                    0.020, "m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "inner_diameter_m": Claim.measured(
                    0.017, "m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "allowable_stress_pa": Claim.measured(
                    6.0e8, "Pa", source_kind="catalog", evidence_ids=catalog_evidence
                ),
                "density_kgm3": Claim.measured(
                    CF_DENSITY_KGM3, "kg/m^3", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[bore(0.020)],
            offers=[synthetic_offer(27.0, "per_metre")],
            evidence_ids=catalog_evidence,
        ),
        CatalogItem(
            catalog_item_id="cat_servo_9g",
            category="servo",
            display_name="Synthetic 9 g servo",
            mass_kg=Claim.measured(
                0.009, "kg", source_kind="catalog", evidence_ids=catalog_evidence
            ),
            claims={
                "stall_torque_nm": Claim.measured(
                    0.157, "N*m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[
                envelope(0.024, 0.013, 0.027, "servo_9g"),
                DeclaredInterface(
                    interface_id="if_pwm_servo_9g", kind="signal_pwm", voltage_v=(4.8, 6.0)
                ),
            ],
            offers=[synthetic_offer(7.0)],
            evidence_ids=catalog_evidence,
        ),
        CatalogItem(
            catalog_item_id="cat_servo_12g_hightorque",
            category="servo",
            display_name="Synthetic 12 g high-torque servo",
            mass_kg=Claim.measured(
                0.012, "kg", source_kind="catalog", evidence_ids=catalog_evidence
            ),
            claims={
                "stall_torque_nm": Claim.measured(
                    0.245, "N*m", source_kind="catalog", evidence_ids=catalog_evidence
                ),
            },
            interfaces=[
                envelope(0.026, 0.013, 0.028, "servo_12g"),
                DeclaredInterface(
                    interface_id="if_pwm_servo_12g", kind="signal_pwm", voltage_v=(4.8, 7.4)
                ),
            ],
            offers=[synthetic_offer(11.0)],
            evidence_ids=catalog_evidence,
        ),
    ]
    return CatalogSnapshot(
        snapshot_id="cat_synthetic_2026-09-19",
        captured_at=CAPTURED_AT,
        items=items,
        all_synthetic=True,
    )


# ---------------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------------


def build() -> dict[str, object]:
    """Return the fixture documents, with a revision id derived from their own content."""
    definitions = _definitions()
    occurrences = _occurrences()

    seed = content_hash(
        {
            "design_id": DESIGN_ID,
            "definitions": [d.model_dump(mode="json") for d in definitions],
            "occurrences": [o.model_dump(mode="json") for o in occurrences],
        }
    )
    revision_id = f"rev_{seed[:16]}"

    parts = PartsDocument(
        revision_id=revision_id,
        definitions=definitions,
        occurrences=occurrences,
        evidence=_evidence(),
    )
    manifest = DesignManifest(
        design_id=DESIGN_ID,
        revision_id=revision_id,
        display_name=FIXTURE_NAME,
        representation_mode="editable_reconstruction",
        excluded_alternatives=[],
        notes=[
            "Synthetic demonstrator authored for Team B. Not derived from the Titan archive and "
            "not a reconstruction of any real aircraft.",
            "The battery sits at the aft end of its corridor on purpose: this is a configured "
            "demo scenario that produces a failing CG check, not a discovered defect.",
        ],
    )
    features = _geometry_features(revision_id)
    mission = _mission()
    catalog = _catalog()

    return {
        "revision_id": revision_id,
        "design_manifest": manifest,
        "parts": parts,
        "geometry_features": features,
        "mission": mission,
        "catalog": catalog,
    }


def write(outdir: Path = OUT, common: Path = COMMON) -> dict[str, str]:
    built = build()
    outdir.mkdir(parents=True, exist_ok=True)
    common.mkdir(parents=True, exist_ok=True)

    targets = {
        outdir / "design_manifest.json": built["design_manifest"],
        outdir / "parts.json": built["parts"],
        outdir / "geometry_features.json": built["geometry_features"],
        outdir / "mission.json": built["mission"],
        common / "catalog.json": built["catalog"],
    }
    written: dict[str, str] = {}
    for path, model in targets.items():
        payload = model.model_dump(mode="json")  # type: ignore[union-attr]
        text = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        path.write_text(text, encoding="utf-8")
        written[str(path.relative_to(ROOT)).replace("\\", "/")] = content_hash(payload)

    fixture_hash = content_hash(
        {name: digest for name, digest in sorted(written.items())}
    )
    (outdir / "FIXTURE_HASH").write_text(fixture_hash + "\n", encoding="utf-8")
    written["fixture_hash"] = fixture_hash
    written["revision_id"] = str(built["revision_id"])
    return written


def main() -> int:
    written = write()
    print(canonical_json(written).replace(",", ",\n  "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
