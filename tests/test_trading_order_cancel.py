from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete

import app.trading_order_cancel as cancel

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
    TradingOrderCancellation,
    TradingOrderOperationLock,
    TradingOrderReconciliation,
    TradingOrderRequest,
)
from app.trading_order_audit import (
    mark_order_request,
    reserve_limit_order,
)
from app.trading_order_identity import (
    gate_text_for_request_id,
)
from app.trading_order_cancel import (
    TradingOrderCancelDenied,
    cancel_limit_order,
)
from app.trading_order_cancel_audit import (
    get_order_cancellation,
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


def make_settings(
    **overrides,
) -> Settings:
    values = {
        "trading_order_cancels_enabled":
            True,
        "trading_order_cancel_confirmation_text":
            "CANCEL ORDER",
        "trading_order_cancel_exptime_ms":
            5000,
        "trading_rate_limit_enabled":
            False,
    }

    values.update(
        overrides
    )

    return Settings(
        _env_file=None,
        **values,
    )


def make_gate_order(
    *,
    status="open",
    finish_as="open",
    amount="1000",
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
            amount,
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
    mode = "success"
    delete_calls = []
    get_calls = 0

    def __init__(
        self,
        settings=None,
        account=None,
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

    async def get_spot_order(
        self,
        order_id,
        *,
        currency_pair=None,
        account="spot",
    ):
        type(self).get_calls += 1

        if self.mode == "closed":
            data = make_gate_order(
                status="closed",
                finish_as="filled",
            )

        elif self.mode == "mismatch":
            data = make_gate_order(
                amount="999",
            )

        elif (
            self.mode
            == "ambiguous_cancelled"
            and type(self).get_calls
            >= 2
        ):
            data = make_gate_order(
                status="cancelled",
                finish_as="cancelled",
            )

        elif (
            self.mode
            == "ambiguous_open"
            and type(self).get_calls
            >= 2
        ):
            data = make_gate_order()

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
        order_id,
        *,
        currency_pair,
        expires_at_ms,
        account="spot",
    ):
        type(self).delete_calls.append(
            {
                "order_id":
                    order_id,
                "currency_pair":
                    currency_pair,
                "expires_at_ms":
                    expires_at_ms,
                "account":
                    account,
            }
        )

        if self.mode in {
            "ambiguous_cancelled",
            "ambiguous_open",
        }:
            raise GateAPIError(
                "network ambiguity",
                status_code=None,
                label="",
                response=None,
            )

        if self.mode == "already_cancelled":
            raise GateAPIError(
                "already cancelled",
                status_code=400,
                label="ORDER_CANCELLED",
                response={
                    "label":
                        "ORDER_CANCELLED",
                },
            )

        data = make_gate_order(
            status="cancelled",
            finish_as="cancelled",
        )

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )


def create_source_order():
    (
        request,
        created,
    ) = reserve_limit_order(
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

    assert created is True

    return mark_order_request(
        "request-a",
        status="submitted",
        response={
            "gate_response":
                make_gate_order(),
        },
        gate_order_id=(
            "123456789"
        ),
        gate_status_code=201,
        write_performed=True,
        completed=True,
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
                    TradingOrderCancellation
                )
            )

            db.execute(
                delete(
                    TradingOrderRequest
                )
            )

    clear()

    create_source_order()

    FakeGateClient.mode = (
        "success"
    )
    FakeGateClient.delete_calls = []
    FakeGateClient.get_calls = 0

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


async def do_cancel(
    *,
    settings=None,
    cancel_request_id="cancel-a",
    allowed_account_ids=None,
    confirmation="CANCEL ORDER",
):
    return await cancel_limit_order(
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
        cancel_request_id=(
            cancel_request_id
        ),
        order_request_id=(
            "request-a"
        ),
        confirmation=(
            confirmation
        ),
    )


@pytest.mark.asyncio
async def test_cancel_arm_false_stops_before_gate_or_audit():
    with pytest.raises(
        TradingOrderCancelDenied,
    ) as caught:
        await do_cancel(
            settings=make_settings(
                trading_order_cancels_enabled=False,
            )
        )

    assert (
        caught.value.code
        == "cancellation_disabled"
    )

    assert (
        FakeGateClient.get_calls
        == 0
    )

    assert (
        FakeGateClient.delete_calls
        == []
    )

    assert (
        get_order_cancellation(
            order_request_id=(
                "request-a"
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_cancel_requires_explicit_account_scope():
    with pytest.raises(
        TradingOrderCancelDenied,
    ) as caught:
        await do_cancel(
            allowed_account_ids={
                "eqtydao"
            }
        )

    assert (
        caught.value.code
        == "order_not_found"
    )

    assert not (
        FakeGateClient.delete_calls
    )


@pytest.mark.asyncio
async def test_cancel_requires_exact_confirmation():
    with pytest.raises(
        TradingOrderCancelDenied,
    ) as caught:
        await do_cancel(
            confirmation="wrong"
        )

    assert (
        caught.value.code
        == "confirmation_mismatch"
    )

    assert (
        FakeGateClient.get_calls
        == 0
    )

    assert not (
        FakeGateClient.delete_calls
    )


@pytest.mark.asyncio
async def test_finished_order_is_not_deleted():
    FakeGateClient.mode = "closed"

    result = await do_cancel()

    assert (
        result["status"]
        == "already_finished"
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

    assert not (
        FakeGateClient.delete_calls
    )


@pytest.mark.asyncio
async def test_precheck_identity_mismatch_blocks_delete():
    FakeGateClient.mode = "mismatch"

    result = await do_cancel()

    assert (
        result["status"]
        == "precheck_conflict"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is False
    )

    assert "amount" in (
        result["mismatches"]
    )

    assert not (
        FakeGateClient.delete_calls
    )


@pytest.mark.asyncio
async def test_success_performs_exactly_one_delete():
    result = await do_cancel()

    assert (
        result["status"]
        == "cancelled"
    )

    assert (
        result[
            "gate_write_performed"
        ]
        is True
    )

    assert (
        result["definitive"]
        is True
    )

    assert len(
        FakeGateClient.delete_calls
    ) == 1

    stored = (
        get_order_cancellation(
            order_request_id=(
                "request-a"
            )
        )
    )

    assert stored is not None

    assert (
        stored["status"]
        == "cancelled"
    )

    assert (
        stored[
            "write_performed"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_idempotent_replay_never_deletes_twice():
    first = await do_cancel()

    second = await do_cancel()

    assert (
        first["status"]
        == "cancelled"
    )

    # Fresh GET happens before cancellation reservation.
    # The fake still reports open, but the existing
    # cancellation record prevents another DELETE.
    assert (
        second["status"]
        == "idempotent_replay"
    )

    assert len(
        FakeGateClient.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_gate_order_cancelled_label_is_definitive():
    FakeGateClient.mode = (
        "already_cancelled"
    )

    result = await do_cancel()

    assert (
        result["status"]
        == "already_cancelled"
    )

    assert (
        result["definitive"]
        is True
    )

    assert len(
        FakeGateClient.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_ambiguous_delete_reconciles_cancelled_without_retry():
    FakeGateClient.mode = (
        "ambiguous_cancelled"
    )

    result = await do_cancel()

    assert (
        result["status"]
        == "confirmed_cancelled"
    )

    assert (
        result["definitive"]
        is True
    )

    assert len(
        FakeGateClient.delete_calls
    ) == 1

    assert (
        FakeGateClient.get_calls
        == 2
    )


@pytest.mark.asyncio
async def test_ambiguous_delete_still_open_is_frozen():
    FakeGateClient.mode = (
        "ambiguous_open"
    )

    result = await do_cancel()

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

    # Critical invariant: never retry DELETE.
    assert len(
        FakeGateClient.delete_calls
    ) == 1

    stored = (
        get_order_cancellation(
            order_request_id=(
                "request-a"
            )
        )
    )

    assert stored is not None

    assert (
        stored["status"]
        == "uncertain"
    )


def test_price_protect_cancelled_is_finished_not_normal_cancel():
    data = make_gate_order(
        status="closed",
        finish_as="price_protect_cancelled",
    )

    assert (
        cancel._is_cancelled(data)
        is False
    )

    assert (
        cancel._is_finished(data)
        is True
    )


def test_liquidate_cancelled_is_finished_not_normal_cancel():
    data = make_gate_order(
        status="closed",
        finish_as="liquidate_cancelled",
    )

    assert (
        cancel._is_cancelled(data)
        is False
    )

    assert (
        cancel._is_finished(data)
        is True
    )


def test_normal_cancelled_remains_confirmed_cancel():
    data = make_gate_order(
        status="cancelled",
        finish_as="cancelled",
    )

    assert (
        cancel._is_cancelled(data)
        is True
    )

    assert (
        cancel._is_finished(data)
        is True
    )


def _clear_cancel_rate_limit_events():
    from sqlalchemy import delete

    from app.models import (
        TradingRateLimitEvent,
    )
    from app.trading_rate_limit import (
        TRADING_ORDER_CANCEL,
    )

    with session_scope() as db:
        db.execute(
            delete(
                TradingRateLimitEvent
            ).where(
                TradingRateLimitEvent.action
                == TRADING_ORDER_CANCEL
            )
        )


@pytest.mark.asyncio
async def test_cancel_rate_limit_blocks_before_audit_or_delete():
    from app.trading_rate_limit import (
        TRADING_ORDER_CANCEL,
        TradingRateLimitExceeded,
        enforce_trading_cancel_rate_limit,
    )

    value = make_settings(
        trading_rate_limit_enabled=True,
        trading_order_cancel_user_limit=1,
        trading_order_cancel_user_window_seconds=600,
        trading_order_cancel_account_limit=100,
        trading_order_cancel_account_window_seconds=600,
    )

    _clear_cancel_rate_limit_events()

    try:
        first = (
            enforce_trading_cancel_rate_limit(
                settings=value,
                username="alice",
                account_id="arnold",
            )
        )

        assert (
            first["action"]
            == TRADING_ORDER_CANCEL
        )

        with pytest.raises(
            TradingRateLimitExceeded,
        ) as caught:
            await do_cancel(
                settings=value,
            )

        detail = caught.value.detail()

        assert detail["action"] == (
            TRADING_ORDER_CANCEL
        )

        assert (
            detail["gate_write_performed"]
            is False
        )

        assert (
            detail["write_performed"]
            is False
        )

        # Fresh Gate GET is intentionally before
        # the rate-limit boundary.
        assert FakeGateClient.get_calls == 1

        # The cancellation write boundary was never
        # crossed.
        assert FakeGateClient.delete_calls == []

        # Rate-limit rejection must not create a
        # cancellation audit.
        assert (
            get_order_cancellation(
                order_request_id=(
                    "request-a"
                )
            )
            is None
        )

    finally:
        _clear_cancel_rate_limit_events()


@pytest.mark.asyncio
async def test_idempotent_cancel_replay_does_not_consume_second_token():
    value = make_settings(
        trading_rate_limit_enabled=True,
        trading_order_cancel_user_limit=1,
        trading_order_cancel_user_window_seconds=600,
        trading_order_cancel_account_limit=1,
        trading_order_cancel_account_window_seconds=600,
    )

    _clear_cancel_rate_limit_events()

    try:
        first = await do_cancel(
            settings=value,
        )

        assert (
            first["status"]
            == "cancelled"
        )

        # User/account bucket is already full. This
        # must still resolve through the existing
        # cancellation audit instead of attempting
        # to consume another token.
        second = await do_cancel(
            settings=value,
            cancel_request_id="cancel-b",
        )

        assert (
            second["status"]
            == "idempotent_replay"
        )

        assert (
            len(
                FakeGateClient.delete_calls
            )
            == 1
        )

        assert (
            second[
                "gate_write_performed"
            ]
            is False
        )

    finally:
        _clear_cancel_rate_limit_events()
