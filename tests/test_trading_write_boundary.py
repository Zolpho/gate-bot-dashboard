from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import (
    delete,
    func,
    select,
)

from app.config import Settings
from app.db import (
    init_db,
    session_scope,
)
from app.gate_client import (
    GateClient,
    GateResponse,
)
from app.models import (
    TradingRateLimitEvent,
)
from app.trading_rate_limit import (
    TRADING_LIMIT_ORDER_EXECUTE,
    TRADING_ORDER_CANCEL,
    TradingRateLimitExceeded,
    enforce_trading_cancel_rate_limit,
    enforce_trading_rate_limit,
)


init_db()


@pytest.fixture(autouse=True)
def clean_rate_events():
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TradingRateLimitEvent
                )
            )

    clear()
    yield
    clear()


def settings_for_limit(
    **kwargs,
):
    values = {
        "trading_rate_limit_enabled": True,
        "trading_limit_order_user_limit": 5,
        "trading_limit_order_user_window_seconds": 600,
        "trading_limit_order_account_limit": 10,
        "trading_limit_order_account_window_seconds": 600,
    }

    values.update(kwargs)

    return Settings(
        _env_file=None,
        **values,
    )


def test_create_spot_order_is_single_signed_post(
    monkeypatch,
):
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
                "body": json_body,
                "signed": signed,
                "headers": extra_headers,
            }
        )

        return GateResponse(
            data={
                "id": "123",
                "status": "open",
            },
            status_code=201,
            headers={},
            raw={
                "id": "123",
                "status": "open",
            },
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    payload = {
        "text": "t-eq-test",
        "currency_pair": "EQTY_USDT",
        "type": "limit",
        "account": "spot",
        "side": "buy",
        "amount": "1000",
        "price": "0.0017",
        "time_in_force": "gtc",
    }

    client = GateClient()

    try:
        response = asyncio.run(
            client.create_spot_order(
                payload,
                expires_at_ms=(
                    1787320005000
                ),
            )
        )
    finally:
        asyncio.run(
            client.close()
        )

    assert (
        response.status_code
        == 201
    )

    assert calls == [
        {
            "method": "POST",
            "endpoint": "/spot/orders",
            "body": payload,
            "signed": True,
            "headers": {
                "X-Gate-Exptime":
                    "1787320005000",
            },
        }
    ]


def test_create_spot_order_rejects_market_order():
    client = GateClient()

    try:
        with pytest.raises(
            ValueError,
            match="Only limit",
        ):
            asyncio.run(
                client.create_spot_order(
                    {
                        "text": "t-eq-test",
                        "currency_pair":
                            "EQTY_USDT",
                        "type": "market",
                        "account": "spot",
                        "side": "buy",
                        "amount": "10",
                        "time_in_force": "ioc",
                    },
                    expires_at_ms=1,
                )
            )
    finally:
        asyncio.run(
            client.close()
        )


def test_trading_user_rate_limit():
    settings = settings_for_limit(
        trading_limit_order_user_limit=1,
        trading_limit_order_account_limit=10,
    )

    enforce_trading_rate_limit(
        settings=settings,
        username="alice",
        account_id="arnold",
    )

    with pytest.raises(
        TradingRateLimitExceeded,
    ) as caught:
        enforce_trading_rate_limit(
            settings=settings,
            username="alice",
            account_id="eqtydao",
        )

    assert (
        caught.value.scope
        == "user"
    )


def test_trading_account_rate_limit():
    settings = settings_for_limit(
        trading_limit_order_user_limit=10,
        trading_limit_order_account_limit=1,
    )

    enforce_trading_rate_limit(
        settings=settings,
        username="alice",
        account_id="arnold",
    )

    with pytest.raises(
        TradingRateLimitExceeded,
    ) as caught:
        enforce_trading_rate_limit(
            settings=settings,
            username="bob",
            account_id="arnold",
        )

    assert (
        caught.value.scope
        == "account"
    )


def test_disabled_rate_limit_does_not_record_event():
    settings = settings_for_limit(
        trading_rate_limit_enabled=False,
    )

    result = enforce_trading_rate_limit(
        settings=settings,
        username="alice",
        account_id="arnold",
    )

    assert result is None

    with session_scope() as db:
        count = int(
            db.scalar(
                select(
                    func.count(
                        TradingRateLimitEvent.id
                    )
                )
            )
            or 0
        )

    assert count == 0


def test_cancel_rate_limit_is_independent_from_create_bucket():
    settings = settings_for_limit(
        trading_limit_order_user_limit=1,
        trading_limit_order_account_limit=1,
        trading_order_cancel_user_limit=1,
        trading_order_cancel_user_window_seconds=600,
        trading_order_cancel_account_limit=1,
        trading_order_cancel_account_window_seconds=600,
    )

    create_result = enforce_trading_rate_limit(
        settings=settings,
        username="alice",
        account_id="arnold",
    )

    cancel_result = enforce_trading_cancel_rate_limit(
        settings=settings,
        username="alice",
        account_id="arnold",
    )

    assert (
        create_result["action"]
        == TRADING_LIMIT_ORDER_EXECUTE
    )

    assert (
        cancel_result["action"]
        == TRADING_ORDER_CANCEL
    )

    # Each independent action bucket is now full.
    with pytest.raises(
        TradingRateLimitExceeded
    ) as create_caught:
        enforce_trading_rate_limit(
            settings=settings,
            username="alice",
            account_id="arnold",
        )

    with pytest.raises(
        TradingRateLimitExceeded
    ) as cancel_caught:
        enforce_trading_cancel_rate_limit(
            settings=settings,
            username="alice",
            account_id="arnold",
        )

    assert (
        create_caught.value.detail()["action"]
        == TRADING_LIMIT_ORDER_EXECUTE
    )

    assert (
        cancel_caught.value.detail()["action"]
        == TRADING_ORDER_CANCEL
    )

    with session_scope() as db:
        rows = db.scalars(
            select(
                TradingRateLimitEvent
            ).order_by(
                TradingRateLimitEvent.id.asc()
            )
        ).all()

    assert [
        row.action
        for row in rows
    ] == [
        TRADING_LIMIT_ORDER_EXECUTE,
        TRADING_ORDER_CANCEL,
    ]


def test_cancel_rate_limit_rejection_is_explicit_no_write():
    settings = settings_for_limit(
        trading_order_cancel_user_limit=1,
        trading_order_cancel_user_window_seconds=600,
        trading_order_cancel_account_limit=100,
        trading_order_cancel_account_window_seconds=600,
    )

    enforce_trading_cancel_rate_limit(
        settings=settings,
        username="alice",
        account_id="arnold",
    )

    with pytest.raises(
        TradingRateLimitExceeded
    ) as caught:
        enforce_trading_cancel_rate_limit(
            settings=settings,
            username="alice",
            account_id="arnold",
        )

    detail = caught.value.detail()

    assert detail["scope"] == "user"
    assert detail["action"] == TRADING_ORDER_CANCEL
    assert detail["limit"] == 1

    assert (
        detail["gate_write_performed"]
        is False
    )

    assert (
        detail["write_performed"]
        is False
    )

    assert (
        caught.value.retry_after_seconds
        >= 1
    )


def test_amend_spot_order_is_single_signed_patch(
    monkeypatch,
):
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
        calls.append({
            "method": method,
            "endpoint": endpoint,
            "params": params,
            "json_body": json_body,
            "signed": signed,
            "extra_headers": extra_headers,
        })

        return GateResponse(
            data={
                "id": "123456789",
                "currency_pair": "EQTY_USDT",
                "account": "spot",
                "status": "open",
                "price": "0.0016",
            },
            status_code=200,
            headers={},
            raw={},
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = object.__new__(
        GateClient
    )

    result = asyncio.run(
        client.amend_spot_order(
            "123456789",
            currency_pair="eqty_usdt",
            price="0.0016000",
            expires_at_ms=1234567890000,
            account="spot",
        )
    )

    assert result.status_code == 200

    assert len(calls) == 1

    assert calls[0] == {
        "method": "PATCH",
        "endpoint":
            "/spot/orders/123456789",
        "params": None,
        "json_body": {
            "currency_pair":
                "EQTY_USDT",
            "account":
                "spot",
            "price":
                "0.0016",
        },
        "signed": True,
        "extra_headers": {
            "X-Gate-Exptime":
                "1234567890000",
        },
    }


@pytest.mark.parametrize(
    "order_id",
    [
        "",
        " ",
        "t-eq-example",
        "123/456",
        "123?456",
        "123#456",
    ],
)
def test_amend_spot_order_requires_real_numeric_gate_id(
    monkeypatch,
    order_id,
):
    calls = []

    async def fake_request(
        self,
        method,
        endpoint,
        **kwargs,
    ):
        calls.append(
            (
                method,
                endpoint,
            )
        )

        raise AssertionError(
            "PATCH must not be attempted"
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = object.__new__(
        GateClient
    )

    with pytest.raises(
        ValueError,
    ):
        asyncio.run(
            client.amend_spot_order(
                order_id,
                currency_pair="EQTY_USDT",
                price="0.0016",
                expires_at_ms=123,
            )
        )

    assert calls == []


@pytest.mark.parametrize(
    "currency_pair",
    [
        "",
        " ",
        "EQTYUSDT",
    ],
)
def test_amend_spot_order_requires_spot_pair(
    monkeypatch,
    currency_pair,
):
    calls = []

    async def fake_request(
        self,
        method,
        endpoint,
        **kwargs,
    ):
        calls.append(
            (
                method,
                endpoint,
            )
        )

        raise AssertionError(
            "PATCH must not be attempted"
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = object.__new__(
        GateClient
    )

    with pytest.raises(
        ValueError,
    ):
        asyncio.run(
            client.amend_spot_order(
                "123456789",
                currency_pair=(
                    currency_pair
                ),
                price="0.0016",
                expires_at_ms=123,
            )
        )

    assert calls == []


def test_amend_spot_order_rejects_non_spot_account(
    monkeypatch,
):
    calls = []

    async def fake_request(
        self,
        method,
        endpoint,
        **kwargs,
    ):
        calls.append(
            (
                method,
                endpoint,
            )
        )

        raise AssertionError(
            "PATCH must not be attempted"
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = object.__new__(
        GateClient
    )

    with pytest.raises(
        ValueError,
        match="account must be spot",
    ):
        asyncio.run(
            client.amend_spot_order(
                "123456789",
                currency_pair="EQTY_USDT",
                price="0.0016",
                expires_at_ms=123,
                account="margin",
            )
        )

    assert calls == []


@pytest.mark.parametrize(
    "price",
    [
        "",
        "0",
        "-0.001",
        "nan",
        "inf",
        "-inf",
        "not-a-price",
    ],
)
def test_amend_spot_order_rejects_invalid_price(
    monkeypatch,
    price,
):
    calls = []

    async def fake_request(
        self,
        method,
        endpoint,
        **kwargs,
    ):
        calls.append(
            (
                method,
                endpoint,
            )
        )

        raise AssertionError(
            "PATCH must not be attempted"
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = object.__new__(
        GateClient
    )

    with pytest.raises(
        ValueError,
    ):
        asyncio.run(
            client.amend_spot_order(
                "123456789",
                currency_pair="EQTY_USDT",
                price=price,
                expires_at_ms=123,
            )
        )

    assert calls == []


@pytest.mark.parametrize(
    "expires_at_ms",
    [
        0,
        -1,
        -5000,
    ],
)
def test_amend_spot_order_requires_positive_expiry(
    monkeypatch,
    expires_at_ms,
):
    calls = []

    async def fake_request(
        self,
        method,
        endpoint,
        **kwargs,
    ):
        calls.append(
            (
                method,
                endpoint,
            )
        )

        raise AssertionError(
            "PATCH must not be attempted"
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = object.__new__(
        GateClient
    )

    with pytest.raises(
        ValueError,
        match="expires_at_ms",
    ):
        asyncio.run(
            client.amend_spot_order(
                "123456789",
                currency_pair="EQTY_USDT",
                price="0.0016",
                expires_at_ms=(
                    expires_at_ms
                ),
            )
        )

    assert calls == []
