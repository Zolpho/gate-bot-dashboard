from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from pydantic import BaseModel, Field

from ..accounts import (
    AccountConfigError,
    get_gate_account,
    load_gate_accounts,
)
from ..config import Settings, get_settings
from ..gate_client import GateAPIError, GateClient
from ..security import DashboardUser, require_user
from ..trading_credentials import (
    TradingConfigError,
    get_trading_account,
)
from ..trading_execution import (
    TradingExecutionDenied,
    execute_limit_order,
)
from ..trading_open_orders import (
    merge_open_spot_orders,
)
from ..trading_order_audit import (
    find_order_requests_by_gate_identity,
    get_order_request,
    list_order_reconciliations,
    list_order_requests_for_market,
)
from ..trading_order_cancel import (
    TradingOrderCancelDenied,
    cancel_limit_order,
    reconcile_limit_order_cancellation,
)
from ..trading_order_cancel_audit import (
    get_order_cancellation,
)
from ..trading_order_locks import (
    get_trading_lock_for_request,
)
from ..trading_order_reconcile import (
    TradingOrderReconcileError,
    reconcile_spot_order_request,
)
from ..trading_order_state import (
    derive_trading_order_state,
)
from ..trading_recent_orders import (
    build_recent_spot_orders,
)

router = APIRouter(
    prefix="/api/trading",
    tags=["trading"],
)


_PAIR_RE = re.compile(
    r"^[A-Z0-9]+_[A-Z0-9]+$"
)

_ALLOWED_INTERVALS = {
    "1m",
    "5m",
    "15m",
    "30m",
    "1h",
    "4h",
    "8h",
    "1d",
    "7d",
    "30d",
}


class LimitOrderExecuteRequest(BaseModel):
    request_id: str = Field(
        min_length=1,
        max_length=128,
    )

    account_id: str = Field(
        min_length=1,
        max_length=64,
    )

    pair: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9]+_[A-Za-z0-9]+$",
    )

    side: Literal[
        "buy",
        "sell",
    ]

    price: Decimal = Field(
        gt=0,
    )

    amount: Decimal = Field(
        gt=0,
    )

    time_in_force: Literal[
        "gtc",
        "poc",
    ] = "gtc"

    confirmation: str = Field(
        min_length=1,
        max_length=256,
    )


class LimitOrderCancelRequest(BaseModel):
    cancel_request_id: str = Field(
        min_length=1,
        max_length=128,
    )

    confirmation: str = Field(
        min_length=1,
        max_length=256,
    )


class LimitOrderPreviewRequest(BaseModel):
    account_id: str = Field(
        min_length=1,
        max_length=64,
    )

    pair: str = Field(
        min_length=3,
        max_length=64,
        pattern=r"^[A-Za-z0-9]+_[A-Za-z0-9]+$",
    )

    side: Literal["buy", "sell"]

    price: Decimal = Field(
        gt=0,
    )

    amount: Decimal = Field(
        gt=0,
    )

    time_in_force: Literal[
        "gtc",
        "poc",
    ] = "gtc"


def _explicit_trading_account(
    user: DashboardUser,
    account_id: str,
) -> str:
    """
    Trading intentionally does NOT use DashboardUser.can_manage().

    A super-admin therefore receives no implicit wildcard. The Gate
    account must be explicitly present in DashboardUser.account_ids.
    """
    normalized = account_id.strip().lower()

    allowed = {
        item.strip().lower()
        for item in user.account_ids
        if item.strip()
    }

    if normalized not in allowed:
        raise HTTPException(
            status_code=403,
            detail=(
                "Trading is limited to Gate accounts explicitly "
                "assigned to this dashboard user"
            ),
        )

    return normalized


def _trading_request_for_user(
    user: DashboardUser,
    request_id: str,
) -> dict[str, Any]:
    """
    Return a persisted Trading request only when its
    Gate account is explicitly assigned to this user.

    Super-admin receives no implicit Trading wildcard.

    Deliberately return 404 for inaccessible request IDs
    so one dashboard user cannot enumerate another
    account's Trading operations.
    """
    request = get_order_request(
        request_id.strip()
    )

    if request is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Trading order request "
                "not found"
            ),
        )

    allowed = {
        item.strip().lower()
        for item in user.account_ids
        if item.strip()
    }

    if (
        str(
            request.get(
                "account_id"
            )
            or ""
        ).strip().lower()
        not in allowed
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Trading order request "
                "not found"
            ),
        )

    return request


def _market(value: str) -> str:
    normalized = value.strip().upper()

    if not _PAIR_RE.fullmatch(normalized):
        raise HTTPException(
            status_code=400,
            detail="Invalid Gate spot currency pair",
        )

    return normalized


