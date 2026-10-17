from __future__ import annotations

import asyncio
import re

from decimal import (
    Decimal,
    InvalidOperation,
)
from typing import Any

from .gate_client import GateClient


_PAIR_RE = re.compile(
    r"^[A-Z0-9]+_[A-Z0-9]+$"
)


def normalize_spot_pair(
    value: str,
) -> str:
    pair = str(
        value or ""
    ).strip().upper()

    if not _PAIR_RE.fullmatch(
        pair
    ):
        raise ValueError(
            "Invalid Gate spot currency pair"
        )

    return pair


def normalize_book_interval(
    value: str,
) -> str:
    normalized = str(
        value or ""
    ).strip()

    try:
        interval = Decimal(
            normalized
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ) as exc:
        raise ValueError(
            "Invalid order-book price interval"
        ) from exc

    if (
        not interval.is_finite()
        or interval < 0
    ):
        raise ValueError(
            "Invalid order-book price interval"
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
        result = Decimal(
            str(value)
        )

    except (
        InvalidOperation,
        TypeError,
        ValueError,
    ):
        return None

    if not result.is_finite():
        return None

    return result


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


def normalize_pair_metadata(
    payload: Any,
) -> dict[str, Any]:
    data = (
        payload
        if isinstance(payload, dict)
        else {}
    )

    pair = normalize_spot_pair(
        str(
            data.get("id")
            or data.get("currency_pair")
            or ""
        )
    )

    base, quote = pair.split(
        "_",
        1,
    )

    return {
        "id":
            pair,
        "base":
            str(
                data.get("base")
                or base
            ).upper(),
        "quote":
            str(
                data.get("quote")
                or quote
            ).upper(),
        "trade_status":
            str(
                data.get("trade_status")
                or ""
            ).lower(),
        "precision":
            _int_or_none(
                data.get("precision")
            ),
        "amount_precision":
            _int_or_none(
                data.get(
                    "amount_precision"
                )
            ),
        "min_base_amount":
            (
                str(
                    data.get(
                        "min_base_amount"
                    )
                )
                if data.get(
                    "min_base_amount"
                )
                is not None
                else None
            ),
        "min_quote_amount":
            (
                str(
                    data.get(
                        "min_quote_amount"
                    )
                )
                if data.get(
                    "min_quote_amount"
                )
                is not None
                else None
            ),
    }


def normalize_order_book(
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
        if not isinstance(
            raw,
            list,
        ):
            return []

        clean: list[
            tuple[
                Decimal,
                Decimal,
            ]
        ] = []

        for item in raw:
            if (
                not isinstance(
                    item,
                    (
                        list,
                        tuple,
                    ),
                )
                or len(item) < 2
            ):
                continue

            price = _decimal(
                item[0]
            )

            amount = _decimal(
                item[1]
            )

            if (
                price is None
                or amount is None
                or price <= 0
                or amount < 0
            ):
                continue

            clean.append(
                (
                    price,
                    amount,
                )
            )

        clean.sort(
            key=lambda row: row[0],
            reverse=reverse,
        )

        return [
            {
                "price":
                    str(price),
                "amount":
                    str(amount),
            }
            for price, amount
            in clean
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
        _decimal(
            asks[0]["price"]
        )
        if asks
        else None
    )

    best_bid = (
        _decimal(
            bids[0]["price"]
        )
        if bids
        else None
    )

    spread = None
    spread_percent = None

    if (
        best_ask is not None
        and best_bid is not None
        and best_ask >= best_bid
    ):
        spread = (
            best_ask
            - best_bid
        )

        midpoint = (
            best_ask
            + best_bid
        ) / Decimal("2")

        if midpoint > 0:
            spread_percent = (
                spread
                / midpoint
                * Decimal("100")
            )

    ratio_asks = asks[:20]
    ratio_bids = bids[:20]

    ask_total = sum(
        (
            _decimal(
                item["amount"]
            )
            or Decimal("0")
        )
        for item in ratio_asks
    )

    bid_total = sum(
        (
            _decimal(
                item["amount"]
            )
            or Decimal("0")
        )
        for item in ratio_bids
    )

    depth_total = (
        ask_total
        + bid_total
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
        "id":
            data.get("id"),
        "current":
            data.get("current"),
        "update":
            data.get("update"),
        "asks":
            asks,
        "bids":
            bids,
        "bid_amount_total":
            str(bid_total),
        "ask_amount_total":
            str(ask_total),
        "buy_percent":
            str(buy_percent),
        "sell_percent":
            str(sell_percent),
        "best_ask":
            (
                str(best_ask)
                if best_ask
                is not None
                else None
            ),
        "best_bid":
            (
                str(best_bid)
                if best_bid
                is not None
                else None
            ),
        "spread":
            (
                str(spread)
                if spread
                is not None
                else None
            ),
        "spread_percent":
            (
                str(
                    spread_percent
                )
                if spread_percent
                is not None
                else None
            ),
    }


def normalize_candlesticks(
    rows: Any,
) -> list[dict[str, Any]]:
    if not isinstance(
        rows,
        list,
    ):
        return []

    result: list[
        dict[str, Any]
    ] = []

    for row in rows:
        if (
            not isinstance(
                row,
                (
                    list,
                    tuple,
                ),
            )
            or len(row) < 6
        ):
            continue

        try:
            timestamp = int(
                row[0]
            )

        except (
            TypeError,
            ValueError,
        ):
            continue

        open_price = _decimal(
            row[5]
        )

        high_price = _decimal(
            row[3]
        )

        low_price = _decimal(
            row[4]
        )

        close_price = _decimal(
            row[2]
        )

        if (
            open_price is None
            or high_price is None
            or low_price is None
            or close_price is None
        ):
            continue

        base_volume = None
        closed = None

        if len(row) >= 8:
            base_volume = str(
                row[6]
            )

            raw_closed = row[7]

            if isinstance(
                raw_closed,
                bool,
            ):
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
            last = str(
                row[6]
            ).strip().lower()

            if last in {
                "true",
                "1",
                "false",
                "0",
            }:
                closed = (
                    last
                    in {
                        "true",
                        "1",
                    }
                )

            else:
                base_volume = str(
                    row[6]
                )

        result.append(
            {
                "time":
                    timestamp,
                "open":
                    str(open_price),
                "high":
                    str(high_price),
                "low":
                    str(low_price),
                "close":
                    str(close_price),
                "quote_volume":
                    str(
                        row[1]
                        or "0"
                    ),
                "base_volume":
                    base_volume,
                "closed":
                    closed,
            }
        )

    result.sort(
        key=lambda item: item[
            "time"
        ]
    )

    return result


def normalize_trades(
    rows: Any,
) -> list[dict[str, str]]:
    if not isinstance(
        rows,
        list,
    ):
        return []

    result: list[
        dict[str, str]
    ] = []

    for item in rows:
        if not isinstance(
            item,
            dict,
        ):
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
            item.get(
                "create_time_ms"
            )
        )

        if timestamp_ms is None:
            timestamp = _decimal(
                item.get(
                    "create_time"
                )
            )

            timestamp_ms = (
                timestamp
                * Decimal("1000")
                if timestamp
                is not None
                else Decimal("0")
            )

        result.append(
            {
                "id":
                    str(
                        item.get("id")
                        or ""
                    ),
                "time_ms":
                    str(timestamp_ms),
                "side":
                    str(
                        item.get("side")
                        or ""
                    ).lower(),
                "price":
                    str(price),
                "amount":
                    str(amount),
                "total":
                    str(
                        price
                        * amount
                    ),
            }
        )

    return result


class PublicSpotMarketData:
    """
    Route-neutral adapter over Gate public Spot market data.

    It deliberately exposes no account-balance, authenticated
    order, transfer, withdrawal, bot-control, or write method.
    """

    def __init__(
        self,
        client: GateClient,
    ) -> None:
        self.client = client

    @staticmethod
    def _base() -> dict[str, Any]:
        return {
            "source":
                "gate",
            "market_data_source":
                "gate",
            "market_data_only":
                True,
            "gate_read_performed":
                True,
            "gate_write_performed":
                False,
            "write_performed":
                False,
        }

    async def catalog(
        self,
    ) -> dict[str, Any]:
        response = (
            await self.client
            .list_spot_currency_pairs()
        )

        rows = (
            response.data
            if isinstance(
                response.data,
                list,
            )
            else []
        )

        pairs = []

        for item in rows:
            if not isinstance(
                item,
                dict,
            ):
                continue

            try:
                pair = (
                    normalize_pair_metadata(
                        item
                    )
                )

            except ValueError:
                continue

            if (
                pair[
                    "trade_status"
                ]
                == "untradable"
            ):
                continue

            pairs.append(
                pair
            )

        pairs.sort(
            key=lambda item: item[
                "id"
            ]
        )

        pair_ids = {
            item["id"]
            for item in pairs
        }

        if "EQTY_USDT" in pair_ids:
            default_pair = (
                "EQTY_USDT"
            )

        else:
            default_pair = next(
                (
                    item["id"]
                    for item
                    in pairs
                    if item[
                        "quote"
                    ]
                    == "USDT"
                ),
                (
                    pairs[0]["id"]
                    if pairs
                    else ""
                ),
            )

        return {
            **self._base(),
            "pairs":
                pairs,
            "default_pair":
                default_pair,
        }

    async def snapshot(
        self,
        *,
        pair: str,
        depth: int,
        book_interval: str,
    ) -> dict[str, Any]:
        market = (
            normalize_spot_pair(
                pair
            )
        )

        normalized_interval = (
            normalize_book_interval(
                book_interval
            )
        )

        (
            pair_response,
            ticker_response,
            book_response,
        ) = await asyncio.gather(
            self.client
            .get_spot_currency_pair(
                market
            ),
            self.client
            .list_spot_tickers(
                market
            ),
            self.client
            .get_spot_order_book(
                market,
                interval=
                    normalized_interval,
                limit=max(
                    1,
                    min(
                        int(depth),
                        100,
                    ),
                ),
                with_id=True,
            ),
        )

        pair_data = (
            pair_response.data
            if isinstance(
                pair_response.data,
                dict,
            )
            else {}
        )

        if not pair_data:
            raise ValueError(
                "Gate did not return spot pair metadata"
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
                for item
                in tickers
                if (
                    isinstance(
                        item,
                        dict,
                    )
                    and str(
                        item.get(
                            "currency_pair"
                        )
                        or ""
                    ).upper()
                    == market
                )
            ),
            {},
        )

        return {
            **self._base(),
            "pair":
                normalize_pair_metadata(
                    pair_data
                ),
            "ticker":
                (
                    ticker
                    if isinstance(
                        ticker,
                        dict,
                    )
                    else {}
                ),
            "book_interval":
                normalized_interval,
            "order_book":
                normalize_order_book(
                    book_response.data
                ),
        }

    async def preview_context(
        self,
        *,
        pair: str,
        depth: int = 20,
    ) -> dict[str, Any]:
        market = (
            normalize_spot_pair(
                pair
            )
        )

        (
            pair_response,
            book_response,
        ) = await asyncio.gather(
            self.client
            .get_spot_currency_pair(
                market
            ),
            self.client
            .get_spot_order_book(
                market,
                interval="0",
                limit=max(
                    1,
                    min(
                        int(depth),
                        100,
                    ),
                ),
                with_id=True,
            ),
        )

        pair_data = (
            pair_response.data
            if isinstance(
                pair_response.data,
                dict,
            )
            else {}
        )

        if not pair_data:
            raise ValueError(
                "Gate did not return spot pair metadata"
            )

        return {
            **self._base(),
            "pair":
                normalize_pair_metadata(
                    pair_data
                ),
            "order_book":
                normalize_order_book(
                    book_response.data
                ),
        }

    async def candles(
        self,
        *,
        pair: str,
        interval: str,
        limit: int,
    ) -> dict[str, Any]:
        market = (
            normalize_spot_pair(
                pair
            )
        )

        normalized_interval = str(
            interval or ""
        ).strip().lower()

        response = (
            await self.client
            .get_spot_candlesticks(
                market,
                interval=
                    normalized_interval,
                limit=max(
                    1,
                    min(
                        int(limit),
                        1000,
                    ),
                ),
            )
        )

        return {
            **self._base(),
            "pair":
                market,
            "interval":
                normalized_interval,
            "candles":
                normalize_candlesticks(
                    response.data
                ),
        }

    async def trades(
        self,
        *,
        pair: str,
        limit: int,
    ) -> dict[str, Any]:
        market = (
            normalize_spot_pair(
                pair
            )
        )

        response = (
            await self.client
            .list_spot_trades(
                market,
                limit=max(
                    1,
                    min(
                        int(limit),
                        1000,
                    ),
                ),
            )
        )

        rows = normalize_trades(
            response.data
        )

        return {
            **self._base(),
            "pair":
                market,
            "count":
                len(rows),
            "trades":
                rows,
        }
