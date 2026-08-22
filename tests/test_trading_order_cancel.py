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
    reconcile_limit_order_cancellation,
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
    list_calls = []

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

        if (
            self.mode
            in {
                "ambiguous_404_absent",
                "ambiguous_404_open",
                "ambiguous_404_mismatch",
                "ambiguous_404_scan_incomplete",
            }
            and type(self).get_calls >= 2
        ):
            raise GateAPIError(
                "order not found",
                status_code=404,
                label="ORDER_NOT_FOUND",
                response={
                    "label":
                        "ORDER_NOT_FOUND",
                    "message":
                        "Order not found",
                },
            )

        if (
            self.mode
            == "manual_404_absent"
        ):
            raise GateAPIError(
                "order not found",
                status_code=404,
                label="ORDER_NOT_FOUND",
                response={
                    "label":
                        "ORDER_NOT_FOUND",
                    "message":
                        "Order not found",
                },
            )

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

    async def list_spot_orders(
        self,
        *,
        currency_pair,
        status,
        page=1,
        limit=100,
        account="spot",
        from_timestamp=None,
        to_timestamp=None,
        side=None,
    ):
        type(self).list_calls.append(
            {
                "currency_pair":
                    currency_pair,
                "status":
                    status,
                "page":
                    page,
                "limit":
                    limit,
                "account":
                    account,
            }
        )

        if self.mode == "ambiguous_404_open":
            rows = [
                make_gate_order()
            ]

        elif (
            self.mode
            == "ambiguous_404_mismatch"
        ):
            rows = [
                make_gate_order(
                    amount="999",
                )
            ]

        elif (
            self.mode
            == "ambiguous_404_scan_incomplete"
        ):
            rows = []

            for index in range(limit):
                item = make_gate_order()

                item["id"] = (
                    f"{page:02d}"
                    f"{index:04d}"
                )

                rows.append(item)

        else:
            rows = []

        return GateResponse(
            data=rows,
            status_code=200,
            headers={},
            raw=rows,
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
            "ambiguous_404_absent",
            "ambiguous_404_open",
            "ambiguous_404_mismatch",
            "ambiguous_404_scan_incomplete",
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
    FakeGateClient.list_calls = []

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


async def do_reconcile(
    *,
    settings=None,
    allowed_account_ids=None,
):
    return await reconcile_limit_order_cancellation(
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
        order_request_id="request-a",
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



def _lifecycle_gate_client(
    *,
    price: str,
    amount: str = "1000",
):
    """
    Gate client whose fresh GET and successful DELETE
    both expose the same lifecycle-current order price.
    """

    class LifecycleGateClient(
        FakeGateClient
    ):
        delete_calls = []
        get_calls = 0

        async def get_spot_order(
            self,
            order_id,
            *,
            currency_pair=None,
            account="spot",
        ):
            type(self).get_calls += 1

            data = make_gate_order(
                amount=amount,
            )

            data["price"] = price

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

            data = make_gate_order(
                status="cancelled",
                finish_as="cancelled",
                amount=amount,
            )

            data["price"] = price

            return GateResponse(
                data=data,
                status_code=200,
                headers={},
                raw=data,
            )

    return LifecycleGateClient


def _completed_amendment(
    *,
    status: str,
    current_price: str,
    requested_price: str,
):
    return {
        "amend_request_id":
            (
                "amend-test-"
                + status
                + "-"
                + requested_price
            ),
        "order_request_id":
            "request-a",
        "gate_order_id":
            "123456789",
        "current_price":
            current_price,
        "requested_price":
            requested_price,
        "status":
            status,
        "write_performed":
            True,
        "completed_at":
            "2026-08-22T12:00:00",
        "created_at":
            "2026-08-22T11:59:59",
    }


@pytest.mark.parametrize(
    "amend_status",
    [
        "amended",
        "confirmed_amended",
    ],
)
@pytest.mark.asyncio
async def test_completed_amendment_price_is_cancel_identity(
    monkeypatch,
    amend_status,
):
    client = _lifecycle_gate_client(
        price="0.0018",
    )

    monkeypatch.setattr(
        cancel,
        "GateClient",
        client,
    )

    monkeypatch.setattr(
        cancel,
        "get_active_order_amendment",
        lambda request_id: None,
    )

    monkeypatch.setattr(
        cancel,
        "list_order_amendments",
        lambda request_id, limit=100: [
            _completed_amendment(
                status=amend_status,
                current_price="0.0017",
                requested_price="0.0018",
            )
        ],
    )

    result = await do_cancel()

    assert result["status"] == "cancelled"

    assert (
        result["gate_write_performed"]
        is True
    )

    assert len(
        client.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_confirmed_not_applied_does_not_change_cancel_price(
    monkeypatch,
):
    monkeypatch.setattr(
        cancel,
        "get_active_order_amendment",
        lambda request_id: None,
    )

    monkeypatch.setattr(
        cancel,
        "list_order_amendments",
        lambda request_id, limit=100: [
            _completed_amendment(
                status="confirmed_not_applied",
                current_price="0.0017",
                requested_price="0.0018",
            )
        ],
    )

    result = await do_cancel()

    assert result["status"] == "cancelled"

    assert len(
        FakeGateClient.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_newest_successful_completed_amendment_wins(
    monkeypatch,
):
    client = _lifecycle_gate_client(
        price="0.0019",
    )

    monkeypatch.setattr(
        cancel,
        "GateClient",
        client,
    )

    monkeypatch.setattr(
        cancel,
        "get_active_order_amendment",
        lambda request_id: None,
    )

    # list_order_amendments is newest-first.
    monkeypatch.setattr(
        cancel,
        "list_order_amendments",
        lambda request_id, limit=100: [
            _completed_amendment(
                status="amended",
                current_price="0.0018",
                requested_price="0.0019",
            ),
            _completed_amendment(
                status="amended",
                current_price="0.0017",
                requested_price="0.0018",
            ),
        ],
    )

    result = await do_cancel()

    assert result["status"] == "cancelled"

    assert len(
        client.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_failed_newer_amendment_keeps_last_successful_price(
    monkeypatch,
):
    client = _lifecycle_gate_client(
        price="0.0018",
    )

    monkeypatch.setattr(
        cancel,
        "GateClient",
        client,
    )

    monkeypatch.setattr(
        cancel,
        "get_active_order_amendment",
        lambda request_id: None,
    )

    monkeypatch.setattr(
        cancel,
        "list_order_amendments",
        lambda request_id, limit=100: [
            _completed_amendment(
                status="rejected",
                current_price="0.0018",
                requested_price="0.0020",
            ),
            _completed_amendment(
                status="amended",
                current_price="0.0017",
                requested_price="0.0018",
            ),
        ],
    )

    result = await do_cancel()

    assert result["status"] == "cancelled"

    assert len(
        client.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_amended_order_still_blocks_immutable_amount_mismatch(
    monkeypatch,
):
    client = _lifecycle_gate_client(
        price="0.0018",
        amount="999",
    )

    monkeypatch.setattr(
        cancel,
        "GateClient",
        client,
    )

    monkeypatch.setattr(
        cancel,
        "get_active_order_amendment",
        lambda request_id: None,
    )

    monkeypatch.setattr(
        cancel,
        "list_order_amendments",
        lambda request_id, limit=100: [
            _completed_amendment(
                status="amended",
                current_price="0.0017",
                requested_price="0.0018",
            )
        ],
    )

    result = await do_cancel()

    assert (
        result["status"]
        == "precheck_conflict"
    )

    assert (
        result["gate_write_performed"]
        is False
    )

    assert "amount" in (
        result["mismatches"]
    )

    assert not (
        client.delete_calls
    )


@pytest.mark.asyncio
async def test_active_unresolved_amendment_blocks_cancel_delete(
    monkeypatch,
):
    monkeypatch.setattr(
        cancel,
        "get_active_order_amendment",
        lambda request_id: {
            "amend_request_id":
                "amend-unresolved",
            "order_request_id":
                request_id,
            "status":
                "uncertain",
            "write_performed":
                True,
            "completed_at":
                None,
        },
    )

    monkeypatch.setattr(
        cancel,
        "list_order_amendments",
        lambda request_id, limit=100: [],
    )

    result = await do_cancel()

    assert (
        result["status"]
        == "precheck_conflict"
    )

    assert (
        result["gate_write_performed"]
        is False
    )

    assert (
        "active_amendment"
        in result["mismatches"]
    )

    assert not (
        FakeGateClient.delete_calls
    )


@pytest.mark.asyncio
async def test_inconsistent_successful_amendment_audit_fails_closed(
    monkeypatch,
):
    monkeypatch.setattr(
        cancel,
        "get_active_order_amendment",
        lambda request_id: None,
    )

    amendment = _completed_amendment(
        status="amended",
        current_price="0.0017",
        requested_price="0.0018",
    )

    amendment[
        "write_performed"
    ] = False

    monkeypatch.setattr(
        cancel,
        "list_order_amendments",
        lambda request_id, limit=100: [
            amendment
        ],
    )

    result = await do_cancel()

    assert (
        result["status"]
        == "precheck_conflict"
    )

    assert (
        "amendment_write_boundary"
        in result["mismatches"]
    )

    assert not (
        FakeGateClient.delete_calls
    )



@pytest.mark.asyncio
async def test_completed_cancel_reconcile_uses_durable_audit_without_gate(
    monkeypatch,
):
    first = await do_cancel()

    assert first["status"] == "cancelled"

    assert len(
        FakeGateClient.delete_calls
    ) == 1

    FakeGateClient.get_calls = 0
    FakeGateClient.list_calls = []

    def fail_credentials(
        account_id,
    ):
        raise AssertionError(
            "Completed audit reconciliation "
            "must not load Gate credentials"
        )

    monkeypatch.setattr(
        cancel,
        "get_trading_account",
        fail_credentials,
    )

    result = await do_reconcile()

    assert result["status"] == "cancelled"
    assert result["definitive"] is True

    assert (
        result["gate_write_performed"]
        is False
    )

    assert (
        result["write_performed"]
        is False
    )

    assert (
        result["reconciliation"]["result"]
        == "durable_completed"
    )

    assert (
        result[
            "historical_cancel_write_performed"
        ]
        is True
    )

    assert FakeGateClient.get_calls == 0
    assert FakeGateClient.list_calls == []

    # Critical invariant:
    # reconciliation never retries DELETE.
    assert len(
        FakeGateClient.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_ambiguous_delete_404_absent_from_open_stays_uncertain():
    FakeGateClient.mode = (
        "ambiguous_404_absent"
    )

    result = await do_cancel()

    assert result["status"] == "uncertain"
    assert result["definitive"] is False

    assert (
        result[
            "manual_review_required"
        ]
        is True
    )

    assert (
        result["reconciliation"]["result"]
        == "not_found_not_open"
    )

    # Exactly the original ambiguous DELETE only.
    assert len(
        FakeGateClient.delete_calls
    ) == 1

    assert len(
        FakeGateClient.list_calls
    ) == 1

    stored = get_order_cancellation(
        order_request_id="request-a"
    )

    assert stored is not None
    assert stored["status"] == "uncertain"
    assert stored["write_performed"] is True
    assert stored["completed_at"] is None


@pytest.mark.asyncio
async def test_ambiguous_delete_404_open_fallback_remains_still_open():
    FakeGateClient.mode = (
        "ambiguous_404_open"
    )

    result = await do_cancel()

    assert result["status"] == "uncertain"

    assert (
        result["reconciliation"]["result"]
        == "still_open"
    )

    assert len(
        FakeGateClient.delete_calls
    ) == 1

    assert len(
        FakeGateClient.list_calls
    ) == 1


@pytest.mark.asyncio
async def test_ambiguous_delete_404_open_identity_conflict_is_attention():
    FakeGateClient.mode = (
        "ambiguous_404_mismatch"
    )

    result = await do_cancel()

    assert result["status"] == "attention"
    assert result["definitive"] is False

    assert (
        result["reconciliation"]["result"]
        == "correlation_conflict"
    )

    assert "amount" in (
        result[
            "reconciliation"
        ]["mismatches"]
    )

    assert len(
        FakeGateClient.delete_calls
    ) == 1


@pytest.mark.asyncio
async def test_ambiguous_delete_404_bounded_open_scan_never_claims_absence():
    FakeGateClient.mode = (
        "ambiguous_404_scan_incomplete"
    )

    result = await do_cancel()

    assert result["status"] == "uncertain"

    assert (
        result["reconciliation"]["result"]
        == "open_scan_incomplete"
    )

    assert len(
        FakeGateClient.delete_calls
    ) == 1

    assert (
        len(
            FakeGateClient.list_calls
        )
        == cancel._CANCEL_OPEN_SCAN_MAX_PAGES
    )


@pytest.mark.asyncio
async def test_manual_reconcile_404_absent_from_open_stays_uncertain_without_delete():
    FakeGateClient.mode = (
        "ambiguous_open"
    )

    first = await do_cancel()

    assert first["status"] == "uncertain"

    assert len(
        FakeGateClient.delete_calls
    ) == 1

    FakeGateClient.mode = (
        "manual_404_absent"
    )

    FakeGateClient.get_calls = 0
    FakeGateClient.list_calls = []

    result = await do_reconcile()

    assert result["status"] == "uncertain"

    assert (
        result["gate_write_performed"]
        is False
    )

    assert (
        result["write_performed"]
        is False
    )

    assert (
        result["reconciliation"]["result"]
        == "not_found_not_open"
    )

    assert (
        result[
            "historical_cancel_write_performed"
        ]
        is True
    )

    # No reconciliation DELETE.
    assert len(
        FakeGateClient.delete_calls
    ) == 1

    assert len(
        FakeGateClient.list_calls
    ) == 1

    stored = get_order_cancellation(
        order_request_id="request-a"
    )

    assert stored is not None
    assert stored["status"] == "uncertain"
    assert stored["write_performed"] is True
    assert stored["completed_at"] is None