def _book_interval(
    value: str,
) -> str:
    normalized = value.strip()

    try:
        interval = Decimal(normalized)
    except (
        InvalidOperation,
        ValueError,
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid order-book price interval",
        )

    if (
        not interval.is_finite()
        or interval < 0
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid order-book price interval",
        )

    if interval == 0:
        return "0"

    return format(
        interval.normalize(),
        "f",
    )


def _decimal(
    value: Any,
) -> Decimal | None:
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


def _balance(
    rows: Any,
    currency: str,
) -> dict[str, str]:
    if not isinstance(rows, list):
        rows = []

    row = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(
                item.get("currency") or ""
            ).upper() == currency
        ),
        {},
    )

    return {
        "currency": currency,
        "available": str(
            row.get("available") or "0"
        ),
        "locked": str(
            row.get("locked") or "0"
        ),
    }


def _normalize_candlesticks(
    rows: Any,
) -> list[dict[str, Any]]:
    """
    Gate currently documents candle rows as:

      time, quote volume, close, high, low, open,
      base volume, closed

    The parser intentionally also tolerates older seven-field
    responses.
    """
    if not isinstance(rows, list):
        return []

    result: list[dict[str, Any]] = []

    for row in rows:
        if (
            not isinstance(row, (list, tuple))
            or len(row) < 6
        ):
            continue

        try:
            timestamp = int(row[0])
        except (
            TypeError,
            ValueError,
        ):
            continue

        open_price = _decimal(row[5])
        high_price = _decimal(row[3])
        low_price = _decimal(row[4])
        close_price = _decimal(row[2])

        if (
            open_price is None
            or high_price is None
            or low_price is None
            or close_price is None
        ):
            continue

        base_volume: str | None = None
        closed: bool | None = None

        if len(row) >= 8:
            base_volume = str(row[6])

            raw_closed = row[7]

            if isinstance(raw_closed, bool):
                closed = raw_closed
            else:
                normalized_closed = str(
                    raw_closed
                ).strip().lower()

                if normalized_closed in {
                    "true",
                    "1",
                }:
                    closed = True
                elif normalized_closed in {
                    "false",
                    "0",
                }:
                    closed = False

        elif len(row) == 7:
            last = str(row[6]).strip().lower()

            if last in {
                "true",
                "1",
                "false",
                "0",
            }:
                closed = last in {
                    "true",
                    "1",
                }
            else:
                base_volume = str(row[6])

        result.append(
            {
                "time": timestamp,
                "open": str(open_price),
                "high": str(high_price),
                "low": str(low_price),
                "close": str(close_price),
                "quote_volume": str(
                    row[1] or "0"
                ),
                "base_volume": base_volume,
                "closed": closed,
            }
        )

    result.sort(
        key=lambda item: item["time"]
    )

    return result


def _normalize_order_book(
    payload: Any,
) -> dict[str, Any]:
    data = (
        payload
        if isinstance(payload, dict)
        else {}
    )

    def levels(
        raw: Any,
        *,
        reverse: bool,
    ) -> list[dict[str, str]]:
        if not isinstance(raw, list):
            return []

        clean: list[
            tuple[Decimal, Decimal]
        ] = []

        for item in raw:
            if (
                not isinstance(
                    item,
                    (list, tuple),
                )
                or len(item) < 2
            ):
                continue

            price = _decimal(item[0])
            amount = _decimal(item[1])

            if (
                price is None
                or amount is None
                or price <= 0
                or amount < 0
            ):
                continue

            clean.append(
                (price, amount)
            )

        clean.sort(
            key=lambda item: item[0],
            reverse=reverse,
        )

        return [
            {
                "price": str(price),
                "amount": str(amount),
            }
            for price, amount in clean
        ]

    asks = levels(
        data.get("asks"),
        reverse=False,
    )

    bids = levels(
        data.get("bids"),
        reverse=True,
    )

    best_ask = (
        _decimal(asks[0]["price"])
        if asks
        else None
    )

    best_bid = (
        _decimal(bids[0]["price"])
        if bids
        else None
    )

    spread: Decimal | None = None
    spread_percent: Decimal | None = None

    if (
        best_ask is not None
        and best_bid is not None
        and best_ask >= best_bid
    ):
        spread = best_ask - best_bid

        midpoint = (
            best_ask + best_bid
        ) / Decimal("2")

        if midpoint > 0:
            spread_percent = (
                spread
                / midpoint
                * Decimal("100")
            )

    # Match Gate's displayed B/S depth convention:
    # calculate from the first 20 price levels on each side
    # of the currently selected order-book grouping.
    ratio_asks = asks[:20]
    ratio_bids = bids[:20]

    ask_total = sum(
        (
            _decimal(item["amount"])
            or Decimal("0")
        )
        for item in ratio_asks
    )

    bid_total = sum(
        (
            _decimal(item["amount"])
            or Decimal("0")
        )
        for item in ratio_bids
    )

    depth_total = (
        ask_total + bid_total
    )

    if depth_total > 0:
        buy_percent = (
            bid_total
            / depth_total
            * Decimal("100")
        )

        sell_percent = (
            ask_total
            / depth_total
            * Decimal("100")
        )
    else:
        buy_percent = Decimal("0")
        sell_percent = Decimal("0")

    return {
        "id": data.get("id"),
        "current": data.get("current"),
        "update": data.get("update"),
        "asks": asks,
        "bids": bids,
        "bid_amount_total": str(bid_total),
        "ask_amount_total": str(ask_total),
        "buy_percent": str(buy_percent),
        "sell_percent": str(sell_percent),
        "best_ask": (
            str(best_ask)
            if best_ask is not None
            else None
        ),
        "best_bid": (
            str(best_bid)
            if best_bid is not None
            else None
        ),
        "spread": (
            str(spread)
            if spread is not None
            else None
        ),
        "spread_percent": (
            str(spread_percent)
            if spread_percent is not None
            else None
        ),
    }


