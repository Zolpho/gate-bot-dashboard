from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

import app.trading_execution as execution
from app.accounts import (
    GateAccountConfig,
)
from app.config import Settings
from app.db import (
    init_db,
    session_scope,
)
from app.gate_client import (
    GateAPIError,
    GateResponse,
)
from app.models import (
    TradingOrderOperationLock,
    TradingOrderReconciliation,
    TradingOrderRequest,
    TradingRateLimitEvent,
)
from app.trading_execution import (
    TradingExecutionDenied,
    execute_limit_order,
)
from app.trading_order_audit import (
    get_order_request,
)
from app.trading_order_locks import (
    acquire_trading_lock,
    get_trading_lock_for_request,
)


init_db()


TRADING_ACCOUNT = (
    GateAccountConfig(
        id="arnold",
        name="arnold",
        api_key="trading-key",
        api_secret=(
            "trading-secret"
        ),
        enabled=True,
        account_type=(
            "subaccount"
        ),
        gate_uid="58601346",
    )
)


def make_settings(
    **overrides,
) -> Settings:
    values = {
        "trading_limit_orders_enabled":
            True,
        "trading_limit_order_confirmation_text":
            "LIMIT ORDER",
        "trading_rate_limit_enabled":
            True,
        "trading_limit_order_user_limit":
            100,
        "trading_limit_order_user_window_seconds":
            600,
        "trading_limit_order_account_limit":
            100,
        "trading_limit_order_account_window_seconds":
            600,
        "trading_order_exptime_ms":
            5000,
    }

    values.update(
        overrides
    )

    return Settings(
        _env_file=None,
        **values,
    )


def ready_preflight(
    *,
    side="buy",
) -> dict:
    funding_asset = (
        "USDT"
        if side == "buy"
        else "EQTY"
    )

    return {
        "status": "ready",
        "account_id": "arnold",
        "pair": "EQTY_USDT",
        "base": "EQTY",
        "quote": "USDT",
        "funding_asset": (
            funding_asset
        ),
        "side": side,
        "time_in_force": "gtc",
        "price": "0.0017",
        "amount": "1000",
        "total": "1.7",
        "available": (
            "100"
            if side == "buy"
            else "100000"
        ),
        "required": (
            "1.7"
            if side == "buy"
            else "1000"
        ),
        "remaining": (
            "98.3"
            if side == "buy"
            else "99000"
        ),
        "best_bid": "0.0016",
        "best_ask": "0.0018",
        "marketable": False,
        "blockers": [],
        "warnings": [
            "Estimated total does not "
            "include trading fees."
        ],
        "gate_payload": {
            "currency_pair": (
                "EQTY_USDT"
            ),
            "type": "limit",
            "account": "spot",
            "side": side,
            "amount": "1000",
            "price": "0.0017",
            "time_in_force": "gtc",
        },
    }


