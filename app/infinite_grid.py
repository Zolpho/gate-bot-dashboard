from __future__ import annotations

from decimal import (
    Decimal,
    ROUND_CEILING,
    ROUND_HALF_UP,
)
from math import (
    ceil,
    log,
    log1p,
)
import re
from typing import (
    Any,
    Mapping,
)

from .spot_grid import (
    decimal_places,
    decimal_text,
)


# Gate's live Infinite Grid UI currently accepts 0.2%
# as the minimum ROI per grid. The API payload represents
# percentages as ratios, so 0.2% is 0.002.
#
# Keep the existing fail-closed upper bound until separate
# live evidence supports changing it.
GATE_MIN_PROFIT_PER_GRID = Decimal("0.002")
GATE_MAX_PROFIT_PER_GRID = Decimal("1")


# EQTY/USDT empirical minimum-investment calibration.
#
# These constants are intentionally market-specific.
# They were fitted against Gate native Infinite Grid
# minimums observed on 2026-10-01 for ROI values from
# 0.2% through 3% and multiple lower price limits.
#
# R in this model is expressed in percentage points:
# R=1 means 1%, R=0.5 means 0.5%.
_EQTY_USDT_MINIMUM_A = Decimal(
    "84.82244465"
)
_EQTY_USDT_MINIMUM_B = Decimal(
    "29.89204933"
)
_EQTY_USDT_MINIMUM_C = Decimal(
    "5.23302279"
)

_MINIMUM_INVESTMENT_PATTERN = re.compile(
    r"invest money\."
    r"(?P<requested>[0-9]+(?:\.[0-9]+)?)"
    r"\s*<\s*"
    r"min invest money\."
    r"(?P<minimum>[0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


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



def estimate_infinite_grid_requirements(
    *,
    market: str,
    current_price: Decimal | None,
    price_floor: Decimal,
    profit_per_grid: Decimal,
) -> dict[str, Any]:
    """Estimate Gate-native Infinite Grid requirements.

    The implicit level count follows the geometric ladder
    visible in Gate's native Infinity UI.

    Minimum-investment calibration is intentionally limited
    to EQTY/USDT until other markets have independent evidence.
    """

    normalized_market = (
        str(
            market
            or ""
        )
        .strip()
        .upper()
    )

    result: dict[str, Any] = {
        "model":
            "native_geometric_v1",
        "market":
            normalized_market,
        "calibrated":
            False,
        "calibration_market":
            (
                "EQTY_USDT"
                if normalized_market
                == "EQTY_USDT"
                else None
            ),
        "calibration_roi_percent_min":
            "0.2",
        "calibration_roi_percent_max":
            "3",
        "estimated_levels_to_floor":
            None,
        "estimated_maintain_market_value":
            None,
        "estimated_gate_minimum":
            None,
        "recommended_minimum":
            None,
        "safety_policy":
            None,
        "observed_fit_error_bound_pct":
            None,
    }

    if (
        current_price is None
        or current_price <= 0
        or price_floor <= 0
        or profit_per_grid <= 0
        or price_floor >= current_price
    ):
        return result

    price_ratio = float(
        current_price
        / price_floor
    )

    step_ratio = float(
        profit_per_grid
    )

    levels = max(
        1,
        int(
            ceil(
                log(
                    price_ratio
                )
                / log1p(
                    step_ratio
                )
            )
        ),
    )

    result[
        "estimated_levels_to_floor"
    ] = levels

    roi_percent = (
        profit_per_grid
        * Decimal("100")
    )

    if roi_percent <= 0:
        return result

    calibrated = (
        normalized_market
        == "EQTY_USDT"
        and roi_percent
        >= Decimal("0.2")
        and roi_percent
        <= Decimal("3")
    )

    result[
        "calibrated"
    ] = calibrated

    if not calibrated:
        return result

    result[
        "safety_policy"
    ] = (
        "ceil(estimate + "
        "max(5 quote, 3% of estimate))"
    )

    result[
        "observed_fit_error_bound_pct"
    ] = "3"

    maintain_value = (
        _EQTY_USDT_MINIMUM_A
        / roi_percent
        + _EQTY_USDT_MINIMUM_B
        / (
            roi_percent
            * roi_percent
        )
        + _EQTY_USDT_MINIMUM_C
    )

    floor_factor = Decimal(
        str(
            1
            + log(
                price_ratio
            )
        )
    )

    estimated = (
        maintain_value
        * floor_factor
    ).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )

    maintain_value = (
        maintain_value.quantize(
            Decimal("0.000001"),
            rounding=ROUND_HALF_UP,
        )
    )

    margin = max(
        Decimal("5"),
        estimated
        * Decimal("0.03"),
    )

    recommended = (
        estimated
        + margin
    ).to_integral_value(
        rounding=ROUND_CEILING,
    )

    result.update(
        {
            "estimated_maintain_market_value":
                decimal_text(
                    maintain_value
                ),
            "estimated_gate_minimum":
                decimal_text(
                    estimated
                ),
            "recommended_minimum":
                decimal_text(
                    recommended
                ),
        }
    )

    return result


def parse_infinite_grid_minimum_rejection(
    *,
    response: Any = None,
    error: str = "",
) -> dict[str, str] | None:
    response_dict = (
        response
        if isinstance(
            response,
            Mapping,
        )
        else {}
    )

    message = str(
        response_dict.get(
            "message"
        )
        or error
        or ""
    )

    match = (
        _MINIMUM_INVESTMENT_PATTERN
        .search(
            message
        )
    )

    if match is None:
        return None

    return {
        "requested_investment":
            match.group(
                "requested"
            ),
        "minimum_investment":
            match.group(
                "minimum"
            ),
    }


def format_infinite_grid_minimum_rejection(
    *,
    response: Any = None,
    error: str = "",
    market: str = "",
) -> str | None:
    parsed = (
        parse_infinite_grid_minimum_rejection(
            response=response,
            error=error,
        )
    )

    if parsed is None:
        return None

    quote = (
        str(
            market
            or ""
        )
        .strip()
        .upper()
        .split(
            "_"
        )[-1]
        or "quote currency"
    )

    return (
        "Infinity Grid not created: "
        f"{parsed['requested_investment']} "
        f"{quote} is below Gate's "
        f"minimum of "
        f"{parsed['minimum_investment']} "
        f"{quote} for these settings. "
        "Gate may recalculate this dynamic "
        "minimum when market conditions or "
        "strategy settings change."
    )


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
        < GATE_MIN_PROFIT_PER_GRID
    ):
        errors.append(
            "Profit per grid must be at least "
            "0.2% (Gate live UI limit)."
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
