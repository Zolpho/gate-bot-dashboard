import pytest
from fastapi import HTTPException

from app.api.trading import (
    _explicit_trading_account,
    _normalize_candlesticks,
    _normalize_order_book,
)
from app.security import DashboardUser


def test_trading_uses_explicit_account_scope():
    user = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )

    assert (
        _explicit_trading_account(
            user,
            "ARNOLD",
        )
        == "arnold"
    )


def test_super_admin_has_no_trading_wildcard():
    user = DashboardUser(
        username="admin",
        role="super_admin",
        account_ids=("zolnode",),
    )

    try:
        _explicit_trading_account(
            user,
            "arnold",
        )
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError(
            "Super-admin trading wildcard was allowed"
        )


def test_normalize_gate_candlesticks():
    rows = [
        [
            "1700000060",
            "100.5",
            "1.20",
            "1.25",
            "1.10",
            "1.15",
            "82.4",
            "true",
        ],
        [
            "1700000000",
            "90",
            "1.15",
            "1.20",
            "1.05",
            "1.10",
            "80",
            "true",
        ],
    ]

    result = _normalize_candlesticks(rows)

    assert [
        item["time"]
        for item in result
    ] == [
        1700000000,
        1700000060,
    ]

    assert result[0]["open"] == "1.10"
    assert result[1]["close"] == "1.20"
    assert result[1]["base_volume"] == "82.4"
    assert result[1]["closed"] is True


def test_normalize_order_book_and_spread():
    result = _normalize_order_book(
        {
            "id": 123,
            "asks": [
                ["1.03", "4"],
                ["1.02", "3"],
            ],
            "bids": [
                ["0.99", "2"],
                ["1.00", "1"],
            ],
        }
    )

    assert (
        result["asks"][0]["price"]
        == "1.02"
    )

    assert (
        result["bids"][0]["price"]
        == "1.00"
    )

    assert result["best_ask"] == "1.02"
    assert result["best_bid"] == "1.00"
    assert result["spread"] == "0.02"


def test_book_interval_validation():
    from app.api.trading import _book_interval

    assert _book_interval("0") == "0"
    assert _book_interval("0.000001") == "0.000001"
    assert _book_interval("0.001000") == "0.001"


def test_order_book_depth_ratio():
    result = _normalize_order_book(
        {
            "asks": [
                ["1.01", "25"],
                ["1.02", "25"],
            ],
            "bids": [
                ["1.00", "50"],
                ["0.99", "50"],
            ],
        }
    )

    assert result["bid_amount_total"] == "100"
    assert result["ask_amount_total"] == "50"

    assert (
        result["buy_percent"]
        == "66.66666666666666666666666667"
    )

    assert (
        result["sell_percent"]
        == "33.33333333333333333333333333"
    )


def test_order_book_depth_ratio_uses_top_20_levels():
    asks = [
        ["2", "1"]
        for _ in range(20)
    ]

    bids = [
        ["1", "1"]
        for _ in range(20)
    ]

    # Huge 21st levels must not affect the displayed ratio.
    asks.append(["3", "100000"])
    bids.append(["0.5", "200000"])

    result = _normalize_order_book(
        {
            "asks": asks,
            "bids": bids,
        }
    )

    assert result["ask_amount_total"] == "20"
    assert result["bid_amount_total"] == "20"
    assert result["buy_percent"] == "50.0"
    assert result["sell_percent"] == "50.0"