class FakeGateClient:
    mode = "success"
    post_calls = []
    last_payload = None
    accounts_used = []

    def __init__(
        self,
        settings=None,
        account=None,
    ):
        self.settings = settings
        self.account = account

        type(self).accounts_used.append(
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

    async def create_spot_order(
        self,
        payload,
        *,
        expires_at_ms,
    ):
        type(self).post_calls.append(
            {
                "payload": dict(
                    payload
                ),
                "expires_at_ms": (
                    expires_at_ms
                ),
                "account_id": (
                    self.account.id
                    if self.account
                    else None
                ),
                "api_key": (
                    self.account.api_key
                    if self.account
                    else None
                ),
            }
        )

        type(self).last_payload = (
            dict(payload)
        )

        if self.mode == "400":
            raise GateAPIError(
                "Gate rejected order",
                status_code=400,
                label="INVALID_PARAM_VALUE",
                response={
                    "label":
                        "INVALID_PARAM_VALUE",
                    "message":
                        "invalid order",
                },
            )

        if self.mode in {
            "network_not_found",
            "network_found",
        }:
            raise GateAPIError(
                "Gate network error",
                status_code=None,
                label="",
                response=None,
            )

        data = dict(
            payload
        )

        data.update(
            {
                "id": "777",
                "status": "open",
            }
        )

        return GateResponse(
            data=data,
            status_code=201,
            headers={},
            raw=data,
        )

    async def get_spot_order(
        self,
        order_id,
        *,
        currency_pair=None,
        account="spot",
    ):
        if (
            self.mode
            == "network_found"
        ):
            data = dict(
                type(self)
                .last_payload
                or {}
            )

            data.update(
                {
                    "id": "888",
                    "status": "open",
                    "left": "1000",
                    "filled_total": "0",
                }
            )

            return GateResponse(
                data=data,
                status_code=200,
                headers={},
                raw=data,
            )

        raise GateAPIError(
            "not found",
            status_code=404,
            label="ORDER_NOT_FOUND",
            response={
                "label":
                    "ORDER_NOT_FOUND",
            },
        )

    async def list_spot_orders(
        self,
        **kwargs,
    ):
        return GateResponse(
            data=[],
            status_code=200,
            headers={},
            raw=[],
        )


@pytest.fixture(autouse=True)
def clean_state(
    monkeypatch,
):
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TradingOrderOperationLock
                )
            )

            db.execute(
                delete(
                    TradingOrderReconciliation
                )
            )

            db.execute(
                delete(
                    TradingRateLimitEvent
                )
            )

            db.execute(
                delete(
                    TradingOrderRequest
                )
            )

    clear()

    FakeGateClient.mode = (
        "success"
    )

    FakeGateClient.post_calls = []
    FakeGateClient.last_payload = (
        None
    )
    FakeGateClient.accounts_used = []

    monkeypatch.setattr(
        execution,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        execution,
        "get_trading_account",
        lambda account_id:
            TRADING_ACCOUNT
            if account_id
            == "arnold"
            else None,
    )

    async def fake_preflight(
        *,
        settings,
        account_id,
        pair,
        side,
        price,
        amount,
        time_in_force,
    ):
        result = (
            ready_preflight(
                side=side
            )
        )

        result[
            "account_id"
        ] = account_id

        return result

    monkeypatch.setattr(
        execution,
        "fresh_limit_order_preflight",
        fake_preflight,
    )

    yield

    clear()


async def call_execute(
    *,
    request_id="request-a",
    settings=None,
    allowed_account_ids=None,
    confirmation="LIMIT ORDER",
):
    return await execute_limit_order(
        settings=(
            settings
            or make_settings()
        ),
        username="alice",
        allowed_account_ids=(
            allowed_account_ids
            if allowed_account_ids
            is not None
            else {"arnold"}
        ),
        request_id=request_id,
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
        confirmation=(
            confirmation
        ),
    )


@pytest.mark.asyncio
async def test_disabled_arm_fails_before_any_audit_or_post():
    settings = make_settings(
        trading_limit_orders_enabled=False,
    )

    with pytest.raises(
        TradingExecutionDenied,
    ) as caught:
        await call_execute(
            settings=settings,
        )

    assert (
        caught.value.code
        == "trading_disabled"
    )

    assert (
        get_order_request(
            "request-a"
        )
        is None
    )

    assert (
        FakeGateClient.post_calls
        == []
    )


@pytest.mark.asyncio
async def test_explicit_account_scope_is_required():
    with pytest.raises(
        TradingExecutionDenied,
    ) as caught:
        await call_execute(
            allowed_account_ids={
                "eqtydao"
            },
        )

    assert (
        caught.value.code
        == "account_not_assigned"
    )

    assert not (
        FakeGateClient.post_calls
    )


@pytest.mark.asyncio
async def test_exact_confirmation_is_required():
    with pytest.raises(
        TradingExecutionDenied,
    ) as caught:
        await call_execute(
            confirmation="wrong",
        )

    assert (
        caught.value.code
        == "confirmation_mismatch"
    )

    assert not (
        FakeGateClient.post_calls
    )