def _decimal_places(
    value: Decimal,
) -> int:
    normalized = value.normalize()
    exponent = normalized.as_tuple().exponent

    if exponent >= 0:
        return 0

    return -exponent


def _decimal_text(
    value: Decimal,
) -> str:
    return format(
        value.normalize(),
        "f",
    )


def _int_or_none(
    value: Any,
) -> int | None:
    try:
        result = int(value)
    except (
        TypeError,
        ValueError,
    ):
        return None

    if result < 0:
        return None

    return result


def _limit_order_preflight(
    *,
    side: Literal["buy", "sell"],
    time_in_force: Literal["gtc", "poc"],
    price: Decimal,
    amount: Decimal,
    trade_status: str,
    price_precision: int | None,
    amount_precision: int | None,
    min_base_amount: Decimal | None,
    min_quote_amount: Decimal | None,
    base_available: Decimal,
    quote_available: Decimal,
    best_bid: Decimal | None,
    best_ask: Decimal | None,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []

    normalized_status = (
        trade_status.strip().lower()
    )

    side_allowed = (
        normalized_status == "tradable"
        or (
            normalized_status == "buyable"
            and side == "buy"
        )
        or (
            normalized_status == "sellable"
            and side == "sell"
        )
    )

    if not side_allowed:
        blockers.append(
            "Gate does not currently allow this side "
            f"for the pair (trade_status="
            f"{normalized_status or 'unknown'})."
        )

    if price_precision is None:
        blockers.append(
            "Gate pair price precision is unavailable."
        )
    elif (
        _decimal_places(price)
        > price_precision
    ):
        blockers.append(
            "Price exceeds Gate pair precision "
            f"({price_precision} decimal places)."
        )

    if amount_precision is None:
        blockers.append(
            "Gate pair amount precision is unavailable."
        )
    elif (
        _decimal_places(amount)
        > amount_precision
    ):
        blockers.append(
            "Amount exceeds Gate pair precision "
            f"({amount_precision} decimal places)."
        )

    total = price * amount

    if (
        min_base_amount is not None
        and min_base_amount > 0
        and amount < min_base_amount
    ):
        blockers.append(
            "Amount is below Gate minimum base amount "
            f"({_decimal_text(min_base_amount)})."
        )

    if (
        min_quote_amount is not None
        and min_quote_amount > 0
        and total < min_quote_amount
    ):
        blockers.append(
            "Order total is below Gate minimum quote amount "
            f"({_decimal_text(min_quote_amount)})."
        )

    if side == "buy":
        required_currency = "quote"
        available = quote_available
        required = total

        marketable = (
            best_ask is not None
            and price >= best_ask
        )

    else:
        required_currency = "base"
        available = base_available
        required = amount

        marketable = (
            best_bid is not None
            and price <= best_bid
        )

    remaining = available - required

    if required > available:
        blockers.append(
            "Insufficient available spot balance."
        )

    if marketable:
        if time_in_force == "poc":
            blockers.append(
                "Post-only order would currently cross "
                "the order book."
            )
        else:
            warnings.append(
                "This limit order is currently marketable "
                "and may execute immediately."
            )

    warnings.append(
        "Estimated total does not include trading fees."
    )

    return {
        "blockers": blockers,
        "warnings": warnings,
        "total": total,
        "required_currency": required_currency,
        "available": available,
        "required": required,
        "remaining": remaining,
        "marketable": marketable,
    }


def _monitor_account_or_http(
    account_id: str,
):
    try:
        account = get_gate_account(
            account_id
        )
    except AccountConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    if (
        account is None
        or not account.enabled
        or not account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Monitor credentials are not configured "
                f"for Gate account {account_id}"
            ),
        )

    return account


