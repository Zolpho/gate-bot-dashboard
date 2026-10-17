from __future__ import annotations

import ast

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.public_spot_market_data import (
    PublicSpotMarketData,
)


class FakePublicGateClient:
    def __init__(
        self,
    ) -> None:
        self.calls = []

    async def list_spot_currency_pairs(
        self,
    ):
        self.calls.append(
            (
                "list_spot_currency_pairs",
                (),
                {},
            )
        )

        return SimpleNamespace(
            data=[
                {
                    "id": "ETH_USDT",
                    "base": "ETH",
                    "quote": "USDT",
                    "trade_status": "tradable",
                    "precision": 2,
                    "amount_precision": 5,
                    "min_base_amount": "0.001",
                    "min_quote_amount": "5",
                },
                {
                    "id": "EQTY_USDT",
                    "base": "EQTY",
                    "quote": "USDT",
                    "trade_status": "tradable",
                    "precision": 6,
                    "amount_precision": 2,
                    "min_base_amount": "100",
                    "min_quote_amount": "5",
                },
                {
                    "id": "OLD_USDT",
                    "base": "OLD",
                    "quote": "USDT",
                    "trade_status": "untradable",
                    "precision": 4,
                    "amount_precision": 2,
                },
            ]
        )

    async def get_spot_currency_pair(
        self,
        pair,
    ):
        self.calls.append(
            (
                "get_spot_currency_pair",
                (pair,),
                {},
            )
        )

        return SimpleNamespace(
            data={
                "id": pair,
                "base": "ETH",
                "quote": "USDT",
                "trade_status": "tradable",
                "precision": 2,
                "amount_precision": 5,
                "min_base_amount": "0.001",
                "min_quote_amount": "5",
            }
        )

    async def list_spot_tickers(
        self,
        pair,
    ):
        self.calls.append(
            (
                "list_spot_tickers",
                (pair,),
                {},
            )
        )

        return SimpleNamespace(
            data=[
                {
                    "currency_pair": pair,
                    "last": "3501.2",
                    "highest_bid": "3501.1",
                    "lowest_ask": "3501.3",
                    "high_24h": "3600",
                    "low_24h": "3400",
                    "base_volume": "12345",
                    "quote_volume": "43210000",
                }
            ]
        )

    async def get_spot_order_book(
        self,
        pair,
        *,
        interval,
        limit,
        with_id,
    ):
        self.calls.append(
            (
                "get_spot_order_book",
                (pair,),
                {
                    "interval":
                        interval,
                    "limit":
                        limit,
                    "with_id":
                        with_id,
                },
            )
        )

        return SimpleNamespace(
            data={
                "id": 99,
                "current": 100,
                "update": 101,
                "asks": [
                    ["3502", "2"],
                    ["3501.3", "1"],
                ],
                "bids": [
                    ["3500", "4"],
                    ["3501.1", "3"],
                ],
            }
        )

    async def get_spot_candlesticks(
        self,
        pair,
        *,
        interval,
        limit,
    ):
        self.calls.append(
            (
                "get_spot_candlesticks",
                (pair,),
                {
                    "interval":
                        interval,
                    "limit":
                        limit,
                },
            )
        )

        return SimpleNamespace(
            data=[
                [
                    "200",
                    "20000",
                    "3510",
                    "3520",
                    "3490",
                    "3500",
                    "5.7",
                    "true",
                ],
                [
                    "100",
                    "18000",
                    "3500",
                    "3510",
                    "3480",
                    "3490",
                    "5.1",
                    "true",
                ],
            ]
        )

    async def list_spot_trades(
        self,
        pair,
        *,
        limit,
    ):
        self.calls.append(
            (
                "list_spot_trades",
                (pair,),
                {
                    "limit":
                        limit,
                },
            )
        )

        return SimpleNamespace(
            data=[
                {
                    "id": "1",
                    "create_time_ms":
                        "1234567890",
                    "side": "buy",
                    "price": "3501.2",
                    "amount": "0.2",
                },
                {
                    "id": "2",
                    "create_time":
                        "1234568",
                    "side": "sell",
                    "price": "3500",
                    "amount": "0.1",
                },
            ]
        )


@pytest.mark.asyncio
async def test_catalog_uses_only_public_pair_catalog():
    client = FakePublicGateClient()

    result = await PublicSpotMarketData(
        client
    ).catalog()

    assert result[
        "source"
    ] == "gate"

    assert result[
        "market_data_source"
    ] == "gate"

    assert result[
        "gate_read_performed"
    ] is True

    assert result[
        "gate_write_performed"
    ] is False

    assert [
        row["id"]
        for row in result[
            "pairs"
        ]
    ] == [
        "EQTY_USDT",
        "ETH_USDT",
    ]

    assert result[
        "default_pair"
    ] == "EQTY_USDT"

    assert [
        call[0]
        for call in client.calls
    ] == [
        "list_spot_currency_pairs",
    ]


