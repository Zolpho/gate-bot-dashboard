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
from ..bot_control_audit import (
    IdempotencyConflict,
    find_matching_request,
    get_request,
    list_requests,
    mark_request,
    reserve_request,
)
from ..bot_control import (
    BotControlConfigError,
    get_bot_control_account,
)
from ..config import get_settings
from ..db import session_scope
from ..models import Bot
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

class SpotGridCreateRequest(SpotGridPrepareRequest):
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=(
            r"^[A-Za-z0-9]"
            r"[A-Za-z0-9._:-]{7,127}$"
        ),
    )

    confirmation: str = Field(
        min_length=1,
        max_length=64,
    )


def _existing_control_result(
    record: dict,
):
    status = record["status"]

    if status in {
        "succeeded",
        "simulated",
    }:
        result = dict(
            record.get("response")
            or {}
        )

        result["request_id"] = (
            record["request_id"]
        )

        result["idempotent_replay"] = True

        return result

    if status in {
        "reserved",
        "submitting",
    }:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "This Bot Control request is already "
                    "in progress. No second Gate request "
                    "was sent."
                ),
                "request_id": record["request_id"],
                "status": status,
            },
        )

    if status == "uncertain":
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "The previous Gate submission has an "
                    "uncertain outcome. Do not retry "
                    "automatically. Check Gate and the "
                    "audit record."
                ),
                "request_id": record["request_id"],
                "status": status,
                "error": record.get("error"),
            },
        )

    raise HTTPException(
        status_code=409,
        detail={
            "message": (
                "This request_id was already used. "
                "No second Gate request was sent."
            ),
            "request_id": record["request_id"],
            "status": status,
            "error": record.get("error"),
        },
    )


@router.post("/spot-grid/create")
async def create_spot_grid(
    request: SpotGridCreateRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    # A request is permitted only when either simulation
    # mode or live Bot Create mode is enabled.
    if (
        not settings.allow_bot_create
        and not settings.bot_create_simulation
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Bot creation and simulation are disabled"
            ),
        )

    if (
        request.confirmation
        != settings.bot_create_confirmation_text
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid Bot Control confirmation text"
            ),
        )

    account_id = require_account_access(
        user,
        request.account_id,
    )

    intent = build_spot_grid_payload(
        market=request.market.strip().upper(),
        money=request.money,
        low_price=request.low_price,
        high_price=request.high_price,
        grid_num=request.grid_num,
        price_type=request.price_type,
        trigger_price=request.trigger_price,
        stop_profit=request.stop_profit,
        stop_loss=request.stop_loss,
    )

    audit_payload = {
        "account_id": account_id,
        "operation": "spot_grid_create",
        "gate_payload": intent,
    }

    try:
        existing = find_matching_request(
            request_id=request.request_id,
            account_id=account_id,
            username=user.username,
            action="spot_grid_create",
            payload=audit_payload,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if existing is not None:
        return _existing_control_result(
            existing
        )

    # Full read-only validation immediately before
    # reserving the write.
    prepared = await prepare_spot_grid(
        request,
        user,
    )

    if not prepared["can_create"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Spot Grid validation failed. "
                    "No Gate write was performed."
                ),
                "errors": prepared["errors"],
                "warnings": prepared["warnings"],
            },
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

    # Atomic reservation / double-submit barrier.
    try:
        audit_record, created = reserve_request(
            request_id=request.request_id,
            account_id=account_id,
            username=user.username,
            action="spot_grid_create",
            payload=audit_payload,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if not created:
        return _existing_control_result(
            audit_record
        )

    mark_request(
        request.request_id,
        status="submitting",
    )

    payload = prepared[
        "gate_create_payload_preview"
    ]

    # Simulation mode exercises authentication, validation,
    # idempotency and persistent auditing but deliberately
    # stops before any Gate write request.
    if settings.bot_create_simulation:
        simulated_result = {
            "status": "simulated",
            "write_performed": False,
            "simulation": True,
            "credential_profile": "bot_control",
            "request_id": request.request_id,
            "idempotent_replay": False,
            "account_id": account_id,
            "authorized_user": user.username,
            "gate_create_payload": payload,
            "strategy": {
                "strategy_id": None,
                "strategy_type": "spot_grid",
                "market": payload.get("market"),
                "status": "not_submitted",
                "jump_url": None,
            },
        }

        mark_request(
            request.request_id,
            status="simulated",
            response=simulated_result,
            completed=True,
        )

        return simulated_result

    # Reaching this point is possible only when live Bot
    # Create is enabled and simulation mode is disabled.
    try:
        async with GateClient(
            settings,
            control_account,
        ) as client:
            response = (
                await client.create_spot_grid(
                    payload
                )
            )

    except GateAPIError as exc:
        # An explicit Gate HTTP/business error means
        # rejection. A network failure may have happened
        # after Gate accepted the request, so it is
        # deliberately treated as uncertain.
        terminal_status = (
            "rejected"
            if exc.status_code is not None
            else "uncertain"
        )

        mark_request(
            request.request_id,
            status=terminal_status,
            response=exc.response,
            error=str(exc),
            gate_status_code=exc.status_code,
            gate_label=exc.label,
            completed=True,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Gate rejected Spot Grid creation."
                    if terminal_status == "rejected"
                    else (
                        "Gate submission outcome is "
                        "uncertain. Do not retry "
                        "automatically."
                    )
                ),
                "request_id": request.request_id,
                "status": terminal_status,
                "gate_error": str(exc),
            },
        ) from exc

    except Exception as exc:
        mark_request(
            request.request_id,
            status="uncertain",
            error=str(exc),
            completed=True,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": (
                    "Unexpected error after Gate "
                    "submission began. Outcome is "
                    "uncertain; do not retry."
                ),
                "request_id": request.request_id,
            },
        ) from exc

    data = (
        response.data
        if isinstance(
            response.data,
            dict,
        )
        else {}
    )

    strategy_id = str(
        data.get("strategy_id")
        or ""
    )

    result = {
        "status": "submitted",
        "write_performed": True,
        "credential_profile": "bot_control",
        "request_id": request.request_id,
        "idempotent_replay": False,
        "account_id": account_id,
        "authorized_user": user.username,
        "strategy": {
            "strategy_id": (
                strategy_id or None
            ),
            "strategy_type": data.get(
                "strategy_type"
            ),
            "market": data.get("market"),
            "status": data.get("status"),
            "jump_url": data.get(
                "jump_url"
            ),
        },
        "gate": response.raw,
    }

    mark_request(
        request.request_id,
        status="succeeded",
        response=result,
        strategy_id=strategy_id,
        gate_status_code=response.status_code,
        completed=True,
    )

    return result