@router.get("/catalog")
async def trading_catalog(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):
    explicit_ids = {
        item.strip().lower()
        for item in user.account_ids
        if item.strip()
    }

    try:
        accounts = [
            account
            for account in load_gate_accounts()
            if (
                account.id in explicit_ids
                and account.enabled
                and account.configured
            )
        ]
    except AccountConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    try:
        async with GateClient(
            settings,
            None,
        ) as client:
            response = (
                await client.list_spot_currency_pairs()
            )
    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    raw_pairs = (
        response.data
        if isinstance(response.data, list)
        else []
    )

    pairs: list[dict[str, Any]] = []

    for item in raw_pairs:
        if not isinstance(item, dict):
            continue

        pair_id = str(
            item.get("id") or ""
        ).upper()

        if not _PAIR_RE.fullmatch(pair_id):
            continue

        status = str(
            item.get("trade_status")
            or ""
        ).lower()

        if status == "untradable":
            continue

        pairs.append(
            {
                "id": pair_id,
                "base": str(
                    item.get("base")
                    or pair_id.split("_", 1)[0]
                ).upper(),
                "quote": str(
                    item.get("quote")
                    or pair_id.split("_", 1)[1]
                ).upper(),
                "trade_status": status,
                "precision": item.get(
                    "precision"
                ),
                "amount_precision": item.get(
                    "amount_precision"
                ),
                "min_base_amount": item.get(
                    "min_base_amount"
                ),
                "min_quote_amount": item.get(
                    "min_quote_amount"
                ),
            }
        )

    pairs.sort(
        key=lambda item: item["id"]
    )

    pair_ids = {
        item["id"]
        for item in pairs
    }

    if "EQTY_USDT" in pair_ids:
        default_pair = "EQTY_USDT"
    else:
        default_pair = next(
            (
                item["id"]
                for item in pairs
                if item["quote"] == "USDT"
            ),
            (
                pairs[0]["id"]
                if pairs
                else ""
            ),
        )

    return {
        "write_performed": False,
        "market_data_only": True,
        "authorized_user": user.safe_dict(),
        "accounts": [
            account.safe_dict()
            for account in accounts
        ],
        "pairs": pairs,
        "default_pair": default_pair,
        "intervals": sorted(
            _ALLOWED_INTERVALS
        ),
    }


@router.get("/snapshot")
async def trading_snapshot(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
    account_id: str = Query(
        min_length=1,
        max_length=64,
    ),
    pair: str = Query(
        default="EQTY_USDT",
        min_length=3,
        max_length=64,
    ),
    depth: int = Query(
        default=50,
        ge=5,
        le=100,
    ),
    book_interval: str = Query(
        default="0",
        min_length=1,
        max_length=32,
    ),
):
    account_id = _explicit_trading_account(
        user,
        account_id,
    )

    market = _market(pair)

    normalized_book_interval = _book_interval(
        book_interval
    )

    base, quote = market.split(
        "_",
        1,
    )

    account = _monitor_account_or_http(
        account_id
    )

    try:
        async with GateClient(
            settings,
            account,
        ) as client:
            (
                ticker_response,
                order_book_response,
                balance_response,
            ) = await asyncio.gather(
                client.list_spot_tickers(
                    market
                ),
                client.get_spot_order_book(
                    market,
                    interval=normalized_book_interval,
                    limit=depth,
                    with_id=True,
                ),
                client.list_spot_accounts(),
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

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
                item.get("currency_pair")
                or ""
            ).upper() == market
        ),
        {},
    )

    balances = balance_response.data

    return {
        "write_performed": False,
        "market_data_only": True,
        "account": account.safe_dict(),
        "pair": {
            "id": market,
            "base": base,
            "quote": quote,
        },
        "ticker": (
            ticker
            if isinstance(ticker, dict)
            else {}
        ),
        "book_interval": normalized_book_interval,
        "order_book": _normalize_order_book(
            order_book_response.data
        ),
        "balances": {
            "base": _balance(
                balances,
                base,
            ),
            "quote": _balance(
                balances,
                quote,
            ),
        },
    }