@pytest.mark.asyncio
async def test_snapshot_combines_only_public_gate_market_reads():
    client = FakePublicGateClient()

    result = await PublicSpotMarketData(
        client
    ).snapshot(
        pair="eth_usdt",
        depth=20,
        book_interval="0.1",
    )

    assert result[
        "pair"
    ][
        "id"
    ] == "ETH_USDT"

    assert result[
        "ticker"
    ][
        "last"
    ] == "3501.2"

    assert result[
        "book_interval"
    ] == "0.1"

    assert result[
        "order_book"
    ][
        "best_ask"
    ] == "3501.3"

    assert result[
        "order_book"
    ][
        "best_bid"
    ] == "3501.1"

    assert result[
        "gate_read_performed"
    ] is True

    assert result[
        "gate_write_performed"
    ] is False

    assert {
        call[0]
        for call in client.calls
    } == {
        "get_spot_currency_pair",
        "list_spot_tickers",
        "get_spot_order_book",
    }


@pytest.mark.asyncio
async def test_preview_context_has_market_data_but_no_balance_read():
    client = FakePublicGateClient()

    result = await PublicSpotMarketData(
        client
    ).preview_context(
        pair="ETH_USDT",
    )

    assert result[
        "pair"
    ][
        "precision"
    ] == 2

    assert result[
        "order_book"
    ][
        "best_bid"
    ] == "3501.1"

    assert {
        call[0]
        for call in client.calls
    } == {
        "get_spot_currency_pair",
        "get_spot_order_book",
    }

    assert all(
        call[0]
        != "list_spot_accounts"
        for call in client.calls
    )


@pytest.mark.asyncio
async def test_candles_are_real_gate_shape_and_chronological():
    client = FakePublicGateClient()

    result = await PublicSpotMarketData(
        client
    ).candles(
        pair="ETH_USDT",
        interval="1h",
        limit=300,
    )

    candles = result[
        "candles"
    ]

    assert [
        row["time"]
        for row in candles
    ] == [
        100,
        200,
    ]

    assert candles[0] == {
        "time": 100,
        "open": "3490",
        "high": "3510",
        "low": "3480",
        "close": "3500",
        "quote_volume": "18000",
        "base_volume": "5.1",
        "closed": True,
    }

    assert result[
        "gate_read_performed"
    ] is True

    assert result[
        "gate_write_performed"
    ] is False


@pytest.mark.asyncio
async def test_trades_are_normalized_from_public_gate_rows():
    client = FakePublicGateClient()

    result = await PublicSpotMarketData(
        client
    ).trades(
        pair="ETH_USDT",
        limit=40,
    )

    assert result[
        "count"
    ] == 2

    assert result[
        "trades"
    ][0] == {
        "id": "1",
        "time_ms": "1234567890",
        "side": "buy",
        "price": "3501.2",
        "amount": "0.2",
        "total": "700.24",
    }

    assert result[
        "trades"
    ][1][
        "time_ms"
    ] == "1234568000"

    assert result[
        "gate_write_performed"
    ] is False


def test_public_market_service_has_no_private_or_write_gate_calls():
    path = Path(
        "app/public_spot_market_data.py"
    )

    tree = ast.parse(
        path.read_text()
    )

    called_attributes = {
        node.func.attr
        for node in ast.walk(
            tree
        )
        if (
            isinstance(
                node,
                ast.Call,
            )
            and isinstance(
                node.func,
                ast.Attribute,
            )
        )
    }

    allowed_gate_calls = {
        "list_spot_currency_pairs",
        "get_spot_currency_pair",
        "list_spot_tickers",
        "get_spot_order_book",
        "get_spot_candlesticks",
        "list_spot_trades",
    }

    gate_like_calls = {
        name
        for name
        in called_attributes
        if (
            name.startswith(
                "list_spot_"
            )
            or name.startswith(
                "get_spot_"
            )
            or name.startswith(
                "create_"
            )
            or name.startswith(
                "cancel_"
            )
            or name.startswith(
                "amend_"
            )
        )
    }

    assert (
        gate_like_calls
        == allowed_gate_calls
    )

    forbidden = {
        "list_spot_accounts",
        "create_spot_order",
        "cancel_spot_order",
        "amend_spot_order",
        "get_spot_order",
        "list_spot_orders",
        "create_withdrawal",
        "create_sub_account_transfer",
    }

    assert not (
        called_attributes
        & forbidden
    )


def test_service_is_wired_to_demo_market_reads_and_preview_create_only():
    source = Path(
        "app/api/trading.py"
    ).read_text()

    tree = ast.parse(
        source
    )

    functions = {
        node.name: node
        for node in tree.body
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        )
    }

    direct_public_reads = {
        "trading_catalog",
        "trading_snapshot",
        "trading_trades",
        "trading_candles",
    }

    for name in direct_public_reads:
        body = ast.unparse(
            functions[name]
        )

        assert (
            "PublicSpotMarketData"
            in body
        ), name

    helper = ast.unparse(
        functions[
            "_demo_public_limit_order_preview"
        ]
    )

    assert (
        "PublicSpotMarketData"
        in helper
    )

    assert (
        "preview_context"
        in helper
    )

    for name in (
        "preview_limit_order",
        "execute_trading_limit_order",
    ):
        body = ast.unparse(
            functions[name]
        )

        assert (
            "_demo_public_limit_order_preview"
            in body
        ), name

    still_demo_local = {
        "cancel_trading_limit_order",
        "amend_trading_limit_order",
        "trading_open_orders",
        "trading_recent_orders",
    }

    for name in still_demo_local:
        body = ast.unparse(
            functions[name]
        )

        assert (
            "PublicSpotMarketData"
            not in body
        ), name

        assert (
            "_demo_public_limit_order_preview"
            not in body
        ), name

