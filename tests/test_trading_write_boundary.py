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
    TradingRateLimitExceeded,
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