class BotStopRequest(BaseModel):
    request_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=(
            r"^[A-Za-z0-9]"
            r"[A-Za-z0-9._:-]{7,127}$"
        ),
    )

    confirmation: str = Field(
        min_length=1,
        max_length=64,
    )


def _load_bot_control_target(
    bot_id: int,
    user: DashboardUser,
) -> dict:
    with session_scope() as db:
        bot = db.get(
            Bot,
            bot_id,
        )

        if bot is None:
            raise HTTPException(
                status_code=404,
                detail="Bot not found",
            )

        require_account_access(
            user,
            bot.account_id,
        )

        return {
            "id": bot.id,
            "account_id": bot.account_id,
            "strategy_id": bot.strategy_id,
            "strategy_name": bot.strategy_name,
            "strategy_type": bot.strategy_type,
            "market": bot.market,
            "status": bot.status,
            "source_status": bot.source_status,
            "invest_amount": (
                decimal_text(bot.invest_amount)
                if bot.invest_amount is not None
                else None
            ),
            "total_profit": (
                decimal_text(bot.total_profit)
                if bot.total_profit is not None
                else None
            ),
            "current_value": (
                decimal_text(bot.current_value)
                if bot.current_value is not None
                else None
            ),
            "stop_supported": bool(
                bot.stop_supported
            ),
        }


