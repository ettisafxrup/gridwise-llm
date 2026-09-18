from __future__ import annotations

import math

from .models import (
    Battery,
    BatteryReserveAdjustment,
    DirectiveInterpretation,
    GridWindowAdjustment,
    SolarReductionAdjustment,
    WindowAdjustment,
)


VALID_DIRECTIVE_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}


def validate_hours(
    hours: list[int]
) -> None:

    if len(hours) != len(set(hours)):
        raise ValueError(
            "Directive hours must be unique"
        )

    if any(
        not isinstance(hour, int)
        for hour in hours
    ):
        raise ValueError(
            "Directive hours must be integers"
        )

    if any(
        hour < 0 or hour > 23
        for hour in hours
    ):
        raise ValueError(
            "Directive hours must be between 0 and 23"
        )

    if hours != sorted(hours):
        raise ValueError(
            "Directive hours must be in ascending order"
        )


def validate_finite(
    value: float,
    field_name: str
) -> None:

    if not math.isfinite(value):
        raise ValueError(
            f"{field_name} must be finite"
        )


def validate_directive_semantics(
    directive: DirectiveInterpretation,
    notes: list[str],
    battery: Battery,
) -> None:

    # --------------------------------------------------------
    # note_index
    # --------------------------------------------------------

    if directive.note_index < 0:
        raise ValueError(
            "note_index cannot be negative"
        )

    if directive.note_index >= len(notes):
        raise ValueError(
            "note_index refers to a non-existent note"
        )

    # --------------------------------------------------------
    # directive type
    # --------------------------------------------------------

    if directive.directive_type not in VALID_DIRECTIVE_TYPES:
        raise ValueError(
            "Unsupported directive_type"
        )

    # --------------------------------------------------------
    # no_op
    # --------------------------------------------------------

    if directive.directive_type == "no_op":

        if directive.applies is not False:
            raise ValueError(
                "no_op must use applies=false"
            )

        if directive.structured_adjustment is not None:
            raise ValueError(
                "no_op must use structured_adjustment=null"
            )

        return

    # --------------------------------------------------------
    # All non-no_op directives must apply
    # --------------------------------------------------------

    if directive.applies is not True:
        raise ValueError(
            "All non-no_op directives must use applies=true"
        )

    adjustment = directive.structured_adjustment

    if adjustment is None:
        raise ValueError(
            "Non-no_op directives require structured_adjustment"
        )

    # --------------------------------------------------------
    # Solar reduction
    # --------------------------------------------------------

    if directive.directive_type == "solar_reduction":

        if not isinstance(
            adjustment,
            SolarReductionAdjustment
        ):
            raise ValueError(
                "solar_reduction has invalid adjustment shape"
            )

        validate_hours(adjustment.hours)

        validate_finite(
            adjustment.factor,
            "solar_reduction.factor"
        )

        if not 0 <= adjustment.factor <= 1:
            raise ValueError(
                "solar_reduction.factor must be between 0 and 1"
            )

        return

    # --------------------------------------------------------
    # Minimum battery reserve
    # --------------------------------------------------------

    if (
        directive.directive_type
        == "minimum_battery_reserve"
    ):

        if not isinstance(
            adjustment,
            BatteryReserveAdjustment
        ):
            raise ValueError(
                "minimum_battery_reserve has invalid adjustment shape"
            )

        validate_hours(adjustment.hours)

        validate_finite(
            adjustment.minimum_energy_kwh,
            "minimum_energy_kwh"
        )

        if adjustment.minimum_energy_kwh < 0:
            raise ValueError(
                "minimum_energy_kwh cannot be negative"
            )

        if (
            adjustment.minimum_energy_kwh
            > battery.capacity_kwh
        ):
            raise ValueError(
                "minimum_energy_kwh cannot exceed battery capacity"
            )

        return

    # --------------------------------------------------------
    # No charge
    # --------------------------------------------------------

    if directive.directive_type == "no_charge_window":

        if not isinstance(
            adjustment,
            WindowAdjustment
        ):
            raise ValueError(
                "no_charge_window has invalid adjustment shape"
            )

        validate_hours(adjustment.hours)

        return

    # --------------------------------------------------------
    # No discharge
    # --------------------------------------------------------

    if (
        directive.directive_type
        == "no_discharge_window"
    ):

        if not isinstance(
            adjustment,
            WindowAdjustment
        ):
            raise ValueError(
                "no_discharge_window has invalid adjustment shape"
            )

        validate_hours(adjustment.hours)

        return

    # --------------------------------------------------------
    # Max grid
    # --------------------------------------------------------

    if directive.directive_type == "max_grid_window":

        if not isinstance(
            adjustment,
            GridWindowAdjustment
        ):
            raise ValueError(
                "max_grid_window has invalid adjustment shape"
            )

        validate_hours(adjustment.hours)

        validate_finite(
            adjustment.max_grid_kwh,
            "max_grid_kwh"
        )

        if adjustment.max_grid_kwh < 0:
            raise ValueError(
                "max_grid_kwh cannot be negative"
            )

        return


def validate_all_directives(
    directives: list[DirectiveInterpretation],
    notes: list[str],
    battery: Battery,
) -> None:

    for directive in directives:
        validate_directive_semantics(
            directive,
            notes,
            battery,
        )