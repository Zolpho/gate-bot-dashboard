from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete

from app.db import (
    init_db,
    session_scope,
)
from app.gate_client import (
    GateClient,
    GateResponse,
)
from app.models import (
    TradingOrderCancellation,
)
from app.trading_order_cancel_audit import (
    TradingOrderCancelConflict,
    get_order_cancellation,
    mark_order_cancellation,
    reserve_order_cancellation,
)


init_db()


@pytest.fixture(autouse=True)
def clean_cancellations():
    def clear():
        with session_scope() as db:
            db.execute(
                delete(
                    TradingOrderCancellation
                )
            )

    clear()
    yield
    clear()


def cancel_args(
    **overrides,
):
    values = {
        "cancel_request_id":
            "cancel-a",
        "order_request_id":
            "request-a",
        "account_id":
            "arnold",
        "username":
            "alice",
        "pair":
            "EQTY_USDT",
        "gate_order_id":
            "123456789",
    }

    values.update(
        overrides
    )

    return values


def test_cancel_reservation_is_idempotent():
    first, created = (
        reserve_order_cancellation(
            **cancel_args()
        )
    )

    second, created_again = (
        reserve_order_cancellation(
            **cancel_args()
        )
    )

    assert created is True
    assert created_again is False

    assert (
        first["id"]
        == second["id"]
    )

    assert (
        first["gate_order_id"]
        == "123456789"
    )


def test_same_order_cannot_create_second_cancel_operation():
    first, created = (
        reserve_order_cancellation(
            **cancel_args()
        )
    )

    second, created_again = (
        reserve_order_cancellation(
            **cancel_args(
                cancel_request_id=(
                    "cancel-b"
                )
            )
        )
    )

    assert created is True
    assert created_again is False

    assert (
        first["id"]
        == second["id"]
    )


def test_cancel_request_id_conflict_is_rejected():
    reserve_order_cancellation(
        **cancel_args()
    )

    with pytest.raises(
        TradingOrderCancelConflict,
    ):
        reserve_order_cancellation(
            **cancel_args(
                order_request_id=(
                    "request-b"
                ),
                gate_order_id=(
                    "987654321"
                ),
            )
        )


def test_cancel_audit_can_be_marked():
    reserve_order_cancellation(
        **cancel_args()
    )

    updated = (
        mark_order_cancellation(
            "cancel-a",
            status="cancelled",
            response={
                "id":
                    "123456789",
                "status":
                    "cancelled",
            },
            gate_status_code=200,
            write_performed=True,
            completed=True,
        )
    )

    assert (
        updated["status"]
        == "cancelled"
    )

    assert (
        updated[
            "write_performed"
        ]
        is True
    )

    stored = (
        get_order_cancellation(
            cancel_request_id=(
                "cancel-a"
            )
        )
    )

    assert stored is not None

    assert (
        stored["response"][
            "status"
        ]
        == "cancelled"
    )


def test_cancel_spot_order_is_single_delete(
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
                "method":
                    method,
                "endpoint":
                    endpoint,
                "params":
                    params,
                "headers":
                    extra_headers,
            }
        )

        data = {
            "id":
                "123456789",
            "currency_pair":
                "EQTY_USDT",
            "status":
                "cancelled",
            "finish_as":
                "cancelled",
        }

        return GateResponse(
            data=data,
            status_code=200,
            headers={},
            raw=data,
        )

    monkeypatch.setattr(
        GateClient,
        "request",
        fake_request,
    )

    client = GateClient()

    try:
        response = asyncio.run(
            client.cancel_spot_order(
                "123456789",
                currency_pair=(
                    "EQTY_USDT"
                ),
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
        == 200
    )

    assert calls == [
        {
            "method":
                "DELETE",
            "endpoint":
                "/spot/orders/123456789",
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
            "headers": {
                "X-Gate-Exptime":
                    "1787320005000",
            },
        }
    ]


def test_cancel_requires_real_gate_order_id():
    client = GateClient()

    try:
        with pytest.raises(
            ValueError,
            match="real Gate order ID",
        ):
            asyncio.run(
                client.cancel_spot_order(
                    "t-eq-something",
                    currency_pair=(
                        "EQTY_USDT"
                    ),
                    expires_at_ms=1,
                )
            )
    finally:
        asyncio.run(
            client.close()
        )
