from __future__ import annotations

from decimal import Decimal
from typing import Any


def decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None

    text = format(value, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def decimal_places(value: Decimal) -> int:
    normalized = value.normalize()

    if normalized == 0:
        return 0

    return max(
        0,
        -normalized.as_tuple().exponent,
    )


def price_type_name(price_type: int) -> str:
    return (
        "arithmetic"
        if price_type == 0
        else "geometric"
    )


def build_spot_grid_payload(
    *,
    market: str,
    money: Decimal,
    low_price: Decimal,
    high_price: Decimal,
    grid_num: int,
    price_type: int,
    trigger_price: Decimal | None = None,
    stop_profit: Decimal | None = None,
    stop_loss: Decimal | None = None,
) -> dict[str, Any]:
    create_params: dict[str, Any] = {
        "money": decimal_text(money),
        "low_price": decimal_text(low_price),
        "high_price": decimal_text(high_price),
        "grid_num": grid_num,
        "price_type": price_type,

        # Phase 1 is quote-currency investment only.
        "is_use_base": False,
    }

    optional = {
        "trigger_price": trigger_price,
        "stop_profit": stop_profit,
        "stop_loss": stop_loss,
    }

    for key, value in optional.items():
        if value is not None:
            create_params[key] = decimal_text(value)

    return {
        "strategy_type": "spot_grid",
        "market": market.upper(),
        "create_params": create_params,
    }


def validate_spot_grid(
    *,
    money: Decimal,
    low_price: Decimal,
    high_price: Decimal,
    grid_num: int,
    price_type: int,
    price_precision: int,
    trade_status: str,
    min_quote_amount: Decimal | None,
    available_quote: Decimal,
    current_price: Decimal | None,
    trigger_price: Decimal | None = None,
    stop_profit: Decimal | None = None,
    stop_loss: Decimal | None = None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    if money <= 0:
        errors.append(
            "Investment amount must be greater than zero."
        )

    if low_price <= 0:
        errors.append(
            "Lower price must be greater than zero."
        )

    if high_price <= low_price:
        errors.append(
            "Upper price must be greater than lower price."
        )

    if grid_num < 1:
        errors.append(
            "Grid count must be at least 1."
        )

    if price_type not in (0, 1):
        errors.append(
            "price_type must be 0 (arithmetic) "
            "or 1 (geometric)."
        )

    if trade_status != "tradable":
        errors.append(
            f"Market is not fully tradable "
            f"(Gate status: {trade_status})."
        )

    if money > available_quote:
        errors.append(
            "Investment exceeds available quote balance."
        )

    if (
        min_quote_amount is not None
        and money < min_quote_amount
    ):
        errors.append(
            "Investment is below Gate's minimum "
            "quote trade amount."
        )

    price_values = {
        "low_price": low_price,
        "high_price": high_price,
        "trigger_price": trigger_price,
        "stop_profit": stop_profit,
        "stop_loss": stop_loss,
    }

    for name, value in price_values.items():
        if value is None:
            continue

        if decimal_places(value) > price_precision:
            errors.append(
                f"{name} has more than "
                f"{price_precision} decimal places."
            )

    tick_size = Decimal(1).scaleb(
        -price_precision
    )

    arithmetic_step: Decimal | None = None
    geometric_step_pct: Decimal | None = None

    if (
        high_price > low_price
        and grid_num > 0
    ):
        arithmetic_step = (
            high_price - low_price
        ) / Decimal(grid_num)

        if price_type == 0:
            if arithmetic_step < tick_size:
                errors.append(
                    "Arithmetic grid spacing is smaller "
                    "than the market price tick size."
                )

        else:
            # This is informational only. Float is used
            # for a fractional exponent, not for Gate
            # order values.
            ratio = (
                float(high_price / low_price)
                ** (1.0 / grid_num)
            )

            geometric_step_pct = Decimal(
                str((ratio - 1.0) * 100.0)
            )

            first_step = (
                float(low_price) * ratio
                - float(low_price)
            )

            if first_step < float(tick_size):
                errors.append(
                    "Geometric grid spacing near the "
                    "lower bound is smaller than the "
                    "market price tick size."
                )

    if current_price is not None:
        if current_price < low_price:
            warnings.append(
                "Current market price is below the "
                "configured grid range."
            )

        elif current_price > high_price:
            warnings.append(
                "Current market price is above the "
                "configured grid range."
            )

    else:
        warnings.append(
            "Gate did not return a current ticker price."
        )

    approx_quote_per_grid = (
        money / Decimal(grid_num)
        if grid_num > 0
        else None
    )

    if (
        min_quote_amount is not None
        and approx_quote_per_grid is not None
        and approx_quote_per_grid
        < min_quote_amount
    ):
        warnings.append(
            "Investment divided by grid count is below "
            "the pair's minimum quote trade amount. "
            "Gate bot allocation is more complex than "
            "a simple division, so the final Gate "
            "validation may still differ."
        )

    math = {
        "price_type": price_type_name(
            price_type
        ),
        "tick_size": decimal_text(
            tick_size
        ),
        "arithmetic_price_step": (
            decimal_text(arithmetic_step)
            if arithmetic_step is not None
            else None
        ),
        "geometric_step_pct": (
            decimal_text(
                geometric_step_pct
            )
            if geometric_step_pct is not None
            else None
        ),
        "approx_quote_per_grid": (
            decimal_text(
                approx_quote_per_grid
            )
            if approx_quote_per_grid is not None
            else None
        ),
    }

    return errors, warnings, math