@router.post("/limit-orders/preview")
async def preview_limit_order(
    request: LimitOrderPreviewRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):
    account_id = _explicit_trading_account(
        user,
        request.account_id,
    )

    market = _market(
        request.pair
    )

    monitor_account = _monitor_account_or_http(
        account_id
    )

    try:
        async with GateClient(
            settings,
            monitor_account,
        ) as client:
            (
                pair_response,
                balance_response,
                book_response,
            ) = await asyncio.gather(
                client.get_spot_currency_pair(
                    market
                ),
                client.list_spot_accounts(),
                client.get_spot_order_book(
                    market,
                    interval="0",
                    limit=20,
                    with_id=True,
                ),
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    pair_data = (
        pair_response.data
        if isinstance(
            pair_response.data,
            dict,
        )
        else {}
    )

    if not pair_data:
        raise HTTPException(
            status_code=502,
            detail=(
                "Gate did not return spot pair metadata"
            ),
        )

    base = str(
        pair_data.get("base")
        or market.split("_", 1)[0]
    ).upper()

    quote = str(
        pair_data.get("quote")
        or market.split("_", 1)[1]
    ).upper()

    balances = balance_response.data

    base_balance = _balance(
        balances,
        base,
    )

    quote_balance = _balance(
        balances,
        quote,
    )

    base_available = (
        _decimal(
            base_balance["available"]
        )
        or Decimal("0")
    )

    quote_available = (
        _decimal(
            quote_balance["available"]
        )
        or Decimal("0")
    )

    book = _normalize_order_book(
        book_response.data
    )

    best_bid = _decimal(
        book.get("best_bid")
    )

    best_ask = _decimal(
        book.get("best_ask")
    )

    min_base_amount = _decimal(
        pair_data.get(
            "min_base_amount"
        )
    )

    min_quote_amount = _decimal(
        pair_data.get(
            "min_quote_amount"
        )
    )

    checks = _limit_order_preflight(
        side=request.side,
        time_in_force=request.time_in_force,
        price=request.price,
        amount=request.amount,
        trade_status=str(
            pair_data.get(
                "trade_status"
            )
            or ""
        ),
        price_precision=_int_or_none(
            pair_data.get(
                "precision"
            )
        ),
        amount_precision=_int_or_none(
            pair_data.get(
                "amount_precision"
            )
        ),
        min_base_amount=min_base_amount,
        min_quote_amount=min_quote_amount,
        base_available=base_available,
        quote_available=quote_available,
        best_bid=best_bid,
        best_ask=best_ask,
    )

    blockers = checks["blockers"]
    warnings = checks["warnings"]

    required_asset = (
        quote
        if checks["required_currency"]
        == "quote"
        else base
    )

    return {
        "status": (
            "ready"
            if not blockers
            else "invalid"
        ),

        # Important safety invariant:
        # this endpoint performs no Gate write and there is
        # deliberately no execute endpoint yet.
        "preview_only": True,
        "execution_implemented": False,
        "execution_enabled": False,
        "can_execute": False,
        "gate_write_required": True,
        "gate_write_performed": False,
        "write_performed": False,

        "account_id": account_id,

        "pair": {
            "id": market,
            "base": base,
            "quote": quote,
            "trade_status": str(
                pair_data.get(
                    "trade_status"
                )
                or ""
            ).lower(),
            "precision": _int_or_none(
                pair_data.get(
                    "precision"
                )
            ),
            "amount_precision": _int_or_none(
                pair_data.get(
                    "amount_precision"
                )
            ),
            "min_base_amount": (
                _decimal_text(
                    min_base_amount
                )
                if min_base_amount
                is not None
                else None
            ),
            "min_quote_amount": (
                _decimal_text(
                    min_quote_amount
                )
                if min_quote_amount
                is not None
                else None
            ),
        },

        "order": {
            "type": "limit",
            "account": "spot",
            "side": request.side,
            "price": _decimal_text(
                request.price
            ),
            "amount": _decimal_text(
                request.amount
            ),
            "total": _decimal_text(
                checks["total"]
            ),
            "time_in_force": (
                request.time_in_force
            ),
        },

        "market": {
            "best_bid": (
                _decimal_text(best_bid)
                if best_bid is not None
                else None
            ),
            "best_ask": (
                _decimal_text(best_ask)
                if best_ask is not None
                else None
            ),
            "marketable": checks[
                "marketable"
            ],
        },

        "funds": {
            "asset": required_asset,
            "available": _decimal_text(
                checks["available"]
            ),
            "required": _decimal_text(
                checks["required"]
            ),
            "remaining": _decimal_text(
                checks["remaining"]
            ),
        },

        "blockers": blockers,
        "warnings": warnings,

        # This is the shape we eventually intend to send
        # through a separate Spot read-write credential.
        # It is DISPLAY ONLY at this stage.
        "gate_payload_preview": {
            "currency_pair": market,
            "type": "limit",
            "account": "spot",
            "side": request.side,
            "amount": _decimal_text(
                request.amount
            ),
            "price": _decimal_text(
                request.price
            ),
            "time_in_force": (
                request.time_in_force
            ),
        },
    }


@router.get("/execution-capabilities")
async def trading_execution_capabilities(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):
    """
    Read-only frontend capability discovery.

    This endpoint performs no Gate call and no local
    Trading execution-state mutation.

    Trading authorization remains explicit account_id
    assignment only. Super-admin receives no wildcard.
    """
    authorized_account_ids = sorted(
        {
            item.strip().lower()
            for item in user.account_ids
            if item.strip()
        }
    )

    configured_account_ids: list[str] = []
    config_error = ""

    for account_id in authorized_account_ids:
        try:
            account = get_trading_account(
                account_id
            )

        except TradingConfigError as exc:
            config_error = str(exc)
            break

        if (
            account is not None
            and account.enabled
            and account.configured
        ):
            configured_account_ids.append(
                account_id
            )

    return {
        "execution_implemented": True,
        "execution_route_available": True,
        "live_arm_enabled": bool(
            settings.trading_limit_orders_enabled
        ),
        "required_confirmation": (
            settings
            .trading_limit_order_confirmation_text
        ),
        "cancellation_implemented": True,
        "cancellation_route_available": True,
        "cancel_arm_enabled": bool(
            settings
            .trading_order_cancels_enabled
        ),
        "cancel_required_confirmation": (
            settings
            .trading_order_cancel_confirmation_text
        ),
        "authorized_account_ids": (
            authorized_account_ids
        ),
        "configured_account_ids": (
            configured_account_ids
        ),
        "config_error": config_error,
        "gate_read_performed": False,
        "gate_write_performed": False,
        "write_performed": False,
    }


@router.post("/limit-orders/execute")
async def execute_trading_limit_order(
    request: LimitOrderExecuteRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):
    account_id = _explicit_trading_account(
        user,
        request.account_id,
    )

    explicit_ids = {
        item.strip().lower()
        for item in user.account_ids
        if item.strip()
    }

    try:
        return await execute_limit_order(
            settings=settings,
            username=user.username,
            allowed_account_ids=(
                explicit_ids
            ),
            request_id=(
                request.request_id
            ),
            account_id=account_id,
            pair=request.pair,
            side=request.side,
            price=request.price,
            amount=request.amount,
            time_in_force=(
                request.time_in_force
            ),
            confirmation=(
                request.confirmation
            ),
        )

    except TradingExecutionDenied as exc:
        raise HTTPException(
            status_code=(
                exc.status_code
            ),
            detail=exc.detail(),
        ) from exc


@router.get(
    "/limit-orders/requests/{request_id}"
)
async def get_trading_limit_order_request(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
):
    request = (
        _trading_request_for_user(
            user,
            request_id,
        )
    )

    cancellation = (
        get_order_cancellation(
            order_request_id=(
                request["request_id"]
            )
        )
    )

    order_state = (
        derive_trading_order_state(
            request=request,
            cancellation=cancellation,
        )
    )

    return {
        # This GET performs no Gate write.
        "gate_write_performed": False,
        "write_performed": False,
        "request": request,
        "order_state": order_state,
        "reconciliations": (
            list_order_reconciliations(
                request["request_id"]
            )
        ),
        "cancellation": cancellation,
        "lock": (
            get_trading_lock_for_request(
                request["request_id"]
            )
        ),
    }


@router.post(
    "/limit-orders/requests/{request_id}/cancel"
)
async def cancel_trading_limit_order(
    request_id: str,
    request: LimitOrderCancelRequest,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):
    source = (
        _trading_request_for_user(
            user,
            request_id,
        )
    )

    explicit_ids = {
        item.strip().lower()
        for item in user.account_ids
        if item.strip()
    }

    try:
        return await cancel_limit_order(
            settings=settings,
            username=user.username,
            allowed_account_ids=(
                explicit_ids
            ),
            cancel_request_id=(
                request.cancel_request_id
            ),
            order_request_id=(
                source["request_id"]
            ),
            confirmation=(
                request.confirmation
            ),
        )

    except TradingOrderCancelDenied as exc:
        raise HTTPException(
            status_code=(
                exc.status_code
            ),
            detail=exc.detail(),
        ) from exc


@router.post(
    "/limit-orders/requests/{request_id}/cancel/reconcile"
)
async def reconcile_trading_limit_order_cancellation(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):
    source = (
        _trading_request_for_user(
            user,
            request_id,
        )
    )

    explicit_ids = {
        item.strip().lower()
        for item in user.account_ids
        if item.strip()
    }

    try:
        result = await (
            reconcile_limit_order_cancellation(
                settings=settings,
                username=user.username,
                allowed_account_ids=(
                    explicit_ids
                ),
                order_request_id=(
                    source["request_id"]
                ),
            )
        )

    except TradingOrderCancelDenied as exc:
        raise HTTPException(
            status_code=(
                exc.status_code
            ),
            detail=exc.detail(),
        ) from exc

    return {
        # This route may update our local
        # cancellation audit, but Gate is
        # queried read-only.
        "gate_write_performed": False,
        "write_performed": False,
        "reconciliation": result,
    }


@router.post(
    "/limit-orders/requests/{request_id}/reconcile"
)
async def reconcile_trading_limit_order_request(
    request_id: str,
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
):
    request = (
        _trading_request_for_user(
            user,
            request_id,
        )
    )

    account_id = str(
        request["account_id"]
    ).strip().lower()

    try:
        trading_account = (
            get_trading_account(
                account_id
            )
        )

    except TradingConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    if (
        trading_account is None
        or not trading_account.enabled
        or not trading_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Isolated Spot Trading "
                "credentials are not "
                "configured for Gate account "
                f"{account_id}"
            ),
        )

    try:
        async with GateClient(
            settings,
            trading_account,
        ) as client:
            result = (
                await reconcile_spot_order_request(
                    client=client,
                    request_id=(
                        request[
                            "request_id"
                        ]
                    ),
                )
            )

    except TradingOrderReconcileError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return {
        # Reconciliation may update our local audit DB,
        # but performs Gate reads only.
        "gate_write_performed": False,
        "write_performed": False,
        "reconciliation": result,
    }




