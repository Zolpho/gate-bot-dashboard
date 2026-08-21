from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

import app.trading_order_cancel as cancel

from app.accounts import GateAccountConfig
from app.config import Settings
from app.db import (
    init_db,
    session_scope,
)
from app.gate_client import (
    GateResponse,
)
from app.models import (
    TradingOrderCancellation,
    TradingOrderRequest,
)
from app.trading_order_audit import (
    mark_order_request,
    reserve_limit_order,
)
from app.trading_order_cancel import (
    TradingOrderCancelDenied,
    reconcile_limit_order_cancellation,
)
from app.trading_order_cancel_audit import (
    get_order_cancellation,
    mark_order_cancellation,
    reserve_order_cancellation,
)
from app.trading_order_identity import (
    gate_text_for_request_id,
)


init_db()


TRADING_ACCOUNT = GateAccountConfig(
    id="arnold",
    name="arnold",
    api_key="trading-key",
    api_secret="trading-secret",
    enabled=True,
    account_type="subaccount",
    gate_uid="58601346",
)


def make_gate_order(
    *,
    status="open",
    finish_as="open",
):
    return {
        "id":
            "123456789",
        "text":
            gate_text_for_request_id(
                "request-a"
            ),
        "currency_pair":
            "EQTY_USDT",
        "type":
            "limit",
        "account":
            "spot",
        "side":
            "buy",
        "amount":
            "1000",
        "price":
            "0.0017",
        "time_in_force":
            "poc",
        "status":
            status,
        "finish_as":
            finish_as,
    }


class FakeGateClient:
    mode = "open"
    get_calls = 0
    delete_calls = 0

    def __init__(
        self,
        settings=None,
        account=None,
    ):
        self.settings = settings
        self.account = account

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        return None

    async def get_spot_order(
        self,
        order_id,
        *,
        currency_pair=None,
        account="spot",
    ):
        type(self).get_calls += 1

        if self.mode == "cancelled":
            data = make_gate_order(
                status="cancelled",
                finish_as="cancelled",
            )

        elif self.mode == "finished":
            data = make_gate_order(
                status="closed",
                finish_as="filled",
            )

        else:
            data = make_gate_order()

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )

    async def cancel_spot_order(
        self,
        *args,
        **kwargs,
    ):
        type(self).delete_calls += 1

        raise AssertionError(
            "reconciliation must never DELETE"
        )


@pytest.fixture(autouse=True)
def clean_state(
    monkeypatch,
):
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TradingOrderCancellation
                )
            )

            db.execute(
                delete(
                    TradingOrderRequest
                )
            )

    clear()

    reserve_limit_order(
        request_id="request-a",
        account_id="arnold",
        username="alice",
        pair="EQTY_USDT",
        side="buy",
        price=Decimal(
            "0.0017"
        ),
        amount=Decimal(
            "1000"
        ),
        time_in_force="poc",
        funding_asset="USDT",
    )

    mark_order_request(
        "request-a",
        status="submitted",
        response={},
        gate_order_id="123456789",
        gate_status_code=201,
        write_performed=True,
        completed=True,
    )

    reserve_order_cancellation(
        cancel_request_id="cancel-a",
        order_request_id="request-a",
        account_id="arnold",
        username="alice",
        pair="EQTY_USDT",
        gate_order_id="123456789",
    )

    mark_order_cancellation(
        "cancel-a",
        status="uncertain",
        response={
            "phase":
                "test_ambiguous_delete",
        },
        write_performed=True,
        completed=False,
    )

    FakeGateClient.mode = "open"
    FakeGateClient.get_calls = 0
    FakeGateClient.delete_calls = 0

    monkeypatch.setattr(
        cancel,
        "GateClient",
        FakeGateClient,
    )

    monkeypatch.setattr(
        cancel,
        "get_trading_account",
        lambda account_id:
            TRADING_ACCOUNT
            if account_id
            == "arnold"
            else None,
    )

    yield

    clear()


def settings():
    return Settings(
        _env_file=None,
        trading_limit_orders_enabled=False,
        trading_order_cancels_enabled=False,
    )


async def reconcile(
    *,
    allowed=None,
):
    return await (
        reconcile_limit_order_cancellation(
            settings=settings(),
            username="alice",
            allowed_account_ids=(
                allowed
                if allowed is not None
                else {"arnold"}
            ),
            order_request_id="request-a",
        )
    )


@pytest.mark.asyncio
async def test_reconcile_cancelled_is_definitive():
    FakeGateClient.mode = "cancelled"

    result = await reconcile()

    assert (
        result["status"]
        == "confirmed_cancelled"
    )

    assert (
        result["definitive"]
        is True
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert (
        FakeGateClient.get_calls
        == 1
    )

    assert (
        FakeGateClient.delete_calls
        == 0
    )


@pytest.mark.asyncio
async def test_reconcile_finished_is_definitive():
    FakeGateClient.mode = "finished"

    result = await reconcile()

    assert (
        result["status"]
        == "confirmed_finished"
    )

    assert (
        result["definitive"]
        is True
    )

    assert (
        FakeGateClient.delete_calls
        == 0
    )


@pytest.mark.asyncio
async def test_reconcile_still_open_remains_uncertain():
    FakeGateClient.mode = "open"

    result = await reconcile()

    assert (
        result["status"]
        == "uncertain"
    )

    assert (
        result["definitive"]
        is False
    )

    assert (
        result[
            "manual_review_required"
        ]
        is True
    )

    assert (
        result["reconciliation"][
            "result"
        ]
        == "still_open"
    )

    assert (
        FakeGateClient.delete_calls
        == 0
    )

    stored = (
        get_order_cancellation(
            order_request_id="request-a"
        )
    )

    assert stored is not None

    assert (
        stored["status"]
        == "uncertain"
    )


@pytest.mark.asyncio
async def test_reconcile_enforces_account_scope():
    with pytest.raises(
        TradingOrderCancelDenied,
    ) as caught:
        await reconcile(
            allowed={"eqtydao"}
        )

    assert (
        caught.value.code
        == "order_not_found"
    )

    assert (
        FakeGateClient.get_calls
        == 0
    )

    assert (
        FakeGateClient.delete_calls
        == 0
    )


@pytest.mark.asyncio
async def test_reconcile_works_with_cancel_arm_false():
    FakeGateClient.mode = "cancelled"

    result = await reconcile()

    assert (
        result["status"]
        == "confirmed_cancelled"
    )

    # Critical operational property:
    # recovery remains available while
    # cancellation writes are disabled.
    assert (
        settings()
        .trading_order_cancels_enabled
        is False
    )

    assert (
        FakeGateClient.delete_calls
        == 0
    )
