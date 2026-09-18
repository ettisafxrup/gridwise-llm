from __future__ import annotations

from asyncio.log import logger
import json
import math
import re
from typing import Any

import requests

from .models import (
    Battery,
    BatteryReserveAdjustment,
    DirectiveInterpretation,
    GridWindowAdjustment,
    SolarReductionAdjustment,
    WindowAdjustment,
)


SYSTEM_PROMPT = """
You are an energy scheduling directive interpreter.

Return ONLY one valid JSON object.

The JSON object MUST have exactly one top-level key:

"directive_interpretation"

"directive_interpretation" must be an array containing exactly
one directive for every input operator note, in note_index order.

IMPORTANT: Every directive object MUST contain an "explanation" field.
"explanation" MUST always be a non-empty string.
Never omit the "explanation" field, including for "no_op".

{
  "note_index": integer,
  "applies": boolean,
  "directive_type": string,
  "structured_adjustment": object or null,
  "explanation": string
}

Allowed directive_type values:

- solar_reduction
- minimum_battery_reserve
- no_charge_window
- no_discharge_window
- max_grid_window
- no_op

Rules:

1. note_index starts at 0 and matches the input note index.

2. Return exactly one directive for every input note.

3. Return directives in note_index order.

4. For unrelated notes, use:
   "directive_type": "no_op"
   "applies": false
   "structured_adjustment": null

5. For every non-no_op directive:
   "applies": true
   "structured_adjustment" must contain the appropriate fields.

6. solar_reduction:
   {
     "hours": [integer hours],
     "factor": number from 0 to 1
   }

7. minimum_battery_reserve:
   {
     "hours": [integer hours],
     "minimum_energy_kwh": non-negative number
   }

8. no_charge_window:
   {
     "hours": [integer hours]
   }

9. no_discharge_window:
   {
     "hours": [integer hours]
   }

10. max_grid_window:
    {
      "hours": [integer hours],
      "max_grid_kwh": non-negative number
    }

11. Hours must be unique integers from 0 through 23.

12. Hours must be sorted in ascending order.

13. Time ranges are half-open.
    For example:
    "2 PM to 4 PM" means [14, 15].

14. Do not invent constraints.

15. Ignore unrelated notes by returning no_op.

16. Return JSON only.
17. Do not use markdown.
18. Do not put JSON inside ``` fences.
""".strip()


def _response_content(response: requests.Response) -> Any:
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("LLM returned a non-JSON response") from exc

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM response did not contain message content") from exc

    if isinstance(content, str):
        content = content.strip()
        if content.startswith("```"):
            content = content.removeprefix("```").removeprefix("json").strip()
            if content.endswith("```"):
                content = content[:-3].strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LLM returned invalid directive JSON") from exc

    return content

def _hour(value: str, meridiem: str | None) -> int:
    hour = int(value)
    if meridiem and meridiem.lower() == "pm" and hour != 12:
        hour += 12
    if meridiem and meridiem.lower() == "am" and hour == 12:
        hour = 0
    return hour


def _hours_from_note(note: str) -> list[int] | None:
    match = re.search(
        r"(?:from|between)\s+(\d{1,2})\s*(am|pm)?\s*(?:to|and|through|-)\s*"
        r"(\d{1,2})\s*(am|pm)?",
        note,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    start = _hour(match.group(1), match.group(2) or match.group(4))
    end = _hour(match.group(3), match.group(4) or match.group(2))
    if start > end or end > 24:
        return None
    return list(range(start, end))


def _interpret_locally(notes: list[str]) -> list[DirectiveInterpretation]:
    directives = []
    for note_index, note in enumerate(notes):
        text = note.lower()
        hours = _hours_from_note(text)
        directive_type = "no_op"
        adjustment = None

        if "solar" in text and ("drop" in text or "reduc" in text):
            percent = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            factor = float(percent.group(1)) / 100 if percent else 0.0
            if hours is not None:
                directive_type = "solar_reduction"
                adjustment = SolarReductionAdjustment(
                    hours=hours,
                    factor=factor,
                )
        elif "do not charge" in text or "no charge" in text or "charging" in text and "unavailable" in text:
            if hours is not None:
                directive_type = "no_charge_window"
                adjustment = WindowAdjustment(hours=hours)
        elif "do not discharge" in text or "no discharge" in text or "discharging" in text and "unavailable" in text:
            if hours is not None:
                directive_type = "no_discharge_window"
                adjustment = WindowAdjustment(hours=hours)
        else:
            reserve = re.search(r"(?:reserve|minimum)[^\d]*(\d+(?:\.\d+)?)\s*kwh", text)
            grid_cap = re.search(r"(?:cap|max(?:imum)?)[^\d]*(\d+(?:\.\d+)?)\s*kwh", text)
            if hours is not None and reserve:
                directive_type = "minimum_battery_reserve"
                adjustment = BatteryReserveAdjustment(
                    hours=hours,
                    minimum_energy_kwh=float(reserve.group(1)),
                )
            elif hours is not None and grid_cap:
                directive_type = "max_grid_window"
                adjustment = GridWindowAdjustment(
                    hours=hours,
                    max_grid_kwh=float(grid_cap.group(1)),
                )

        applies = directive_type != "no_op"
        directives.append(
            DirectiveInterpretation(
                note_index=note_index,
                applies=applies,
                directive_type=directive_type,
                structured_adjustment=adjustment,
                explanation=(
                    "Local rule-based interpretation."
                    if applies
                    else "No supported energy directive detected."
                ),
            )
        )

    return directives


def interpret_operator_notes(
    notes: list[str],
    settings: Any,
) -> list[DirectiveInterpretation]:
    """Interpret notes locally or through the configured provider."""

    user_payload = json.dumps(
        {"operator_notes": notes},
        ensure_ascii=True,
    )

    try:
        
        response = requests.post(
        settings.llm_api_url,
        headers={
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
        },
        json={
        "model": settings.llm_model,
        "temperature": 0,
        "max_tokens": settings.llm_max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_payload,
            },
        ],
        },
        timeout=settings.request_timeout_seconds,
        )

       
        
        response.raise_for_status()
    except requests.RequestException as exc:
        if exc.response is not None:
            logger.error(
            "LLM API error: status=%s body=%s",
            exc.response.status_code,
            exc.response.text,
        )

        raise RuntimeError(
        f"LLM request failed: {exc}"
        ) from exc


    content = _response_content(response)
    if not isinstance(content, dict):
        raise RuntimeError("LLM response must be a JSON object")

    raw_directives = content.get("directive_interpretation")
    if not isinstance(raw_directives, list):
        raise RuntimeError("LLM response missing directive_interpretation")

    try:
        return [
            DirectiveInterpretation.model_validate(item)
            for item in raw_directives
        ]
    except (TypeError, ValueError) as exc:
        logger.exception(
        "Invalid directive returned by LLM. Raw directives: %r",
        raw_directives,
    )

        raise RuntimeError(
        f"LLM returned invalid structured directives: {exc}"
        ) from exc



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

    if len(directives) != len(notes):
        raise ValueError(
            "There must be exactly one directive "
            "interpretation for every operator note"
        )

    expected_indices = list(range(len(notes)))

    actual_indices = [
        directive.note_index
        for directive in directives
    ]

    if actual_indices != expected_indices:
        raise ValueError(
            "directive_interpretation must be ordered "
            "by note_index 0..N-1"
        )

    if len(actual_indices) != len(set(actual_indices)):
        raise ValueError(
            "Duplicate note_index detected"
        )

    for directive in directives:
        validate_directive_semantics(
            directive,
            notes,
            battery,
        )