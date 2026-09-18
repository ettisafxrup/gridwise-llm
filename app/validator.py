from __future__ import annotations

import math

from .models import (
    DirectiveInterpretation,
    OptimizeRequest,
)


TOLERANCE = 0.01


def approximately_equal(
    a: float,
    b: float,
) -> bool:

    return abs(a - b) <= TOLERANCE


def assert_finite(
    value: float,
    name: str,
) -> None:

    if not math.isfinite(value):
        raise ValueError(
            f"{name} must be finite"
        )


def validate_hourly_plan(
    request: OptimizeRequest,
    directives: list[DirectiveInterpretation],
    hourly_plan: list[dict],
) -> None:

    if len(hourly_plan) != 24:
        raise ValueError(
            "hourly_plan must contain exactly 24 entries"
        )

    actual_hours = [
        entry["hour"]
        for entry in hourly_plan
    ]

    if actual_hours != list(range(24)):
        raise ValueError(
            "hourly_plan must contain hours 0 through 23"
        )

    # --------------------------------------------------------
    # Build directive constraint maps
    # --------------------------------------------------------

    no_charge_hours = set()
    no_discharge_hours = set()

    grid_caps = {}

    solar_factors = {}

    reserve_requirements = {}

    for directive in directives:

        if not directive.applies:
            continue

        adjustment = (
            directive.structured_adjustment
        )

        if (
            directive.directive_type
            == "solar_reduction"
        ):

            for hour in adjustment.hours:

                # Multiple reductions are combined
                # multiplicatively.
                solar_factors[hour] = (
                    solar_factors.get(
                        hour,
                        1.0,
                    )
                    * adjustment.factor
                )

        elif (
            directive.directive_type
            == "minimum_battery_reserve"
        ):

            for hour in adjustment.hours:

                reserve_requirements[hour] = max(
                    reserve_requirements.get(
                        hour,
                        request.battery.minimum_energy_kwh,
                    ),
                    adjustment.minimum_energy_kwh,
                )

        elif (
            directive.directive_type
            == "no_charge_window"
        ):

            no_charge_hours.update(
                adjustment.hours
            )

        elif (
            directive.directive_type
            == "no_discharge_window"
        ):

            no_discharge_hours.update(
                adjustment.hours
            )

        elif (
            directive.directive_type
            == "max_grid_window"
        ):

            for hour in adjustment.hours:

                existing = grid_caps.get(
                    hour,
                    float("inf"),
                )

                grid_caps[hour] = min(
                    existing,
                    adjustment.max_grid_kwh,
                )

    # --------------------------------------------------------
    # Replay battery state
    # --------------------------------------------------------

    energy = (
        request.battery.initial_energy_kwh
    )

    for hour in range(24):

        plan = hourly_plan[hour]
        scenario_hour = request.hours[hour]

        grid = float(
            plan["grid_kwh"]
        )

        solar_used = float(
            plan["solar_used_kwh"]
        )

        battery_kwh = float(
            plan["battery_kwh"]
        )

        reported_energy = float(
            plan["battery_energy_after_kwh"]
        )

        action = plan["battery_action"]

        # ----------------------------------------------------
        # Basic numerical validity
        # ----------------------------------------------------

        assert_finite(
            grid,
            f"hour {hour} grid_kwh",
        )

        assert_finite(
            solar_used,
            f"hour {hour} solar_used_kwh",
        )

        assert_finite(
            battery_kwh,
            f"hour {hour} battery_kwh",
        )

        assert_finite(
            reported_energy,
            f"hour {hour} battery_energy_after_kwh",
        )

        if grid < -TOLERANCE:
            raise ValueError(
                f"Negative grid energy at hour {hour}"
            )

        if solar_used < -TOLERANCE:
            raise ValueError(
                f"Negative solar usage at hour {hour}"
            )

        if battery_kwh < -TOLERANCE:
            raise ValueError(
                f"Negative battery magnitude at hour {hour}"
            )

        # ----------------------------------------------------
        # Effective solar
        # ----------------------------------------------------

        factor = solar_factors.get(
            hour,
            1.0,
        )

        effective_solar = (
            scenario_hour.solar_kwh
            * factor
        )

        if solar_used > (
            effective_solar + TOLERANCE
        ):

            raise ValueError(
                f"Solar usage exceeds effective "
                f"solar at hour {hour}"
            )

        # ----------------------------------------------------
        # Battery action
        # ----------------------------------------------------

        if action == "charge":

            if battery_kwh > (
                request.battery.max_charge_kwh_per_hour
                + TOLERANCE
            ):

                raise ValueError(
                    f"Charge rate exceeded at hour {hour}"
                )

            if hour in no_charge_hours:

                raise ValueError(
                    f"Charging forbidden at hour {hour}"
                )

            battery_discharge = 0.0
            battery_charge = battery_kwh

            expected_energy = (
                energy + battery_kwh
            )

        elif action == "discharge":

            if battery_kwh > (
                request.battery.max_discharge_kwh_per_hour
                + TOLERANCE
            ):

                raise ValueError(
                    f"Discharge rate exceeded at hour {hour}"
                )

            if hour in no_discharge_hours:

                raise ValueError(
                    f"Discharging forbidden at hour {hour}"
                )

            battery_charge = 0.0
            battery_discharge = battery_kwh

            expected_energy = (
                energy - battery_kwh
            )

        elif action == "idle":

            if abs(battery_kwh) > TOLERANCE:

                raise ValueError(
                    f"Idle action must have battery_kwh=0 "
                    f"at hour {hour}"
                )

            battery_charge = 0.0
            battery_discharge = 0.0

            expected_energy = energy

        else:

            raise ValueError(
                f"Invalid battery action at hour {hour}"
            )

        # ----------------------------------------------------
        # Battery bounds
        # ----------------------------------------------------

        if expected_energy < (
            request.battery.minimum_energy_kwh
            - TOLERANCE
        ):

            raise ValueError(
                f"Base battery reserve violated at hour {hour}"
            )

        if expected_energy > (
            request.battery.capacity_kwh
            + TOLERANCE
        ):

            raise ValueError(
                f"Battery capacity exceeded at hour {hour}"
            )

        # ----------------------------------------------------
        # Additional reserve directive
        # ----------------------------------------------------

        required_reserve = reserve_requirements.get(
            hour,
            request.battery.minimum_energy_kwh,
        )

        if expected_energy < (
            required_reserve - TOLERANCE
        ):

            raise ValueError(
                f"Operator battery reserve violated "
                f"at hour {hour}"
            )

        # ----------------------------------------------------
        # Grid cap
        # ----------------------------------------------------

        if hour in grid_caps:

            if grid > (
                grid_caps[hour] + TOLERANCE
            ):

                raise ValueError(
                    f"Grid cap violated at hour {hour}"
                )

        # ----------------------------------------------------
        # Energy balance
        #
        # grid + solar + discharge
        # =
        # demand + charge
        # ----------------------------------------------------

        lhs = (
            grid
            + solar_used
            + battery_discharge
        )

        rhs = (
            scenario_hour.demand_kwh
            + battery_charge
        )

        if not approximately_equal(
            lhs,
            rhs,
        ):

            raise ValueError(
                f"Energy balance violated at hour {hour}: "
                f"{lhs} != {rhs}"
            )

        # ----------------------------------------------------
        # Reported battery state must agree with replay
        # ----------------------------------------------------

        if not approximately_equal(
            reported_energy,
            expected_energy,
        ):

            raise ValueError(
                f"battery_energy_after_kwh mismatch "
                f"at hour {hour}"
            )

        energy = expected_energy

    # --------------------------------------------------------
    # End-of-day neutrality
    # --------------------------------------------------------

    initial_energy = (
        request.battery.initial_energy_kwh
    )

    if not approximately_equal(
        energy,
        initial_energy,
    ):

        raise ValueError(
            "End-of-day battery neutrality violated"
        )


