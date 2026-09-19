"""Reference analytic evaluator (architecture section 8), owned by Team C.

**This is Team B's stub.** Team C owns ``packages/evaluate``; until it lands, B needs a real
evaluator to build the revision store, recommender, and transaction machine against, and section 12
puts "analytic mass/CG/endurance/structure with hand checks" in the first four hours. Every
:class:`Evaluation` this module produces is stamped ``produced_by="B-stub"`` and reports
``fidelity="analytic"``. It never claims a solver ran, and :meth:`available_tiers` reports only what
it can actually deliver.

The equations are section 8's, used as written:

    m = sum(m_i);  r_CG = sum(m_i r_i) / m
    W = m g;  AR = b^2 / S;  q = 0.5 rho V^2;  CL = W / (q S)
    CD = CD0 + k CL^2,  k = 1 / (pi e AR);  D = q S CD
    P_elec = D V / (eta_prop eta_motor eta_esc) + P_avionics
    Wh_per_km = P_elec / (3.6 V);  endurance_min = 60 E_usable / P_elec
    V_stall = sqrt(2 W / (rho S CLmax))
    I = pi (Do^4 - Di^4) / 64;  sigma = M (Do/2) / I
    static margin = (s_NP - s_CG) / MAC

The rule that shapes the code more than any equation: **unknown propagates**. Section 8 says
missing important masses make CG and weight-dependent checks unknown, and section 5 says unknown
values stay null and carry no confidence. So a single occurrence with no mass evidence turns off
mass, CG, static margin, stall, energy, and current - it does not quietly contribute zero.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from dronebench_contracts import (
    CheckResult,
    Claim,
    Evaluation,
    FidelityTier,
    G0,
    GeometryFeatures,
    Mission,
    PartsDocument,
    REGISTRIES,
    SensitivityInterval,
    SolverManifest,
    content_hash,
)
from dronebench_recommend.regulatory import assess

#: Minimum genuine penetration, in metres, before an overlap counts as interference. Bodies that
#: merely touch at a face are not interfering.
INTERFERENCE_TOL_M = 5e-4

#: Physics this evaluator does not model. Stated on every result (section 8).
OMITTED_PHYSICS: tuple[str, ...] = (
    "spar buckling, joints, adhesive bonds, and local damage - only root bending stress is modelled",
    "skin/spar load sharing - the spar is assumed to carry the full wing bending moment",
    "trim drag and control-surface deflection at the trimmed condition",
    "propeller-airframe interaction, and propeller efficiency as a function of advance ratio",
    "battery internal resistance, voltage sag, and capacity dependence on discharge rate",
    "manoeuvre loads and turn drag - the mission model is straight and level",
    "Reynolds-number dependence of the zero-lift drag coefficient",
    "stall, separation, and post-stall behaviour beyond the declared CLmax assumption",
)


@dataclass
class _MassProperties:
    total_kg: float | None
    station_cg_m: float | None
    missing: list[str]


class AnalyticEvaluator:
    """Implements :class:`dronebench_contracts.EvaluatePort`."""

    owner = "B-stub"

    def available_tiers(self) -> list[FidelityTier]:
        """Only what is really installed.

        VSPAERO is Team C's, and this stub has no binary to call. Reporting the tier here would let
        the UI print a solver label with nothing behind it.
        """
        return ["analytic"]

    def evaluate(
        self,
        *,
        revision_id: str,
        parts: PartsDocument,
        features: GeometryFeatures,
        mission: Mission,
        fidelity: FidelityTier = "analytic",
    ) -> Evaluation:
        started = time.perf_counter()

        effective: FidelityTier = "analytic"
        downgrade_note: list[str] = []
        if fidelity != "analytic":
            # Section 8: a missing binary downgrades explicitly rather than mislabelling.
            downgrade_note.append(
                f"{fidelity} was requested but is not available on this installation; the result "
                "is an analytic estimate and is labelled as one"
            )

        mass = self._mass_properties(parts)
        inputs, unknown_inputs = self._inputs(parts, features, mission, mass)

        metrics: dict[str, Claim] = {}
        checks: list[CheckResult] = []

        self._mass_and_cg(mass, mission, metrics, checks)
        self._stability(mass, features, mission, metrics, checks)
        aero = self._aerodynamics(mass, features, mission, metrics, checks)
        self._propulsion_and_energy(parts, aero, mission, metrics, checks)
        self._structure(parts, mass, features, mission, metrics, checks)
        self._clearance(parts, checks)
        self._regulatory(parts, mission, mass, checks)
        self._tail_volume(features, metrics, checks)

        sensitivity = self._sensitivity(parts, mass, features, mission, aero)

        run_input_hash = content_hash(
            {
                "revision": revision_id,
                "parts": parts.model_dump(mode="json"),
                "features": features.model_dump(mode="json"),
                "mission": mission.model_dump(mode="json"),
                "evaluator": f"{self.owner}/analytic/1.0",
            }
        )

        return Evaluation(
            evaluation_id=f"eval_{run_input_hash[:16]}",
            revision_id=revision_id,
            mission_hash=mission.mission_hash(),
            registry_version=mission.registry_version,
            fidelity=effective,
            solver=SolverManifest(solver="none", version=f"{self.owner}-analytic-1.0"),
            metrics=metrics,
            checks=checks,
            sensitivity=sensitivity,
            inputs_used=inputs,
            unknown_inputs=unknown_inputs,
            omitted_physics=list(OMITTED_PHYSICS) + downgrade_note,
            run_input_hash=run_input_hash,
            produced_by="B-stub",
            elapsed_s=time.perf_counter() - started,
        )

    # -- inputs ------------------------------------------------------------------------------

    def _mass_properties(self, parts: PartsDocument) -> _MassProperties:
        total = 0.0
        moment = 0.0
        missing: list[str] = []

        for occurrence in parts.occurrences:
            mass = occurrence.mass_kg.number()
            if mass is None:
                missing.append(f"{occurrence.part_id}.mass_kg")
                continue
            com = occurrence.world_com_m()
            if com is None:
                missing.append(f"{occurrence.part_id}.local_com_m")
                continue
            total += mass
            moment += mass * com[0]

        if missing or total <= 0:
            return _MassProperties(None, None, missing)
        # Station is aft-positive: s = -x.
        return _MassProperties(total, -(moment / total), [])

    def _inputs(
        self,
        parts: PartsDocument,
        features: GeometryFeatures,
        mission: Mission,
        mass: _MassProperties,
    ) -> tuple[dict[str, Claim], list[str]]:
        """Section 8: report inputs and unknowns before numbers."""
        inputs: dict[str, Claim] = {
            "cruise_speed_mps": Claim.assumed(
                mission.cruise_speed_mps, "m/s", assumption="locked by the mission"
            ),
            "air_density_kgm3": Claim.assumed(
                mission.air_density_kgm3,
                "kg/m^3",
                assumption=f"ISA at {mission.altitude_m:.0f} m, declared by the mission",
            ),
            "wing_reference_area_m2": features.wing_reference_area_m2,
            "wing_span_m": features.wing_span_m,
            "wing_mac_m": features.wing_mac_m,
        }
        if features.neutral_point_station_m is not None:
            inputs["neutral_point_station_m"] = features.neutral_point_station_m

        for name, claim in self._aero_claims(parts).items():
            inputs[name] = claim
        for name, claim in self._electrical_claims(parts).items():
            inputs[name] = claim

        unknown = list(mass.missing)
        unknown += [name for name, claim in inputs.items() if not claim.is_known]
        return inputs, sorted(set(unknown))

    def _aero_claims(self, parts: PartsDocument) -> dict[str, Claim]:
        out: dict[str, Claim] = {}
        for definition in parts.definitions:
            if definition.role != "wing":
                continue
            for key in ("cl_max", "cd0", "oswald_efficiency"):
                claim = definition.claims.get(key)
                if claim is not None:
                    out[key] = claim
        return out

    def _electrical_claims(self, parts: PartsDocument) -> dict[str, Claim]:
        out: dict[str, Claim] = {}
        wanted = {
            "battery": ("capacity_wh", "nominal_voltage_v", "continuous_current_a"),
            "motor": ("efficiency",),
            "propeller": ("efficiency",),
            "esc": ("efficiency", "current_limit_a"),
            "flight_controller": ("power_w",),
        }
        for occurrence in parts.occurrences:
            for key in wanted.get(occurrence.role, ()):
                claim = occurrence.claims.get(key)
                if claim is not None:
                    out[f"{occurrence.role}.{key}"] = claim
        return out

    # -- checks ------------------------------------------------------------------------------

    def _mass_and_cg(
        self,
        mass: _MassProperties,
        mission: Mission,
        metrics: dict[str, Claim],
        checks: list[CheckResult],
    ) -> None:
        registry = REGISTRIES[mission.registry_version]

        if mass.total_kg is None:
            reason = (
                "at least one installed occurrence has no mass or no mass distribution, so all-up "
                "mass is not established. Geometry does not determine mass, and a missing value is "
                "not zero."
            )
            checks.append(
                CheckResult(
                    check_id="mass_budget",
                    check_class=registry.get("mass_budget").check_class,
                    status="unknown",
                    title=registry.get("mass_budget").title,
                    limit=f"<= {mission.max_takeoff_mass_kg:.3f} kg",
                    reason=reason,
                    missing_inputs=mass.missing,
                )
            )
            checks.append(
                CheckResult(
                    check_id="cg_envelope",
                    check_class=registry.get("cg_envelope").check_class,
                    status="unknown",
                    title=registry.get("cg_envelope").title,
                    limit=(
                        f"station in [{mission.cg_envelope_station_m[0]:.4f}, "
                        f"{mission.cg_envelope_station_m[1]:.4f}] m"
                    ),
                    reason=reason,
                    missing_inputs=mass.missing,
                )
            )
            return

        metrics["mass_kg"] = Claim.computed(
            mass.total_kg, "kg", assumptions=["sum of installed occurrence masses"]
        )
        metrics["cg_station_m"] = Claim.computed(
            mass.station_cg_m,  # type: ignore[arg-type]
            "m",
            assumptions=[
                "aft-positive station s = -x",
                "each occurrence contributes R @ local_com_m + translation",
            ],
        )

        checks.append(
            CheckResult(
                check_id="mass_budget",
                check_class=registry.get("mass_budget").check_class,
                status="pass" if mass.total_kg <= mission.max_takeoff_mass_kg else "fail",
                title=registry.get("mass_budget").title,
                value=metrics["mass_kg"],
                limit=f"<= {mission.max_takeoff_mass_kg:.3f} kg",
                reason=(
                    f"all-up mass {mass.total_kg:.3f} kg against a "
                    f"{mission.max_takeoff_mass_kg:.3f} kg limit "
                    f"({mission.max_takeoff_mass_kg - mass.total_kg:+.3f} kg margin)"
                ),
            )
        )

        lo, hi = mission.cg_envelope_station_m
        station = mass.station_cg_m
        assert station is not None
        inside = lo <= station <= hi
        checks.append(
            CheckResult(
                check_id="cg_envelope",
                check_class=registry.get("cg_envelope").check_class,
                status="pass" if inside else "fail",
                title=registry.get("cg_envelope").title,
                value=metrics["cg_station_m"],
                limit=f"station in [{lo:.4f}, {hi:.4f}] m",
                reason=(
                    f"centre of gravity at station {station:.4f} m, "
                    + (
                        "inside the envelope"
                        if inside
                        else (
                            "too far aft" if station > hi else "too far forward"
                        )
                        + f" by {(station - hi if station > hi else lo - station) * 1000:.0f} mm"
                    )
                ),
            )
        )

    def _stability(
        self,
        mass: _MassProperties,
        features: GeometryFeatures,
        mission: Mission,
        metrics: dict[str, Claim],
        checks: list[CheckResult],
    ) -> None:
        registry = REGISTRIES[mission.registry_version]
        declared = registry.get("static_margin")
        neutral_point = features.neutral_point_station_m
        mac = features.wing_mac_m.number()

        missing: list[str] = []
        if neutral_point is None or not neutral_point.is_known:
            missing.append("geometry_features.neutral_point_station_m")
        if mac is None:
            missing.append("geometry_features.wing_mac_m")
        if mass.station_cg_m is None:
            missing += mass.missing or ["centre of gravity"]

        if missing:
            checks.append(
                CheckResult(
                    check_id="static_margin",
                    check_class=declared.check_class,
                    status="unknown",
                    title=declared.title,
                    limit=(
                        f"[{mission.static_margin_bounds[0]:.2f}, "
                        f"{mission.static_margin_bounds[1]:.2f}] of MAC"
                    ),
                    reason=(
                        "no suitable stability method has produced a neutral point for this "
                        "V-tail aircraft, or the centre of gravity is unknown. A wing "
                        "quarter-chord guess is not a substitute."
                    ),
                    missing_inputs=missing,
                )
            )
            return

        assert neutral_point is not None and mac is not None and mass.station_cg_m is not None
        margin = (neutral_point.require("neutral point") - mass.station_cg_m) / mac
        metrics["static_margin"] = Claim(
            value=margin,
            unit="1",
            status="estimated",
            source_kind="computed",
            assumptions=[
                "(s_NP - s_CG) / MAC with aft-positive stations",
                *neutral_point.assumptions,
            ],
            evidence_ids=list(features.wing_mac_m.evidence_ids),
        )
        lo, hi = mission.static_margin_bounds
        checks.append(
            CheckResult(
                check_id="static_margin",
                check_class=declared.check_class,
                status="pass" if lo <= margin <= hi else "fail",
                title=declared.title,
                value=metrics["static_margin"],
                limit=f"[{lo:.2f}, {hi:.2f}] of MAC",
                reason=(
                    f"static margin {margin * 100:.1f}% of MAC, computed against an assumed "
                    f"neutral point at station {neutral_point.value} m. The neutral point is an "
                    "assumption of this synthetic fixture, not a solver result."
                ),
            )
        )

    def _aerodynamics(
        self,
        mass: _MassProperties,
        features: GeometryFeatures,
        mission: Mission,
        metrics: dict[str, Claim],
        checks: list[CheckResult],
    ) -> dict[str, float | None]:
        registry = REGISTRIES[mission.registry_version]
        area = features.wing_reference_area_m2.number()
        span = features.wing_span_m.number()
        rho = mission.air_density_kgm3
        speed = mission.cruise_speed_mps

        out: dict[str, float | None] = {"drag_n": None, "cl": None}

        if area is None or span is None or mass.total_kg is None:
            checks.append(
                CheckResult(
                    check_id="stall_margin",
                    check_class=registry.get("stall_margin").check_class,
                    status="unknown",
                    title=registry.get("stall_margin").title,
                    reason="weight or wing reference area is unknown, so stall speed is not computable",
                    missing_inputs=mass.missing or ["wing_reference_area_m2", "wing_span_m"],
                )
            )
            return out

        weight = mass.total_kg * G0
        aspect_ratio = span * span / area
        q = 0.5 * rho * speed * speed
        cl = weight / (q * area)

        metrics["aspect_ratio"] = Claim.computed(aspect_ratio, "1", assumptions=["b^2 / S"])
        metrics["cruise_cl"] = Claim.computed(
            cl, "1", assumptions=["steady level flight: CL = W / (q S)"]
        )
        out["cl"] = cl
        out["q"] = q
        out["area"] = area
        out["aspect_ratio"] = aspect_ratio
        return out

    def _propulsion_and_energy(
        self,
        parts: PartsDocument,
        aero: dict[str, float | None],
        mission: Mission,
        metrics: dict[str, Claim],
        checks: list[CheckResult],
    ) -> None:
        registry = REGISTRIES[mission.registry_version]
        electrical = self._electrical_claims(parts)
        aero_claims = self._aero_claims(parts)

        needed = {
            "cd0": aero_claims.get("cd0"),
            "oswald_efficiency": aero_claims.get("oswald_efficiency"),
            "cl_max": aero_claims.get("cl_max"),
            "battery.capacity_wh": electrical.get("battery.capacity_wh"),
            "battery.nominal_voltage_v": electrical.get("battery.nominal_voltage_v"),
            "battery.continuous_current_a": electrical.get("battery.continuous_current_a"),
            "motor.efficiency": electrical.get("motor.efficiency"),
            "propeller.efficiency": electrical.get("propeller.efficiency"),
            "esc.efficiency": electrical.get("esc.efficiency"),
            "esc.current_limit_a": electrical.get("esc.current_limit_a"),
            "flight_controller.power_w": electrical.get("flight_controller.power_w"),
        }
        missing = [name for name, claim in needed.items() if claim is None or not claim.is_known]

        cl = aero.get("cl")
        q = aero.get("q")
        area = aero.get("area")
        aspect_ratio = aero.get("aspect_ratio")
        if cl is None or q is None or area is None or aspect_ratio is None:
            missing.append("cruise lift coefficient (weight or reference area unknown)")

        def unknown(check_id: str, reason: str) -> None:
            declared = registry.get(check_id)
            checks.append(
                CheckResult(
                    check_id=check_id,
                    check_class=declared.check_class,
                    status="unknown",
                    title=declared.title,
                    reason=reason,
                    missing_inputs=sorted(set(missing)),
                )
            )

        if missing:
            reason = "the electrical or drag model is incomplete: " + ", ".join(sorted(set(missing)))
            unknown("energy_reserve", reason)
            unknown("battery_current", reason)
            if not any(c.check_id == "stall_margin" for c in checks):
                unknown("stall_margin", reason)
            return

        cd0 = needed["cd0"].require("cd0")  # type: ignore[union-attr]
        oswald = needed["oswald_efficiency"].require("oswald")  # type: ignore[union-attr]
        cl_max = needed["cl_max"].require("cl_max")  # type: ignore[union-attr]
        capacity = needed["battery.capacity_wh"].require("capacity")  # type: ignore[union-attr]
        voltage = needed["battery.nominal_voltage_v"].require("voltage")  # type: ignore[union-attr]
        pack_limit = needed["battery.continuous_current_a"].require("pack")  # type: ignore[union-attr]
        eta_motor = needed["motor.efficiency"].require("motor")  # type: ignore[union-attr]
        eta_prop = needed["propeller.efficiency"].require("prop")  # type: ignore[union-attr]
        eta_esc = needed["esc.efficiency"].require("esc")  # type: ignore[union-attr]
        esc_limit = needed["esc.current_limit_a"].require("esc limit")  # type: ignore[union-attr]
        avionics_w = needed["flight_controller.power_w"].require("avionics")  # type: ignore[union-attr]

        speed = mission.cruise_speed_mps
        induced_k = 1.0 / (math.pi * oswald * aspect_ratio)
        cd = cd0 + induced_k * cl * cl
        drag = q * area * cd
        power = drag * speed / (eta_prop * eta_motor * eta_esc) + avionics_w
        current = power / voltage
        wh_per_km = power / (3.6 * speed)
        usable_wh = capacity * (1.0 - mission.energy_reserve_fraction)
        endurance_min = 60.0 * usable_wh / power
        range_km = usable_wh / wh_per_km

        metrics.update(
            {
                "cruise_cd": Claim.computed(
                    cd, "1", assumptions=["CD = CD0 + k CL^2 with k = 1/(pi e AR)"]
                ),
                "drag_n": Claim.computed(drag, "N", assumptions=["D = q S CD"]),
                "cruise_power_w": Claim.computed(
                    power,
                    "W",
                    assumptions=[
                        "P = D V / (eta_prop eta_motor eta_esc) + P_avionics",
                        "single-point efficiencies standing in for curves",
                    ],
                ),
                "cruise_current_a": Claim.computed(
                    current,
                    "A",
                    assumptions=["I = P / V_nominal; voltage sag and internal resistance omitted"],
                ),
                "wh_per_km": Claim.computed(
                    wh_per_km, "Wh/km", assumptions=["Wh/km = P / (3.6 V)"]
                ),
                "usable_energy_wh": Claim.computed(
                    usable_wh,
                    "Wh",
                    assumptions=[
                        f"pack capacity less the {mission.energy_reserve_fraction:.0%} reserve"
                    ],
                ),
                "endurance_min": Claim.computed(
                    endurance_min, "min", assumptions=["60 E_usable / P at the locked cruise point"]
                ),
                "range_km": Claim.computed(
                    range_km, "km", assumptions=["E_usable / (Wh per km) at the locked cruise point"]
                ),
            }
        )

        route = mission.route_length_km
        checks.append(
            CheckResult(
                check_id="energy_reserve",
                check_class=registry.get("energy_reserve").check_class,
                status="pass" if range_km >= route else "fail",
                title=registry.get("energy_reserve").title,
                value=metrics["range_km"],
                limit=f">= {route:.1f} km on usable energy",
                reason=(
                    f"{range_km:.1f} km achievable on {usable_wh:.1f} Wh usable "
                    f"({mission.energy_reserve_fraction:.0%} reserve already withheld) against a "
                    f"{route:.1f} km route"
                ),
            )
        )

        limit = min(pack_limit, esc_limit)
        checks.append(
            CheckResult(
                check_id="battery_current",
                check_class=registry.get("battery_current").check_class,
                status="pass" if current <= limit else "fail",
                title=registry.get("battery_current").title,
                value=metrics["cruise_current_a"],
                limit=f"<= {limit:.1f} A (lower of pack {pack_limit:.0f} A and ESC {esc_limit:.0f} A)",
                reason=(
                    f"cruise current {current:.1f} A against a {limit:.1f} A continuous limit. "
                    "This is the cruise point only; climb and gust response draw more."
                ),
            )
        )

        # Stall, only if it has not already been reported unknown upstream.
        if not any(c.check_id == "stall_margin" for c in checks):
            weight = q * area * cl
            v_stall = math.sqrt(2 * weight / (mission.air_density_kgm3 * area * cl_max))
            required = v_stall * (1.0 + mission.stall_margin_fraction)
            metrics["v_stall_mps"] = Claim(
                value=v_stall,
                unit="m/s",
                status="estimated",
                source_kind="computed",
                assumptions=[
                    "V_stall = sqrt(2W / (rho S CLmax))",
                    "CLmax is a declared assumption, not a solver or wind-tunnel result",
                ],
            )
            checks.append(
                CheckResult(
                    check_id="stall_margin",
                    check_class=registry.get("stall_margin").check_class,
                    status="pass" if speed >= required else "fail",
                    title=registry.get("stall_margin").title,
                    value=metrics["v_stall_mps"],
                    limit=(
                        f"cruise >= {required:.1f} m/s "
                        f"(stall {v_stall:.1f} m/s + {mission.stall_margin_fraction:.0%})"
                    ),
                    reason=(
                        f"cruise {speed:.1f} m/s against an estimated stall speed of "
                        f"{v_stall:.1f} m/s. The stall estimate rests entirely on the assumed CLmax."
                    ),
                )
            )

    def _structure(
        self,
        parts: PartsDocument,
        mass: _MassProperties,
        features: GeometryFeatures,
        mission: Mission,
        metrics: dict[str, Claim],
        checks: list[CheckResult],
    ) -> None:
        registry = REGISTRIES[mission.registry_version]
        declared = registry.get("spar_stress")

        spars = [o for o in parts.occurrences if o.role == "spar"]
        span = features.wing_span_m.number()
        missing: list[str] = []
        if not spars:
            missing.append("no spar occurrence")
        if span is None:
            missing.append("geometry_features.wing_span_m")
        if mass.total_kg is None:
            missing += mass.missing

        outer = inner = allowable = None
        if spars:
            definition = parts.definition(spars[0].definition_id)
            outer = definition.parameters.get("outer_diameter_m")
            inner = definition.parameters.get("inner_diameter_m")
            allowable = definition.claims.number("allowable_stress_pa")
            if outer is None or inner is None:
                missing.append(f"{definition.definition_id} tube dimensions")
            if allowable is None:
                missing.append(f"{definition.definition_id}.allowable_stress_pa")

        if missing:
            checks.append(
                CheckResult(
                    check_id="spar_stress",
                    check_class=declared.check_class,
                    status="unknown",
                    title=declared.title,
                    reason="the spar bending model is missing inputs",
                    missing_inputs=sorted(set(missing)),
                )
            )
            return

        assert outer is not None and inner is not None and allowable is not None
        assert span is not None and mass.total_kg is not None

        # Half-wing lift acting at the centroid of an elliptical spanwise distribution,
        # at the mission limit load factor.
        weight = mass.total_kg * G0
        half_lift = weight * mission.load_factor_limit / 2.0
        arm = (4.0 / (3.0 * math.pi)) * (span / 2.0)
        moment = half_lift * arm
        second_moment = math.pi * (outer**4 - inner**4) / 64.0
        stress = moment * (outer / 2.0) / second_moment
        safety_factor = allowable / stress

        metrics["spar_root_moment_nm"] = Claim.computed(
            moment,
            "N*m",
            assumptions=[
                f"half-wing lift at limit load factor {mission.load_factor_limit:.1f}",
                "elliptical spanwise lift distribution; centroid at 4/(3 pi) of the semi-span",
                "the spar carries the full bending moment; no skin/spar load sharing is modelled",
            ],
        )
        metrics["spar_stress_pa"] = Claim.computed(
            stress, "Pa", assumptions=["sigma = M (Do/2) / I", "I = pi (Do^4 - Di^4) / 64"]
        )
        metrics["spar_safety_factor"] = Claim.computed(
            safety_factor, "1", assumptions=["allowable stress divided by computed bending stress"]
        )

        checks.append(
            CheckResult(
                check_id="spar_stress",
                check_class=declared.check_class,
                status="pass" if stress <= allowable else "fail",
                title=declared.title,
                value=metrics["spar_stress_pa"],
                limit=f"<= {allowable / 1e6:.0f} MPa",
                reason=(
                    f"root bending stress {stress / 1e6:.1f} MPa at limit load "
                    f"(safety factor {safety_factor:.1f}). Bending only: buckling, joints, "
                    "adhesive, and local damage are not modelled."
                ),
            )
        )

    def _clearance(self, parts: PartsDocument, checks: list[CheckResult]) -> None:
        """Unintended interference only. Declared mating and nesting pairs are excluded.

        This is a bounding-box screen, which is coarse. Team A's kernel-level check supersedes it;
        the reason text says so rather than implying a solid-model result.
        """
        registry_check = REGISTRIES["fixed_wing_cruise/1.0"].get("clearance")
        placed = [(o, o.world_bounds_m()) for o in parts.occurrences]
        findings: list[str] = []
        skipped: list[str] = []

        for index, (a, box_a) in enumerate(placed):
            if box_a is None:
                skipped.append(a.part_id)
                continue
            for b, box_b in placed[index + 1 :]:
                if box_b is None:
                    continue
                if b.part_id in a.allowed_contact_part_ids or a.part_id in b.allowed_contact_part_ids:
                    continue
                overlap = min(
                    min(box_a.max_m[k], box_b.max_m[k]) - max(box_a.min_m[k], box_b.min_m[k])
                    for k in range(3)
                )
                if overlap > INTERFERENCE_TOL_M:
                    kind = (
                        "propeller swept volume"
                        if "propeller" in (a.role, b.role)
                        else "unintended overlap"
                    )
                    findings.append(
                        f"{a.part_id} and {b.part_id} interpenetrate by "
                        f"{overlap * 1000:.1f} mm ({kind})"
                    )

        if findings:
            status, reason = "fail", "; ".join(findings)
        elif skipped:
            status = "unknown"
            reason = (
                "these occurrences have no bounds, so their clearance was not checked: "
                + ", ".join(skipped)
            )
        else:
            status = "pass"
            reason = (
                "no unintended interference between installed occurrences. Bounding-box screen at "
                f"{INTERFERENCE_TOL_M * 1000:.1f} mm penetration; declared mating, bonded, and "
                "nesting pairs are excluded. A kernel-level solid check supersedes this."
            )

        checks.append(
            CheckResult(
                check_id="clearance",
                check_class=registry_check.check_class,
                status=status,  # type: ignore[arg-type]
                title=registry_check.title,
                limit=f"no unintended penetration over {INTERFERENCE_TOL_M * 1000:.1f} mm",
                reason=reason,
                missing_inputs=skipped,
            )
        )

    def _regulatory(
        self,
        parts: PartsDocument,
        mission: Mission,
        mass: _MassProperties,
        checks: list[CheckResult],
    ) -> None:
        registry = REGISTRIES[mission.registry_version]
        report = assess(mission=mission, parts=parts, total_mass_kg=mass.total_kg)

        mapping = {
            "registration_applicability": "registration",
            "remote_id_applicability": "remote_id",
        }
        for check_id, rule_id in mapping.items():
            declared = registry.get(check_id)
            finding = report.by_id(rule_id)
            if finding is None:  # pragma: no cover - assess always returns both
                checks.append(
                    CheckResult(
                        check_id=check_id,
                        check_class=declared.check_class,
                        status="unknown",
                        title=declared.title,
                        reason="no applicability determination was produced",
                        missing_inputs=["regulatory profile"],
                    )
                )
                continue

            # An applicability finding is not a pass/fail of the design. "applies" means the rule
            # is in scope; "does_not_apply" means it is out of scope. Neither certifies anything,
            # so both map to a passing check and the rationale carries the meaning.
            status = "unknown" if finding.applicability == "unknown" else (
                "pass" if finding.applicability == "does_not_apply" else "pass"
            )
            checks.append(
                CheckResult(
                    check_id=check_id,
                    check_class=declared.check_class,
                    status=status,  # type: ignore[arg-type]
                    title=declared.title,
                    limit=f"{finding.jurisdiction} / {finding.operation}",
                    reason=f"{finding.applicability}: {finding.rationale} {finding.disclaimer}",
                    missing_inputs=list(finding.missing_context),
                )
            )

    def _tail_volume(
        self,
        features: GeometryFeatures,
        metrics: dict[str, Claim],
        checks: list[CheckResult],
    ) -> None:
        declared = REGISTRIES["fixed_wing_cruise/1.0"].get("tail_volume")
        area = features.wing_reference_area_m2.number()
        mac = features.wing_mac_m.number()

        if not features.vtail_panels or area is None or mac is None:
            checks.append(
                CheckResult(
                    check_id="tail_volume",
                    check_class=declared.check_class,
                    status="unknown",
                    title=declared.title,
                    reason="no V-tail panels or no wing reference quantities",
                    missing_inputs=["vtail_panels", "wing_reference_area_m2", "wing_mac_m"],
                )
            )
            return

        # Effective horizontal projection of the canted panels. A conventional horizontal-tail
        # template does not apply unchanged to a V-tail (architecture section 6).
        effective_area = sum(
            panel.area_m2 * math.cos(panel.cant_rad) ** 2 for panel in features.vtail_panels
        )
        arm = sum(p.arm_m for p in features.vtail_panels) / len(features.vtail_panels)
        coefficient = effective_area * arm / (area * mac)

        metrics["tail_volume_coefficient"] = Claim.computed(
            coefficient,
            "1",
            assumptions=[
                "effective horizontal projection of the canted V-tail panels, cos^2(cant)",
                "a profile heuristic, not a certification criterion",
            ],
        )
        low, high = 0.30, 0.90
        checks.append(
            CheckResult(
                check_id="tail_volume",
                check_class=declared.check_class,
                status="pass" if low <= coefficient <= high else "fail",
                title=declared.title,
                value=metrics["tail_volume_coefficient"],
                limit=f"informational range [{low:.2f}, {high:.2f}]",
                reason=(
                    f"effective tail volume coefficient {coefficient:.3f} from the horizontal "
                    "projection of the canted panels. Informational only: a conventional-tail "
                    "template is not a pass/fail criterion for a V-tail aircraft."
                ),
            )
        )

    # -- sensitivity ---------------------------------------------------------------------------

    def _sensitivity(
        self,
        parts: PartsDocument,
        mass: _MassProperties,
        features: GeometryFeatures,
        mission: Mission,
        aero: dict[str, float | None],
    ) -> list[SensitivityInterval]:
        """Low/nominal/high endurance over the declared uncertain efficiencies and CD0.

        Section 8 calls this an "assumption range", not a calibrated confidence interval, and
        :class:`SensitivityInterval` carries that label as a required literal.
        """
        electrical = self._electrical_claims(parts)
        aero_claims = self._aero_claims(parts)
        needed = [
            aero_claims.get("cd0"),
            aero_claims.get("oswald_efficiency"),
            electrical.get("battery.capacity_wh"),
            electrical.get("motor.efficiency"),
            electrical.get("propeller.efficiency"),
            electrical.get("esc.efficiency"),
            electrical.get("flight_controller.power_w"),
        ]
        if any(claim is None or not claim.is_known for claim in needed):
            return []
        cl = aero.get("cl")
        q = aero.get("q")
        area = aero.get("area")
        aspect_ratio = aero.get("aspect_ratio")
        if cl is None or q is None or area is None or aspect_ratio is None:
            return []

        cd0 = needed[0].require("cd0")  # type: ignore[union-attr]
        oswald = needed[1].require("e")  # type: ignore[union-attr]
        capacity = needed[2].require("wh")  # type: ignore[union-attr]
        eta = (
            needed[3].require("m")  # type: ignore[union-attr]
            * needed[4].require("p")  # type: ignore[union-attr]
            * needed[5].require("e")  # type: ignore[union-attr]
        )
        avionics = needed[6].require("a")  # type: ignore[union-attr]
        speed = mission.cruise_speed_mps
        usable = capacity * (1.0 - mission.energy_reserve_fraction)

        def endurance(cd0_v: float, eta_v: float) -> float:
            cd = cd0_v + cl * cl / (math.pi * oswald * aspect_ratio)
            power = q * area * cd * speed / eta_v + avionics
            return 60.0 * usable / power

        # +/-20% on CD0 and +/-10% on the efficiency chain: the declared spread of single-point
        # figures standing in for curves.
        pessimistic = endurance(cd0 * 1.2, eta * 0.9)
        nominal = endurance(cd0, eta)
        optimistic = endurance(cd0 * 0.8, eta * 1.1)

        return [
            SensitivityInterval(
                metric="endurance_min",
                unit="min",
                low=pessimistic,
                nominal=nominal,
                high=optimistic,
                varied_inputs=[
                    "cd0 +/- 20% (build-up estimate, no solver or tunnel data)",
                    "propulsion efficiency chain +/- 10% (single points standing in for curves)",
                ],
            )
        ]
