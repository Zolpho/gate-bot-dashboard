from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

import app.api.trading as trading_api

from app.accounts import (
    GateAccountConfig,
)
from app.config import Settings
from app.security import (
    DashboardUser,
)
from app.trading_execution import (
    TradingExecutionDenied,
)


ARNOLD_USER = DashboardUser(
    username="alice",
    role="account_operator",
    account_ids=("arnold",),
)

ADMIN_WITH_ARNOLD = DashboardUser(
    username="admin",
    role="super_admin",
    account_ids=("arnold",),
)

ADMIN_WITHOUT_ARNOLD = DashboardUser(
    username="admin",
    role="super_admin",
    account_ids=("zolnode",),
)

TRADING_ACCOUNT = GateAccountConfig(
    id="arnold",
    name="arnold",
    api_key="trading-key",
    api_secret="trading-secret",
    enabled=True,
    account_type="subaccount",
    gate_uid="58601346",
)


def execute_payload():
    return (
        trading_api
        .LimitOrderExecuteRequest(
            request_id="request-api-a",
            account_id="arnold",
            pair="EQTY_USDT",
            side="buy",
            price=Decimal(
                "0.0017"
            ),
            amount=Decimal(
                "1000"
            ),
            time_in_force="gtc",
            confirmation="LIMIT ORDER",
        )
    )


def settings():
    return Settings(
        _env_file=None,
        trading_limit_orders_enabled=False,
    )


@pytest.mark.asyncio
async def test_execute_api_preserves_explicit_account_scope(
    monkeypatch,
):
    calls = []

    async def fake_execute(
        **kwargs,
    ):
        calls.append(kwargs)

        return {
            "status": "submitted",
        }

    monkeypatch.setattr(
        trading_api,
        "execute_limit_order",
        fake_execute,
    )

    request = execute_payload()

    request.account_id = "eqtydao"

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .execute_trading_limit_order(
                request=request,
                user=ARNOLD_USER,
                settings=settings(),
            )
        )

    assert (
        caught.value.status_code
        == 403
    )

    assert calls == []


@pytest.mark.asyncio
async def test_super_admin_has_no_execute_wildcard(
    monkeypatch,
):
    calls = []

    async def fake_execute(
        **kwargs,
    ):
        calls.append(kwargs)

        return {}

    monkeypatch.setattr(
        trading_api,
        "execute_limit_order",
        fake_execute,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .execute_trading_limit_order(
                request=execute_payload(),
                user=(
                    ADMIN_WITHOUT_ARNOLD
                ),
                settings=settings(),
            )
        )

    assert (
        caught.value.status_code
        == 403
    )

    assert calls == []


@pytest.mark.asyncio
async def test_execute_api_passes_only_explicit_ids(
    monkeypatch,
):
    captured = {}

    async def fake_execute(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return {
            "status": "disabled-test",
        }

    monkeypatch.setattr(
        trading_api,
        "execute_limit_order",
        fake_execute,
    )

    result = await (
        trading_api
        .execute_trading_limit_order(
            request=execute_payload(),
            user=ADMIN_WITH_ARNOLD,
            settings=settings(),
        )
    )

    assert (
        result["status"]
        == "disabled-test"
    )

    assert (
        captured[
            "allowed_account_ids"
        ]
        == {"arnold"}
    )

    assert (
        captured["account_id"]
        == "arnold"
    )

    assert (
        captured["username"]
        == "admin"
    )


@pytest.mark.asyncio
async def test_execution_denied_maps_to_http(
    monkeypatch,
):
    async def denied(
        **kwargs,
    ):
        raise TradingExecutionDenied(
            code="trading_disabled",
            message=(
                "Live Spot limit-order "
                "execution is disabled"
            ),
            status_code=503,
        )

    monkeypatch.setattr(
        trading_api,
        "execute_limit_order",
        denied,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .execute_trading_limit_order(
                request=execute_payload(),
                user=ARNOLD_USER,
                settings=settings(),
            )
        )

    assert (
        caught.value.status_code
        == 503
    )

    assert (
        caught.value.detail[
            "code"
        ]
        == "trading_disabled"
    )

    assert (
        caught.value.detail[
            "gate_write_performed"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_status_request_is_account_scoped(
    monkeypatch,
):
    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id: {
            "request_id": request_id,
            "account_id": "eqtydao",
        },
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .get_trading_limit_order_request(
                request_id="request-a",
                user=ARNOLD_USER,
            )
        )

    # Do not reveal cross-account request existence.
    assert (
        caught.value.status_code
        == 404
    )


@pytest.mark.asyncio
async def test_status_returns_audit_and_lock(
    monkeypatch,
):
    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id: {
            "request_id": request_id,
            "account_id": "arnold",
            "status": "uncertain",
            "write_performed": True,
        },
    )

    monkeypatch.setattr(
        trading_api,
        "list_order_reconciliations",
        lambda request_id: [
            {
                "request_id":
                    request_id,
                "outcome":
                    "not_found",
            }
        ],
    )

    monkeypatch.setattr(
        trading_api,
        "get_trading_lock_for_request",
        lambda request_id: {
            "owner_request_id":
                request_id,
            "funding_asset":
                "USDT",
        },
    )

    result = await (
        trading_api
        .get_trading_limit_order_request(
            request_id="request-a",
            user=ARNOLD_USER,
        )
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        result[
            "write_performed"
        ]
        is False
    )

    assert (
        result["request"][
            "status"
        ]
        == "uncertain"
    )

    assert (
        result["lock"][
            "funding_asset"
        ]
        == "USDT"
    )


@pytest.mark.asyncio
async def test_reconcile_uses_isolated_trading_account(
    monkeypatch,
):
    used_accounts = []

    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id: {
            "request_id": request_id,
            "account_id": "arnold",
        },
    )

    monkeypatch.setattr(
        trading_api,
        "get_trading_account",
        lambda account_id:
            TRADING_ACCOUNT,
    )

    class FakeGateClient:
        def __init__(
            self,
            settings,
            account,
        ):
            used_accounts.append(
                account
            )

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

    async def fake_reconcile(
        *,
        client,
        request_id,
    ):
        return {
            "status":
                "confirmed_open",
            "request_id":
                request_id,
        }

    monkeypatch.setattr(
        trading_api,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        trading_api,
        "reconcile_spot_order_request",
        fake_reconcile,
    )

    result = await (
        trading_api
        .reconcile_trading_limit_order_request(
            request_id="request-a",
            user=ARNOLD_USER,
            settings=settings(),
        )
    )

    assert len(
        used_accounts
    ) == 1

    assert (
        used_accounts[0].api_key
        == "trading-key"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_reconcile_cross_account_is_hidden(
    monkeypatch,
):
    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id: {
            "request_id": request_id,
            "account_id": "eqtydao",
        },
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .reconcile_trading_limit_order_request(
                request_id="request-a",
                user=ARNOLD_USER,
                settings=settings(),
            )
        )

    assert (
        caught.value.status_code
        == 404
    )
