from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ============================================================
# Basic aliases
# ============================================================

NonNegativeFloat = Annotated[
    float,
    Field(ge=0)
]


# ============================================================
# Hourly scenario
# ============================================================

class HourEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hour: int
    demand_kwh: NonNegativeFloat
    solar_kwh: NonNegativeFloat
    tariff_bdt_per_kwh: NonNegativeFloat

    @field_validator("hour")
    @classmethod
    def validate_hour(cls, value: int) -> int:
        if value < 0 or value > 23:
            raise ValueError("hour must be between 0 and 23")

        return value


# ============================================================
# Battery
# ============================================================

class Battery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capacity_kwh: NonNegativeFloat
    initial_energy_kwh: NonNegativeFloat
    minimum_energy_kwh: NonNegativeFloat
    max_charge_kwh_per_hour: NonNegativeFloat
    max_discharge_kwh_per_hour: NonNegativeFloat

    @field_validator("capacity_kwh")
    @classmethod
    def validate_capacity(cls, value: float) -> float:
        if value <= 0:
            raise ValueError(
                "capacity_kwh must be greater than zero"
            )

        return value

    @field_validator("initial_energy_kwh")
    @classmethod
    def validate_initial_energy(cls, value: float) -> float:
        if value < 0:
            raise ValueError(
                "initial_energy_kwh cannot be negative"
            )

        return value


# ============================================================
# Request
# ============================================================

class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    operator_notes: list[str] = Field(min_length=1, max_length=3)
    hours: list[HourEntry]
    battery: Battery

    @field_validator("scenario_id")
    @classmethod
    def validate_scenario_id(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "scenario_id cannot be empty"
            )

        return value

    @field_validator("operator_notes")
    @classmethod
    def validate_notes(cls, value: list[str]) -> list[str]:

        cleaned = []

        for note in value:
            if not isinstance(note, str):
                raise ValueError(
                    "Every operator note must be a string"
                )

            note = note.strip()

            if not note:
                raise ValueError(
                    "Operator notes cannot be empty"
                )

            cleaned.append(note)

        return cleaned

    @field_validator("hours")
    @classmethod
    def validate_hours(
        cls,
        value: list[HourEntry]
    ) -> list[HourEntry]:

        if len(value) != 24:
            raise ValueError(
                "hours must contain exactly 24 entries"
            )

        actual_hours = [
            entry.hour
            for entry in value
        ]

        expected_hours = list(range(24))

        if actual_hours != expected_hours:
            raise ValueError(
                "hours must contain exactly 0 through 23 "
                "in ascending order"
            )

        return value

    @field_validator("battery")
    @classmethod
    def validate_battery(
        cls,
        battery: Battery
    ) -> Battery:

        if battery.initial_energy_kwh > battery.capacity_kwh:
            raise ValueError(
                "initial_energy_kwh cannot exceed capacity_kwh"
            )

        if battery.minimum_energy_kwh > battery.capacity_kwh:
            raise ValueError(
                "minimum_energy_kwh cannot exceed capacity_kwh"
            )

        if battery.minimum_energy_kwh > battery.initial_energy_kwh:
            raise ValueError(
                "initial energy must satisfy the base minimum reserve"
            )

        return battery


# ============================================================
# Directive types
# ============================================================

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


# ============================================================
# Directive adjustment structures
# ============================================================

class SolarReductionAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: list[int]
    factor: float


class BatteryReserveAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: list[int]
    minimum_energy_kwh: NonNegativeFloat


class WindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: list[int]


class GridWindowAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hours: list[int]
    max_grid_kwh: NonNegativeFloat


# ============================================================
# LLM directive interpretation
# ============================================================

class DirectiveInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note_index: int
    applies: bool
    directive_type: DirectiveType

    structured_adjustment: (
        SolarReductionAdjustment
        | BatteryReserveAdjustment
        | WindowAdjustment
        | GridWindowAdjustment
        | None
    )

    explanation: str = ""

    @field_validator("note_index")
    @classmethod
    def validate_note_index(
        cls,
        value: int
    ) -> int:

        if value < 0:
            raise ValueError(
                "note_index cannot be negative"
            )

        return value


# ============================================================
# Hourly plan
# ============================================================

BatteryAction = Literal[
    "charge",
    "discharge",
    "idle"
]


class HourlyPlanEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hour: int
    grid_kwh: NonNegativeFloat
    solar_used_kwh: NonNegativeFloat
    battery_action: BatteryAction
    battery_kwh: NonNegativeFloat
    battery_energy_after_kwh: NonNegativeFloat


# ============================================================
# Final response
# ============================================================

class OptimizeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str

    directive_interpretation: list[
        DirectiveInterpretation
    ]

    hourly_plan: list[
        HourlyPlanEntry
    ]

    total_grid_kwh: NonNegativeFloat
    total_cost_bdt: NonNegativeFloat
    peak_grid_kwh: NonNegativeFloat

    plan_summary: str