@router.get("/orders/recent")
async def trading_recent_orders(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    account_id: str = Query(
        min_length=1,
        max_length=64,
    ),
    pair: str = Query(
        default="EQTY_USDT",
        min_length=3,
        max_length=64,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
):
    """
    Return durable recent Spot order history from
    the dashboard audit database.

    This route intentionally performs no Gate request.
    """

    account_id = (
        _explicit_trading_account(
            user,
            account_id,
        )
    )

    market = _market(pair)

    requests = (
        list_order_requests_for_market(
            account_id=account_id,
            pair=market,
            limit=limit,
        )
    )

    cancellations_by_request_id = {
        str(
            request.get(
                "request_id"
            )
            or ""
        ): get_order_cancellation(
            order_request_id=str(
                request[
                    "request_id"
                ]
            )
        )
        for request in requests
        if request.get(
            "request_id"
        )
    }

    orders = build_recent_spot_orders(
        requests=requests,
        cancellations_by_request_id=(
            cancellations_by_request_id
        ),
    )

    return {
        "history_source": (
            "dashboard_audit"
        ),
        "gate_read_performed": False,
        "gate_write_performed": False,
        "write_performed": False,
        "account_id": account_id,
        "pair": market,
        "count": len(orders),
        "orders": orders,
    }

@router.get("/orders/open")
async def trading_open_orders(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
    account_id: str = Query(
        min_length=1,
        max_length=64,
    ),
    pair: str = Query(
        default="EQTY_USDT",
        min_length=3,
        max_length=64,
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
    ),
):
    """
    Read the actual open Spot orders from Gate and
    enrich them with dashboard audit/cancellation state.

    This route performs Gate reads only.
    """

    account_id = (
        _explicit_trading_account(
            user,
            account_id,
        )
    )

    market = _market(pair)

    try:
        trading_account = (
            get_trading_account(
                account_id
            )
        )

    except TradingConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    if (
        trading_account is None
        or not trading_account.enabled
        or not trading_account.configured
    ):
        raise HTTPException(
            status_code=503,
            detail=(
                "Isolated Spot Trading "
                "credentials are not "
                "configured for Gate account "
                f"{account_id}"
            ),
        )

    try:
        async with GateClient(
            settings,
            trading_account,
        ) as client:
            response = (
                await client.list_spot_orders(
                    currency_pair=market,
                    status="open",
                    page=1,
                    limit=limit,
                    account="spot",
                )
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    gate_orders = (
        [
            item
            for item in response.data
            if isinstance(item, dict)
        ]
        if isinstance(
            response.data,
            list,
        )
        else []
    )

    gate_order_ids = {
        str(
            item.get("id") or ""
        ).strip()
        for item in gate_orders
        if str(
            item.get("id") or ""
        ).strip()
    }

    gate_texts = {
        str(
            item.get("text") or ""
        ).strip()
        for item in gate_orders
        if str(
            item.get("text") or ""
        ).strip()
    }

    local_requests = (
        find_order_requests_by_gate_identity(
            account_id=account_id,
            gate_order_ids=(
                gate_order_ids
            ),
            gate_texts=gate_texts,
        )
    )

    cancellations_by_request_id = {
        str(
            request.get(
                "request_id"
            )
            or ""
        ): get_order_cancellation(
            order_request_id=str(
                request[
                    "request_id"
                ]
            )
        )
        for request in local_requests
        if request.get(
            "request_id"
        )
    }

    orders = merge_open_spot_orders(
        account_id=account_id,
        pair=market,
        gate_orders=gate_orders,
        local_requests=(
            local_requests
        ),
        cancellations_by_request_id=(
            cancellations_by_request_id
        ),
    )

    return {
        "gate_read_performed": True,
        "gate_write_performed": False,
        "write_performed": False,
        "account_id": account_id,
        "pair": market,
        "count": len(orders),
        "orders": orders,
    }

@router.get("/trades")
async def trading_trades(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
    account_id: str = Query(
        min_length=1,
        max_length=64,
    ),
    pair: str = Query(
        default="EQTY_USDT",
        min_length=3,
        max_length=64,
    ),
    limit: int = Query(
        default=40,
        ge=1,
        le=100,
    ),
):
    account_id = _explicit_trading_account(
        user,
        account_id,
    )

    market = _market(pair)

    try:
        async with GateClient(
            settings,
            None,
        ) as client:
            response = (
                await client.list_spot_trades(
                    market,
                    limit=limit,
                )
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    rows = (
        response.data
        if isinstance(response.data, list)
        else []
    )

    trades: list[dict[str, Any]] = []

    for item in rows:
        if not isinstance(item, dict):
            continue

        price = _decimal(
            item.get("price")
        )

        amount = _decimal(
            item.get("amount")
        )

        if (
            price is None
            or amount is None
        ):
            continue

        timestamp_ms = _decimal(
            item.get("create_time_ms")
        )

        if timestamp_ms is None:
            timestamp = _decimal(
                item.get("create_time")
            )

            timestamp_ms = (
                timestamp * Decimal("1000")
                if timestamp is not None
                else Decimal("0")
            )

        trades.append(
            {
                "id": str(
                    item.get("id") or ""
                ),
                "time_ms": str(
                    timestamp_ms
                ),
                "side": str(
                    item.get("side")
                    or ""
                ).lower(),
                "price": str(price),
                "amount": str(amount),
                "total": str(
                    price * amount
                ),
            }
        )

    return {
        "write_performed": False,
        "market_data_only": True,
        "account_id": account_id,
        "pair": market,
        "trades": trades,
    }


@router.get("/candles")
async def trading_candles(
    user: Annotated[
        DashboardUser,
        Depends(require_user),
    ],
    settings: Annotated[
        Settings,
        Depends(get_settings),
    ],
    account_id: str = Query(
        min_length=1,
        max_length=64,
    ),
    pair: str = Query(
        default="EQTY_USDT",
        min_length=3,
        max_length=64,
    ),
    interval: str = Query(
        default="5m",
        min_length=2,
        max_length=8,
    ),
    limit: int = Query(
        default=300,
        ge=50,
        le=1000,
    ),
):
    account_id = _explicit_trading_account(
        user,
        account_id,
    )

    market = _market(pair)

    normalized_interval = (
        interval.strip().lower()
    )

    if (
        normalized_interval
        not in _ALLOWED_INTERVALS
    ):
        raise HTTPException(
            status_code=400,
            detail="Unsupported candlestick interval",
        )

    account = _monitor_account_or_http(
        account_id
    )

    try:
        async with GateClient(
            settings,
            account,
        ) as client:
            response = (
                await client.get_spot_candlesticks(
                    market,
                    interval=normalized_interval,
                    limit=limit,
                )
            )

    except GateAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    return {
        "write_performed": False,
        "market_data_only": True,
        "account_id": account_id,
        "pair": market,
        "interval": normalized_interval,
        "candles": _normalize_candlesticks(
            response.data
        ),
    }
