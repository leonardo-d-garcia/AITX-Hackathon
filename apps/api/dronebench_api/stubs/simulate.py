"""Reference reduced-order mission model (architecture section 8), owned by Team C.

**This is Team B's stub**, so the Simulate mode and the baseline/candidate comparison have real
telemetry to render while ``packages/sim`` is being built.

Section 8's MVP plant, implemented as written: integrate distance and energy along a declared route
at fixed altitude and speed; at each step compute electrical power at that operating point and
update remaining usable Wh and distance.

Three rules the model keeps:

* ``remaining_energy_wh`` is energy usable **after** the reserve was withheld. The run terminates at
  zero and an incomplete route is marked energy-limited. The display is never clamped to zero while
  flight continues.
* Turns and bank angle are visual. The v1 model is straight and level, so manoeuvre loads and turn
  drag are absent, and the run says so in ``assumptions``.
* This is not physical bench testing, autonomous flight control, or a tested turning-flight
  envelope, and nothing here is labelled as though it were.
"""

from __future__ import annotations

import math
import time

from dronebench_contracts import (
    DroneBenchError,
    Evaluation,
    Mission,
    SimulationRun,
    SolverManifest,
    TelemetrySample,
)

#: Integration step. Small enough that the trapezoidal energy error is negligible at these powers,
#: large enough that a 40-minute mission is a few hundred samples rather than tens of thousands.
STEP_S = 5.0

#: Hard cap on samples, so a pathological input cannot spin forever.
MAX_SAMPLES = 20_000


class ReducedOrderSimulator:
    """Implements :class:`dronebench_contracts.SimulatePort`."""

    owner = "B-stub"

    def simulate(
        self,
        *,
        revision_id: str,
        evaluation: Evaluation,
        mission: Mission,
        run_id: str,
    ) -> SimulationRun:
        started = time.perf_counter()

        power_claim = evaluation.metrics.get("cruise_power_w")
        usable_claim = evaluation.metrics.get("usable_energy_wh")
        power = power_claim.number() if power_claim else None
        usable = usable_claim.number() if usable_claim else None

        if power is None or usable is None or power <= 0:
            # Without a power figure there is nothing to integrate. Returning a flat or invented
            # trace would put a plausible chart behind an unknown.
            raise DroneBenchError.of(
                "MISSING_EVIDENCE",
                "the reduced-order mission model needs cruise power and usable energy, and the "
                "evaluation did not establish them",
                revision_id=revision_id,
                missing=[
                    name
                    for name, value in (
                        ("cruise_power_w", power),
                        ("usable_energy_wh", usable),
                    )
                    if value is None
                ],
            )

        speed = mission.cruise_speed_mps
        route_m = mission.route_length_km * 1000.0

        samples: list[TelemetrySample] = [
            TelemetrySample(
                t_s=0.0,
                distance_km=0.0,
                speed_mps=speed,
                altitude_m=mission.altitude_m,
                power_w=power,
                remaining_energy_wh=usable,
                position_frd_m=(0.0, 0.0, -mission.altitude_m),
                bank_rad=0.0,
            )
        ]

        t = 0.0
        distance_m = 0.0
        remaining = usable
        completed = False

        while len(samples) < MAX_SAMPLES:
            # Energy consumed over the next step, at this operating point.
            step = STEP_S
            consumed = power * step / 3600.0

            if consumed >= remaining:
                # Terminate exactly at zero rather than stepping past it.
                step = remaining * 3600.0 / power
                consumed = remaining

            t += step
            distance_m += speed * step
            remaining = max(0.0, remaining - consumed)

            if distance_m >= route_m:
                # Land exactly on the route end.
                overshoot_m = distance_m - route_m
                overshoot_s = overshoot_m / speed
                t -= overshoot_s
                distance_m = route_m
                remaining += power * overshoot_s / 3600.0
                completed = True

            samples.append(
                TelemetrySample(
                    t_s=t,
                    distance_km=distance_m / 1000.0,
                    speed_mps=speed,
                    altitude_m=mission.altitude_m,
                    power_w=power,
                    remaining_energy_wh=remaining,
                    position_frd_m=_position(distance_m, route_m, mission.altitude_m),
                    bank_rad=_bank(distance_m, route_m),
                )
            )

            if completed or remaining <= 0.0:
                break

        return SimulationRun(
            run_id=run_id,
            revision_id=revision_id,
            mission_hash=mission.mission_hash(),
            fidelity="replay",
            solver=SolverManifest(solver="none", version=f"{self.owner}-reduced-order-1.0"),
            flight_model_tier="reduced_order_mission",
            samples=samples,
            completed_route=completed,
            termination_reason="route_complete" if completed else "energy_limited",
            assumptions=[
                "straight and level at the locked cruise speed and altitude",
                "constant electrical power at the single cruise operating point",
                "route turns and displayed bank are visual: manoeuvre loads and the extra drag of "
                "turning flight are not in this model, so the animation is not evidence of a "
                "tested turning-flight envelope",
                "no climb segment: takeoff and climb energy are not modelled",
                f"remaining energy is usable energy after the {mission.energy_reserve_fraction:.0%} "
                "reserve was withheld, so zero here means the reserve is untouched",
                "a model replay, not physical bench testing and not autonomous flight control",
            ],
            recorded_fallback=False,
            elapsed_s=time.perf_counter() - started,
        )


def _position(distance_m: float, route_m: float, altitude_m: float) -> tuple[float, float, float]:
    """A simple out-and-back leg with one turn, purely so the replay has something to show."""
    half = route_m / 2.0
    if distance_m <= half:
        return (distance_m, 0.0, -altitude_m)
    back = distance_m - half
    return (half - back, min(back, 40.0), -altitude_m)


def _bank(distance_m: float, route_m: float) -> float:
    """A declared visual bank convention. It is not derived from a turn-rate model."""
    half = route_m / 2.0
    turn_width = max(route_m * 0.02, 1.0)
    if abs(distance_m - half) < turn_width:
        return math.radians(25.0)
    return 0.0