@router.get("/bots/{bot_id}/stop/prepare")
async def prepare_bot_stop(
    bot_id: int,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    bot = _load_bot_control_target(
        bot_id,
        user,
    )

    errors: list[str] = []
    warnings: list[str] = []

    if not bot["stop_supported"]:
        errors.append(
            "Gate reports that this strategy "
            "does not support stopping."
        )

    if str(bot["status"]).lower() in {
        "stopped",
        "finished",
        "closed",
    }:
        errors.append(
            "The local bot record is already stopped."
        )

    monitor_account = get_gate_account(
        bot["account_id"]
    )

    if (
        monitor_account is None
        or not monitor_account.enabled
        or not monitor_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Monitor credentials are not configured "
                f"for {bot['account_id']}"
            ),
        )

    try:
        control_account = (
            get_bot_control_account(
                bot["account_id"]
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
                f"configured for {bot['account_id']}"
            ),
        )

    gate_detail: dict = {}

    try:
        async with GateClient(
            settings,
            monitor_account,
        ) as client:
            response = await client.get_bot_detail(
                bot["strategy_id"],
                bot["strategy_type"],
            )

            if isinstance(
                response.data,
                dict,
            ):
                gate_detail = response.data

    except GateAPIError as exc:
        warnings.append(
            "Unable to refresh Gate bot detail "
            f"during preflight: {exc}"
        )

    gate_status = str(
        gate_detail.get("status")
        or bot["source_status"]
        or bot["status"]
        or ""
    )

    if (
        gate_status
        and gate_status.lower()
        not in {
            "running",
            "active",
        }
    ):
        warnings.append(
            "Gate currently reports strategy status "
            f"'{gate_status}'. Review before stopping."
        )

    stop_payload = {
        "strategy_id": bot["strategy_id"],
        "strategy_type": bot["strategy_type"],
    }

    return {
        "status": (
            "ready"
            if not errors
            else "invalid"
        ),
        "can_stop": not errors,
        "write_performed": False,
        "credential_profiles": {
            "prepare": "monitor",
            "stop": "bot_control",
        },
        "bot": bot,
        "gate_snapshot": {
            "status": gate_status or None,
        },
        "errors": errors,
        "warnings": warnings,
        "gate_stop_payload_preview": stop_payload,
    }


@router.post("/bots/{bot_id}/stop")
async def stop_bot_control(
    bot_id: int,
    request: BotStopRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    if (
        not settings.allow_bot_stop
        and not settings.bot_stop_simulation
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Bot stopping and simulation "
                "are disabled"
            ),
        )

    if (
        request.confirmation
        != settings.bot_stop_confirmation_text
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid Bot Stop confirmation text"
            ),
        )

    bot = _load_bot_control_target(
        bot_id,
        user,
    )

    audit_payload = {
        "account_id": bot["account_id"],
        "operation": "bot_stop",
        "gate_payload": {
            "strategy_id": bot["strategy_id"],
            "strategy_type": bot["strategy_type"],
            "market": bot["market"],
            "stop_params": {
                "bot_id": bot["id"],
                "strategy_name": (
                    bot["strategy_name"]
                ),
            },
        },
    }

    try:
        existing = find_matching_request(
            request_id=request.request_id,
            account_id=bot["account_id"],
            username=user.username,
            action="bot_stop",
            payload=audit_payload,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if existing is not None:
        return _existing_control_result(
            existing
        )

    prepared = await prepare_bot_stop(
        bot_id,
        user,
    )

    if not prepared["can_stop"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Bot Stop validation failed. "
                    "No Gate write was performed."
                ),
                "errors": prepared["errors"],
                "warnings": prepared["warnings"],
            },
        )

    try:
        control_account = (
            get_bot_control_account(
                bot["account_id"]
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
                "Bot Control credential unavailable "
                f"for {bot['account_id']}"
            ),
        )

    try:
        audit_record, created = reserve_request(
            request_id=request.request_id,
            account_id=bot["account_id"],
            username=user.username,
            action="bot_stop",
            payload=audit_payload,
        )
    except IdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    if not created:
        return _existing_control_result(
            audit_record
        )

    mark_request(
        request.request_id,
        status="submitting",
        strategy_id=bot["strategy_id"],
    )

    payload = prepared[
        "gate_stop_payload_preview"
    ]

    # Simulation deliberately exits before the Gate
    # stop request.
    if settings.bot_stop_simulation:
        result = {
            "status": "simulated",
            "write_performed": False,
            "simulation": True,
            "credential_profile": "bot_control",
            "request_id": request.request_id,
            "idempotent_replay": False,
            "account_id": bot["account_id"],
            "authorized_user": user.username,
            "action": "bot_stop",
            "bot": {
                "id": bot["id"],
                "strategy_id": bot["strategy_id"],
                "strategy_name": (
                    bot["strategy_name"]
                ),
                "strategy_type": (
                    bot["strategy_type"]
                ),
                "market": bot["market"],
                "status": bot["status"],
            },
            "gate_stop_payload": payload,
        }

        mark_request(
            request.request_id,
            status="simulated",
            response=result,
            strategy_id=bot["strategy_id"],
            completed=True,
        )

        return result

    # Live path. Reached only when simulation is off
    # and ALLOW_BOT_STOP is explicitly enabled.
    try:
        async with GateClient(
            settings,
            control_account,
        ) as client:
            response = await client.stop_bot(
                bot["strategy_id"],
                bot["strategy_type"],
            )

    except GateAPIError as exc:
        terminal_status = (
            "rejected"
            if exc.status_code is not None
            else "uncertain"
        )

        mark_request(
            request.request_id,
            status=terminal_status,
            response=exc.response,
            error=str(exc),
            strategy_id=bot["strategy_id"],
            gate_status_code=exc.status_code,
            gate_label=exc.label,
            completed=True,
        )

        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "Gate rejected Bot Stop."
                    if terminal_status == "rejected"
                    else (
                        "Gate Stop outcome is uncertain. "
                        "Do not retry automatically."
                    )
                ),
                "request_id": request.request_id,
                "status": terminal_status,
                "gate_error": str(exc),
            },
        ) from exc

    except Exception as exc:
        mark_request(
            request.request_id,
            status="uncertain",
            error=str(exc),
            strategy_id=bot["strategy_id"],
            completed=True,
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": (
                    "Unexpected error after Gate Stop "
                    "submission began. Outcome is "
                    "uncertain; do not retry."
                ),
                "request_id": request.request_id,
            },
        ) from exc

    result = {
        "status": "submitted",
        "write_performed": True,
        "simulation": False,
        "credential_profile": "bot_control",
        "request_id": request.request_id,
        "idempotent_replay": False,
        "account_id": bot["account_id"],
        "authorized_user": user.username,
        "action": "bot_stop",
        "bot": {
            "id": bot["id"],
            "strategy_id": bot["strategy_id"],
            "strategy_name": bot["strategy_name"],
            "strategy_type": bot["strategy_type"],
            "market": bot["market"],
        },
        "gate": response.raw,
    }

    mark_request(
        request.request_id,
        status="succeeded",
        response=result,
        strategy_id=bot["strategy_id"],
        gate_status_code=response.status_code,
        completed=True,
    )

    return result


