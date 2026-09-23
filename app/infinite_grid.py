from __future__ import annotations

from decimal import Decimal
from typing import Any

from .spot_grid import (
    decimal_places,
    decimal_text,
)


# Gate documents Infinite Grid profit-per-grid in percentage
# terms as strictly greater than 0.4% and strictly less
# than 100%. The API payload uses a ratio, so those limits
# are represented here as 0.004 and 1 respectively.
GATE_MIN_PROFIT_PER_GRID = Decimal("0.004")
GATE_MAX_PROFIT_PER_GRID = Decimal("1")


def build_infinite_grid_payload(
    *,
    market: str,
    money: Decimal,
    price_floor: Decimal,
    profit_per_grid: Decimal,
    grid_num: int | None = None,
    price_type: int | None = None,
    trigger_price: Decimal | None = None,
    stop_profit: Decimal | None = None,
    stop_loss: Decimal | None = None,
    profit_sharing_ratio: Decimal | None = None,
    is_use_base: bool | None = None,
) -> dict[str, Any]:
    """Build Gate's native Infinity Grid creation payload.

    Required vs optional fields intentionally follow Gate's
    documented bot API contract. Optional fields are omitted
    when the caller does not explicitly provide them so Gate's
    server-side defaults remain authoritative.
    """

    create_params: dict[str, Any] = {
        "money": decimal_text(money),
        "price_floor": decimal_text(
            price_floor
        ),
        "profit_per_grid": decimal_text(
            profit_per_grid
        ),
    }

    optional_decimal = {
        "trigger_price": trigger_price,
        "stop_profit": stop_profit,
        "stop_loss": stop_loss,
        "profit_sharing_ratio":
            profit_sharing_ratio,
    }

    if grid_num is not None:
        create_params[
            "grid_num"
        ] = grid_num

    if price_type is not None:
        create_params[
            "price_type"
        ] = price_type

    for key, value in (
        optional_decimal.items()
    ):
        if value is not None:
            create_params[key] = (
                decimal_text(
                    value
                )
            )

    if is_use_base is not None:
        create_params[
            "is_use_base"
        ] = is_use_base

    return {
        "strategy_type":
            "infinite_grid",
        "market":
            market.upper(),
        "create_params":
            create_params,
    }


def validate_infinite_grid(
    *,
    money: Decimal,
    price_floor: Decimal,
    profit_per_grid: Decimal,
    price_precision: int,
    trade_status: str,
    min_quote_amount: Decimal | None,
    available_quote: Decimal,
    current_price: Decimal | None,
    grid_num: int | None = None,
    price_type: int | None = None,
    trigger_price: Decimal | None = None,
    stop_profit: Decimal | None = None,
    stop_loss: Decimal | None = None,
) -> tuple[
    list[str],
    list[str],
    dict[str, Any],
]:
    """Perform locally-supported Infinity Grid checks.

    Enforce constraints Gate currently documents for Infinite
    Grid and avoid inventing unpublished limits. In particular,
    no undocumented maximum grid count is imposed here.
    """

    errors: list[str] = []
    warnings: list[str] = []

    if money <= 0:
        errors.append(
            "Investment amount must be greater than zero."
        )

    if price_floor <= 0:
        errors.append(
            "Price floor must be greater than zero."
        )

    if (
        profit_per_grid
        <= GATE_MIN_PROFIT_PER_GRID
    ):
        errors.append(
            "Profit per grid must be greater than "
            "0.4% (Gate documented limit)."
        )

    if (
        profit_per_grid
        >= GATE_MAX_PROFIT_PER_GRID
    ):
        errors.append(
            "Profit per grid must be less than "
            "100% (Gate documented limit)."
        )

    if (
        grid_num is not None
        and grid_num < 1
    ):
        errors.append(
            "Grid count must be at least 1 when provided."
        )

    if (
        price_type is not None
        and price_type not in (
            0,
            1,
        )
    ):
        errors.append(
            "price_type must be 0 (arithmetic), "
            "1 (geometric), or omitted."
        )

    if trade_status != "tradable":
        errors.append(
            "Market is not fully tradable "
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
        "price_floor":
            price_floor,
        "trigger_price":
            trigger_price,
        "stop_profit":
            stop_profit,
        "stop_loss":
            stop_loss,
    }

    for name, value in (
        price_values.items()
    ):
        if value is None:
            continue

        if (
            decimal_places(
                value
            )
            > price_precision
        ):
            errors.append(
                f"{name} has more than "
                f"{price_precision} decimal places."
            )

    if (
        trigger_price is not None
        and current_price is None
    ):
        errors.append(
            "Current market price is unavailable, so "
            "the trigger price cannot be validated."
        )

    if (
        trigger_price is not None
        and current_price is not None
        and trigger_price >= current_price
    ):
        errors.append(
            "Trigger price must be below the current "
            "market price (Gate documented limit)."
        )

    if (
        current_price is not None
        and price_floor
        >= current_price
    ):
        warnings.append(
            "The configured price floor is at or above "
            "the current market price. Gate remains "
            "authoritative for whether this setup can "
            "be created."
        )

    math: dict[str, Any] = {
        "strategy_type":
            "infinite_grid",
        "price_floor":
            decimal_text(
                price_floor
            ),
        "profit_per_grid":
            decimal_text(
                profit_per_grid
            ),
        "grid_num":
            grid_num,
        "price_type": (
            "arithmetic"
            if price_type == 0
            else (
                "geometric"
                if price_type == 1
                else None
            )
        ),
        "has_fixed_upper_bound":
            False,
        "current_price":
            decimal_text(
                current_price
            ),
    }

    return (
        errors,
        warnings,
        math,
    )