def test_limit_order_buy_preflight_ready():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="buy",
        time_in_force="gtc",
        price=Decimal("2"),
        amount=Decimal("3"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=3,
        min_base_amount=Decimal("0.1"),
        min_quote_amount=Decimal("1"),
        base_available=Decimal("10"),
        quote_available=Decimal("10"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2.1"),
    )

    assert result["blockers"] == []
    assert result["total"] == Decimal("6")
    assert result["required"] == Decimal("6")
    assert result["available"] == Decimal("10")
    assert result["remaining"] == Decimal("4")
    assert result["marketable"] is False


def test_limit_order_buy_insufficient_quote():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="buy",
        time_in_force="gtc",
        price=Decimal("2"),
        amount=Decimal("6"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=3,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("100"),
        quote_available=Decimal("10"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2.1"),
    )

    assert any(
        "Insufficient" in item
        for item in result["blockers"]
    )


def test_limit_order_post_only_crossing_is_blocked():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="buy",
        time_in_force="poc",
        price=Decimal("2.1"),
        amount=Decimal("1"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=3,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("100"),
        quote_available=Decimal("100"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2"),
    )

    assert result["marketable"] is True

    assert any(
        "Post-only" in item
        for item in result["blockers"]
    )


def test_limit_order_precision_is_enforced():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="sell",
        time_in_force="gtc",
        price=Decimal("1.234"),
        amount=Decimal("1.111"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=2,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("100"),
        quote_available=Decimal("100"),
        best_bid=Decimal("1"),
        best_ask=Decimal("2"),
    )

    assert any(
        "Price exceeds" in item
        for item in result["blockers"]
    )

    assert any(
        "Amount exceeds" in item
        for item in result["blockers"]
    )


def test_limit_order_sell_uses_base_balance():
    from decimal import Decimal

    from app.api.trading import (
        _limit_order_preflight,
    )

    result = _limit_order_preflight(
        side="sell",
        time_in_force="gtc",
        price=Decimal("2"),
        amount=Decimal("11"),
        trade_status="tradable",
        price_precision=2,
        amount_precision=0,
        min_base_amount=None,
        min_quote_amount=None,
        base_available=Decimal("10"),
        quote_available=Decimal("999"),
        best_bid=Decimal("1.9"),
        best_ask=Decimal("2.1"),
    )

    assert result["required_currency"] == "base"

    assert any(
        "Insufficient" in item
        for item in result["blockers"]
    )


@pytest.mark.asyncio
async def test_limit_order_preview_blocks_above_configured_notional(
    monkeypatch,
):
    from decimal import Decimal

    import app.api.trading as trading_api

    from app.accounts import (
        GateAccountConfig,
    )
    from app.config import Settings
    from app.gate_client import (
        GateResponse,
    )

    user = DashboardUser(
        username="arnold",
        role="account_operator",
        account_ids=("arnold",),
    )

    monitor = GateAccountConfig(
        id="arnold",
        name="arnold",
        api_key="monitor-key",
        api_secret="monitor-secret",
        enabled=True,
        account_type="subaccount",
        gate_uid="58601346",
    )

    monkeypatch.setattr(
        trading_api,
        "_monitor_account_or_http",
        lambda account_id: (
            monitor
            if account_id == "arnold"
            else None
        ),
    )

    class FakeGateClient:
        def __init__(
            self,
            settings,
            account,
        ):
            self.settings = settings
            self.account = account

        async def __aenter__(
            self,
        ):
            return self

        async def __aexit__(
            self,
            exc_type,
            exc,
            tb,
        ):
            return None

        async def get_spot_currency_pair(
            self,
            pair,
        ):
            assert pair == "EQTY_USDT"

            data = {
                "id": "EQTY_USDT",
                "base": "EQTY",
                "quote": "USDT",
                "trade_status": "tradable",
                "precision": 6,
                "amount_precision": 0,
                "min_base_amount": "1",
                "min_quote_amount": "3",
            }

            return GateResponse(
                data=data,
                status_code=200,
                headers={},
                raw=data,
            )

        async def list_spot_accounts(
            self,
        ):
            data = [
                {
                    "currency": "EQTY",
                    "available": "100000",
                    "locked": "0",
                },
                {
                    "currency": "USDT",
                    "available": "100",
                    "locked": "0",
                },
            ]

            return GateResponse(
                data=data,
                status_code=200,
                headers={},
                raw=data,
            )

        async def get_spot_order_book(
            self,
            pair,
            *,
            interval,
            limit,
            with_id,
        ):
            assert pair == "EQTY_USDT"
            assert interval == "0"
            assert limit == 20
            assert with_id is True

            data = {
                "id": 1,
                "asks": [
                    [
                        "0.002100",
                        "10000",
                    ],
                ],
                "bids": [
                    [
                        "0.001900",
                        "10000",
                    ],
                ],
            }

            return GateResponse(
                data=data,
                status_code=200,
                headers={},
                raw=data,
            )

    monkeypatch.setattr(
        trading_api,
        "GateClient",
        FakeGateClient,
    )

    request = (
        trading_api
        .LimitOrderPreviewRequest(
            account_id="arnold",
            pair="EQTY_USDT",
            side="buy",
            price=Decimal(
                "0.002000"
            ),
            amount=Decimal(
                "3000"
            ),
            time_in_force="gtc",
        )
    )

    result = await (
        trading_api
        .preview_limit_order(
            request=request,
            user=user,
            settings=Settings(
                _env_file=None,
                trading_limit_order_max_quote_notional=(
                    Decimal("5")
                ),
            ),
        )
    )

    assert result["status"] == "invalid"

    assert (
        result["gate_write_performed"]
        is False
    )

    assert (
        result["write_performed"]
        is False
    )

    assert (
        result["order"]["total"]
        == "6"
    )

    assert (
        result["order"][
            "max_quote_notional"
        ]
        == "5"
    )

    assert (
        result["order"][
            "max_quote_currency"
        ]
        == "USDT"
    )

    assert (
        "Order total exceeds configured "
        "maximum (5 USDT)."
        in result["blockers"]
    )


def test_get_spot_order_is_signed_get(monkeypatch):
    import asyncio

    from app.gate_client import (
        GateClient,
        GateResponse,
    )

    calls = []

    async def fake_request(
        self,
        method,
        endpoint,
        *,
        params=None,
        json_body=None,
        signed=True,
        extra_headers=None,
    ):
        calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "params": params,
                "signed": signed,
            }
        )

        return GateResponse(
            data={},
            status_code=200,
            headers={},
            raw={},
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = GateClient()

    try:
        asyncio.run(
            client.get_spot_order(
                "t-eq-test",
                currency_pair=(
                    "EQTY_USDT"
                ),
            )
        )
    finally:
        asyncio.run(
            client.close()
        )

    assert calls == [
        {
            "method": "GET",
            "endpoint": (
                "/spot/orders/t-eq-test"
            ),
            "params": [
                (
                    "currency_pair",
                    "EQTY_USDT",
                ),
                (
                    "account",
                    "spot",
                ),
            ],
            "signed": True,
        }
    ]


def test_open_spot_orders_reject_time_filter():
    import asyncio

    from app.gate_client import (
        GateClient,
    )

    client = GateClient()

    try:
        with pytest.raises(
            ValueError,
            match="do not support",
        ):
            asyncio.run(
                client.list_spot_orders(
                    currency_pair=(
                        "EQTY_USDT"
                    ),
                    status="open",
                    from_timestamp=1,
                )
            )
    finally:
        asyncio.run(
            client.close()
        )