@pytest.mark.asyncio
async def test_success_uses_exactly_one_trading_post():
    result = await call_execute()

    assert (
        result["status"]
        == "submitted"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is True
    )

    assert (
        result["gate_order_id"]
        == "777"
    )

    assert len(
        FakeGateClient.post_calls
    ) == 1

    call = (
        FakeGateClient
        .post_calls[0]
    )

    assert (
        call["account_id"]
        == "arnold"
    )

    assert (
        call["api_key"]
        == "trading-key"
    )

    assert (
        call["payload"][
            "text"
        ].startswith("t-")
    )

    saved = get_order_request(
        "request-a"
    )

    assert saved is not None
    assert (
        saved["status"]
        == "submitted"
    )
    assert (
        saved[
            "write_performed"
        ]
        is True
    )
    assert (
        saved["gate_order_id"]
        == "777"
    )

    assert (
        get_trading_lock_for_request(
            "request-a"
        )
        is None
    )


@pytest.mark.asyncio
async def test_idempotent_replay_never_posts_twice():
    first = await call_execute()

    second = await call_execute()

    assert (
        first["status"]
        == "submitted"
    )

    assert (
        second["status"]
        == "idempotent_replay"
    )

    assert (
        second[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        second[
            "original_write_performed"
        ]
        is True
    )

    assert len(
        FakeGateClient.post_calls
    ) == 1


@pytest.mark.asyncio
async def test_preflight_blocker_prevents_post(
    monkeypatch,
):
    async def blocked(
        **kwargs,
    ):
        result = (
            ready_preflight()
        )

        result["status"] = (
            "invalid"
        )

        result["blockers"] = [
            "Insufficient available "
            "spot balance."
        ]

        return result

    monkeypatch.setattr(
        execution,
        "fresh_limit_order_preflight",
        blocked,
    )

    result = await call_execute()

    assert (
        result["status"]
        == "preflight_failed"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert not (
        FakeGateClient.post_calls
    )

    saved = get_order_request(
        "request-a"
    )

    assert saved is not None
    assert (
        saved["status"]
        == "preflight_failed"
    )
    assert (
        saved[
            "write_performed"
        ]
        is False
    )


@pytest.mark.asyncio
async def test_funding_asset_lock_blocks_second_operation():
    acquire_trading_lock(
        account_id="arnold",
        funding_asset="USDT",
        pair="BTC_USDT",
        side="buy",
        owner_request_id=(
            "other-request"
        ),
        username="bob",
    )

    result = await call_execute()

    assert (
        result["status"]
        == "lock_blocked"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert not (
        FakeGateClient.post_calls
    )


@pytest.mark.asyncio
async def test_definitive_400_rejection_releases_lock():
    FakeGateClient.mode = "400"

    result = await call_execute()

    assert (
        result["status"]
        == "rejected"
    )

    assert (
        result[
            "definitive_rejection"
        ]
        is True
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is True
    )

    assert (
        result["lock_released"]
        is True
    )

    assert len(
        FakeGateClient.post_calls
    ) == 1

    assert (
        get_trading_lock_for_request(
            "request-a"
        )
        is None
    )


@pytest.mark.asyncio
async def test_network_ambiguity_not_found_keeps_lock():
    FakeGateClient.mode = (
        "network_not_found"
    )

    result = await call_execute()

    assert (
        result["status"]
        == "uncertain"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is True
    )

    assert (
        result["lock_released"]
        is False
    )

    assert len(
        FakeGateClient.post_calls
    ) == 1

    assert (
        get_trading_lock_for_request(
            "request-a"
        )
        is not None
    )


@pytest.mark.asyncio
async def test_network_ambiguity_found_by_text_reconciles_without_retry():
    FakeGateClient.mode = (
        "network_found"
    )

    result = await call_execute()

    assert (
        result["status"]
        == "confirmed_open"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is True
    )

    assert (
        result["lock_released"]
        is True
    )

    # The critical invariant:
    # reconciliation performed reads,
    # but never another POST.
    assert len(
        FakeGateClient.post_calls
    ) == 1

    saved = get_order_request(
        "request-a"
    )

    assert saved is not None
    assert (
        saved["gate_order_id"]
        == "888"
    )

    assert (
        get_trading_lock_for_request(
            "request-a"
        )
        is None
    )
