from __future__ import annotations

import asyncio
import re
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from ..accounts import (
    AccountConfigError,
    get_gate_account,
    load_gate_accounts,
)
from ..config import Settings, get_settings
from ..gate_client import GateAPIError, GateClient
from ..security import DashboardUser, require_user


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
