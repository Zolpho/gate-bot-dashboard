from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel, Field

from ..accounts import (
    AccountConfigError,
    get_gate_account,
)
from ..bot_control import (
    BotControlConfigError,
    get_bot_control_account,
)
from ..config import get_settings
from ..gate_client import (
    GateAPIError,
    GateClient,
)
from ..security import (
    DashboardUser,
    require_account_access,
    require_user,
)
from ..spot_grid import (
    build_spot_grid_payload,
    decimal_text,
    validate_spot_grid,
)


router = APIRouter(
    prefix="/api/bot-control",
    tags=["bot-control"],
)

settings = get_settings()


class SpotGridPrepareRequest(BaseModel):
    account_id: str = Field(
        min_length=1,
        max_length=64,
    )

    market: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9]+_[A-Za-z0-9]+$",
    )

    money: Decimal = Field(gt=0)

    low_price: Decimal = Field(gt=0)

    high_price: Decimal = Field(gt=0)

    grid_num: int = Field(ge=1)

    price_type: Literal[0, 1] = 0

    trigger_price: Decimal | None = Field(
        default=None,
        gt=0,
    )

    stop_profit: Decimal | None = Field(
        default=None,
        gt=0,
    )

    stop_loss: Decimal | None = Field(
        default=None,
        gt=0,
    )


def as_decimal(
    value,
) -> Decimal | None:
    if value is None:
        return None

    try:
        result = Decimal(str(value))
    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None

    if not result.is_finite():
        return None

    return result


@router.post("/spot-grid/prepare")
async def prepare_spot_grid(
    request: SpotGridPrepareRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    account_id = require_account_access(
        user,
        request.account_id,
    )

    market = request.market.strip().upper()

    monitor_account = get_gate_account(
        account_id
    )

    if (
        monitor_account is None
        or not monitor_account.enabled
        or not monitor_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Monitor credentials are not "
                f"configured for {account_id}"
            ),
        )

    try:
        control_account = (
            get_bot_control_account(
                account_id
            )
        )
    except BotControlConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    if control_account is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Bot Control credentials are not "
                f"configured for {account_id}"
            ),
        )

    try:
        async with GateClient(
            settings,
            monitor_account,
        ) as client:
            pair_response = (
                await client.get_spot_currency_pair(
                    market
                )
            )

            ticker_response = (
                await client.list_spot_tickers(
                    market
                )
            )

            balances_response = (
                await client.list_spot_accounts()
            )

    except (
        GateAPIError,
        AccountConfigError,
    ) as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    pair = (
        pair_response.data
        if isinstance(
            pair_response.data,
            dict,
        )
        else {}
    )

    if not pair:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Gate returned no metadata "
                f"for market {market}"
            ),
        )

    base = str(
        pair.get("base")
        or market.split("_", 1)[0]
    ).upper()

    quote = str(
        pair.get("quote")
        or market.split("_", 1)[1]
    ).upper()

    trade_status = str(
        pair.get("trade_status")
        or ""
    ).lower()

    try:
        price_precision = int(
            pair.get("precision")
        )
    except (
        TypeError,
        ValueError,
    ):
        raise HTTPException(
            status_code=502,
            detail=(
                "Gate market metadata is missing "
                "price precision"
            ),
        )

    min_quote_amount = as_decimal(
        pair.get("min_quote_amount")
    )

    tickers = (
        ticker_response.data
        if isinstance(
            ticker_response.data,
            list,
        )
        else []
    )

    ticker = next(
        (
            item
            for item in tickers
            if isinstance(item, dict)
            and str(
                item.get(
                    "currency_pair",
                    "",
                )
            ).upper() == market
        ),
        {},
    )

    current_price = as_decimal(
        ticker.get("last")
        if isinstance(
            ticker,
            dict,
        )
        else None
    )

    balances = (
        balances_response.data
        if isinstance(
            balances_response.data,
            list,
        )
        else []
    )

    quote_balance = next(
        (
            item
            for item in balances
            if isinstance(item, dict)
            and str(
                item.get("currency", "")
            ).upper() == quote
        ),
        {},
    )

    available_quote = (
        as_decimal(
            quote_balance.get("available")
        )
        or Decimal("0")
    )

    locked_quote = (
        as_decimal(
            quote_balance.get("locked")
        )
        or Decimal("0")
    )

    errors, warnings, grid_math = (
        validate_spot_grid(
            money=request.money,
            low_price=request.low_price,
            high_price=request.high_price,
            grid_num=request.grid_num,
            price_type=request.price_type,
            price_precision=price_precision,
            trade_status=trade_status,
            min_quote_amount=min_quote_amount,
            available_quote=available_quote,
            current_price=current_price,
            trigger_price=(
                request.trigger_price
            ),
            stop_profit=request.stop_profit,
            stop_loss=request.stop_loss,
        )
    )

    payload = build_spot_grid_payload(
        market=market,
        money=request.money,
        low_price=request.low_price,
        high_price=request.high_price,
        grid_num=request.grid_num,
        price_type=request.price_type,
        trigger_price=request.trigger_price,
        stop_profit=request.stop_profit,
        stop_loss=request.stop_loss,
    )

    return {
        "status": (
            "ready"
            if not errors
            else "invalid"
        ),
        "can_create": not errors,

        "write_performed": False,

        "credential_profiles": {
            "prepare": "monitor",
            "create": "bot_control",
        },

        "account": {
            "id": monitor_account.id,
            "name": monitor_account.name,
            "bot_control_available": True,
        },

        "market": {
            "id": market,
            "base": base,
            "quote": quote,
            "trade_status": trade_status,
            "price_precision": (
                price_precision
            ),
            "amount_precision": (
                pair.get(
                    "amount_precision"
                )
            ),
            "min_base_amount": (
                pair.get(
                    "min_base_amount"
                )
            ),
            "min_quote_amount": (
                pair.get(
                    "min_quote_amount"
                )
            ),
        },

        "market_snapshot": {
            "last": decimal_text(
                current_price
            ),
            "highest_bid": (
                ticker.get("highest_bid")
                if isinstance(
                    ticker,
                    dict,
                )
                else None
            ),
            "lowest_ask": (
                ticker.get("lowest_ask")
                if isinstance(
                    ticker,
                    dict,
                )
                else None
            ),
        },

        "balance": {
            "currency": quote,
            "available": decimal_text(
                available_quote
            ),
            "locked": decimal_text(
                locked_quote
            ),
            "requested_investment": (
                decimal_text(
                    request.money
                )
            ),
            "remaining_after_investment": (
                decimal_text(
                    available_quote
                    - request.money
                )
                if available_quote
                >= request.money
                else None
            ),
        },

        "grid": grid_math,

        "errors": errors,
        "warnings": warnings,

        "gate_create_payload_preview": (
            payload
        ),
    }