@router.get("/requests")
def list_bot_control_activity(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    limit: int = 50,
    account_id: str | None = None,
):
    limit = max(
        1,
        min(int(limit), 200),
    )

    if account_id:
        normalized = require_account_access(
            user,
            account_id,
        )

        visible_account_ids = {
            normalized
        }

    elif user.is_super_admin:
        visible_account_ids = None

    else:
        visible_account_ids = set(
            user.account_ids
        )

    records = list_requests(
        limit=limit,
        account_ids=visible_account_ids,
    )

    items = []

    for record in records:
        request_data = (
            record.get("request")
            or {}
        )

        gate_payload = (
            request_data.get("gate_payload")
            or {}
        )

        params = (
            gate_payload.get("create_params")
            or {}
        )

        response = (
            record.get("response")
            or {}
        )

        status = str(
            record.get("status")
            or ""
        )

        simulation = bool(
            response.get("simulation")
            or status == "simulated"
        )

        write_performed = bool(
            response.get("write_performed")
        )

        if simulation:
            mode = "simulation"

        elif (
            write_performed
            or status in {
                "submitting",
                "succeeded",
                "rejected",
                "uncertain",
            }
        ):
            mode = "live"

        else:
            mode = "pending"

        items.append({
            "request_id": record["request_id"],
            "action": record["action"],
            "account_id": record["account_id"],
            "username": record["username"],
            "status": status,
            "mode": mode,
            "write_performed": write_performed,
            "market": gate_payload.get("market"),
            "investment": params.get("money"),
            "grid_num": params.get("grid_num"),
            "price_type": params.get("price_type"),
            "strategy_id": (
                record.get("strategy_id")
                or None
            ),
            "gate_status_code": (
                record.get("gate_status_code")
            ),
            "gate_label": (
                record.get("gate_label")
            ),
            "error": (
                record.get("error")
                or ""
            ),
            "created_at": record["created_at"],
            "completed_at": (
                record.get("completed_at")
            ),
        })

    return {
        "count": len(items),
        "items": items,
    }


@router.get("/requests/{request_id}")
def get_bot_control_request(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    record = get_request(
        request_id
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Bot Control request not found"
            ),
        )

    require_account_access(
        user,
        record["account_id"],
    )

    return {
        "request_id": record["request_id"],
        "action": record["action"],
        "account_id": record["account_id"],
        "username": record["username"],
        "status": record["status"],
        "strategy_id": (
            record["strategy_id"] or None
        ),
        "gate_status_code": (
            record["gate_status_code"]
        ),
        "gate_label": (
            record["gate_label"]
        ),
        "error": record["error"],
        "request": record["request"],
        "response": record["response"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "completed_at": record["completed_at"],
    }

