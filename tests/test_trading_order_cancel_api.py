from __future__ import annotations

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
from app.trading_order_cancel import (
    TradingOrderCancelDenied,
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


def cancel_payload():
    return (
        trading_api
        .LimitOrderCancelRequest(
            cancel_request_id=(
                "cancel-api-a"
            ),
            confirmation=(
                "CANCEL ORDER"
            ),
        )
    )


def settings(
    *,
    cancel_enabled=False,
):
    return Settings(
        _env_file=None,
        trading_limit_orders_enabled=False,
        trading_order_cancels_enabled=(
            cancel_enabled
        ),
        trading_limit_order_confirmation_text=(
            "LIMIT ORDER"
        ),
        trading_order_cancel_confirmation_text=(
            "CANCEL ORDER"
        ),
    )


def source(
    *,
    account_id="arnold",
):
    return {
        "request_id":
            "request-a",
        "account_id":
            account_id,
        "status":
            "submitted",
        "gate_order_id":
            "123456789",
        "write_performed":
            True,
    }


@pytest.mark.asyncio
async def test_capabilities_report_cancel_disarmed(
    monkeypatch,
):
    monkeypatch.setattr(
        trading_api,
        "get_trading_account",
        lambda account_id:
            TRADING_ACCOUNT,
    )

    result = await (
        trading_api
        .trading_execution_capabilities(
            user=ARNOLD_USER,
            settings=settings(
                cancel_enabled=False
            ),
        )
    )

    assert (
        result[
            "cancellation_implemented"
        ]
        is True
    )

    assert (
        result[
            "cancellation_route_available"
        ]
        is True
    )

    assert (
        result[
            "cancel_arm_enabled"
        ]
        is False
    )

    assert (
        result[
            "cancel_required_confirmation"
        ]
        == "CANCEL ORDER"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_cancel_api_cross_account_is_hidden(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id:
            source(
                account_id="eqtydao"
            ),
    )

    async def fake_cancel(
        **kwargs,
    ):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(
        trading_api,
        "cancel_limit_order",
        fake_cancel,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .cancel_trading_limit_order(
                request_id="request-a",
                request=cancel_payload(),
                user=ARNOLD_USER,
                settings=settings(),
            )
        )

    assert (
        caught.value.status_code
        == 404
    )

    assert calls == []


@pytest.mark.asyncio
async def test_super_admin_has_no_cancel_wildcard(
    monkeypatch,
):
    calls = []

    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id:
            source(
                account_id="arnold"
            ),
    )

    async def fake_cancel(
        **kwargs,
    ):
        calls.append(kwargs)
        return {}

    monkeypatch.setattr(
        trading_api,
        "cancel_limit_order",
        fake_cancel,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .cancel_trading_limit_order(
                request_id="request-a",
                request=cancel_payload(),
                user=(
                    ADMIN_WITHOUT_ARNOLD
                ),
                settings=settings(),
            )
        )

    assert (
        caught.value.status_code
        == 404
    )

    assert calls == []


@pytest.mark.asyncio
async def test_cancel_api_passes_only_audited_source(
    monkeypatch,
):
    captured = {}

    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id:
            source(),
    )

    async def fake_cancel(
        **kwargs,
    ):
        captured.update(
            kwargs
        )

        return {
            "status":
                "disabled-test",
        }

    monkeypatch.setattr(
        trading_api,
        "cancel_limit_order",
        fake_cancel,
    )

    result = await (
        trading_api
        .cancel_trading_limit_order(
            request_id="request-a",
            request=cancel_payload(),
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
        captured[
            "order_request_id"
        ]
        == "request-a"
    )

    assert (
        captured[
            "cancel_request_id"
        ]
        == "cancel-api-a"
    )

    assert (
        captured["username"]
        == "admin"
    )

    # Pair/account/Gate order ID are deliberately
    # not accepted from the API request body.
    assert (
        "gate_order_id"
        not in captured
    )

    assert (
        "pair"
        not in captured
    )

    assert (
        "account_id"
        not in captured
    )


@pytest.mark.asyncio
async def test_cancel_denied_maps_to_http(
    monkeypatch,
):
    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id:
            source(),
    )

    async def denied(
        **kwargs,
    ):
        raise (
            TradingOrderCancelDenied(
                code=(
                    "cancellation_disabled"
                ),
                message=(
                    "Live Spot order "
                    "cancellation is disabled"
                ),
                status_code=503,
            )
        )

    monkeypatch.setattr(
        trading_api,
        "cancel_limit_order",
        denied,
    )

    with pytest.raises(
        HTTPException,
    ) as caught:
        await (
            trading_api
            .cancel_trading_limit_order(
                request_id="request-a",
                request=cancel_payload(),
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
        == "cancellation_disabled"
    )

    assert (
        caught.value.detail[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        caught.value.detail[
            "write_performed"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_status_includes_cancellation_audit(
    monkeypatch,
):
    monkeypatch.setattr(
        trading_api,
        "get_order_request",
        lambda request_id:
            source(),
    )

    monkeypatch.setattr(
        trading_api,
        "list_order_reconciliations",
        lambda request_id:
            [],
    )

    monkeypatch.setattr(
        trading_api,
        "get_trading_lock_for_request",
        lambda request_id:
            None,
    )

    monkeypatch.setattr(
        trading_api,
        "get_order_cancellation",
        lambda *,
        order_request_id: {
            "cancel_request_id":
                "cancel-api-a",
            "order_request_id":
                order_request_id,
            "status":
                "uncertain",
            "write_performed":
                True,
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
        result[
            "cancellation"
        ][
            "cancel_request_id"
        ]
        == "cancel-api-a"
    )

    assert (
        result[
            "cancellation"
        ][
            "status"
        ]
        == "uncertain"
    )
