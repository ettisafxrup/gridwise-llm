from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog

from .models import (
    DirectiveInterpretation,
    OptimizeRequest,
)


@dataclass
class OptimizationResult:
    hourly_plan: list[dict]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float


GRID_START = 0
SOLAR_START = 24
BATTERY_START = 48

VARIABLE_COUNT = 72
HOURS = 24


def _apply_directives(
    request: OptimizeRequest,
    directives: list[DirectiveInterpretation],
):
    """
    Convert structured directives into deterministic arrays
    consumed by the LP model.
    """

    original_solar = np.array(
        [
            entry.solar_kwh
            for entry in request.hours
        ],
        dtype=float,
    )

    effective_solar = original_solar.copy()

    charge_allowed = np.ones(
        HOURS,
        dtype=bool,
    )

    discharge_allowed = np.ones(
        HOURS,
        dtype=bool,
    )

    grid_caps = np.full(
        HOURS,
        np.inf,
        dtype=float,
    )

    base_reserve = (
        request.battery.minimum_energy_kwh
    )

    reserve = np.full(
        HOURS,
        base_reserve,
        dtype=float,
    )

    for directive in directives:

        if directive.directive_type == "no_op":
            continue

        adjustment = (
            directive.structured_adjustment
        )

        if (
            directive.directive_type
            == "solar_reduction"
        ):

            factor = adjustment.factor

            for hour in adjustment.hours:

                effective_solar[hour] *= factor

        elif (
            directive.directive_type
            == "minimum_battery_reserve"
        ):

            for hour in adjustment.hours:

                reserve[hour] = max(
                    reserve[hour],
                    adjustment.minimum_energy_kwh,
                )

        elif (
            directive.directive_type
            == "no_charge_window"
        ):

            for hour in adjustment.hours:
                charge_allowed[hour] = False

        elif (
            directive.directive_type
            == "no_discharge_window"
        ):

            for hour in adjustment.hours:
                discharge_allowed[hour] = False

        elif (
            directive.directive_type
            == "max_grid_window"
        ):

            for hour in adjustment.hours:

                grid_caps[hour] = min(
                    grid_caps[hour],
                    adjustment.max_grid_kwh,
                )

    return (
        effective_solar,
        charge_allowed,
        discharge_allowed,
        grid_caps,
        reserve,
    )


