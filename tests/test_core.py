import json
from pathlib import Path

import pytest

from app.directives import validate_all_directives
from app.models import (
    BatteryReserveAdjustment,
    DirectiveInterpretation,
    GridWindowAdjustment,
    OptimizeRequest,
    SolarReductionAdjustment,
    WindowAdjustment,
)
from app.optimizer import optimize
from app.validator import (
    validate_hourly_plan,
)


ROOT = Path(__file__).resolve().parent


def load_request():

    with open(
        ROOT / "sample_request.json",
        "r",
        encoding="utf-8",
    ) as file:

        data = json.load(file)

    return OptimizeRequest.model_validate(
        data
    )


def test_request_schema():

    request = load_request()

    assert request.scenario_id == "GRID-101"
    assert len(request.operator_notes) == 3
    assert len(request.hours) == 24
    assert [h.hour for h in request.hours] == list(
        range(24)
    )


def test_directive_validation():

    request = load_request()

    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment=SolarReductionAdjustment(
                hours=[13, 14],
                factor=0.2,
            ),
            explanation="Solar availability is reduced.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment=WindowAdjustment(
                hours=[14, 15],
            ),
            explanation="Charging is unavailable.",
        ),
        DirectiveInterpretation(
            note_index=2,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="The note is irrelevant.",
        ),
    ]

    validate_all_directives(
        directives,
        request.operator_notes,
        request.battery,
    )


def test_optimizer_with_directives():

    request = load_request()

    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="solar_reduction",
            structured_adjustment=SolarReductionAdjustment(
                hours=[13, 14],
                factor=0.2,
            ),
            explanation="Solar reduced.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment=WindowAdjustment(
                hours=[14, 15],
            ),
            explanation="No charging.",
        ),
        DirectiveInterpretation(
            note_index=2,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="The note is unrelated.",
        ),
    ]

    validate_all_directives(
        directives,
        request.operator_notes,
        request.battery,
    )

    result = optimize(
        request,
        directives,
    )

    assert len(result.hourly_plan) == 24

    validate_hourly_plan(
        request,
        directives,
        result.hourly_plan,
    )


def test_no_charge_window():

    request = load_request()

    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_charge_window",
            structured_adjustment=WindowAdjustment(
                hours=[10, 11, 12],
            ),
            explanation="Charging is unavailable.",
        ),
    ]

    result = optimize(
        request,
        directives,
    )

    for hour in [10, 11, 12]:

        entry = result.hourly_plan[hour]

        assert entry["battery_action"] != "charge"

    validate_hourly_plan(
        request,
        directives,
        result.hourly_plan,
    )


def test_no_discharge_window():

    request = load_request()

    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="no_discharge_window",
            structured_adjustment=WindowAdjustment(
                hours=[18, 19, 20],
            ),
            explanation="Discharging is unavailable.",
        ),
    ]

    result = optimize(
        request,
        directives,
    )

    for hour in [18, 19, 20]:

        entry = result.hourly_plan[hour]

        assert entry["battery_action"] != "discharge"

    validate_hourly_plan(
        request,
        directives,
        result.hourly_plan,
    )


def test_battery_reserve():

    request = load_request()

    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="minimum_battery_reserve",
            structured_adjustment=BatteryReserveAdjustment(
                hours=[18, 19, 20],
                minimum_energy_kwh=120,
            ),
            explanation="Reserve requirement.",
        ),
    ]

    result = optimize(
        request,
        directives,
    )

    for hour in [18, 19, 20]:

        energy = result.hourly_plan[hour][
            "battery_energy_after_kwh"
        ]

        assert energy >= 120 - 0.01

    validate_hourly_plan(
        request,
        directives,
        result.hourly_plan,
    )


def test_grid_cap():

    request = load_request()

    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=True,
            directive_type="max_grid_window",
            structured_adjustment=GridWindowAdjustment(
                hours=[18, 19, 20],
                max_grid_kwh=180,
            ),
            explanation="Grid import is capped.",
        ),
    ]

    result = optimize(
        request,
        directives,
    )

    for hour in [18, 19, 20]:

        grid = result.hourly_plan[hour][
            "grid_kwh"
        ]

        assert grid <= 180.01

    validate_hourly_plan(
        request,
        directives,
        result.hourly_plan,
    )


def test_no_op():

    request = load_request()

    directives = [
        DirectiveInterpretation(
            note_index=0,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Irrelevant note.",
        ),
        DirectiveInterpretation(
            note_index=1,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Irrelevant note.",
        ),
        DirectiveInterpretation(
            note_index=2,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Irrelevant note.",
        ),
    ]

    validate_all_directives(
        directives,
        request.operator_notes,
        request.battery,
    )

    result = optimize(
        request,
        directives,
    )

    validate_hourly_plan(
        request,
        directives,
        result.hourly_plan
    )