def calculate_totals(
    request: OptimizeRequest,
    hourly_plan: list[dict],
) -> tuple[float, float, float]:

    total_grid = 0.0
    total_cost = 0.0
    peak_grid = 0.0

    for entry in hourly_plan:

        hour = entry["hour"]
        grid = float(
            entry["grid_kwh"]
        )

        total_grid += grid

        total_cost += (
            grid
            * request.hours[hour]
            .tariff_bdt_per_kwh
        )

        peak_grid = max(
            peak_grid,
            grid,
        )

    return (
        total_grid,
        total_cost,
        peak_grid,
    )


def validate_reported_totals(
    request: OptimizeRequest,
    hourly_plan: list[dict],
    total_grid_kwh: float,
    total_cost_bdt: float,
    peak_grid_kwh: float,
) -> None:

    (
        recalculated_grid,
        recalculated_cost,
        recalculated_peak,
    ) = calculate_totals(
        request,
        hourly_plan,
    )

    if not approximately_equal(
        total_grid_kwh,
        recalculated_grid,
    ):

        raise ValueError(
            "total_grid_kwh does not match hourly_plan"
        )

    if not approximately_equal(
        total_cost_bdt,
        recalculated_cost,
    ):

        raise ValueError(
            "total_cost_bdt does not match hourly_plan"
        )

    if not approximately_equal(
        peak_grid_kwh,
        recalculated_peak,
    ):

        raise ValueError(
            "peak_grid_kwh does not match hourly_plan"
        )