def optimize(
    request: OptimizeRequest,
    directives: list[DirectiveInterpretation],
) -> OptimizationResult:

    demand = np.array(
        [
            entry.demand_kwh
            for entry in request.hours
        ],
        dtype=float,
    )

    tariff = np.array(
        [
            entry.tariff_bdt_per_kwh
            for entry in request.hours
        ],
        dtype=float,
    )

    (
        effective_solar,
        charge_allowed,
        discharge_allowed,
        grid_caps,
        reserve,
    ) = _apply_directives(
        request,
        directives,
    )

    battery = request.battery

    # --------------------------------------------------------
    # Objective vector
    #
    # Minimize:
    #
    # SUM(grid[h] * tariff[h])
    # --------------------------------------------------------

    objective = np.zeros(
        VARIABLE_COUNT,
        dtype=float,
    )

    objective[
        GRID_START:GRID_START + HOURS
    ] = tariff

    # --------------------------------------------------------
    # Variable bounds
    # --------------------------------------------------------

    bounds = []

    # Grid variables
    for hour in range(HOURS):

        bounds.append(
            (
                0.0,
                float(grid_caps[hour]),
            )
        )

    # Solar variables
    for hour in range(HOURS):

        bounds.append(
            (
                0.0,
                float(effective_solar[hour]),
            )
        )

    # Signed battery delta variables
    #
    # Positive = charge
    # Negative = discharge
    #

    max_charge = (
        battery.max_charge_kwh_per_hour
    )

    max_discharge = (
        battery.max_discharge_kwh_per_hour
    )

    for hour in range(HOURS):

        lower = -max_discharge
        upper = max_charge

        if not discharge_allowed[hour]:
            lower = 0.0

        if not charge_allowed[hour]:
            upper = 0.0

        bounds.append(
            (
                lower,
                upper,
            )
        )

    # --------------------------------------------------------
    # Equality constraints
    # --------------------------------------------------------

    A_eq = []
    b_eq = []

    # Energy balance:
    #
    # grid + solar - battery_delta = demand
    #

    for hour in range(HOURS):

        row = np.zeros(
            VARIABLE_COUNT,
            dtype=float,
        )

        row[
            GRID_START + hour
        ] = 1.0

        row[
            SOLAR_START + hour
        ] = 1.0

        row[
            BATTERY_START + hour
        ] = -1.0

        A_eq.append(row)
        b_eq.append(demand[hour])

    # End-of-day neutrality:
    #
    # SUM(delta[h]) = 0
    #

    neutrality_row = np.zeros(
        VARIABLE_COUNT,
        dtype=float,
    )

    for hour in range(HOURS):

        neutrality_row[
            BATTERY_START + hour
        ] = 1.0

    A_eq.append(neutrality_row)
    b_eq.append(0.0)

    # --------------------------------------------------------
    # Inequality constraints
    # --------------------------------------------------------

    A_ub = []
    b_ub = []

    initial_energy = (
        battery.initial_energy_kwh
    )

    capacity = (
        battery.capacity_kwh
    )

    # Battery state:
    #
    # E_after[h] =
    # initial_energy + SUM(delta[0:h])
    #
    # Need:
    #
    # reserve[h] <= E_after[h] <= capacity
    #

    for hour in range(HOURS):

        cumulative_row = np.zeros(
            VARIABLE_COUNT,
            dtype=float,
        )

        for previous_hour in range(
            hour + 1
        ):

            cumulative_row[
                BATTERY_START + previous_hour
            ] = 1.0

        # E_after <= capacity
        #
        # initial + cumulative <= capacity
        #
        # cumulative <= capacity - initial
        #

        A_ub.append(
            cumulative_row.copy()
        )

        b_ub.append(
            capacity - initial_energy
        )

        # E_after >= reserve
        #
        # initial + cumulative >= reserve
        #
        # -cumulative <= initial - reserve
        #

        A_ub.append(
            -cumulative_row.copy()
        )

        b_ub.append(
            initial_energy - reserve[hour]
        )

    # --------------------------------------------------------
    # Solve
    # --------------------------------------------------------

    result = linprog(
        c=objective,
        A_ub=np.asarray(A_ub),
        b_ub=np.asarray(b_ub),
        A_eq=np.asarray(A_eq),
        b_eq=np.asarray(b_eq),
        bounds=bounds,
        method="highs",
    )

    if not result.success:

        raise RuntimeError(
            "Optimization failed: "
            f"{result.message}"
        )

    solution = result.x

    grid = solution[
        GRID_START:GRID_START + HOURS
    ]

    solar_used = solution[
        SOLAR_START:SOLAR_START + HOURS
    ]

    battery_delta = solution[
        BATTERY_START:BATTERY_START + HOURS
    ]

    # --------------------------------------------------------
    # Convert optimizer variables into challenge response
    # --------------------------------------------------------

    current_energy = (
        battery.initial_energy_kwh
    )

    hourly_plan = []

    for hour in range(HOURS):

        delta = float(
            battery_delta[hour]
        )

        # Avoid tiny floating-point artifacts.
        if abs(delta) < 1e-8:
            delta = 0.0

        if delta > 0:

            action = "charge"
            battery_kwh = delta

        elif delta < 0:

            action = "discharge"
            battery_kwh = -delta

        else:

            action = "idle"
            battery_kwh = 0.0

        current_energy += delta

        hourly_plan.append(
            {
                "hour": hour,
                "grid_kwh": float(
                    grid[hour]
                ),
                "solar_used_kwh": float(
                    solar_used[hour]
                ),
                "battery_action": action,
                "battery_kwh": float(
                    battery_kwh
                ),
                "battery_energy_after_kwh": float(
                    current_energy
                ),
            }
        )

    # --------------------------------------------------------
    # Recalculate totals from the actual plan
    # --------------------------------------------------------

    total_grid = sum(
        entry["grid_kwh"]
        for entry in hourly_plan
    )

    total_cost = sum(
        entry["grid_kwh"]
        * request.hours[entry["hour"]]
        .tariff_bdt_per_kwh
        for entry in hourly_plan
    )

    peak_grid = max(
        entry["grid_kwh"]
        for entry in hourly_plan
    )

    return OptimizationResult(
        hourly_plan=hourly_plan,
        total_grid_kwh=float(total_grid),
        total_cost_bdt=float(total_cost),
        peak_grid_kwh=float(peak_grid),
    )