
from __future__ import annotations

import logging

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .directives import validate_all_directives
from .llm import interpret_operator_notes
from .models import (
    OptimizeRequest,
    OptimizeResponse,
)
from .optimizer import optimize
from .validator import (
    calculate_totals,
    validate_hourly_plan,
    validate_reported_totals,
)


logging.basicConfig(
    level=logging.INFO,
)

logger = logging.getLogger(
    "gridwise"
)


app = FastAPI(
    title="GridWise Energy Optimizer",
    version="1.0.0",
    description=(
        "LLM-assisted smart-campus energy "
        "optimization API."
    ),
)


@app.get("/health")
def health():
    """
    Required readiness endpoint.

    The challenge requires HTTP 200 with:
        {"status": "ok"}
    """

    return {
        "status": "ok"
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
):
    """
    Controlled internal error handler.

    Never expose raw stack traces, API keys,
    provider responses, or other secrets.
    """

    logger.exception(
        "Unhandled internal error"
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error"
        },
    )


@app.post(
    "/optimize-energy",
    response_model=OptimizeResponse,
)
def optimize_energy(
    request: OptimizeRequest,
):

    # --------------------------------------------------------
    # Load configuration
    # --------------------------------------------------------

    try:

        settings = get_settings()

    except RuntimeError as exc:

        logger.error(
            "Configuration error"
        )

        raise HTTPException(
            status_code=500,
            detail="Service configuration error",
        ) from exc

    # --------------------------------------------------------
    # LLM interpretation
    # --------------------------------------------------------

    try:

        directives = interpret_operator_notes(
            request.operator_notes,
            settings,
        )

    except Exception as exc:

        logger.exception(
        "Operator-note interpretation failed"
    )

        raise HTTPException(
        status_code=500,
        detail=str(exc),
            ) from exc

        

    # --------------------------------------------------------
    # Deterministic guardrails
    # --------------------------------------------------------

    try:

        validate_all_directives(
            directives,
            request.operator_notes,
            request.battery,
        )

    except ValueError as exc:
        
        logger.error(
            "LLM directive validation failed"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "LLM returned invalid "
                "structured directives"
                f"${exc}"
            ),
        ) from exc

    # --------------------------------------------------------
    # Select applicable directives
    # --------------------------------------------------------

    applicable_directives = [
        directive
        for directive in directives
        if directive.applies
    ]

    # --------------------------------------------------------
    # Optimization
    # --------------------------------------------------------

    try:

        result = optimize(
            request,
            applicable_directives,
        )

    except Exception as exc:

        logger.error(
            "Optimization failed"
        )

        raise HTTPException(
            status_code=500,
            detail="Optimization failed safely",
        ) from exc

    # --------------------------------------------------------
    # Replay validation
    # --------------------------------------------------------

    try:

        validate_hourly_plan(
            request,
            applicable_directives,
            result.hourly_plan,
        )

    except ValueError as exc:

        logger.error(
            "Generated plan failed replay validation"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Generated optimization plan "
                "failed validation"
            ),
        ) from exc

    # --------------------------------------------------------
    # Recalculate totals independently
    # --------------------------------------------------------

    (
        total_grid,
        total_cost,
        peak_grid,
    ) = calculate_totals(
        request,
        result.hourly_plan,
    )

    # --------------------------------------------------------
    # Human-readable summary
    #
    # No second LLM call needed.
    # --------------------------------------------------------

    active_types = [
        directive.directive_type
        for directive in directives
        if directive.applies
    ]

    if active_types:

        directive_text = ", ".join(
            active_types
        )

        summary = (
            "The 24-hour schedule applies the "
            f"operator directives ({directive_text}) "
            "and minimizes grid electricity cost "
            "while satisfying the battery, solar, "
            "grid, and energy-balance constraints."
        )

    else:

        summary = (
            "No applicable operator energy directives "
            "were identified. The schedule minimizes "
            "grid electricity cost while satisfying "
            "the standard battery, solar, and "
            "energy-balance constraints."
        )

    response = OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=result.hourly_plan,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        plan_summary=summary,
    )

    # Final total consistency check.
    validate_reported_totals(
        request,
        result.hourly_plan,
        response.total_grid_kwh,
        response.total_cost_bdt,
        response.peak_grid_kwh,
    )

    return response